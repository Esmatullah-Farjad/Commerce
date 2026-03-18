from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import activate, gettext_lazy as _

from store.utils import safe_int
from store.models import BranchStock, Expense, InventoryMovement, OtherIncome, SalesDetails

from .forms import BranchEmployeeForm, BranchSettingsForm, RegistrationForm, UserActivationForm
from .models import BranchMember, StoreMember, Tenant, TenantMember, UserOnboarding
from .permissions import (
    get_accessible_branches,
    get_accessible_stores,
    has_tenant_admin_access,
)
from .services import active_tenant, sync_user_memberships_from_onboarding


def _branch_management_redirect_url(branch, start_date, end_date):
    params = []
    if branch:
        params.append(f"branch_id={branch.id}")
    if start_date:
        params.append(f"from_date={start_date.isoformat()}")
    if end_date:
        params.append(f"to_date={end_date.isoformat()}")
    query = f"?{'&'.join(params)}" if params else ""
    return f"{reverse('branch-management')}{query}"


def _resolve_branch_date_range(request):
    today = timezone.localdate()
    end_date = parse_date(request.GET.get("to_date") or "") or today
    start_date = parse_date(request.GET.get("from_date") or "") or (end_date - timedelta(days=29))
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date


def _branch_report_snapshot(tenant, branch, start_date, end_date):
    sales_total = (
        SalesDetails.objects
        .filter(tenant=tenant, branch=branch, created_at__date__range=(start_date, end_date))
        .aggregate(total=Sum("total_amount"), count=Count("id"))
    )
    income_total = (
        OtherIncome.objects
        .filter(tenant=tenant, branch=branch, date_created__range=(start_date, end_date))
        .aggregate(total=Sum("amount"))
    )
    expense_total = (
        Expense.objects
        .filter(tenant=tenant, branch=branch, date_created__range=(start_date, end_date))
        .aggregate(total=Sum("amount"))
    )
    stock_total = (
        BranchStock.objects
        .filter(branch=branch)
        .aggregate(
            total_stock=Sum("stock"),
            active_products=Count("id", filter=Q(stock__gt=0)),
            tracked_products=Count("id"),
        )
    )
    sales_amount = sales_total["total"] or 0
    income_amount = income_total["total"] or 0
    expense_amount = expense_total["total"] or 0
    return {
        "branch": branch,
        "sales_count": sales_total["count"] or 0,
        "sales_total": sales_amount,
        "income_total": income_amount,
        "expense_total": expense_amount,
        "profit_total": sales_amount + income_amount - expense_amount,
        "stock_total": stock_total["total_stock"] or 0,
        "active_products": stock_total["active_products"] or 0,
        "tracked_products": stock_total["tracked_products"] or 0,
        "employee_count": branch.memberships.count(),
    }


def switch_language(request, lang_code):
    if lang_code in ["en", "fa"]:
        activate(lang_code)
        response = redirect(request.META.get("HTTP_REFERER", "/"))
        response.set_cookie("django_language", lang_code, max_age=31536000)
        return response
    return redirect("/")


def root_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    return redirect("landing")


def landing(request):
    return render(request, "landing-page.html", {"all_tenant": Tenant.objects.all()})


