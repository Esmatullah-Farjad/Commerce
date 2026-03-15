from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from client.services import active_branch, active_tenant
from store.accounting import record_customer_payment_entry
from store.models import SalesDetails
from store.utils import to_decimal

from .forms import CustomerForm, CustomerPaymentForm
from .models import Customer
from .services import (
    WALK_IN_CUSTOMER_ADDRESS,
    WALK_IN_CUSTOMER_NAME,
    WALK_IN_CUSTOMER_PHONE,
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
                customer, _ = Customer.objects.get_or_create(
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

    customer_data = []
    for customer_obj in customers:
        sales_data = SalesDetails.objects.filter(
            customer=customer_obj,
            tenant=tenant,
            branch=branch,
        ).aggregate(
            total_amount=Sum("total_amount"),
            total_paid=Sum("paid_amount"),
            total_unpaid=Sum("unpaid_amount"),
            bill_count=Count("bill_number"),
        )
        customer_data.append(
            {
                "customer": customer_obj,
                "total_amount": sales_data["total_amount"] or 0,
                "total_paid": sales_data["total_paid"] or 0,
                "total_unpaid": sales_data["total_unpaid"] or 0,
                "bill_count": sales_data["bill_count"],
            }
        )

    return render(
        request,
        "partials/management/_customer-view.html",
        {"customer_data": customer_data},
    )


def create_payment(request, cid):
    tenant = active_tenant(request)
    branch = active_branch(request)
    customer_obj = get_object_or_404(Customer, pk=cid, tenant=tenant)

    sales_details = (
        SalesDetails.objects
        .filter(customer=customer_obj, tenant=tenant, branch=branch)
        .order_by("-id")
    )

    totals = sales_details.aggregate(
        total_amount=Sum("total_amount"),
        total_paid=Sum("paid_amount"),
        total_unpaid=Sum("unpaid_amount"),
    )
    total_amount = to_decimal(totals["total_amount"] or 0)
    total_paid = to_decimal(totals["total_paid"] or 0)
    total_due = to_decimal(totals["total_unpaid"] or 0)

    if request.method == "POST":
        form = CustomerPaymentForm(request.POST)
        if form.is_valid():
            paid_amount = to_decimal(form.cleaned_data["payment_amount"])

            if paid_amount <= Decimal("0.00"):
                messages.error(request, "Payment amount must be greater than 0.")
                return redirect("create-payment", cid=customer_obj.id)

            with transaction.atomic():
                payment = form.save(commit=False)
                payment.customer = customer_obj
                payment.tenant = tenant
                payment.branch = branch
                payment.save()

                last_sale = (
                    SalesDetails.objects
                    .select_for_update()
                    .filter(customer=customer_obj, tenant=tenant, branch=branch)
                    .order_by("-id")
                    .first()
                )

                if not last_sale:
                    messages.error(request, "No sales record found for this customer.")
                    return redirect("create-payment", cid=customer_obj.id)

                current_unpaid = to_decimal(last_sale.unpaid_amount or 0)
                if paid_amount > current_unpaid:
                    messages.error(
                        request,
                        f"Payment cannot be greater than unpaid amount ({current_unpaid}).",
                    )
                    return redirect("create-payment", cid=customer_obj.id)

                last_sale.unpaid_amount = current_unpaid - paid_amount
                last_sale.paid_amount = to_decimal(last_sale.paid_amount) + paid_amount
                last_sale.save(update_fields=["unpaid_amount", "paid_amount"])

                store = branch.store if branch else None
                record_customer_payment_entry(
                    tenant=tenant,
                    amount=paid_amount,
                    store=store,
                    branch=branch,
                    created_by=request.user,
                    reference_id=payment.id,
                )

            messages.success(request, "Customer payment added successfully.")
            return redirect("create-payment", cid=customer_obj.id)
    else:
        form = CustomerPaymentForm()

    context = {
        "customer": customer_obj,
        "sales_details": sales_details,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_due": total_due,
        "has_unpaid": total_due > 0,
        "form": form,
    }
    return render(request, "partials/management/_customer-account.html", context)


def customer_lists(request):
    return render(request, "customer/customer_list.html")
