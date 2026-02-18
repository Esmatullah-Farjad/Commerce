from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum

from .models import JournalEntry, JournalLine, LedgerAccount

MONEY_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")

# Essential chart of accounts for inventory retail.
SYSTEM_ACCOUNTS = {
    "1000": ("Cash on Hand", "asset"),
    "1100": ("Accounts Receivable", "asset"),
    "1200": ("Inventory Asset", "asset"),
    "2000": ("Accounts Payable", "liability"),
    "3000": ("Owner Equity", "equity"),
    "4000": ("Sales Revenue", "revenue"),
    "4100": ("Other Income", "revenue"),
    "5000": ("Cost of Goods Sold", "expense"),
    "6100": ("Operating Expense", "expense"),
}


def money(value):
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    except Exception:
        return ZERO


def ensure_default_accounts(tenant):
    created_or_existing = {}
    for code, (name, account_type) in SYSTEM_ACCOUNTS.items():
        account, _ = LedgerAccount.objects.get_or_create(
            tenant=tenant,
            code=code,
            defaults={
                "name": name,
                "account_type": account_type,
                "is_system": True,
                "is_active": True,
            },
        )
        created_or_existing[code] = account
    return created_or_existing


def get_account(tenant, code):
    return ensure_default_accounts(tenant)[code]


def post_journal_entry(
    *,
    tenant,
    store=None,
    branch=None,
    reference_type,
    reference_id="",
    memo="",
    created_by=None,
    entry_date=None,
    lines,
):
    prepared = []
    total_debit = ZERO
    total_credit = ZERO

    for line in lines:
        code = line["account_code"]
        debit = money(line.get("debit"))
        credit = money(line.get("credit"))
        if debit <= ZERO and credit <= ZERO:
            continue
        if debit > ZERO and credit > ZERO:
            raise ValueError("A journal line cannot contain both debit and credit amounts.")
        account = get_account(tenant, code)
        if not account.is_active:
            raise ValueError(f"Account {account.code} is inactive.")
        description = line.get("description", "")
        prepared.append(
            {
                "account": account,
                "debit": debit,
                "credit": credit,
                "description": description,
            }
        )
        total_debit += debit
        total_credit += credit

    total_debit = money(total_debit)
    total_credit = money(total_credit)

    if not prepared:
        return None
    if total_debit != total_credit:
        raise ValueError("Journal entry is not balanced.")

    with transaction.atomic():
        entry_kwargs = {
            "tenant": tenant,
            "store": store,
            "branch": branch,
            "reference_type": reference_type,
            "reference_id": str(reference_id or ""),
            "memo": memo or "",
            "created_by": created_by,
        }
        if entry_date is not None:
            entry_kwargs["entry_date"] = entry_date

        entry = JournalEntry.objects.create(
            **entry_kwargs,
        )

        JournalLine.objects.bulk_create(
            [
                JournalLine(
                    journal_entry=entry,
                    account=item["account"],
                    debit=item["debit"],
                    credit=item["credit"],
                    description=item["description"],
                )
                for item in prepared
            ]
        )
        return entry


def record_purchase_entry(*, tenant, total_cost, product=None, store=None, branch=None, created_by=None, reference_id=""):
    amount = money(total_cost)
    if amount <= ZERO:
        return None
    memo = f"Purchase stock-in{f' for {product.name}' if product else ''}"
    return post_journal_entry(
        tenant=tenant,
        store=store,
        branch=branch,
        reference_type="purchase",
        reference_id=reference_id,
        memo=memo,
        created_by=created_by,
        lines=[
            {
                "account_code": "1200",
                "debit": amount,
                "credit": ZERO,
                "description": "Inventory increase",
            },
            {
                "account_code": "1000",
                "debit": ZERO,
                "credit": amount,
                "description": "Cash paid for purchase",
            },
        ],
    )