def signin(request):
    if request.method == "POST":
        email = request.POST["email"]
        password = request.POST.get("password")
        user = authenticate(request, username=email, email=email, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, _("Welcome !"))

            sync_user_memberships_from_onboarding(
                user,
                include_pending_for_active_user=True,
            )

            memberships = (
                TenantMember.objects
                .select_related("tenant")
                .filter(user=user, tenant__is_active=True)
                .order_by("tenant__name")
            )
            if memberships.count() == 1:
                tenant = memberships.first().tenant
                request.session["active_tenant_id"] = tenant.id

                branches = get_accessible_branches(user, tenant)
                branch_count = branches.count()
                if branch_count == 1:
                    only_branch = branches.first()
                    request.session["active_branch_id"] = only_branch.id
                    request.session["active_store_id"] = only_branch.store_id
                    return redirect("home")

                if branch_count == 0:
                    request.session.pop("active_branch_id", None)
                    request.session.pop("active_store_id", None)
                    messages.error(
                        request,
                        _("No active branch assigned to your account for this tenant."),
                    )
                    return redirect("select-tenant")

                request.session.pop("active_store_id", None)
                return redirect("select-branch")

            if memberships.count() > 1:
                messages.info(request, _("Select the tenant you want to work in."))
                return redirect("select-tenant")

            messages.error(
                request,
                _("No tenant assigned to this account. Please contact an admin."),
            )
            request.session.pop("active_tenant_id", None)
            request.session.pop("active_branch_id", None)
            request.session.pop("active_store_id", None)
            return redirect("select-tenant")

        try:
            from django.contrib.auth import get_user_model

            user_model = get_user_model()
            existing = (
                user_model.objects.filter(email=email).first()
                or user_model.objects.filter(username=email).first()
            )
            if existing and not existing.is_active:
                messages.error(
                    request,
                    _("Your account is inactive. Please contact an admin for activation."),
                )
                return render(request, "auth/login.html")
        except Exception:
            pass
        messages.error(request, _("Invalid username or password"))
    return render(request, "auth/login.html")


def signup(request):
    form = RegistrationForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()

            UserOnboarding.objects.create(
                user=user,
                tenant=form.cleaned_data["tenant"],
                store=form.cleaned_data["store"],
                status="pending",
            )
            messages.success(
                request,
                _("Account created. Your account is pending admin activation."),
            )
            return redirect("sign-in")

        messages.error(request, _("Something Went wrong. Please fix the below error !"))

    context = {
        "form": form,
        "tenants": form.fields["tenant"].queryset,
        "stores": form.fields["store"].queryset,
    }
    return render(request, "auth/register.html", context)


def signout(request):
    logout(request)
    return redirect("sign-in")


