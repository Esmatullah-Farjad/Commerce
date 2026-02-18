from datetime import date, timedelta
from django.shortcuts import redirect, render, get_object_or_404
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils.translation import activate
from django.utils import timezone
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string

from decimal import Decimal, ROUND_HALF_UP



from store.filters import ProductsFilter, SalesDetailsFilter
from .accounting import (
    account_balances,
    ensure_default_accounts,
    money,
    record_customer_payment_entry,
    record_expense_entry,
    record_other_income_entry,
    record_purchase_entry,
    record_sale_entry,
)
from .models import BaseUnit, Branch, BranchMember, BranchStock, Category, Customer, ExchangeRate, OtherIncome, Expense, InventoryMovement, InventoryTransfer, JournalEntry, JournalLine, LedgerAccount, Products, SalesDetails, SalesProducts, Store, StoreMember, StoreStock, Tenant, TenantMember, TenantStock, UserOnboarding
from .forms import BaseUnitForm, CustomerForm, CustomerPaymentForm, ExchangeRateForm, OtherIncomeForm, ExpenseForm, PurchaseForm, RegistrationForm, UserActivationForm, InventoryTransferForm
from .permissions import can_transfer_stock, resolve_transfer_scope
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import authenticate, login, logout
import jdatetime


import json
from django.http import HttpResponse, JsonResponse

# Create your views here.
def _active_tenant(request):
    return getattr(request, "tenant", None)

def _active_branch(request):
    return getattr(request, "branch", None)


def _sync_user_memberships_from_onboarding(user, include_pending_for_active_user=False):
    """
    Backfill tenant/store/branch memberships from active onboarding records.
    This heals older users that were activated before membership rows existed.
    """
    if not user or not user.is_authenticated:
        return

    allowed_statuses = ["active"]
    if include_pending_for_active_user and user.is_active:
        allowed_statuses.append("pending")

    onboardings = (
        UserOnboarding.objects.select_related("tenant", "store", "assigned_branch")
        .filter(
            user=user,
            status__in=allowed_statuses,
            tenant__is_active=True,
            store__is_active=True,
        )
        .order_by("-activated_at", "-requested_at")
    )
    if not onboardings.exists():
        return

    for onboarding in onboardings:
        if onboarding.store.tenant_id != onboarding.tenant_id:
            continue

        tenant_member, _ = TenantMember.objects.get_or_create(
            tenant=onboarding.tenant,
            user=user,
            defaults={"role": "staff", "is_owner": False},
        )

        StoreMember.objects.get_or_create(
            store=onboarding.store,
            user=user,
            defaults={"role": "staff"},
        )

        if onboarding.assigned_branch_id and onboarding.assigned_branch.store.tenant_id == onboarding.tenant_id:
            BranchMember.objects.get_or_create(
                branch=onboarding.assigned_branch,
                user=user,
                defaults={"role": "staff"},
            )

        # If admin activated the auth user but onboarding record is still pending,
        # normalize onboarding status to active and keep audit timestamp.
        if onboarding.status == "pending" and user.is_active and include_pending_for_active_user:
            onboarding.status = "active"
            if not onboarding.activated_at:
                onboarding.activated_at = timezone.now()
            onboarding.save(update_fields=["status", "activated_at"])


def to_decimal(value, default=Decimal("0.00")):
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return default


def _branch_and_store_access(request, tenant):
    user = request.user
    if not user.is_authenticated or not tenant:
        return False, Store.objects.none(), Branch.objects.none()

    can_tenant_scope = user.is_superuser or TenantMember.objects.filter(
        user=user,
        tenant=tenant,
        role__in=["owner", "admin", "manager"],
    ).exists()

    if can_tenant_scope:
        store_qs = Store.objects.filter(tenant=tenant, is_active=True).order_by("name")
        branch_qs = Branch.objects.filter(store__tenant=tenant, is_active=True).select_related("store").order_by("store__name", "name")
        return can_tenant_scope, store_qs, branch_qs

    store_ids = set(
        StoreMember.objects.filter(
            user=user,
            store__tenant=tenant,
            store__is_active=True,
        ).values_list("store_id", flat=True)
    )

    branch_qs = (
        Branch.objects.filter(
            memberships__user=user,
            store__tenant=tenant,
            is_active=True,
        )
        .select_related("store")
        .distinct()
        .order_by("store__name", "name")
    )
    store_ids.update(branch_qs.values_list("store_id", flat=True))

    store_qs = Store.objects.filter(id__in=store_ids, is_active=True).order_by("name")
    return can_tenant_scope, store_qs, branch_qs


def _resolve_reporting_scope(request, tenant):
    can_tenant_scope, store_qs, branch_qs = _branch_and_store_access(request, tenant)
    active_branch = _active_branch(request)
    requested_scope = request.GET.get("scope")
    requested_store_id = safe_int(request.GET.get("store_id"), 0)
    requested_branch_id = safe_int(request.GET.get("branch_id"), 0)

    selected_store = None
    selected_branch = None
    scope = "tenant" if can_tenant_scope else None

    if requested_scope == "tenant" and can_tenant_scope:
        scope = "tenant"
    elif requested_scope == "store":
        selected_store = store_qs.filter(id=requested_store_id).first()
        if selected_store:
            scope = "store"
    elif requested_scope == "branch":
        selected_branch = branch_qs.filter(id=requested_branch_id).first()
        if selected_branch:
            scope = "branch"

    if not scope:
        if active_branch and branch_qs.filter(id=active_branch.id).exists():
            selected_branch = active_branch
            scope = "branch"
        else:
            selected_branch = branch_qs.first()
            if selected_branch:
                scope = "branch"
            else:
                selected_store = store_qs.first()
                if selected_store:
                    scope = "store"
                elif can_tenant_scope:
                    scope = "tenant"

    if scope == "branch" and selected_branch:
        selected_store = selected_branch.store
    elif scope == "store" and selected_store:
        selected_branch = None

    return {
        "scope": scope,
        "store": selected_store,
        "branch": selected_branch,
        "can_tenant_scope": can_tenant_scope,
        "store_options": store_qs,
        "branch_options": branch_qs,
    }


def _apply_branch_scope(qs, scope_data, branch_field="branch"):
    scope = scope_data.get("scope")
    store = scope_data.get("store")
    branch = scope_data.get("branch")
    if scope == "branch" and branch:
        return qs.filter(**{f"{branch_field}_id": branch.id})
    if scope == "store" and store:
        return qs.filter(**{f"{branch_field}__store_id": store.id})
    return qs


def _apply_journal_scope(qs, scope_data):
    scope = scope_data.get("scope")
    store = scope_data.get("store")
    branch = scope_data.get("branch")
    if scope == "branch" and branch:
        return qs.filter(branch=branch)
    if scope == "store" and store:
        return qs.filter(Q(store=store) | Q(branch__store=store))
    return qs

def _resolve_inventory_scope(request, tenant, branch=None):
    if branch:
        return "branch", {"branch": branch}

    store_member = (
        StoreMember.objects
        .select_related("store")
        .filter(user=request.user, store__tenant=tenant, store__is_active=True)
        .first()
        if tenant and request.user.is_authenticated
        else None
    )
    if store_member:
        return "store", {"store": store_member.store}

    onboarding = (
        UserOnboarding.objects
        .select_related("store")
        .filter(user=request.user, tenant=tenant, status="active")
        .order_by("-activated_at", "-requested_at")
        .first()
        if tenant and request.user.is_authenticated
        else None
    )
    if onboarding and onboarding.store and onboarding.store.is_active:
        return "store", {"store": onboarding.store}

    return "tenant", {"tenant": tenant}


def _split_stock(product, total_items):
    package_contain = safe_int(getattr(product, "package_contain", 1), 1)
    if package_contain <= 0:
        package_contain = 1
    num_packages = total_items // package_contain
    num_items = total_items % package_contain
    return num_packages, num_items


def _set_stock(scope, product, total_items, tenant=None, store=None, branch=None):
    num_packages, num_items = _split_stock(product, total_items)
    defaults = {
        "stock": total_items,
        "num_of_packages": num_packages,
        "num_items": num_items,
    }
    if scope == "branch":
        BranchStock.objects.update_or_create(
            branch=branch,
            product=product,
            defaults=defaults,
        )
    elif scope == "store":
        StoreStock.objects.update_or_create(
            store=store,
            product=product,
            defaults=defaults,
        )
    else:
        TenantStock.objects.update_or_create(
            tenant=tenant,
            product=product,
            defaults=defaults,
        )


