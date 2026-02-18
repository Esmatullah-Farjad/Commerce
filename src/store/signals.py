from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.utils import timezone

from .models import BranchMember, ExchangeRate, Products, StoreMember, TenantMember, UserOnboarding
from decimal import Decimal

@receiver(post_save, sender=ExchangeRate)
def update_afn_prices_for_usd_products(sender, instance, created, **kwargs):
    rate = instance.usd_to_afn
    usd_products = Products.objects.filter(purchase_unit__code__iexact='usd', usd_package_sale_price__isnull=False)

    for product in usd_products:
        product.package_sale_price = round(product.usd_package_sale_price * rate, 2)
        product.item_sale_price = round(product.package_sale_price / product.package_contain, 2)
        product.save()


def _assign_memberships_from_onboarding(onboarding):
    if not onboarding or not onboarding.user_id:
        return
    if onboarding.store_id and onboarding.store.tenant_id != onboarding.tenant_id:
        return

    user = onboarding.user
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])

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

    if (
        onboarding.assigned_branch_id
        and onboarding.assigned_branch.store_id == onboarding.store_id
        and onboarding.assigned_branch.store.tenant_id == onboarding.tenant_id
    ):
        BranchMember.objects.get_or_create(
            branch=onboarding.assigned_branch,
            user=user,
            defaults={"role": "staff"},
        )


@receiver(post_save, sender=UserOnboarding)
def ensure_memberships_on_onboarding_activation(sender, instance, created, **kwargs):
    if instance.status == "active":
        _assign_memberships_from_onboarding(instance)


@receiver(post_save, sender=User)
def ensure_memberships_on_user_activation(sender, instance, created, **kwargs):
    # Covers admin workflows that only toggle user.is_active and forget memberships.
    if not instance.is_active:
        return

    onboarding = (
        UserOnboarding.objects.select_related("tenant", "store", "assigned_branch")
        .filter(user=instance, tenant__is_active=True, store__is_active=True)
        .first()
    )
    if not onboarding:
        return

    if onboarding.status == "pending":
        onboarding.status = "active"
        if not onboarding.activated_at:
            onboarding.activated_at = timezone.now()
        onboarding.save(update_fields=["status", "activated_at"])
        return

    if onboarding.status == "active":
        _assign_memberships_from_onboarding(onboarding)