def select_tenant(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    sync_user_memberships_from_onboarding(
        request.user,
        include_pending_for_active_user=True,
    )

    memberships = (
        TenantMember.objects
        .select_related("tenant")
        .filter(user=request.user, tenant__is_active=True)
        .order_by("tenant__name")
    )
    tenants = [membership.tenant for membership in memberships]

    if request.method == "POST":
        tenant_id = request.POST.get("tenant_id")
        allowed = next((m for m in memberships if str(m.tenant_id) == str(tenant_id)), None)
        if not allowed:
            messages.error(request, _("Invalid tenant selection."))
            return redirect("select-tenant")

        request.session["active_tenant_id"] = allowed.tenant_id
        request.session.pop("active_branch_id", None)
        request.session.pop("active_store_id", None)
        request.session.pop("cart", None)
        request.session.pop("customer", None)

        branches = get_accessible_branches(request.user, allowed.tenant)
        if branches.count() == 1:
            only_branch = branches.first()
            request.session["active_branch_id"] = only_branch.id
            request.session["active_store_id"] = only_branch.store_id
            return redirect("home")
        if branches.count() == 0:
            messages.error(
                request,
                _("No active branch assigned to your account for this tenant."),
            )
            return redirect("select-tenant")

        return redirect("select-branch")

    return render(request, "tenancy/select_tenant.html", {"tenants": tenants})


def select_branch(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    sync_user_memberships_from_onboarding(
        request.user,
        include_pending_for_active_user=True,
    )

    tenant_id = request.session.get("active_tenant_id")
    if not tenant_id:
        return redirect("select-tenant")

    tenant = Tenant.objects.filter(id=tenant_id, is_active=True).first()
    if not tenant:
        request.session.pop("active_tenant_id", None)
        return redirect("select-tenant")
    if not TenantMember.objects.filter(user=request.user, tenant=tenant).exists():
        request.session.pop("active_tenant_id", None)
        request.session.pop("active_store_id", None)
        return redirect("select-tenant")

    stores = get_accessible_stores(request.user, tenant)
    selected_store_id = safe_int(
        request.POST.get("store_id") if request.method == "POST" else request.GET.get("store_id"),
        0,
    )
    if not stores.filter(id=selected_store_id).exists():
        active_store_id = safe_int(request.session.get("active_store_id"), 0)
        if stores.filter(id=active_store_id).exists():
            selected_store_id = active_store_id
        elif stores.exists():
            selected_store_id = stores.first().id

    branches = get_accessible_branches(
        request.user,
        tenant,
        store_id=selected_store_id if selected_store_id else None,
    )
    all_allowed_branches = get_accessible_branches(request.user, tenant)

    if not all_allowed_branches.exists():
        messages.error(
            request,
            _("No active branch assigned to your account for this tenant."),
        )
        request.session.pop("active_branch_id", None)
        request.session.pop("active_store_id", None)
        return redirect("select-tenant")

    if request.method == "POST":
        branch_id = request.POST.get("branch_id")
        branch = all_allowed_branches.filter(id=branch_id).first()
        if not branch:
            messages.error(request, _("Invalid branch selection."))
            return redirect("select-branch")

        request.session["active_branch_id"] = branch.id
        request.session["active_store_id"] = branch.store_id
        request.session.pop("cart", None)
        request.session.pop("customer", None)
        return redirect("home")

    context = {
        "stores": stores,
        "branches": branches,
        "selected_store_id": selected_store_id,
    }
    return render(request, "tenancy/select_branch.html", context)


def switch_context(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")
    if request.method != "POST":
        return redirect("home")

    tenant = active_tenant(request)
    if not tenant:
        return redirect("select-tenant")

    branch_id = safe_int(request.POST.get("branch_id"), 0)
    branch = get_accessible_branches(request.user, tenant).filter(id=branch_id).first()
    if not branch:
        messages.error(request, _("You are not authorized to switch to that branch."))
        return redirect("select-branch")

    request.session["active_branch_id"] = branch.id
    request.session["active_store_id"] = branch.store_id
    request.session.pop("cart", None)
    request.session.pop("customer", None)

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or ""
    if not next_url or not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect("home")
    return redirect(next_url)


def branch_management(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    tenant = active_tenant(request)
    if not tenant:
        return redirect("select-tenant")

    if not has_tenant_admin_access(request.user, tenant):
        messages.error(request, _("You do not have permission to manage branches."))
        return redirect("home")

    branches = get_accessible_branches(request.user, tenant)
    if not branches.exists():
        messages.error(request, _("No branches are available for this tenant."))
        return redirect("home")

    selected_branch_id = safe_int(request.GET.get("branch_id"), 0) or safe_int(request.session.get("active_branch_id"), 0)
    selected_branch = branches.filter(id=selected_branch_id).first() or branches.first()
    start_date, end_date = _resolve_branch_date_range(request)

    branch_form = BranchSettingsForm(instance=selected_branch, prefix="branch")
    employee_form = BranchEmployeeForm(tenant=tenant, branch=selected_branch, prefix="employee")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_branch":
            branch_form = BranchSettingsForm(request.POST, instance=selected_branch, prefix="branch")
            if branch_form.is_valid():
                branch_form.save()
                messages.success(request, _("Branch details updated successfully."))
                return redirect(_branch_management_redirect_url(selected_branch, start_date, end_date))
            messages.error(request, _("Please correct the branch details form."))
        elif action == "add_employee":
            employee_form = BranchEmployeeForm(request.POST, tenant=tenant, branch=selected_branch, prefix="employee")
            if employee_form.is_valid():
                employee = employee_form.cleaned_data["user"]
                role = employee_form.cleaned_data["role"]
                BranchMember.objects.update_or_create(
                    branch=selected_branch,
                    user=employee,
                    defaults={"role": role},
                )
                StoreMember.objects.get_or_create(
                    store=selected_branch.store,
                    user=employee,
                    defaults={"role": role},
                )
                messages.success(request, _("Employee access updated for this branch."))
                return redirect(_branch_management_redirect_url(selected_branch, start_date, end_date))
            messages.error(request, _("Please correct the employee assignment form."))
        elif action == "remove_employee":
            membership_id = safe_int(request.POST.get("membership_id"), 0)
            membership = (
                selected_branch.memberships
                .select_related("user")
                .filter(id=membership_id)
                .first()
            )
            if not membership:
                messages.error(request, _("Employee assignment not found."))
            else:
                membership.delete()
                messages.success(request, _("Employee removed from this branch."))
            return redirect(_branch_management_redirect_url(selected_branch, start_date, end_date))
        elif action == "update_employee_role":
            membership_id = safe_int(request.POST.get("membership_id"), 0)
            role = request.POST.get("role")
            membership = (
                selected_branch.memberships
                .select_related("user")
                .filter(id=membership_id)
                .first()
            )
            valid_roles = {choice[0] for choice in BranchMember.ROLE_CHOICES}
            if not membership or role not in valid_roles:
                messages.error(request, _("Invalid employee role update request."))
            else:
                membership.role = role
                membership.save(update_fields=["role"])
                StoreMember.objects.update_or_create(
                    store=selected_branch.store,
                    user=membership.user,
                    defaults={"role": role},
                )
                messages.success(request, _("Employee role updated successfully."))
            return redirect(_branch_management_redirect_url(selected_branch, start_date, end_date))

    selected_snapshot = _branch_report_snapshot(tenant, selected_branch, start_date, end_date)
    comparison_rows = [
        _branch_report_snapshot(tenant, branch, start_date, end_date)
        for branch in branches
    ]
    recent_activity = (
        InventoryMovement.objects
        .select_related("product", "created_by")
        .filter(
            tenant=tenant,
            branch=selected_branch,
            created_at__date__range=(start_date, end_date),
        )
        .order_by("-created_at")[:10]
    )
    branch_members = (
        selected_branch.memberships
        .select_related("user")
        .order_by("role", "user__username")
    )

    context = {
        "tenant": tenant,
        "branches": branches,
        "selected_branch": selected_branch,
        "selected_snapshot": selected_snapshot,
        "comparison_rows": comparison_rows,
        "recent_activity": recent_activity,
        "branch_members": branch_members,
        "branch_form": branch_form,
        "employee_form": employee_form,
        "branch_role_choices": BranchMember.ROLE_CHOICES,
        "from_date": start_date,
        "to_date": end_date,
    }
    return render(request, "tenancy/branch_management.html", context)


def pending_users(request):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    tenant = active_tenant(request)
    if not tenant:
        return redirect("select-tenant")

    if not has_tenant_admin_access(request.user, tenant):
        messages.error(request, _("You do not have permission to view pending users."))
        return redirect("home")

    pending = (
        UserOnboarding.objects
        .select_related("user", "tenant", "store")
        .filter(tenant=tenant, status="pending")
        .order_by("-requested_at")
    )
    return render(
        request,
        "tenancy/pending_users.html",
        {"tenant": tenant, "pending_users": pending},
    )


def activate_user(request, onboarding_id):
    if not request.user.is_authenticated:
        return redirect("sign-in")

    tenant = active_tenant(request)
    if not tenant:
        return redirect("select-tenant")

    if not has_tenant_admin_access(request.user, tenant):
        messages.error(request, _("You do not have permission to activate users."))
        return redirect("home")

    onboarding = get_object_or_404(UserOnboarding, pk=onboarding_id, tenant=tenant)
    if onboarding.status != "pending":
        messages.info(request, _("This user is already processed."))
        return redirect("pending-users")

    form = UserActivationForm(request.POST or None, store=onboarding.store, tenant=tenant)
    has_branches = form.fields["branch"].queryset.exists()

    if request.method == "POST":
        if not has_branches:
            messages.error(
                request,
                _("No branches available for this store. Please create one first."),
            )
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
                onboarding.save(
                    update_fields=["status", "assigned_branch", "activated_by", "activated_at"]
                )

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
