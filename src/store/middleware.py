from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import resolve

from .models import Branch, Tenant, TenantMember
from .permissions import can_access_branch, get_accessible_branches

TENANT_SESSION_KEY = "active_tenant_id"
BRANCH_SESSION_KEY = "active_branch_id"
STORE_SESSION_KEY = "active_store_id"


def _is_exempt_path(request, exempt_names, exempt_prefixes):
    if request.path.startswith(tuple(exempt_prefixes)):
        return True
    try:
        match = resolve(request.path_info)
        return match.url_name in exempt_names
    except Exception:
        return False


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)
        if not request.user.is_active:
            logout(request)
            return redirect("sign-in")

        if _is_exempt_path(
            request,
            exempt_names={"sign-in", "sign-up", "sign-out", "select-tenant", "select-branch"},
            exempt_prefixes=("/static/", "/media/", "/admin/", "/admin"),
        ):
            return self.get_response(request)

        tenant_id = request.session.get(TENANT_SESSION_KEY)
        tenant = None
        if tenant_id:
            tenant = Tenant.objects.filter(id=tenant_id, is_active=True).first()

        if not tenant:
            return redirect("select-tenant")

        if not TenantMember.objects.filter(tenant=tenant, user=request.user).exists():
            request.session.pop(TENANT_SESSION_KEY, None)
            return redirect("select-tenant")

        request.tenant = tenant
        return self.get_response(request)


class BranchMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)
        if not request.user.is_active:
            logout(request)
            return redirect("sign-in")

        if _is_exempt_path(
            request,
            exempt_names={
                "sign-in",
                "sign-up",
                "sign-out",
                "select-tenant",
                "select-branch",
                "switch-context",
                "pending-users",
                "activate-user",
            },
            exempt_prefixes=("/static/", "/media/", "/admin/", "/admin"),
        ):
            return self.get_response(request)

        tenant = getattr(request, "tenant", None)
        if not tenant:
            return self.get_response(request)

        branch_id = request.session.get(BRANCH_SESSION_KEY)
        branch = None
        if branch_id:
            branch = (
                Branch.objects
                .select_related("store", "store__tenant")
                .filter(id=branch_id, store__tenant=tenant, is_active=True)
                .first()
            )
            if branch and not can_access_branch(request.user, tenant, branch.id):
                branch = None
                request.session.pop(BRANCH_SESSION_KEY, None)
                request.session.pop(STORE_SESSION_KEY, None)

        if not branch:
            allowed_branches = get_accessible_branches(request.user, tenant)
            if allowed_branches.count() == 1:
                only_branch = allowed_branches.first()
                request.branch = only_branch
                request.session[BRANCH_SESSION_KEY] = only_branch.id
                request.session[STORE_SESSION_KEY] = only_branch.store_id
                return self.get_response(request)
            if allowed_branches.exists():
                return redirect("select-branch")
            request.session.pop(BRANCH_SESSION_KEY, None)
            request.session.pop(STORE_SESSION_KEY, None)
            return self.get_response(request)

        request.branch = branch
        request.session[STORE_SESSION_KEY] = branch.store_id
        return self.get_response(request)
