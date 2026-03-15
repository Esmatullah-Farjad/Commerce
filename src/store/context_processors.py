import json
from pathlib import Path
from django.conf import settings
from .models import Branch, BranchMember, TenantMember
from .permissions import (
    can_transfer_stock,
    get_accessible_branches,
    get_accessible_stores,
    get_active_role,
    ROLE_LABELS,
)

def cart_context(request):
    try:
        # Retrieve the cart from the session
        cart = request.session.get('cart', {})
        json.dumps(cart)

        # Calculate cart length
        cart_length = len(cart) if cart else 0

        tenant_membership = None
        branch_membership = None
        can_transfer = False
        active_tenant = None
        active_store = None
        active_branch = None
        store_options = []
        branch_options = []
        all_branch_options = []
        selected_store_id = None
        selected_branch_id = None
        can_switch_context = False
        active_access_role = None
        active_access_role_label = None
        if request.user.is_authenticated:
            tenant_id = request.session.get("active_tenant_id")
            if tenant_id:
                tenant_membership = TenantMember.objects.filter(
                    user=request.user,
                    tenant_id=tenant_id,
                ).select_related("tenant").first()
                if tenant_membership:
                    active_tenant = tenant_membership.tenant
            branch_id = request.session.get("active_branch_id")
            if branch_id:
                branch_membership = BranchMember.objects.filter(
                    user=request.user,
                    branch_id=branch_id,
                ).select_related("branch").first()
            if active_tenant:
                selected_store_id = request.session.get("active_store_id")
                accessible_stores = get_accessible_stores(request.user, active_tenant)
                if selected_store_id and not accessible_stores.filter(id=selected_store_id).exists():
                    selected_store_id = None

                active_branch = getattr(request, "branch", None)
                if not active_branch and branch_id:
                    active_branch = (
                        Branch.objects
                        .select_related("store")
                        .filter(id=branch_id, store__tenant=active_tenant, is_active=True)
                        .first()
                    )
                if active_branch:
                    active_store = active_branch.store
                    selected_store_id = active_branch.store_id
                    selected_branch_id = active_branch.id
                elif selected_store_id:
                    active_store = accessible_stores.filter(id=selected_store_id).first()

                if not selected_store_id:
                    selected_store_id = accessible_stores.first().id if accessible_stores.exists() else None

                accessible_branches = get_accessible_branches(
                    request.user,
                    active_tenant,
                    store_id=selected_store_id if selected_store_id else None,
                )
                all_accessible_branches = get_accessible_branches(request.user, active_tenant)
                store_options = list(accessible_stores)
                branch_options = list(accessible_branches)
                all_branch_options = list(all_accessible_branches)
                can_switch_context = len(branch_options) > 1 or len(store_options) > 1

                can_transfer = can_transfer_stock(
                    request.user,
                    active_tenant,
                    active_branch_id=branch_id,
                )
                active_access_role = get_active_role(
                    request.user,
                    active_tenant,
                    branch=active_branch,
                    store=active_store,
                )
                active_access_role_label = ROLE_LABELS.get(
                    active_access_role,
                    active_access_role.title() if active_access_role else None,
                )

        return {
            "cart_length": cart_length,
            "tenant_membership": tenant_membership,
            "branch_membership": branch_membership,
            "can_transfer": can_transfer,
            "active_tenant": active_tenant,
            "active_store": active_store,
            "active_branch": active_branch,
            "context_store_options": store_options,
            "context_branch_options": branch_options,
            "context_all_branch_options": all_branch_options,
            "context_selected_store_id": selected_store_id,
            "context_selected_branch_id": selected_branch_id,
            "can_switch_context": can_switch_context,
            "active_access_role": active_access_role,
            "active_access_role_label": active_access_role_label,
        }

    except Exception as e:
        return {
            "cart_length": 0,
            "tenant_membership": None,
            "branch_membership": None,
            "active_tenant": None,
            "active_store": None,
            "active_branch": None,
            "context_store_options": [],
            "context_branch_options": [],
            "context_all_branch_options": [],
            "context_selected_store_id": None,
            "context_selected_branch_id": None,
            "can_switch_context": False,
            "active_access_role": None,
            "active_access_role_label": None,
        }


def asset_context(request):
    css_file = Path(settings.BASE_DIR) / "static" / "styles" / "tailwind.css"
    version = "1"
    try:
        if css_file.exists():
            version = str(int(css_file.stat().st_mtime))
    except OSError:
        version = "1"

    return {
        "STATIC_ASSET_VERSION": version,
    }
