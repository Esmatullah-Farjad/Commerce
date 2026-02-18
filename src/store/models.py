from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Tenant(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class TenantMember(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("staff", "Staff"),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tenant_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="staff")
    is_owner = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tenant", "user")

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.name}"


class Store(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="stores")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("tenant", "code")

    def __str__(self):
        return self.name


class Branch(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, null=True, blank=True)
    address = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("store", "code")

    def __str__(self):
        return f"{self.store.name} - {self.name}"


class BranchMember(models.Model):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("staff", "Staff"),
    ]
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="branch_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="staff")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("branch", "user")

    def clean(self):
        super().clean()
        if self.branch_id and self.user_id:
            tenant_id = self.branch.store.tenant_id
            if not TenantMember.objects.filter(tenant_id=tenant_id, user_id=self.user_id).exists():
                raise ValidationError({"user": _("User must be a member of the branch tenant first.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} @ {self.branch}"


class StoreMember(models.Model):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("staff", "Staff"),
    ]
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="store_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="staff")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("store", "user")

    def clean(self):
        super().clean()
        if self.store_id and self.user_id:
            tenant_id = self.store.tenant_id
            if not TenantMember.objects.filter(tenant_id=tenant_id, user_id=self.user_id).exists():
                raise ValidationError({"user": _("User must be a member of the store tenant first.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} @ {self.store.name}"


class UserOnboarding(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="onboarding")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="onboarding_requests")
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="onboarding_requests")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    assigned_branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarded_users",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activated_users",
    )

    def clean(self):
        super().clean()
        if self.store_id and self.tenant_id and self.store.tenant_id != self.tenant_id:
            raise ValidationError({"store": _("Store must belong to the selected tenant.")})
        if self.assigned_branch_id:
            if self.store_id and self.assigned_branch.store_id != self.store_id:
                raise ValidationError({"assigned_branch": _("Assigned branch must belong to the selected store.")})
            if self.assigned_branch.store.tenant_id != self.tenant_id:
                raise ValidationError({"assigned_branch": _("Assigned branch must belong to the selected tenant.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.tenant.name} ({self.status})"


class Category(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="categories", null=True, blank=True)
    name = models.CharField(max_length=50)
    description = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class BaseUnit(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="base_units", null=True, blank=True)
    name = models.CharField(max_length=50)
    is_weight_base = models.BooleanField(default=False)
    base_unit = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_units",
        help_text=_("Select the base unit this converts to (optional)."),
    )
    conversion_to_base = models.FloatField(
        null=True,
        blank=True,
        help_text=_(
            "Conversion factor to the base unit (e.g., 7 for Sir if base is KG). Leave blank if conversion is product-specific."
        ),
    )

    def __str__(self):
        return self.name


class PurchaseUnit(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_units", null=True, blank=True)
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class ExchangeRate(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="exchange_rates", null=True, blank=True)
    usd_to_afn = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)


class Products(models.Model):
    NUMBER_CHOICES = [(i, str(i)) for i in range(1, 201)]
    CURRENCY_CHOICES = [
        ("usd", "USD"),
        ("afn", "AFN"),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="products", null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    code = models.IntegerField(null=True, default=0)
    name = models.CharField(max_length=100)
    unit = models.ForeignKey(BaseUnit, on_delete=models.CASCADE, null=True, blank=True)
    purchase_unit = models.ForeignKey(PurchaseUnit, on_delete=models.CASCADE, null=True, blank=True)
    currency_category = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="afn")

    package_contain = models.PositiveBigIntegerField(choices=NUMBER_CHOICES)
    package_purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    package_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)

    usd_package_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    num_of_packages = models.IntegerField(default=1)
    total_package_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, default=0)
    item_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, default=0)

    num_items = models.IntegerField(default=0, null=True, blank=True)
    stock = models.IntegerField()
    image = models.ImageField(default="default.png", upload_to="item_images")
    description = models.TextField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_product_code_per_tenant"),
        ]

    def __str__(self):
        return self.name

    @property
    def latest_usd_rate(self):
        rate = ExchangeRate.objects.filter(tenant=self.tenant).last() if self.tenant_id else ExchangeRate.objects.last()
        return rate.usd_to_afn if rate else Decimal("1")

    def is_usd_unit(self):
        return self.purchase_unit and self.purchase_unit.code.lower() == "usd"

    @property
    def dynamic_afn_sale_price(self):
        if self.is_usd_unit() and self.usd_package_sale_price:
            return round(self.usd_package_sale_price * self.latest_usd_rate, 2)
        return self.package_sale_price or Decimal("0")


