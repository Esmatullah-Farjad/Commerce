from decimal import Decimal

from django.db.models import Count, Sum

from .models import Customer
from store.models import SalesDetails
from store.utils import to_decimal

WALK_IN_CUSTOMER_NAME = "Walk-in Customer"
WALK_IN_CUSTOMER_PHONE = 0
WALK_IN_CUSTOMER_ADDRESS = "------"


def set_active_customer(request, customer):
    request.session["customer"] = {str(customer.id): customer.name}


def get_or_create_walk_in_customer(tenant):
    customer, _ = Customer.objects.get_or_create(
        tenant=tenant,
        name=WALK_IN_CUSTOMER_NAME,
        phone=WALK_IN_CUSTOMER_PHONE,
        defaults={"address": WALK_IN_CUSTOMER_ADDRESS},
    )
    return customer


def get_active_customer(request, tenant, create_if_missing=True):
    customer_session = request.session.get("customer", {})
    customer = None
    if customer_session:
        customer_pk = list(customer_session.keys())[0]
        customer = Customer.objects.filter(pk=customer_pk, tenant=tenant).first()

    if not customer and create_if_missing and tenant:
        customer = get_or_create_walk_in_customer(tenant)
        set_active_customer(request, customer)

    return customer


def is_walk_in_customer(customer):
    if not customer:
        return False
    return (
        customer.name == WALK_IN_CUSTOMER_NAME
        and (customer.phone or 0) == WALK_IN_CUSTOMER_PHONE
        and (customer.address or WALK_IN_CUSTOMER_ADDRESS) == WALK_IN_CUSTOMER_ADDRESS
    )


def customer_sales_queryset(customer, tenant, branch=None):
    queryset = SalesDetails.objects.filter(customer=customer, tenant=tenant)
    if branch:
        queryset = queryset.filter(branch=branch)
    return queryset.order_by("-id")


def customer_account_summary(customer, tenant, branch=None):
    sales_queryset = customer_sales_queryset(customer, tenant, branch=branch)
    totals = sales_queryset.aggregate(
        total_amount=Sum("total_amount"),
        total_paid=Sum("paid_amount"),
        total_unpaid=Sum("unpaid_amount"),
        bill_count=Count("id"),
    )
    total_amount = to_decimal(totals["total_amount"] or 0)
    total_paid = to_decimal(totals["total_paid"] or 0)
    total_due = to_decimal(totals["total_unpaid"] or 0)
    return {
        "sales_queryset": sales_queryset,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_due": total_due,
        "bill_count": totals["bill_count"] or 0,
        "has_unpaid": total_due > Decimal("0.00"),
    }