def _adjust_stock(scope, product, delta_items, tenant=None, store=None, branch=None):
    if scope == "branch":
        row = (
            BranchStock.objects
            .select_for_update()
            .filter(branch=branch, product=product)
            .first()
        )
        if not row:
            row = BranchStock(branch=branch, product=product, stock=0, num_of_packages=0, num_items=0)
    elif scope == "store":
        row = (
            StoreStock.objects
            .select_for_update()
            .filter(store=store, product=product)
            .first()
        )
        if not row:
            row = StoreStock(store=store, product=product, stock=0, num_of_packages=0, num_items=0)
    else:
        row = (
            TenantStock.objects
            .select_for_update()
            .filter(tenant=tenant, product=product)
            .first()
        )
        if not row:
            row = TenantStock(tenant=tenant, product=product, stock=0, num_of_packages=0, num_items=0)

    new_total = safe_int(row.stock) + delta_items
    if new_total < 0:
        raise ValueError("Insufficient stock for this transfer.")
    num_packages, num_items = _split_stock(product, new_total)
    row.stock = new_total
    row.num_of_packages = num_packages
    row.num_items = num_items
    row.save()
    return row

def _apply_branch_stock(products, branch):
    if not products or not branch:
        return
    product_ids = [p.id for p in products]
    stock_map = {
        stock.product_id: stock
        for stock in BranchStock.objects.filter(branch=branch, product_id__in=product_ids)
    }
    for product in products:
        stock = stock_map.get(product.id)
        if stock:
            product.stock = stock.stock
            product.num_of_packages = stock.num_of_packages
            product.num_items = stock.num_items
        else:
            product.stock = 0
            product.num_of_packages = 0
            product.num_items = 0


def _apply_scope_stock(products, scope, tenant=None, store=None, branch=None):
    if not products:
        return
    product_ids = [p.id for p in products]
    stock_map = {}
    if scope == "branch" and branch:
        stock_map = {
            stock.product_id: stock
            for stock in BranchStock.objects.filter(branch=branch, product_id__in=product_ids)
        }
    elif scope == "store" and store:
        stock_map = {
            stock.product_id: stock
            for stock in StoreStock.objects.filter(store=store, product_id__in=product_ids)
        }
    elif scope == "tenant" and tenant:
        stock_map = {
            stock.product_id: stock
            for stock in TenantStock.objects.filter(tenant=tenant, product_id__in=product_ids)
        }

    for product in products:
        stock = stock_map.get(product.id)
        if stock:
            product.stock = stock.stock
            product.num_of_packages = stock.num_of_packages
            product.num_items = stock.num_items
        else:
            product.stock = 0
            product.num_of_packages = 0
            product.num_items = 0


def _parse_jalali_date(value):
    if not value:
        return None
    try:
        year, month, day = map(int, value.split('-'))
        jalali_date = jdatetime.date(year, month, day)
        return jalali_date.togregorian()
    except Exception:
        return None


def switch_language(request, lang_code):
    if lang_code in dict(settings.LANGUAGES):  # ✅ Ensure the language is valid
        activate(lang_code)
        request.session['django_language'] = lang_code  # ✅ Store in session
        # ✅ Store the language in a cookie
        response = redirect(request.META.get('HTTP_REFERER', '/'))
        response.set_cookie('django_language', lang_code, max_age=31536000)  # 1 year
        return response
    return redirect('/')

def root_view(request):
    if request.user.is_authenticated:  # Check if the user is authenticated
        return redirect('home')  # Redirect to the 'home' page
    else:
        return redirect("landing")

def landing(request):    
    return render(request, "landing-page.html")

def Home(request):
    if not request.user.is_authenticated:
        return redirect("landing")
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    store = branch.store if branch else None
    order_products = (
        Products.objects
        .filter(tenant=tenant, branch_stocks__branch=branch, branch_stocks__num_of_packages__lt=10)
        .distinct()
    )
    today_date = date.today()
    sales_details = (
        SalesDetails.objects
        .filter(tenant=tenant, branch=branch, user=request.user, created_at__date=today_date)
        .aggregate(
            total_sale=Sum('total_amount'),
            total_paid=Sum('paid_amount'),
            total_unpaid=Sum('unpaid_amount'),
            total_customer=Count('customer', distinct=True)  # Ensure distinct customers are counted
        )
    )
    
    top_packages = (
        SalesProducts.objects
        .filter(
            sale_detail__tenant=tenant,
            sale_detail__branch=branch,
            sale_detail__user=request.user,
            sale_detail__created_at__date=today_date,
        )
        .values('product__name','product__category__name')  # Group by product name
        .annotate(total_package_qty=Sum('package_qty'))  # Calculate total package quantity for each product
        .order_by('-total_package_qty')[:10]  # Order by total package quantity in descending order
    )
    context = {
        'top_packages':top_packages,
        'sales_details':sales_details,
        'order_products':order_products,
        'tenant': tenant,
        'store': store,
    }
    return render(request, 'home.html', context)

def signin(request):
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST.get('password')
        user = authenticate(request, username=email, email=email, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, _("Welcome !"))

            # Ensure active onboarded users are linked to tenant/store/branch memberships.
            _sync_user_memberships_from_onboarding(user, include_pending_for_active_user=True)

            memberships = (
                TenantMember.objects
                .select_related("tenant")
                .filter(user=user, tenant__is_active=True)
                .order_by("tenant__name")
            )
            if memberships.count() == 1:
                tenant_id = memberships.first().tenant_id
                request.session["active_tenant_id"] = tenant_id

                onboarding = (
                    UserOnboarding.objects
                    .select_related("store", "assigned_branch")
                    .filter(user=user, tenant_id=tenant_id, status="active")
                    .order_by("-activated_at", "-requested_at")
                    .first()
                )

                branch_id = None
                if onboarding and onboarding.assigned_branch_id:
                    branch_id = onboarding.assigned_branch_id
                elif onboarding and onboarding.store_id:
                    store_branch = (
                        Branch.objects
                        .filter(store_id=onboarding.store_id, is_active=True)
                        .order_by("name")
                        .first()
                    )
                    if store_branch:
                        branch_id = store_branch.id
                if not branch_id:
                    branch_membership = (
                        BranchMember.objects
                        .select_related("branch", "branch__store")
                        .filter(user=user, branch__store__tenant_id=tenant_id, branch__is_active=True)
                        .order_by("branch__store__name", "branch__name")
                        .first()
                    )
                    if branch_membership:
                        branch_id = branch_membership.branch_id

                if not branch_id:
                    first_branch = (
                        Branch.objects
                        .filter(store__tenant_id=tenant_id, is_active=True)
                        .order_by("store__name", "name")
                        .first()
                    )
                    if first_branch:
                        branch_id = first_branch.id

                if branch_id:
                    request.session["active_branch_id"] = branch_id
                else:
                    request.session.pop("active_branch_id", None)

                return redirect('home')

            if memberships.count() > 1:
                messages.info(request, _("Select the tenant you want to work in."))
                return redirect('select-tenant')

            messages.error(request, _("No tenant assigned to this account. Please contact an admin."))
            request.session.pop("active_tenant_id", None)
            request.session.pop("active_branch_id", None)
            return redirect('select-tenant')
        else:
            try:
                from django.contrib.auth import get_user_model
                UserModel = get_user_model()
                existing = UserModel.objects.filter(email=email).first() or UserModel.objects.filter(username=email).first()
                if existing and not existing.is_active:
                    messages.error(request, _("Your account is inactive. Please contact an admin for activation."))
                    return render(request, 'auth/login.html')
            except Exception:
                pass
            messages.error(request, _("Invalid username or password"))
    return render(request, 'auth/login.html')

def signup(request):
    form = RegistrationForm()
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()

            tenant = form.cleaned_data.get("tenant")
            store = form.cleaned_data.get("store")

            UserOnboarding.objects.create(
                user=user,
                tenant=tenant,
                store=store,
                status="pending",
            )
            messages.success(request, _("Account created. Your account is pending admin activation."))
            return redirect("sign-in")
            messages.success(request, _("The user has been registered successfully"))
            
        else:
            messages.error(request, _("Something Went wrong. Please fix the below error !"))
           
    register_form = form
    context = {
        'form':register_form,
        'tenants': form.fields["tenant"].queryset,
        'stores': form.fields["store"].queryset,
    }
    return render(request, 'auth/register.html', context)

def signout(request):
    logout(request) 
    return redirect('sign-in') 


