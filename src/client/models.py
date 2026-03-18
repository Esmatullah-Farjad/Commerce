from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Tenant(models.Model):
    logo = models.ImageField(null=True, blank=True)
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "store_tenant"

    def __str__(self):
        return self.name


class TenantMember(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("staff", "Staff"),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tenant_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="staff")
    is_owner = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "store_tenantmember"
        unique_together = ("tenant", "user")

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.name}"


class Store(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="stores")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "store_store"
        unique_together = ("tenant", "code")

    def __str__(self):
        return self.name


class Branch(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, null=True, blank=True)
    address = models.CharField(max_length=200, blank=True, default="")
    contact_phone = models.CharField(max_length=50, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "store_branch"
        unique_together = ("store", "code")

    def __str__(self):
        return f"{self.store.name} - {self.name}"


class BranchMember(models.Model):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("staff", "Staff"),
    ]
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="branch_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="staff")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "store_branchmember"
        unique_together = ("branch", "user")

    def clean(self):
        super().clean()
        if self.branch_id and self.user_id:
            tenant_id = self.branch.store.tenant_id
            if not TenantMember.objects.filter(tenant_id=tenant_id, user_id=self.user_id).exists():
                raise ValidationError({"user": _("User must be a member of the branch tenant first.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} @ {self.branch}"


class StoreMember(models.Model):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("manager", "Manager"),
        ("staff", "Staff"),
    ]
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="store_memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="staff")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "store_storemember"
        unique_together = ("store", "user")

    def clean(self):
        super().clean()
        if self.store_id and self.user_id:
            tenant_id = self.store.tenant_id
            if not TenantMember.objects.filter(tenant_id=tenant_id, user_id=self.user_id).exists():
                raise ValidationError({"user": _("User must be a member of the store tenant first.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} @ {self.store.name}"


class UserOnboarding(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="onboarding")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="onboarding_requests")
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="onboarding_requests")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    assigned_branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarded_users",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activated_users",
    )

    class Meta:
        db_table = "store_useronboarding"

    def clean(self):
        super().clean()
        if self.store_id and self.tenant_id and self.store.tenant_id != self.tenant_id:
            raise ValidationError({"store": _("Store must belong to the selected tenant.")})
        if self.assigned_branch_id:
            if self.store_id and self.assigned_branch.store_id != self.store_id:
                raise ValidationError({"assigned_branch": _("Assigned branch must belong to the selected store.")})
            if self.assigned_branch.store.tenant_id != self.tenant_id:
                raise ValidationError({"assigned_branch": _("Assigned branch must belong to the selected tenant.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.tenant.name} ({self.status})"