class Customer(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="customers", null=True, blank=True)
    name = models.CharField(max_length=200, null=True, blank=True, default="Walk-in Customer")
    phone = models.IntegerField(null=True, blank=True, default=0)
    address = models.CharField(max_length=200, null=True, blank=True, default="------")

    def __str__(self):
        return self.name or f"Customer #{self.id}"


class BillNumberTracker(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="bill_tracker", null=True, blank=True)
    current_number = models.PositiveIntegerField(default=1001)

    @classmethod
    def get_next_bill_number(cls, tenant):
        tracker, _ = cls.objects.get_or_create(tenant=tenant)
        next_number = tracker.current_number
        tracker.current_number += 1
        tracker.save(update_fields=["current_number"])
        return next_number


class SalesDetails(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_details", null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, related_name="sales_details", null=True, blank=True)
    user = models.ForeignKey(User, related_name="user", null=True, blank=True, on_delete=models.SET_NULL)
    bill_number = models.CharField(max_length=100, editable=False, default="")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="customer")
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    unpaid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "bill_number"], name="uniq_bill_per_tenant"),
        ]

    def clean(self):
        super().clean()
        if self.tenant_id and self.customer_id and self.customer.tenant_id != self.tenant_id:
            raise ValidationError({"customer": _("Customer must belong to the selected tenant.")})
        if self.branch_id and self.tenant_id and self.branch.store.tenant_id != self.tenant_id:
            raise ValidationError({"branch": _("Branch must belong to the selected tenant.")})

    def save(self, *args, **kwargs):
        if not self.bill_number:
            self.bill_number = str(BillNumberTracker.get_next_bill_number(self.tenant))
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.bill_number


class SalesProducts(models.Model):
    sale_detail = models.ForeignKey(SalesDetails, related_name="sale_detail", on_delete=models.CASCADE)
    product = models.ForeignKey(Products, related_name="produts", null=True, blank=True, on_delete=models.SET_NULL)
    item_price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    package_price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    item_qty = models.IntegerField(default=0)
    package_qty = models.IntegerField(default=0)
    total_price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return f"bill number {self.sale_detail}"


class OtherIncome(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="other_incomes", null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, related_name="other_incomes", null=True, blank=True)
    date_created = models.DateField()
    source = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.source


class Expense(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="expenses", null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, related_name="expenses", null=True, blank=True)
    date_created = models.DateField()
    category = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.category


