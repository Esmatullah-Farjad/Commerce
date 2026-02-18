import json
from pathlib import Path
from django.conf import settings
from .models import BranchMember, TenantMember
from .permissions import can_transfer_stock

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
        if request.user.is_authenticated:
            tenant_id = request.session.get("active_tenant_id")
            if tenant_id:
                tenant_membership = TenantMember.objects.filter(
                    user=request.user,
                    tenant_id=tenant_id,
                ).select_related("tenant").first()
            branch_id = request.session.get("active_branch_id")
            if branch_id:
                branch_membership = BranchMember.objects.filter(
                    user=request.user,
                    branch_id=branch_id,
                ).select_related("branch").first()
            if tenant_membership:
                can_transfer = can_transfer_stock(
                    request.user,
                    tenant_membership.tenant,
                    active_branch_id=branch_id,
                )

        return {
            "cart_length": cart_length,
            "tenant_membership": tenant_membership,
            "branch_membership": branch_membership,
            "can_transfer": can_transfer,
        }

    except Exception as e:
        return {
            "cart_length": 0,
            "tenant_membership": None,
            "branch_membership": None,
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
