from .models import BranchMember, StoreMember, TenantMember

ALLOWED_TRANSFER_ROLES = {"admin", "manager"}


def resolve_transfer_scope(user, tenant, active_branch_id=None):
    if not user or not user.is_authenticated or not tenant:
        return None, None, None

    branch_qs = (
        BranchMember.objects
        .select_related("branch", "branch__store")
        .filter(user=user, branch__store__tenant=tenant)
    )
    branch_member = None
    if active_branch_id:
        branch_member = branch_qs.filter(branch_id=active_branch_id).first()
    if not branch_member:
        branch_member = branch_qs.first()
    if branch_member:
        return "branch", {"branch": branch_member.branch}, branch_member.role

    store_member = (
        StoreMember.objects
        .select_related("store")
        .filter(user=user, store__tenant=tenant)
        .first()
    )
    if store_member:
        return "store", {"store": store_member.store}, store_member.role

    tenant_member = (
        TenantMember.objects
        .select_related("tenant")
        .filter(user=user, tenant=tenant)
        .first()
    )
    if tenant_member:
        return "tenant", {"tenant": tenant}, tenant_member.role

    return None, None, None


def can_transfer_stock(user, tenant, active_branch_id=None):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    scope, _, role = resolve_transfer_scope(user, tenant, active_branch_id=active_branch_id)
    if scope not in {"branch", "store"}:
        return False
    return role in ALLOWED_TRANSFER_ROLES