def select_tenant(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    # Heal missing memberships for users already activated by onboarding.
    _sync_user_memberships_from_onboarding(request.user, include_pending_for_active_user=True)

    memberships = (
        TenantMember.objects
        .select_related("tenant")
        .filter(user=request.user, tenant__is_active=True)
        .order_by("tenant__name")
    )
    tenants = [m.tenant for m in memberships]

    if request.method == "POST":
        tenant_id = request.POST.get("tenant_id")
        allowed = next((m for m in memberships if str(m.tenant_id) == str(tenant_id)), None)
        if not allowed:
            messages.error(request, _("Invalid tenant selection."))
            return redirect("select-tenant")
        tenant_id = allowed.tenant_id

        request.session["active_tenant_id"] = tenant_id
        request.session.pop("active_branch_id", None)
        request.session.pop("cart", None)
        request.session.pop("customer", None)

        branches = Branch.objects.filter(store__tenant_id=tenant_id, is_active=True)
        if branches.count() == 1:
            request.session["active_branch_id"] = branches.first().id
            return redirect("home")

        return redirect("select-branch")

    context = {
        "tenants": tenants,
    }
    return render(request, "tenancy/select_tenant.html", context)


def select_branch(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    _sync_user_memberships_from_onboarding(request.user, include_pending_for_active_user=True)

    tenant_id = request.session.get("active_tenant_id")
    if not tenant_id:
        return redirect("select-tenant")
    if not TenantMember.objects.filter(user=request.user, tenant_id=tenant_id).exists():
        request.session.pop("active_tenant_id", None)
        return redirect("select-tenant")

    member_branch_ids = (
        BranchMember.objects
        .filter(user=request.user, branch__store__tenant_id=tenant_id)
        .values_list("branch_id", flat=True)
    )
    if member_branch_ids.exists():
        branches = Branch.objects.filter(id__in=list(member_branch_ids), is_active=True).select_related("store")
    else:
        branches = Branch.objects.filter(store__tenant_id=tenant_id, is_active=True).select_related("store")

    if request.method == "POST":
        branch_id = request.POST.get("branch_id")
        branch = branches.filter(id=branch_id).first()
        if not branch:
            messages.error(request, _("Invalid branch selection."))
            return redirect("select-branch")

        request.session["active_branch_id"] = branch.id
        request.session.pop("cart", None)
        request.session.pop("customer", None)
        return redirect("home")

    context = {
        "branches": branches,
    }
    return render(request, "tenancy/select_branch.html", context)


def pending_users(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    tenant = _active_tenant(request)
    if not tenant:
        return redirect("select-tenant")

    is_admin = request.user.is_superuser or TenantMember.objects.filter(
        user=request.user,
        tenant=tenant,
        role__in=["owner", "admin"],
    ).exists()
    if not is_admin:
        messages.error(request, _("You do not have permission to view pending users."))
        return redirect("home")

    pending = (
        UserOnboarding.objects
        .select_related("user", "tenant", "store")
        .filter(tenant=tenant, status="pending")
        .order_by("-requested_at")
    )

    context = {
        "tenant": tenant,
        "pending_users": pending,
    }
    return render(request, "tenancy/pending_users.html", context)


def activate_user(request, onboarding_id):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    tenant = _active_tenant(request)
    if not tenant:
        return redirect("select-tenant")

    is_admin = request.user.is_superuser or TenantMember.objects.filter(
        user=request.user,
        tenant=tenant,
        role__in=["owner", "admin"],
    ).exists()
    if not is_admin:
        messages.error(request, _("You do not have permission to activate users."))
        return redirect("home")

    onboarding = get_object_or_404(UserOnboarding, pk=onboarding_id, tenant=tenant)
    if onboarding.status != "pending":
        messages.info(request, _("This user is already processed."))
        return redirect("pending-users")

    form = UserActivationForm(
        request.POST or None,
        store=onboarding.store,
        tenant=tenant,
    )
    branch_queryset = form.fields["branch"].queryset
    has_branches = branch_queryset.exists()

    if request.method == "POST":
        if not has_branches:
            messages.error(request, _("No branches available for this store. Please create one first."))
        elif form.is_valid():
            branch = form.cleaned_data["branch"]
            with transaction.atomic():
                onboarding.user.is_active = True
                onboarding.user.save(update_fields=["is_active"])

                TenantMember.objects.get_or_create(
                    tenant=tenant,
                    user=onboarding.user,
                    defaults={"role": "staff", "is_owner": False},
                )
                StoreMember.objects.get_or_create(
                    store=onboarding.store,
                    user=onboarding.user,
                    defaults={"role": "staff"},
                )
                BranchMember.objects.get_or_create(
                    branch=branch,
                    user=onboarding.user,
                    defaults={"role": "staff"},
                )

                onboarding.status = "active"
                onboarding.assigned_branch = branch
                onboarding.activated_by = request.user
                onboarding.activated_at = timezone.now()
                onboarding.save(update_fields=["status", "assigned_branch", "activated_by", "activated_at"])

            messages.success(
                request,
                _("User activated successfully. Tenant, store, and branch access were assigned."),
            )
            return redirect("pending-users")

    context = {
        "tenant": tenant,
        "onboarding": onboarding,
        "form": form,
        "has_branches": has_branches,
    }
    return render(request, "tenancy/activate_user.html", context)


def transfer_inventory(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    tenant = _active_tenant(request)
    if not tenant:
        return redirect("select-tenant")

    if not can_transfer_stock(request.user, tenant, active_branch_id=request.session.get("active_branch_id")):
        messages.error(request, _("You do not have permission to transfer stock."))
        return redirect("home")

    scope, scope_obj, role = resolve_transfer_scope(
        request.user,
        tenant,
        active_branch_id=request.session.get("active_branch_id"),
    )
    if scope not in {"branch", "store"}:
        messages.error(request, _("Transfers are only allowed from a branch or store location."))
        return redirect("home")

    form = InventoryTransferForm(
        request.POST or None,
        tenant=tenant,
        fixed_from_scope=scope,
        fixed_from_store=scope_obj.get("store"),
        fixed_from_branch=scope_obj.get("branch"),
    )
    if request.method == "POST" and form.is_valid():
        product = form.cleaned_data["product"]
        from_scope = scope
        to_scope = form.cleaned_data["to_scope"]
        from_store = scope_obj.get("store")
        from_branch = scope_obj.get("branch")
        to_store = form.cleaned_data.get("to_store")
        to_branch = form.cleaned_data.get("to_branch")
        package_qty = safe_int(form.cleaned_data.get("package_qty"))
        item_qty = safe_int(form.cleaned_data.get("item_qty"))

        package_contain = safe_int(getattr(product, "package_contain", 1), 1)
        total_items = (package_qty * package_contain) + item_qty
        if total_items <= 0:
            messages.error(request, _("Quantity must be greater than 0."))
            return redirect("transfer-inventory")

        if to_scope == from_scope:
            messages.error(request, _("Transfers must be between a store and a branch."))
            return redirect("transfer-inventory")
        if to_scope == "store" and to_store and to_store.tenant_id != tenant.id:
            messages.error(request, _("Invalid destination store."))
            return redirect("transfer-inventory")
        if to_scope == "branch" and to_branch and to_branch.store.tenant_id != tenant.id:
            messages.error(request, _("Invalid destination branch."))
            return redirect("transfer-inventory")

        try:
            with transaction.atomic():
                _adjust_stock(
                    from_scope,
                    product,
                    -total_items,
                    tenant=tenant,
                    store=from_store,
                    branch=from_branch,
                )
                _adjust_stock(
                    to_scope,
                    product,
                    total_items,
                    tenant=tenant,
                    store=to_store,
                    branch=to_branch,
                )

                transfer = InventoryTransfer.objects.create(
                    tenant=tenant,
                    product=product,
                    from_scope=from_scope,
                    to_scope=to_scope,
                    from_store=from_store,
                    from_branch=from_branch,
                    to_store=to_store,
                    to_branch=to_branch,
                    package_qty=package_qty,
                    item_qty=item_qty,
                    total_items=total_items,
                    created_by=request.user,
                )

                InventoryMovement.objects.create(
                    tenant=tenant,
                    product=product,
                    scope=from_scope,
                    store=from_store,
                    branch=from_branch,
                    movement_type="transfer_out",
                    package_qty=package_qty,
                    item_qty=item_qty,
                    total_items=total_items,
                    transfer=transfer,
                    created_by=request.user,
                    note="Transfer out",
                )
                InventoryMovement.objects.create(
                    tenant=tenant,
                    product=product,
                    scope=to_scope,
                    store=to_store,
                    branch=to_branch,
                    movement_type="transfer_in",
                    package_qty=package_qty,
                    item_qty=item_qty,
                    total_items=total_items,
                    transfer=transfer,
                    created_by=request.user,
                    note="Transfer in",
                )

            messages.success(request, _("Transfer completed successfully."))
            return redirect("transfer-inventory")
        except ValueError as exc:
            messages.error(request, str(exc))

    context = {
        "form": form,
        "tenant": tenant,
        "from_scope": scope,
        "from_store": scope_obj.get("store"),
        "from_branch": scope_obj.get("branch"),
    }
    return render(request, "stock/transfer.html", context)

# views.py


def purchase(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    scope, scope_obj = _resolve_inventory_scope(request, tenant, branch)
    scope_store = scope_obj.get("store") if scope == "store" else (branch.store if branch else None)
    scope_branch = scope_obj.get("branch") if scope == "branch" else None
    form = PurchaseForm(tenant=tenant)
    if request.method == 'POST':
        form = PurchaseForm(request.POST, request.FILES, tenant=tenant)

        if form.is_valid():
            cd = form.cleaned_data
            package_contain = cd['package_contain']
            package_purchase_price = to_decimal(cd['package_purchase_price'])
            num_of_packages = cd['num_of_packages']
            package_sale_price_afn = to_decimal(cd['package_sale_price'])
            purchase_unit = cd['purchase_unit']
            currency_category = "usd" if purchase_unit and purchase_unit.code.lower() == "usd" else "afn"

            # Calculate USD equivalent of AFN sale price (for USD products)
            usd_package_sale_price = None
            rate = ExchangeRate.objects.filter(tenant=tenant).last()
            usd_rate = rate.usd_to_afn if rate else Decimal('1')

            if purchase_unit and purchase_unit.code.lower() == 'usd':
                usd_package_sale_price = (package_sale_price_afn / usd_rate).quantize(Decimal("0.01"))

            # Basic calculations
            total_package_price = (package_purchase_price * num_of_packages).quantize(Decimal("0.01"))
            stock = package_contain * num_of_packages
            num_items = stock % package_contain
            item_sale_price = (package_sale_price_afn / Decimal(package_contain)).quantize(Decimal("0.01"))

            product = form.save(commit=False)
            product.total_package_price = total_package_price
            product.stock = stock
            product.num_of_packages = num_of_packages
            product.num_items = num_items
            product.item_sale_price = item_sale_price
            product.usd_package_sale_price = usd_package_sale_price
            product.currency_category = currency_category
            product.tenant = tenant
            product.save()

            _set_stock(scope, product, stock, tenant=tenant, store=scope_obj.get("store"), branch=scope_obj.get("branch"))

            InventoryMovement.objects.create(
                tenant=tenant,
                product=product,
                scope=scope,
                store=scope_store,
                branch=scope_branch,
                movement_type="purchase",
                package_qty=num_of_packages,
                item_qty=num_items,
                total_items=stock,
                created_by=request.user,
                note="Purchase entry",
            )

            record_purchase_entry(
                tenant=tenant,
                total_cost=total_package_price,
                product=product,
                store=scope_store,
                branch=scope_branch,
                created_by=request.user,
                reference_id=f"PRODUCT-{product.id}",
            )

            messages.success(request, "Product added successfully!")
            return redirect('purchase')
        else:
            messages.error(request, f"Something went wrong. Please fix the below errors: {form.errors}")

    purchase = Products.objects.filter(tenant=tenant).order_by('-id')

    # Pagination
    p = Paginator(purchase, 14)
    page_number = request.GET.get('page')
    page_obj = p.get_page(page_number or 1)
    _apply_branch_stock(list(page_obj.object_list), branch)

    context = {
        'category': Category.objects.filter(tenant=tenant),
        'page_obj': page_obj,
        'num': range(1, 100),
        'form': form
    }
    return render(request, 'purchase/purchase.html', context)



def products_display(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    currency_filter = request.GET.get("currency", "all")
    product = Products.objects.filter(tenant=tenant).order_by('-id')
    if currency_filter == "usd":
        product = product.filter(currency_category="usd")
    elif currency_filter == "afn":
        product = product.filter(currency_category="afn")
    p = Paginator(product, 14)
    page_number = request.GET.get('page')
    try:
        page_obj = p.get_page(page_number)
    except PageNotAnInteger:
        page_obj = p.page(1)
    except EmptyPage:
        page_obj = p.page(p.num_pages)
    # paginator end
    scope, scope_obj = _resolve_inventory_scope(request, tenant, branch)
    _apply_scope_stock(
        list(page_obj.object_list),
        scope,
        tenant=tenant,
        store=scope_obj.get("store"),
        branch=scope_obj.get("branch"),
    )

    exchange_rate = ExchangeRate.objects.filter(tenant=tenant).last()
    exchange_form = ExchangeRateForm(instance=exchange_rate)
    if request.method == "POST":
        exchange_form = ExchangeRateForm(request.POST, instance=exchange_rate)
        if exchange_form.is_valid():
            rate = exchange_form.save(commit=False)
            rate.tenant = tenant
            rate.save()
            messages.success(request, _("Exchange rate has been updated successfully"))
            return redirect(f"{request.path}?currency=usd")
        else:
            messages.error(request, _("Something went wrong. Please try again"))

    context = {
        'page_obj': page_obj,
        'flag': 'list',
        'currency_filter': currency_filter,
        'exchange_rate': exchange_rate,
        'exchange_form': exchange_form,
        'usd_count': Products.objects.filter(tenant=tenant, currency_category="usd").count(),
        'afn_count': Products.objects.filter(tenant=tenant, currency_category="afn").count(),
        'can_transfer': can_transfer_stock(request.user, tenant, active_branch_id=request.session.get("active_branch_id")),
    }
    return render(request, 'purchase/product.html', context)

def update_products(request, pid):
    tenant = _active_tenant(request)
    product = get_object_or_404(Products, pk=pid, tenant=tenant)

    form = PurchaseForm(instance=product, tenant=tenant)
    if request.method == 'POST':
        form = PurchaseForm(request.POST, request.FILES, instance=product, tenant=tenant)
        if form.is_valid():
            package_purchase_price = form.cleaned_data['package_purchase_price']
            package_contain = form.cleaned_data.get('package_contain')
            num_of_packages = form.cleaned_data.get('num_of_packages')
            package_sale_price = form.cleaned_data.get('package_sale_price')
            purchase_unit = form.cleaned_data.get("purchase_unit")
            currency_category = "usd" if purchase_unit and purchase_unit.code.lower() == "usd" else "afn"

            total_package_price = int(num_of_packages) * int(package_purchase_price)
            total_items = int(package_contain) * int(num_of_packages)
            item_sale_price = round((package_sale_price / package_contain), 3) if package_contain else 0

            product = form.save(commit=False)
            product.total_items = total_items
            product.item_sale_price = item_sale_price
            product.total_package_price = total_package_price
            product.currency_category = currency_category
            product.save()

            messages.success(request, "Product updated successfully.")
            return redirect("products_display")
        else:
            messages.error(request, f"Form has error: {form.errors}")

    context = {
        'product': product,
        'form': form
    }
    return render(request, 'purchase/purchase.html', context)

def delete_products(request, pid):
    tenant = _active_tenant(request)
    product = get_object_or_404(Products, pk=pid, tenant=tenant)
    if product:
        product.delete()
        messages.success(request, _("Product deleted successfully"))
    return redirect("products_display")

def products_view(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    categories = Category.objects.filter(tenant=tenant)
    customer = request.session.get('customer', {})
    customer_list = []
    products_queryset = Products.objects.filter(tenant=tenant).select_related('category')

    products_filter = ProductsFilter(
        request.GET,
        request=request,
        queryset=products_queryset,
        tenant=tenant,
    )

    # Handle session customer data
    if customer:  
        customer_list = list(customer.values())[0]

    # # Pagination
    # paginator = Paginator(products_filter.qs, 10)  # Show 10 products per page
    # page_number = request.GET.get('page')
    # page_obj = paginator.get_page(page_number)
    products = list(products_filter.qs)
    _apply_branch_stock(products, branch)
    context = {
        'products': products,
        'categories': categories,
        'filter_form': products_filter,
        'customer': customer_list
    }
    return render(request, 'sale/product_view.html', context)

def check_customer(request):
    tenant = _active_tenant(request)
    code = request.GET.get("code")
    try:
        existing_customer = Customer.objects.get(id=code, tenant=tenant)
        customer_session = request.session.get('customer', {})
        customer_session[existing_customer.id] = existing_customer.name
        request.session['customer'] = customer_session
        form = CustomerForm(instance=existing_customer)
    except Customer.DoesNotExist:
        form = CustomerForm(initial={"code": code})
    return render(request, "partials/_customer_form.html", {"form": form})

def create_customer(request):
    tenant = _active_tenant(request)
    form = CustomerForm()
    if request.method == 'POST':
        if 'ignore' in request.POST:
            customer, created = Customer.objects.get_or_create(
                tenant=tenant,
                name="متفرقه",
                phone="0000000",  # Put phone in quotes if it's a CharField
                defaults={"address": "------"},
            )

            existing_customer = get_object_or_404(Customer, pk=customer.id)
            customer_session = request.session.get('customer', {})
            customer_session[existing_customer.id] = existing_customer.name
            request.session['customer'] = customer_session
            return redirect('products-view')
            
        else:
            form = CustomerForm(request.POST)
            if form.is_valid():
                new_customer = form.save(commit=False)
                new_customer.tenant = tenant
                new_customer.save()
                # Add to session
                customer_session = request.session.get('customer', {})
                customer_session[new_customer.id] = new_customer.name
                request.session['customer'] = customer_session
                # Notify user
                messages.success(request, _("Customer has been added successfully."))
                return redirect('products-view')
            else:
                messages.error(request, _("Something went wrong. Please fix the errors below."))
                print(f"Form errors: {form.errors}")

                
    else:
        form=CustomerForm()
        
    context = {
        'form':form
    }
    return render(request, 'sale/product_view.html', context)

def old_customer(request, pk):
    tenant = _active_tenant(request)
    customer = get_object_or_404(Customer, pk=pk, tenant=tenant)
    customer_session = request.session.get('customer', {})
    customer_session[customer.id] = customer.name
    request.session['customer'] = customer_session
    messages.success(request, _("Customer has been selected successfully."))
    return redirect('products-view')

def search_products(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    search = request.GET.get('search')
    products = Products.objects.filter(tenant=tenant).select_related('category')
    product_list = (
        products.filter(category__name__istartswith=search) | products.filter(name__istartswith=search)
    )
    product_list = list(product_list)
    _apply_branch_stock(product_list, branch)
    context = {
        'products':product_list
    }
    return render(request, 'partials/_search_list.html', context)


def remove_cart_item(request, pid):
    cart = request.session.get('cart', {})
    # Find the key of the item with the specified product_id
    item_key_to_remove = None
    for item_key, item in cart.items():
        if str(item['product_id']) == pid:
            item_key_to_remove = item_key
            break

    # Remove the item from the cart if found
    if item_key_to_remove:
        del cart[item_key_to_remove]

        # Update the session
        request.session['cart'] = cart
    return redirect('cart-view')

# Add to Cart
def add_to_cart(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON body'}, status=400)

        # Extract data
        product_id = data.get('product_id')
        item_quantity = data.get('item_quantity', 0)
        package_quantity = data.get('package_quantity', 0)
        item_price = data.get('item_price', 0)
        package_price = data.get('package_price', 0)

        # Validate product existence
        tenant = _active_tenant(request)
        product = Products.objects.filter(id=product_id, tenant=tenant).first()
        if not product:
            return JsonResponse({'status': 'error', 'message': 'Product not found'}, status=404)

        # Retrieve cart from session and update it
        cart = request.session.get('cart', {})
        cart[str(product_id)] = {
            'product_id': product_id,
            'item_quantity': item_quantity,
            'package_quantity': package_quantity,
            'item_price': item_price,
            'package_price': package_price,
        }
        request.session['cart'] = cart  # Save updated cart back into session

        return JsonResponse({"status": 200, "message": "success", "cart_length": len(cart)})
    
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def print_invoice(request, sales_id):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    sales_details = get_object_or_404(SalesDetails, bill_number=sales_id, tenant=tenant, branch=branch)
    
    sales_product = SalesProducts.objects.filter(sale_detail=sales_details)

    calculate = sales_product.aggregate(
        total_amount=Sum('total_price')
    )
    context = {
        'sales_details':sales_details,
        'sales_products':sales_product,
        'calculate':calculate
    }
    return render(request, 'partials/_print_invoice.html', context)

def cart_view(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    if not branch:
        messages.error(request, _("Select a branch before checking out sales."))
        return redirect("select-branch")

    # Retrieve cart and customer from session
    cart = request.session.get('cart', {})
    customer_session = request.session.get('customer', {})
    cart_details = []
    stock_updates = []
    grand_total = Decimal("0.00")
    pre_unpaid_amount = Decimal("0.00")
    total = Decimal("0.00")

    if not cart:
        return render(request, 'sale/cart_view.html', {'cart_details': [], 'grand_total': 0, 'customer': None})

    # Fetch all products at once
    product_ids = [item['product_id'] for item in cart.values()]
    products = Products.objects.filter(pk__in=product_ids, tenant=tenant).select_related()
    product_mapping = {product.id: product for product in products}
    branch_stocks = BranchStock.objects.filter(branch=branch, product_id__in=product_ids)
    stock_mapping = {stock.product_id: stock for stock in branch_stocks}
    missing_ids = [pid for pid in product_ids if pid not in stock_mapping]
    if missing_ids:
        BranchStock.objects.bulk_create(
            [BranchStock(branch=branch, product_id=pid, stock=0, num_of_packages=0, num_items=0) for pid in missing_ids],
            ignore_conflicts=True,
        )
        branch_stocks = BranchStock.objects.filter(branch=branch, product_id__in=product_ids)
        stock_mapping = {stock.product_id: stock for stock in branch_stocks}

    # Build cart details
    for item in cart.values():
        product = product_mapping.get(safe_int(item.get('product_id')))
        if not product:
            continue

        item_quantity = safe_int(item.get('item_quantity'))
        package_quantity = safe_int(item.get('package_quantity'))
        item_price = to_decimal(item.get('item_price'))
        package_price = to_decimal(item.get('package_price'))

        # Calculate stock updates
        package_contain = safe_int(product.package_contain, 1)  # Default to 1 to avoid division by zero
        sold_stock = (package_quantity * package_contain) + item_quantity
        stock_row = stock_mapping.get(product.id)
        current_stock = safe_int(stock_row.stock if stock_row else 0)
        new_stock = current_stock - sold_stock
        if new_stock < 0:
            messages.error(request, _(f"Insufficient stock for {product.name}."))
            return redirect("products-view")
        if stock_row:
            stock_row.stock = new_stock
            stock_row.num_of_packages = new_stock // package_contain
            stock_row.num_items = new_stock % package_contain
            stock_updates.append(stock_row)
        product.stock = current_stock
        product.num_of_packages = safe_int(stock_row.num_of_packages if stock_row else 0)
        product.num_items = safe_int(stock_row.num_items if stock_row else 0)

        # Calculate subtotal and cart details
        sub_total = to_decimal((Decimal(item_quantity) * item_price) + (Decimal(package_quantity) * package_price))
        grand_total += sub_total
        cart_details.append({
            'product': product,
            'item_quantity': item_quantity,
            'package_quantity': package_quantity,
            'item_price': item_price,
            'package_price': package_price,
            'sub_total': sub_total,
            'sold_stock': sold_stock,
        })

    # Retrieve customer instance
    customer_instance = None
    if customer_session:
        customer_pk = list(customer_session.keys())[0]
        customer_instance = Customer.objects.filter(pk=customer_pk, tenant=tenant).first() 
        if customer_instance:
            pre_unpaid = SalesDetails.objects.filter(customer=customer_instance, tenant=tenant, branch=branch).aggregate(
                total_unpaid=Sum('unpaid_amount')
            )
            pre_unpaid_amount = to_decimal(pre_unpaid['total_unpaid'] or 0)
    total = grand_total
    grand_total = grand_total + pre_unpaid_amount
    # Handle sale submission
    if request.method == 'POST':
        try:
            paid_amount = to_decimal(request.POST.get('paid', 0))
            if paid_amount < 0:
                messages.error(request, _("Paid amount cannot be negative."))
                return redirect("cart-view")
            if paid_amount > grand_total:
                messages.error(request, _("Paid amount cannot be greater than the grand total."))
                return redirect("cart-view")
            unpaid_amount = grand_total - paid_amount
           
            SalesDetails.objects.filter(customer=customer_instance, tenant=tenant, branch=branch, unpaid_amount__gt=0).update(unpaid_amount=Decimal("0.00"))
            # Create SalesDetails instance
            with transaction.atomic():
                sales_details = SalesDetails.objects.create(
                    user = request.user,
                    tenant=tenant,
                    branch=branch,
                    customer=customer_instance,
                    total_amount=grand_total,
                    paid_amount=paid_amount,
                    unpaid_amount=unpaid_amount,
                )
                
                # Bulk update product stock
                if stock_updates:
                    BranchStock.objects.bulk_update(stock_updates, ['stock', 'num_of_packages', 'num_items'])

                # Bulk create SalesProducts
                sales_products = [
                    SalesProducts(
                        sale_detail=sales_details,
                        product=item['product'],  # Directly use the product instance
                        item_price=item['item_price'],
                        package_price=item['package_price'],
                        item_qty=item['item_quantity'],
                        package_qty=item['package_quantity'],
                        total_price=item['sub_total'],
                    ) for item in cart_details
                ]
                SalesProducts.objects.bulk_create(sales_products)

                cogs_total = Decimal("0.00")
                for item in cart_details:
                    product = item["product"]
                    package_contain = max(safe_int(getattr(product, "package_contain", 1), 1), 1)
                    unit_cost = to_decimal(product.package_purchase_price or 0) / Decimal(package_contain)
                    cogs_total += to_decimal(Decimal(item["sold_stock"]) * unit_cost)

                record_sale_entry(
                    tenant=tenant,
                    sale_total=grand_total,
                    paid_amount=paid_amount,
                    unpaid_amount=unpaid_amount,
                    cogs_total=cogs_total,
                    store=branch.store,
                    branch=branch,
                    created_by=request.user,
                    reference_id=sales_details.bill_number,
                )

            # Clear cart after successful sale
            request.session['cart'] = {}
            request.session['customer'] = {}
            messages.success(request, "Products have been sold successfully!")
            return redirect("print-invoice", sales_details.bill_number)
        except Exception as e:
            # Roll back the transaction and handle the error gracefully
            messages.error(request, f"An error occurred: {str(e)}")

    context = {
        'cart_details': cart_details,
        'grand_total': grand_total,
        'pre_unpaid_amount':pre_unpaid_amount,
        'customer': customer_instance,
        'total':total
    }
    return render(request, 'sale/cart_view.html', context)

def sold_products_view(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    sales_details = (
        SalesDetails.objects
        .select_related("customer")
        .prefetch_related("sale_detail")
        .filter(tenant=tenant, branch=branch)
    )
    if request.method == 'POST':
        bill_number = request.POST.get('bill-number')
        if bill_number:
            sales_details=sales_details.filter(bill_number=bill_number)

    context = {
        'sold_products':sales_details
    }
    return render(request, 'sale/sold_products_view.html', context)

def sold_product_detail(request, pk):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    sales_id = get_object_or_404(SalesDetails, pk=pk, tenant=tenant, branch=branch)
   
    sales_products = SalesProducts.objects.filter(sale_detail=pk).select_related('product')

    context = {
        'sales_products':sales_products,
        'sales_info':sales_id,
    }
    return render(request, 'sale/sold_products_detail.html', context)

def return_items(request, pk):
    # Get the returned product or raise 404
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    returned_product = get_object_or_404(
        SalesProducts,
        id=pk,
        sale_detail__tenant=tenant,
        sale_detail__branch=branch,
    )
    
    # Calculate new quantities
    returned_pkg = safe_int(returned_product.package_qty)
    returned_item = safe_int(returned_product.item_qty)
    product = returned_product.product  # Get the related product
    
    # Use atomic transaction to prevent race conditions
    with transaction.atomic():
        stock_row, created = BranchStock.objects.get_or_create(
            branch=branch,
            product=product,
            defaults={"stock": 0, "num_of_packages": 0, "num_items": 0},
        )
        stock_row.num_of_packages = safe_int(stock_row.num_of_packages) + returned_pkg
        stock_row.num_items = safe_int(stock_row.num_items) + returned_item
        stock_row.stock = (stock_row.num_of_packages * safe_int(product.package_contain)) + stock_row.num_items
        stock_row.save()
        returned_product.delete()
        return HttpResponse('', headers={'HX-Trigger': 'returnSuccess'})

    



# dashboard contaner view
def income(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    store = branch.store if branch else None
    form = OtherIncomeForm()
    today_date = date.today()
    other_income = OtherIncome.objects.filter(tenant=tenant, branch=branch, date_created=today_date)
    if request.method == 'POST':
        form = OtherIncomeForm(request.POST)
        if form.is_valid():
            income_obj = form.save(commit=False)
            income_obj.tenant = tenant
            income_obj.branch = branch
            income_obj.save()
            record_other_income_entry(
                tenant=tenant,
                amount=income_obj.amount,
                store=store,
                branch=branch,
                created_by=request.user,
                reference_id=income_obj.id,
                memo=income_obj.source,
            )
            messages.success(request, _("Income has been added successfully"))
        else:
            messages.error(request, _("Something went wrong. Please try again"))
    context = {
        'form':form,
        'other_income':other_income
    }
    return render(request, 'partials/management/_income-view.html', context)

def expense(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    store = branch.store if branch else None
    form = ExpenseForm()
    today_date = date.today()
    expenses = Expense.objects.filter(tenant=tenant, branch=branch, date_created=today_date).order_by('-id')
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense_obj = form.save(commit=False)
            expense_obj.tenant = tenant
            expense_obj.branch = branch
            expense_obj.save()
            record_expense_entry(
                tenant=tenant,
                amount=expense_obj.amount,
                store=store,
                branch=branch,
                created_by=request.user,
                reference_id=expense_obj.id,
                memo=expense_obj.category,
            )
            messages.success(request, _("Expense has been added successfully"))
        else:
            messages.error(request, _("Something went wrong. Please try again"))
    context = {
        'form': form,
        'expenses': expenses
    }
    return render(request, 'partials/management/_expense-view.html', context)

def summary(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    sales = SalesDetails.objects.filter(tenant=tenant, branch=branch).order_by("-created_at")
    sales_filter = SalesDetailsFilter(request.GET, queryset=sales)
    filtered_sales = sales_filter.qs
    totals = filtered_sales.aggregate(
        total_paid_amount=Sum("paid_amount"),
        total_unpaid_amount=Sum("unpaid_amount"),
        total_sale_value=Sum(
            ExpressionWrapper(
                F("paid_amount") + F("unpaid_amount"),
                output_field=DecimalField(),
            )
        ),
    )
    total_customers = filtered_sales.aggregate(total_customer=Count("customer", distinct=True))

    from_date = _parse_jalali_date(request.GET.get("from_date", ""))
    to_date = _parse_jalali_date(request.GET.get("to_date", ""))

    income_qs = OtherIncome.objects.filter(tenant=tenant, branch=branch)
    expense_qs = Expense.objects.filter(tenant=tenant, branch=branch)

    if from_date:
        income_qs = income_qs.filter(date_created__gte=from_date)
        expense_qs = expense_qs.filter(date_created__gte=from_date)
    if to_date:
        income_qs = income_qs.filter(date_created__lte=to_date)
        expense_qs = expense_qs.filter(date_created__lte=to_date)

    income_totals = income_qs.aggregate(total_amount=Sum("amount"))
    expense_totals = expense_qs.aggregate(total_amount=Sum("amount"))

    total_paid = to_decimal(totals["total_paid_amount"] or 0)
    total_unpaid = to_decimal(totals["total_unpaid_amount"] or 0)
    total_value = to_decimal(totals["total_sale_value"] or 0)
    total_customer = total_customers["total_customer"] or 0
    total_income = to_decimal(income_totals["total_amount"] or 0)
    total_expense = to_decimal(expense_totals["total_amount"] or 0)
    net_balance = total_income - total_expense

    daily_sales = list(
        filtered_sales.values("created_at__date")
        .annotate(
            sales=Sum("total_amount"),
            paid=Sum("paid_amount"),
            unpaid=Sum("unpaid_amount"),
        )
        .order_by("created_at__date")
    )
    if len(daily_sales) > 31:
        daily_sales = daily_sales[-31:]

    trend_labels = [row["created_at__date"].isoformat() for row in daily_sales]
    trend_sales = [float(to_decimal(row["sales"] or 0)) for row in daily_sales]
    trend_paid = [float(to_decimal(row["paid"] or 0)) for row in daily_sales]
    trend_unpaid = [float(to_decimal(row["unpaid"] or 0)) for row in daily_sales]

    top_products_rows = list(
        SalesProducts.objects.filter(sale_detail__in=filtered_sales)
        .values("product__name")
        .annotate(total=Sum("total_price"))
        .order_by("-total")[:6]
    )
    top_product_labels = [row["product__name"] or _("Unknown Product") for row in top_products_rows]
    top_product_values = [float(to_decimal(row["total"] or 0)) for row in top_products_rows]

    revenue_vs_cost_labels = [_("Sales"), _("Other Income"), _("Expense"), _("Net Position")]
    revenue_vs_cost_values = [
        float(total_value),
        float(total_income),
        float(total_expense),
        float(net_balance),
    ]

    context = {
        "sales": filtered_sales,
        "filter": sales_filter,
        "total_paid": total_paid,
        "total_unpaid": total_unpaid,
        "total_value": total_value,
        "total_customer": total_customer,
        "total_income": total_income,
        "total_expense": total_expense,
        "net_balance": net_balance,
        "trend_labels": trend_labels,
        "trend_sales": trend_sales,
        "trend_paid": trend_paid,
        "trend_unpaid": trend_unpaid,
        "payment_mix": [float(total_paid), float(total_unpaid)],
        "top_product_labels": top_product_labels,
        "top_product_values": top_product_values,
        "revenue_cost_labels": revenue_vs_cost_labels,
        "revenue_cost_values": revenue_vs_cost_values,
    }
    return render(request, "partials/management/_summary-view.html", context)


def financial_reports(request):
    tenant = _active_tenant(request)
    if not tenant:
        return redirect("select-tenant")

    ensure_default_accounts(tenant)
    scope_data = _resolve_reporting_scope(request, tenant)
    scope = scope_data.get("scope")
    if not scope:
        messages.error(request, _("No reporting scope available for your account."))
        return redirect("home")

    from_date = _parse_jalali_date(request.GET.get("from_date", ""))
    to_date = _parse_jalali_date(request.GET.get("to_date", ""))

    sales_qs = _apply_branch_scope(SalesDetails.objects.filter(tenant=tenant), scope_data)
    income_qs = _apply_branch_scope(OtherIncome.objects.filter(tenant=tenant), scope_data)
    expense_qs = _apply_branch_scope(Expense.objects.filter(tenant=tenant), scope_data)
    journal_qs = _apply_journal_scope(
        JournalEntry.objects.filter(tenant=tenant).select_related("store", "branch", "created_by"),
        scope_data,
    )

    if from_date:
        sales_qs = sales_qs.filter(created_at__date__gte=from_date)
        income_qs = income_qs.filter(date_created__gte=from_date)
        expense_qs = expense_qs.filter(date_created__gte=from_date)
        journal_qs = journal_qs.filter(entry_date__gte=from_date)
    if to_date:
        sales_qs = sales_qs.filter(created_at__date__lte=to_date)
        income_qs = income_qs.filter(date_created__lte=to_date)
        expense_qs = expense_qs.filter(date_created__lte=to_date)
        journal_qs = journal_qs.filter(entry_date__lte=to_date)

    sales_total = to_decimal(sales_qs.aggregate(total=Sum("total_amount"))["total"] or 0)
    paid_total = to_decimal(sales_qs.aggregate(total=Sum("paid_amount"))["total"] or 0)
    unpaid_total = to_decimal(sales_qs.aggregate(total=Sum("unpaid_amount"))["total"] or 0)

    journal_lines = JournalLine.objects.filter(journal_entry__in=journal_qs).select_related("account", "journal_entry")
    ledger_rows = account_balances(journal_lines)
    account_by_code = {row["code"]: row for row in ledger_rows}

    cash_balance = to_decimal(account_by_code.get("1000", {}).get("balance", 0))
    receivable_balance = to_decimal(account_by_code.get("1100", {}).get("balance", 0))
    inventory_balance = to_decimal(account_by_code.get("1200", {}).get("balance", 0))
    payable_balance = to_decimal(account_by_code.get("2000", {}).get("balance", 0))
    sales_revenue = to_decimal(account_by_code.get("4000", {}).get("balance", 0))
    other_income_value = to_decimal(account_by_code.get("4100", {}).get("balance", 0))
    cogs_total = to_decimal(account_by_code.get("5000", {}).get("balance", 0))
    operating_expense = to_decimal(account_by_code.get("6100", {}).get("balance", 0))

    gross_profit = sales_revenue - cogs_total
    net_profit = (sales_revenue + other_income_value) - (cogs_total + operating_expense)

    assets_total = sum(
        (to_decimal(row["balance"]) for row in ledger_rows if row["account_type"] == "asset"),
        Decimal("0.00"),
    )
    liabilities_total = sum(
        (to_decimal(row["balance"]) for row in ledger_rows if row["account_type"] == "liability"),
        Decimal("0.00"),
    )

    purchase_total = to_decimal(
        journal_lines.filter(
            account__code="1200",
            journal_entry__reference_type="purchase",
        ).aggregate(total=Sum("debit"))["total"] or 0
    )

    transactions = []
    for entry in journal_qs.prefetch_related("lines__account")[:60]:
        total_amount = sum((to_decimal(line.debit) for line in entry.lines.all()), Decimal("0.00"))
        transactions.append(
            {
                "entry": entry,
                "total": total_amount,
            }
        )

    sales_daily_rows = list(
        sales_qs.values("created_at__date").annotate(total=Sum("total_amount")).order_by("created_at__date")
    )
    sales_daily_map = {row["created_at__date"]: float(to_decimal(row["total"] or 0)) for row in sales_daily_rows}

    purchase_daily_rows = list(
        journal_lines.filter(
            account__code="1200",
            journal_entry__reference_type="purchase",
        )
        .values("journal_entry__entry_date")
        .annotate(total=Sum("debit"))
        .order_by("journal_entry__entry_date")
    )
    purchase_daily_map = {row["journal_entry__entry_date"]: float(to_decimal(row["total"] or 0)) for row in purchase_daily_rows}

    income_daily_rows = list(
        journal_lines.filter(account__code="4100")
        .values("journal_entry__entry_date")
        .annotate(total=Sum("credit"))
        .order_by("journal_entry__entry_date")
    )
    income_daily_map = {row["journal_entry__entry_date"]: float(to_decimal(row["total"] or 0)) for row in income_daily_rows}

    cogs_daily_rows = list(
        journal_lines.filter(account__code="5000")
        .values("journal_entry__entry_date")
        .annotate(total=Sum("debit"))
        .order_by("journal_entry__entry_date")
    )
    cogs_daily_map = {row["journal_entry__entry_date"]: float(to_decimal(row["total"] or 0)) for row in cogs_daily_rows}

    expense_daily_rows = list(
        journal_lines.filter(account__code="6100")
        .values("journal_entry__entry_date")
        .annotate(total=Sum("debit"))
        .order_by("journal_entry__entry_date")
    )
    expense_daily_map = {row["journal_entry__entry_date"]: float(to_decimal(row["total"] or 0)) for row in expense_daily_rows}

    all_dates = sorted(
        set(sales_daily_map.keys())
        | set(purchase_daily_map.keys())
        | set(income_daily_map.keys())
        | set(cogs_daily_map.keys())
        | set(expense_daily_map.keys())
    )
    if not all_dates:
        range_end = to_date or timezone.localdate()
        range_start = from_date or (range_end - timedelta(days=13))
        all_dates = [range_start + timedelta(days=i) for i in range((range_end - range_start).days + 1)]
    if len(all_dates) > 31:
        all_dates = all_dates[-31:]

    trend_labels = [d.isoformat() for d in all_dates]
    trend_sales = [sales_daily_map.get(d, 0.0) for d in all_dates]
    trend_purchase = [purchase_daily_map.get(d, 0.0) for d in all_dates]
    trend_expense = [expense_daily_map.get(d, 0.0) for d in all_dates]
    trend_net = [
        (sales_daily_map.get(d, 0.0) + income_daily_map.get(d, 0.0))
        - (expense_daily_map.get(d, 0.0) + cogs_daily_map.get(d, 0.0))
        for d in all_dates
    ]

    reference_choices = dict(JournalEntry.REFERENCE_TYPE_CHOICES)
    trx_type_rows = list(journal_qs.values("reference_type").annotate(count=Count("id")).order_by("-count"))
    trx_type_labels = [reference_choices.get(row["reference_type"], row["reference_type"]) for row in trx_type_rows]
    trx_type_values = [row["count"] for row in trx_type_rows]

    ledger_top_rows = sorted(ledger_rows, key=lambda row: abs(to_decimal(row["balance"])), reverse=True)[:7]
    ledger_top_labels = [f'{row["code"]} {row["name"]}' for row in ledger_top_rows]
    ledger_top_values = [float(to_decimal(row["balance"])) for row in ledger_top_rows]

    context = {
        "scope": scope,
        "scope_store": scope_data.get("store"),
        "scope_branch": scope_data.get("branch"),
        "store_options": scope_data.get("store_options"),
        "branch_options": scope_data.get("branch_options"),
        "can_tenant_scope": scope_data.get("can_tenant_scope"),
        "sales_total": sales_total,
        "paid_total": paid_total,
        "unpaid_total": unpaid_total,
        "purchase_total": purchase_total,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
        "cash_balance": cash_balance,
        "receivable_balance": receivable_balance,
        "inventory_balance": inventory_balance,
        "payable_balance": payable_balance,
        "assets_total": assets_total,
        "liabilities_total": liabilities_total,
        "sales_revenue": sales_revenue,
        "other_income_value": other_income_value,
        "cogs_total": cogs_total,
        "operating_expense": operating_expense,
        "manual_income_total": to_decimal(income_qs.aggregate(total=Sum("amount"))["total"] or 0),
        "manual_expense_total": to_decimal(expense_qs.aggregate(total=Sum("amount"))["total"] or 0),
        "ledger_rows": ledger_rows,
        "transactions": transactions,
        "trend_labels": trend_labels,
        "trend_sales": trend_sales,
        "trend_purchase": trend_purchase,
        "trend_expense": trend_expense,
        "trend_net": trend_net,
        "pnl_labels": [_("Sales Revenue"), _("Other Income"), _("COGS"), _("Operating Expense")],
        "pnl_values": [
            float(sales_revenue),
            float(other_income_value),
            float(cogs_total),
            float(operating_expense),
        ],
        "asset_liability_labels": [_("Assets"), _("Liabilities")],
        "asset_liability_values": [float(assets_total), float(liabilities_total)],
        "trx_type_labels": trx_type_labels,
        "trx_type_values": trx_type_values,
        "ledger_top_labels": ledger_top_labels,
        "ledger_top_values": ledger_top_values,
    }
    return render(request, "partials/management/_financial_reports.html", context)


def returned(request):
    bill_query = request.GET.get('bill')
    customer_query = request.GET.get('customer')
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    sales = SalesDetails.objects.select_related('customer').filter(tenant=tenant, branch=branch).order_by('-created_at')
    if bill_query:
        sales = sales.filter(bill_number__icontains=bill_query)
    if customer_query:
        sales = sales.filter(customer__name__icontains=customer_query)
    recent_sales = sales[:30]
    context = {
        "recent_sales": recent_sales,
        "bill_query": bill_query or "",
        "customer_query": customer_query or "",
    }
    return render(request, 'partials/management/_return-view.html', context)

def base_unit(request):
    tenant = _active_tenant(request)
    form = BaseUnitForm(tenant=tenant)
    base_units = (
        BaseUnit.objects.filter(tenant=tenant)
        if tenant and BaseUnit.objects.filter(tenant=tenant).exists()
        else BaseUnit.objects.filter(tenant__isnull=True)
    )
    if request.method == 'POST':
        form = BaseUnitForm(request.POST, tenant=tenant)
        if form.is_valid():
            unit = form.save(commit=False)
            unit.tenant = tenant
            unit.save()
            messages.success(request, _("Unit has been saved successfully"))
            return redirect('base-unit')
        else:
            messages.error(request, _("Something went wrong. Please try again"))
    else:
        form = form
    context = {
        'form':form,
        'base_units':base_units
    }
    return render(request, 'partials/management/_base_unit-view.html',context)

def update_base_unit(request, unit_id):
    tenant = _active_tenant(request)
    baseunit = get_object_or_404(BaseUnit, pk=unit_id, tenant=tenant)
    base_units = BaseUnit.objects.filter(tenant=tenant)
    if request.method == 'POST':
        form = BaseUnitForm(request.POST, instance=baseunit, tenant=tenant)
        if form.is_valid():
            form.save()
            messages.success(request, _("Unit has been updated successfully"))
            return redirect('base-unit')
        else:
            messages.error(request, _("Something went wrong. Please try again"))
    else:
        form = BaseUnitForm(instance=baseunit, tenant=tenant)

    context = {
        'form': form,
        'base_units': base_units
    }
    return render(request, 'partials/management/_base_unit-view.html', context)

def delete_base_unit(request, unit_id):
    tenant = _active_tenant(request)
    baseunit = get_object_or_404(BaseUnit, pk=unit_id, tenant=tenant)
    # Delete the object
    deleted_count = baseunit.delete()  # delete() returns (number_of_deleted_objects, details)
    # Check if the object was deleted successfully
    if deleted_count:
        messages.success(request, _("Unit has been deleted successfully"))
    else:
        messages.error(request, _("Unable to delete the unit"))
    
    # Redirect to the base-unit page
    return redirect('base-unit')

# stock management view

def stock_management(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    currency_filter = request.GET.get('currency')

    products = Products.objects.filter(tenant=tenant).order_by('-id')

    if currency_filter == 'usd':
        products = products.filter(purchase_unit__code__iexact='usd')
    elif currency_filter == 'afn':
        products = products.exclude(purchase_unit__code__iexact='usd')
    else:
        products = products.all()  # No filter applied

    # Apply pagination

    p = Paginator(products, 14)
    page_number = request.GET.get('page')
    try:
        page_obj = p.get_page(page_number)
    except PageNotAnInteger:
        page_obj = p.page(1)
    except EmptyPage:
        page_obj = p.page(p.num_pages)
    _apply_branch_stock(list(page_obj.object_list), branch)
    exchange_rate = ExchangeRate.objects.filter(tenant=tenant).last()
    exchange_form = ExchangeRateForm(instance=exchange_rate)
    if request.method == 'POST':
        exchange_form = ExchangeRateForm(request.POST, instance=exchange_rate)
        if exchange_form.is_valid():
            rate = exchange_form.save(commit=False)
            rate.tenant = tenant
            rate.save()
            messages.success(request, _("Exchange rate has been updated successfully"))
        else:
            messages.error(request, _("Something went wrong. Please try again"))
            exchange_form= ExchangeRateForm(instance=exchange_rate)
    

    context = {
        'page_obj': page_obj,
        'flag': 'list',
        'currency_filter': currency_filter,
        'exchange_form': exchange_form,
    }
    return render(request, 'partials/management/_stock_management.html', context)



def customer(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    customers = Customer.objects.filter(tenant=tenant)
    # Add customer sales details (paid, unpaid, bill count) for each customer
    if request.method == 'POST':
        phone = request.POST.get('phone')
        customers = customers.filter(phone=phone)
    customer_data = []
    for customer in customers:
        sales_data = SalesDetails.objects.filter(customer=customer, tenant=tenant, branch=branch).aggregate(
            total_amount=Sum('total_amount'),
            total_paid=Sum('paid_amount'),
            total_unpaid=Sum('unpaid_amount'),
            bill_count=Count('bill_number')
        )
        customer_data.append({
            'customer': customer,
            'total_amount':sales_data['total_amount'] or 0, 
            'total_paid': sales_data['total_paid'] or 0,  # Default to 0 if None
            'total_unpaid': sales_data['total_unpaid'] or 0,  # Default to 0 if None
            'bill_count': sales_data['bill_count'],
        })
    

    context = {
        'customer_data':customer_data
    }
    return render(request, 'partials/management/_customer-view.html', context)

def sales_dashboard(request):
    return redirect('summary')




def create_payment(request, cid):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    customer = get_object_or_404(Customer, pk=cid, tenant=tenant)

    sales_details = (
        SalesDetails.objects
        .filter(customer=customer, tenant=tenant, branch=branch)
        .order_by("-id")
    )

    # totals for UI + payment box
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
                return redirect("create-payment", cid=customer.id)

            with transaction.atomic():
                # Save payment + attach customer
                payment = form.save(commit=False)
                payment.customer = customer
                payment.tenant = tenant
                payment.branch = branch
                payment.save()

                # Lock and update the LAST SalesDetails record only (overall unpaid stored there)
                last_sale = (
                    SalesDetails.objects
                    .select_for_update()
                    .filter(customer=customer, tenant=tenant, branch=branch)
                    .order_by("-id")
                    .first()
                )

                if not last_sale:
                    messages.error(request, "No sales record found for this customer.")
                    return redirect("create-payment", cid=customer.id)

                current_unpaid = to_decimal(last_sale.unpaid_amount or 0)

                if paid_amount > current_unpaid:
                    messages.error(request, f"Payment cannot be greater than unpaid amount ({current_unpaid}).")
                    return redirect("create-payment", cid=customer.id)

                last_sale.unpaid_amount = current_unpaid - paid_amount

                # Optional: also increase paid_amount on last_sale (if you use it)
                if last_sale.paid_amount is None:
                    last_sale.paid_amount = Decimal("0.00")
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
            return redirect("create-payment", cid=customer.id)
    else:
        form = CustomerPaymentForm()

    context = {
        "customer": customer,
        "sales_details": sales_details,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_due": total_due,
        "has_unpaid": total_due > 0,
        "form": form,
    }
    return render(request, "partials/management/_customer-account.html", context)






# Bar code scanner view
@csrf_exempt
def get_product_by_barcode(request):
    if request.method == 'POST':
        barcode = request.POST.get('barcode')
        if not barcode:
            return JsonResponse({'status': 'error', 'message': 'No barcode provided'}, status=400)

        tenant = _active_tenant(request)
        product = Products.objects.filter(code=barcode, tenant=tenant).first()
        if not product:
            return JsonResponse({'status': 'error', 'message': 'Product not found'}, status=404)

        return JsonResponse({
            'status': 'success',
            'product': {
                'id': product.id,
                'item_price': float(to_decimal(product.item_sale_price)),
                'package_price': float(to_decimal(product.package_sale_price)),
                'name': product.name,
            }
        })

    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=400)


def scanner_view(request):
    customer = request.session.get('customer', {})
    customer_list = []
    # Handle session customer data
    if customer:  
        customer_list = list(customer.values())[0]
    context = {
        'customer': customer_list
    }
    return render(request, 'sale/scanner_view.html',context)

# cart fragment for cart view

def cart_fragment(request):
    tenant = _active_tenant(request)
    branch = _active_branch(request)
    cart = request.session.get('cart', {})
    customer_session = request.session.get('customer', {})
    cart_details = []
    grand_total = Decimal("0.00")

    if not cart:
        html = render_to_string('partials/_cart_table.html', {
            'cart_details': [],
            'grand_total': Decimal("0.00"),
            'customer': None
        }, request=request)
        return JsonResponse({'html': html})

    # Reuse logic from cart_view
    product_ids = [item['product_id'] for item in cart.values()]
    products = Products.objects.filter(pk__in=product_ids, tenant=tenant)
    product_mapping = {product.id: product for product in products}
    branch_stocks = BranchStock.objects.filter(branch=branch, product_id__in=product_ids)
    stock_mapping = {stock.product_id: stock for stock in branch_stocks}

    for item in cart.values():
        product = product_mapping.get(safe_int(item.get('product_id')))
        if not product:
            continue

        item_quantity = safe_int(item.get('item_quantity'))
        package_quantity = safe_int(item.get('package_quantity'))
        item_price = to_decimal(item.get('item_price'), Decimal("0.00"))
        package_price = to_decimal(item.get('package_price'), Decimal("0.00"))

        stock_row = stock_mapping.get(product.id)
        product.stock = safe_int(stock_row.stock if stock_row else 0)

        sub_total = to_decimal((Decimal(item_quantity) * item_price) + (Decimal(package_quantity) * package_price))
        grand_total += sub_total
        cart_details.append({
            'product': product,
            'item_quantity': item_quantity,
            'package_quantity': package_quantity,
            'item_price': item_price,
            'package_price': package_price,
            'sub_total': sub_total,
        })

    customer_instance = None
    if customer_session:
        customer_pk = list(customer_session.keys())[0]
        customer_instance = Customer.objects.filter(pk=customer_pk, tenant=tenant).first()

    html = render_to_string('partials/_cart_table.html', {
        'cart_details': cart_details,
        'grand_total': grand_total,
        'customer': customer_instance
    }, request=request)

    return JsonResponse({'html': html})
