from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import activate, gettext_lazy as _

from store.utils import safe_int

from .forms import RegistrationForm, UserActivationForm
from .models import BranchMember, StoreMember, Tenant, TenantMember, UserOnboarding
from .permissions import (
    get_accessible_branches,
    get_accessible_stores,
    has_tenant_admin_access,
)
from .services import active_tenant, sync_user_memberships_from_onboarding


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
