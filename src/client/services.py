from .models import BranchMember, StoreMember, TenantMember, UserOnboarding


def active_tenant(request):
    return getattr(request, "tenant", None)


def active_branch(request):
    return getattr(request, "branch", None)


def sync_user_memberships_from_onboarding(user, include_pending_for_active_user=False):
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

        TenantMember.objects.get_or_create(
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

        if onboarding.status == "pending" and user.is_active and include_pending_for_active_user:
            if not onboarding.activated_at:
                from django.utils import timezone
                onboarding.activated_at = timezone.now()
            onboarding.status = "active"
            onboarding.save(update_fields=["status", "activated_at"])