def record_sale_entry(
    *,
    tenant,
    sale_total,
    paid_amount,
    unpaid_amount,
    cogs_total,
    store=None,
    branch=None,
    created_by=None,
    reference_id="",
):
    sale_total = money(sale_total)
    paid_amount = money(paid_amount)
    unpaid_amount = money(unpaid_amount)
    cogs_total = money(cogs_total)

    if sale_total <= ZERO:
        return None

    lines = []
    if paid_amount > ZERO:
        lines.append(
            {
                "account_code": "1000",
                "debit": paid_amount,
                "credit": ZERO,
                "description": "Cash received from sale",
            }
        )
    if unpaid_amount > ZERO:
        lines.append(
            {
                "account_code": "1100",
                "debit": unpaid_amount,
                "credit": ZERO,
                "description": "Receivable from customer",
            }
        )

    lines.append(
        {
            "account_code": "4000",
            "debit": ZERO,
            "credit": sale_total,
            "description": "Sales revenue",
        }
    )

    if cogs_total > ZERO:
        lines.append(
            {
                "account_code": "5000",
                "debit": cogs_total,
                "credit": ZERO,
                "description": "Recognized COGS",
            }
        )
        lines.append(
            {
                "account_code": "1200",
                "debit": ZERO,
                "credit": cogs_total,
                "description": "Inventory reduction",
            }
        )

    return post_journal_entry(
        tenant=tenant,
        store=store,
        branch=branch,
        reference_type="sale",
        reference_id=reference_id,
        memo="Sales invoice posted",
        created_by=created_by,
        lines=lines,
    )


def record_customer_payment_entry(*, tenant, amount, store=None, branch=None, created_by=None, reference_id=""):
    amount = money(amount)
    if amount <= ZERO:
        return None
    return post_journal_entry(
        tenant=tenant,
        store=store,
        branch=branch,
        reference_type="payment",
        reference_id=reference_id,
        memo="Customer payment received",
        created_by=created_by,
        lines=[
            {
                "account_code": "1000",
                "debit": amount,
                "credit": ZERO,
                "description": "Cash received",
            },
            {
                "account_code": "1100",
                "debit": ZERO,
                "credit": amount,
                "description": "Accounts receivable settled",
            },
        ],
    )


def record_expense_entry(*, tenant, amount, store=None, branch=None, created_by=None, reference_id="", memo=""):
    amount = money(amount)
    if amount <= ZERO:
        return None
    return post_journal_entry(
        tenant=tenant,
        store=store,
        branch=branch,
        reference_type="expense",
        reference_id=reference_id,
        memo=memo or "Operating expense posted",
        created_by=created_by,
        lines=[
            {
                "account_code": "6100",
                "debit": amount,
                "credit": ZERO,
                "description": "Expense booked",
            },
            {
                "account_code": "1000",
                "debit": ZERO,
                "credit": amount,
                "description": "Cash paid",
            },
        ],
    )


def record_other_income_entry(*, tenant, amount, store=None, branch=None, created_by=None, reference_id="", memo=""):
    amount = money(amount)
    if amount <= ZERO:
        return None
    return post_journal_entry(
        tenant=tenant,
        store=store,
        branch=branch,
        reference_type="other_income",
        reference_id=reference_id,
        memo=memo or "Other income posted",
        created_by=created_by,
        lines=[
            {
                "account_code": "1000",
                "debit": amount,
                "credit": ZERO,
                "description": "Cash received",
            },
            {
                "account_code": "4100",
                "debit": ZERO,
                "credit": amount,
                "description": "Other income",
            },
        ],
    )


def account_balances(queryset):
    grouped = (
        queryset.values("account_id", "account__code", "account__name", "account__account_type")
        .annotate(total_debit=Sum("debit"), total_credit=Sum("credit"))
        .order_by("account__code")
    )
    results = []
    for row in grouped:
        debit = money(row["total_debit"])
        credit = money(row["total_credit"])
        account_type = row["account__account_type"]
        if account_type in {"asset", "expense"}:
            balance = debit - credit
        else:
            balance = credit - debit
        results.append(
            {
                "account_id": row["account_id"],
                "code": row["account__code"],
                "name": row["account__name"],
                "account_type": account_type,
                "debit": debit,
                "credit": credit,
                "balance": money(balance),
            }
        )
    return results
