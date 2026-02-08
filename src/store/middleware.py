from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import resolve

from .models import Branch, Tenant, TenantMember

TENANT_SESSION_KEY = "active_tenant_id"
BRANCH_SESSION_KEY = "active_branch_id"


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
            exempt_names={"sign-in", "sign-up", "sign-out", "select-tenant", "select-branch"},
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

        if not branch:
            return redirect("select-branch")

        request.branch = branch
        return self.get_response(request)
