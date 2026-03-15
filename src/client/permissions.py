from django.db.models import Q

from .models import Branch, BranchMember, Store, StoreMember, TenantMember

ELEVATED_TENANT_ROLES = {"owner", "admin"}
TENANT_ADMIN_ROLES = {"owner", "admin"}
ALLOWED_TRANSFER_ROLES = {"owner", "admin", "manager"}
ROLE_LABELS = {
    "superadmin": "Superadmin",
    "owner": "Owner",
    "admin": "Admin",
    "manager": "Manager",
    "staff": "Staff",
}


def _normalized_tenant_role(tenant_member):
    if not tenant_member:
        return None
    if tenant_member.is_owner:
        return "owner"
    return tenant_member.role


def get_tenant_membership(user, tenant):
    if not user or not user.is_authenticated or not tenant:
        return None
    return (
        TenantMember.objects
        .select_related("tenant")
        .filter(user=user, tenant=tenant)
        .first()
    )


def has_tenant_scope_access(user, tenant):
    if not user or not user.is_authenticated or not tenant:
        return False
    if user.is_superuser:
        return True
    return TenantMember.objects.filter(
        Q(role__in=ELEVATED_TENANT_ROLES) | Q(is_owner=True),
        user=user,
        tenant=tenant,
    ).exists()


def has_tenant_admin_access(user, tenant):
    if not user or not user.is_authenticated or not tenant:
        return False
    if user.is_superuser:
        return True
    return TenantMember.objects.filter(
        Q(role__in=TENANT_ADMIN_ROLES) | Q(is_owner=True),
        user=user,
        tenant=tenant,
    ).exists()


def get_accessible_stores(user, tenant):
    if not user or not user.is_authenticated or not tenant:
        return Store.objects.none()
    if user.is_superuser or has_tenant_scope_access(user, tenant):
        return Store.objects.filter(tenant=tenant, is_active=True).order_by("name")

    store_ids = set(
        StoreMember.objects.filter(
            user=user,
            store__tenant=tenant,
            store__is_active=True,
        ).values_list("store_id", flat=True)
    )
    store_ids.update(
        BranchMember.objects.filter(
            user=user,
            branch__store__tenant=tenant,
            branch__is_active=True,
            branch__store__is_active=True,
        ).values_list("branch__store_id", flat=True)
    )
    if not store_ids:
        return Store.objects.none()
    return Store.objects.filter(id__in=store_ids, tenant=tenant, is_active=True).order_by("name")


def get_accessible_branches(user, tenant, store_id=None):
    if not user or not user.is_authenticated or not tenant:
        return Branch.objects.none()

    qs = Branch.objects.filter(
        store__tenant=tenant,
        store__is_active=True,
        is_active=True,
    ).select_related("store")

    if not (user.is_superuser or has_tenant_scope_access(user, tenant)):
        branch_ids = set(
            BranchMember.objects.filter(
                user=user,
                branch__store__tenant=tenant,
                branch__is_active=True,
                branch__store__is_active=True,
            ).values_list("branch_id", flat=True)
        )
        store_ids = set(
            StoreMember.objects.filter(
                user=user,
                store__tenant=tenant,
                store__is_active=True,
            ).values_list("store_id", flat=True)
        )
        if not branch_ids and not store_ids:
            return Branch.objects.none()
        allowed_filter = Q()
        if branch_ids:
            allowed_filter |= Q(id__in=branch_ids)
        if store_ids:
            allowed_filter |= Q(store_id__in=store_ids)
        qs = qs.filter(allowed_filter)

    if store_id:
        qs = qs.filter(store_id=store_id)
    return qs.distinct().order_by("store__name", "name")


def can_access_branch(user, tenant, branch_id):
    if not branch_id:
        return False
    return get_accessible_branches(user, tenant).filter(id=branch_id).exists()


def resolve_transfer_scope(user, tenant, active_branch_id=None):
    if not user or not user.is_authenticated or not tenant:
        return None, None, None

    tenant_member = get_tenant_membership(user, tenant)
    tenant_role = _normalized_tenant_role(tenant_member)
    if tenant_member and tenant_role in ELEVATED_TENANT_ROLES:
        if active_branch_id:
            active_branch = (
                Branch.objects
                .select_related("store")
                .filter(id=active_branch_id, store__tenant=tenant, is_active=True)
                .first()
            )
            if active_branch:
                return "branch", {"branch": active_branch}, tenant_role

        first_branch = get_accessible_branches(user, tenant).first()
        if first_branch:
            return "branch", {"branch": first_branch}, tenant_role

        first_store = get_accessible_stores(user, tenant).first()
        if first_store:
            return "store", {"store": first_store}, tenant_role

        return "tenant", {"tenant": tenant}, tenant_role

    branch_qs = (
        BranchMember.objects
        .select_related("branch", "branch__store")
        .filter(
            user=user,
            branch__store__tenant=tenant,
            branch__is_active=True,
            branch__store__is_active=True,
        )
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
        .filter(user=user, store__tenant=tenant, store__is_active=True)
        .first()
    )
    if store_member:
        return "store", {"store": store_member.store}, store_member.role

    if tenant_member:
        return "tenant", {"tenant": tenant}, tenant_role

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


def get_active_role(user, tenant, branch=None, store=None):
    if not user or not user.is_authenticated or not tenant:
        return None
    if user.is_superuser:
        return "superadmin"

    tenant_member = get_tenant_membership(user, tenant)
    tenant_role = _normalized_tenant_role(tenant_member)
    if tenant_role in {"owner", "admin"}:
        return tenant_role

    if branch:
        branch_role = (
            BranchMember.objects
            .filter(user=user, branch=branch)
            .values_list("role", flat=True)
            .first()
        )
        if branch_role:
            return branch_role

    target_store = store or (branch.store if branch else None)
    if target_store:
        store_role = (
            StoreMember.objects
            .filter(user=user, store=target_store)
            .values_list("role", flat=True)
            .first()
        )
        if store_role:
            return store_role

    return tenant_role
