from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from client.services import active_branch, active_tenant
from store.accounting import record_customer_payment_entry
from store.utils import to_decimal

from .forms import CustomerForm, CustomerPaymentForm
from .models import Customer
from .services import (
    WALK_IN_CUSTOMER_ADDRESS,
    WALK_IN_CUSTOMER_NAME,
    WALK_IN_CUSTOMER_PHONE,
    customer_account_summary,
    customer_sales_queryset,
    get_or_create_walk_in_customer,
    set_active_customer,
)


def check_customer(request):
    tenant = active_tenant(request)
    code = request.GET.get("code")
    try:
        existing_customer = Customer.objects.get(id=code, tenant=tenant)
        set_active_customer(request, existing_customer)
        form = CustomerForm(instance=existing_customer)
    except Customer.DoesNotExist:
        form = CustomerForm(initial={"code": code})
    return render(request, "partials/_customer_form.html", {"form": form})


def create_customer(request):
    tenant = active_tenant(request)
    form = CustomerForm(request.POST or None)

    if request.method == "POST":
        if "ignore" in request.POST:
            customer = get_or_create_walk_in_customer(tenant)
            set_active_customer(request, customer)
            return redirect("products-view")

        if form.is_valid():
            name = (form.cleaned_data.get("name") or "").strip() or WALK_IN_CUSTOMER_NAME
            phone = form.cleaned_data.get("phone") or WALK_IN_CUSTOMER_PHONE
            address = (form.cleaned_data.get("address") or "").strip() or WALK_IN_CUSTOMER_ADDRESS

            if (
                name == WALK_IN_CUSTOMER_NAME
                and phone == WALK_IN_CUSTOMER_PHONE
                and address == WALK_IN_CUSTOMER_ADDRESS
            ):
                customer = get_or_create_walk_in_customer(tenant)
            else:
                existing_customer = None
                if phone not in (None, "", WALK_IN_CUSTOMER_PHONE):
                    existing_customer = (
                        Customer.objects
                        .filter(tenant=tenant, phone=phone)
                        .order_by("id")
                        .first()
                    )

                if existing_customer:
                    update_fields = []
                    if name and existing_customer.name != name:
                        existing_customer.name = name
                        update_fields.append("name")
                    if address and existing_customer.address != address:
                        existing_customer.address = address
                        update_fields.append("address")
                    if update_fields:
                        existing_customer.save(update_fields=update_fields)
                    customer = existing_customer
                else:
                    customer = Customer.objects.create(
                        tenant=tenant,
                        name=name,
                        phone=phone,
                        address=address,
                    )

            set_active_customer(request, customer)
            messages.success(request, _("Customer has been added successfully."))
            return redirect("products-view")

        messages.error(request, _("Something went wrong. Please fix the errors below."))

    return render(request, "sale/product_view.html", {"form": form})


def old_customer(request, pk):
    tenant = active_tenant(request)
    customer = get_object_or_404(Customer, pk=pk, tenant=tenant)
    set_active_customer(request, customer)
    messages.success(request, _("Customer has been selected successfully."))
    return redirect("products-view")


def customer(request):
    tenant = active_tenant(request)
    branch = active_branch(request)
    customers = Customer.objects.filter(tenant=tenant)
    if request.method == "POST":
        phone = request.POST.get("phone")
        customers = customers.filter(phone=phone)

    paid_customers = []
    unpaid_customers = []
    for customer_obj in customers:
        account = customer_account_summary(customer_obj, tenant, branch=branch)
        if not account["bill_count"]:
            continue
        row = {
            "customer": customer_obj,
            "total_amount": account["total_amount"],
            "total_paid": account["total_paid"],
            "total_unpaid": account["total_due"],
            "bill_count": account["bill_count"],
        }
        if account["has_unpaid"]:
            unpaid_customers.append(row)
        else:
            paid_customers.append(row)

    return render(
        request,
        "partials/management/_customer-view.html",
        {
            "unpaid_customers": unpaid_customers,
            "paid_customers": paid_customers,
        },
    )


def create_payment(request, cid):
    tenant = active_tenant(request)
    branch = active_branch(request)
    customer_obj = get_object_or_404(Customer, pk=cid, tenant=tenant)

    account = customer_account_summary(customer_obj, tenant, branch=branch)
    sales_details = account["sales_queryset"]
    total_amount = account["total_amount"]
    total_payable = account["total_payable"]
    total_carried_forward = account["total_carried_forward"]
    total_paid = account["total_paid"]
    total_due = account["total_due"]

    if request.method == "POST":
        form = CustomerPaymentForm(request.POST)
        if form.is_valid():
            paid_amount = to_decimal(form.cleaned_data["payment_amount"])

            if paid_amount <= Decimal("0.00"):
                messages.error(request, _("Payment amount must be greater than 0."))
                return redirect("create-payment", cid=customer_obj.id)

            if paid_amount > total_due:
                messages.error(
                    request,
                    _("Payment cannot be greater than unpaid amount (%(amount)s).") % {"amount": total_due},
                )
                return redirect("create-payment", cid=customer_obj.id)

            with transaction.atomic():
                payment = form.save(commit=False)
                payment.customer = customer_obj
                payment.tenant = tenant
                payment.branch = branch
                payment.save()

                remaining_payment = paid_amount
                unpaid_sales = (
                    customer_sales_queryset(customer_obj, tenant, branch=branch)
                    .select_for_update()
                    .filter(unpaid_amount__gt=0)
                    .order_by("created_at", "id")
                )

                if not unpaid_sales.exists():
                    messages.error(request, _("No unpaid sales record found for this customer."))
                    return redirect("create-payment", cid=customer_obj.id)

                for sale in unpaid_sales:
                    current_unpaid = to_decimal(sale.unpaid_amount or 0)
                    if current_unpaid <= Decimal("0.00"):
                        continue
                    allocation = min(remaining_payment, current_unpaid)
                    if allocation <= Decimal("0.00"):
                        break
                    sale.unpaid_amount = current_unpaid - allocation
                    sale.paid_amount = to_decimal(sale.paid_amount or 0) + allocation
                    sale.save(update_fields=["unpaid_amount", "paid_amount"])
                    remaining_payment -= allocation
                    if remaining_payment <= Decimal("0.00"):
                        break

                store = branch.store if branch else None
                record_customer_payment_entry(
                    tenant=tenant,
                    amount=paid_amount,
                    store=store,
                    branch=branch,
                    created_by=request.user,
                    reference_id=payment.id,
                )
            messages.success(request, _("Customer payment added successfully."))
            return redirect("create-payment", cid=customer_obj.id)
    else:
        form = CustomerPaymentForm()

    context = {
        "customer": customer_obj,
        "sales_details": sales_details,
        "total_amount": total_amount,
        "total_payable": total_payable,
        "total_carried_forward": total_carried_forward,
        "total_paid": total_paid,
        "total_due": total_due,
        "has_unpaid": total_due > 0,
        "form": form,
    }
    return render(request, "partials/management/_customer-account.html", context)


def customer_lists(request):
    return render(request, "customer/customer_list.html")