class CustomerPayment(models.Model):
    PAYMENT_METHOD = [
        ("cash", "Cash"),
        ("bank_transfer", "Bank Transfer"),
        ("hesab_pay", "Hesab Pay"),
        ("hawala", "Hawala"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="customer_payments", null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, related_name="customer_payments", null=True, blank=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    payment_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(max_length=255, choices=PAYMENT_METHOD, default="cash")
    note = models.TextField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.customer_id and self.tenant_id and self.customer.tenant_id != self.tenant_id:
            raise ValidationError({"customer": _("Customer must belong to the selected tenant.")})
        if self.branch_id and self.tenant_id and self.branch.store.tenant_id != self.tenant_id:
            raise ValidationError({"branch": _("Branch must belong to the selected tenant.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        customer_name = self.customer.name if self.customer else "Deleted Customer"
        return f"{customer_name} - {self.get_payment_method_display()} - {self.payment_amount}"


class LedgerAccount(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ("asset", "Asset"),
        ("liability", "Liability"),
        ("equity", "Equity"),
        ("revenue", "Revenue"),
        ("expense", "Expense"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="ledger_accounts")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_ledger_code_per_tenant"),
            models.UniqueConstraint(fields=["tenant", "name"], name="uniq_ledger_name_per_tenant"),
        ]
        ordering = ["code", "name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class JournalEntry(models.Model):
    REFERENCE_TYPE_CHOICES = [
        ("sale", "Sale"),
        ("purchase", "Purchase"),
        ("payment", "Payment"),
        ("expense", "Expense"),
        ("other_income", "Other Income"),
        ("adjustment", "Adjustment"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="journal_entries")
    store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True, related_name="journal_entries")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="journal_entries")
    entry_date = models.DateField(default=timezone.localdate)
    reference_type = models.CharField(max_length=20, choices=REFERENCE_TYPE_CHOICES)
    reference_id = models.CharField(max_length=80, blank=True, default="")
    memo = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="journal_entries")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-entry_date", "-id"]

    def clean(self):
        super().clean()
        if self.store_id and self.store.tenant_id != self.tenant_id:
            raise ValidationError({"store": _("Store must belong to the selected tenant.")})
        if self.branch_id and self.branch.store.tenant_id != self.tenant_id:
            raise ValidationError({"branch": _("Branch must belong to the selected tenant.")})
        if self.branch_id and self.store_id and self.branch.store_id != self.store_id:
            raise ValidationError({"branch": _("Branch must belong to the selected store.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference_type} #{self.id}"


class JournalLine(models.Model):
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="journal_lines")
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    description = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["id"]

    def clean(self):
        super().clean()
        if self.journal_entry_id and self.account_id:
            if self.journal_entry.tenant_id != self.account.tenant_id:
                raise ValidationError({"account": _("Account tenant must match journal entry tenant.")})
        if self.debit < 0 or self.credit < 0:
            raise ValidationError(_("Debit and credit amounts cannot be negative."))
        if self.debit == 0 and self.credit == 0:
            raise ValidationError(_("Either debit or credit must be greater than zero."))
        if self.debit > 0 and self.credit > 0:
            raise ValidationError(_("A line cannot have both debit and credit values."))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.account.code} (D:{self.debit} C:{self.credit})"


class BranchStock(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stock_levels")
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="branch_stocks")
    stock = models.IntegerField(default=0)
    num_of_packages = models.IntegerField(default=0)
    num_items = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("branch", "product")

    def __str__(self):
        return f"{self.branch} - {self.product.name}"


class StoreStock(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="stock_levels")
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="store_stocks")
    stock = models.IntegerField(default=0)
    num_of_packages = models.IntegerField(default=0)
    num_items = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("store", "product")

    def __str__(self):
        return f"{self.store} - {self.product.name}"


class TenantStock(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="stock_levels")
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="tenant_stocks")
    stock = models.IntegerField(default=0)
    num_of_packages = models.IntegerField(default=0)
    num_items = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("tenant", "product")

    def __str__(self):
        return f"{self.tenant} - {self.product.name}"


class InventoryTransfer(models.Model):
    SCOPE_CHOICES = [
        ("tenant", "Tenant"),
        ("store", "Store"),
        ("branch", "Branch"),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="inventory_transfers")
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="inventory_transfers")
    from_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    to_scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    from_store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True, related_name="transfers_out")
    from_branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="transfers_out")
    to_store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True, related_name="transfers_in")
    to_branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="transfers_in")
    package_qty = models.IntegerField(default=0)
    item_qty = models.IntegerField(default=0)
    total_items = models.IntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_transfers")
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.product_id and self.product.tenant_id != self.tenant_id:
            raise ValidationError({"product": _("Product must belong to the selected tenant.")})

        for field in ["from_store", "to_store"]:
            obj = getattr(self, field)
            if obj and obj.tenant_id != self.tenant_id:
                raise ValidationError({field: _("Store must belong to the selected tenant.")})

        for field in ["from_branch", "to_branch"]:
            obj = getattr(self, field)
            if obj and obj.store.tenant_id != self.tenant_id:
                raise ValidationError({field: _("Branch must belong to the selected tenant.")})

        if self.from_branch_id and self.from_store_id and self.from_branch.store_id != self.from_store_id:
            raise ValidationError({"from_branch": _("Source branch must belong to source store.")})
        if self.to_branch_id and self.to_store_id and self.to_branch.store_id != self.to_store_id:
            raise ValidationError({"to_branch": _("Destination branch must belong to destination store.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} {self.from_scope} -> {self.to_scope} ({self.total_items})"


class InventoryMovement(models.Model):
    MOVEMENT_CHOICES = [
        ("purchase", "Purchase"),
        ("transfer_in", "Transfer In"),
        ("transfer_out", "Transfer Out"),
        ("adjustment", "Adjustment"),
    ]
    SCOPE_CHOICES = InventoryTransfer.SCOPE_CHOICES
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="inventory_movements")
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="inventory_movements")
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_movements")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_movements")
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_CHOICES)
    package_qty = models.IntegerField(default=0)
    item_qty = models.IntegerField(default=0)
    total_items = models.IntegerField(default=0)
    transfer = models.ForeignKey(InventoryTransfer, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_movements")
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True, default="")

    def clean(self):
        super().clean()
        if self.product_id and self.product.tenant_id != self.tenant_id:
            raise ValidationError({"product": _("Product must belong to the selected tenant.")})
        if self.store_id and self.store.tenant_id != self.tenant_id:
            raise ValidationError({"store": _("Store must belong to the selected tenant.")})
        if self.branch_id and self.branch.store.tenant_id != self.tenant_id:
            raise ValidationError({"branch": _("Branch must belong to the selected tenant.")})
        if self.branch_id and self.store_id and self.branch.store_id != self.store_id:
            raise ValidationError({"branch": _("Branch must belong to the selected store.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} {self.movement_type} ({self.total_items})"


class StockTransfer(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    from_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stock_transfers_out")
    to_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stock_transfers_in")
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="stock_transfers")
    quantity = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="requested_transfers")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_transfers")
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.product.name}: {self.from_branch} -> {self.to_branch}"
