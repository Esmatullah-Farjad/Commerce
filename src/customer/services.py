from .models import Customer

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
