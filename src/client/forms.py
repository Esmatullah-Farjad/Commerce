from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from store.form_utils import apply_tailwind_classes

from .models import Branch, BranchMember, Store, Tenant, TenantMember


class RegistrationForm(UserCreationForm):
    tenant = forms.ModelChoiceField(
        label=_("Tenant"),
        queryset=Tenant.objects.filter(is_active=True).order_by("name"),
        empty_label=_("Select a tenant"),
    )
    store = forms.ModelChoiceField(
        label=_("Store"),
        queryset=Store.objects.filter(
            is_active=True,
            tenant__is_active=True,
        ).select_related("tenant").order_by("name"),
        empty_label=_("Select a store"),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
        ]
        labels = {
            "username": _("Username"),
            "first_name": _("First Name"),
            "last_name": _("Last Name"),
            "email": _("Email"),
            "password1": _("Password"),
            "password2": _("Confrim Password"),
        }

    username = forms.CharField(
        label="Username",
        help_text="",
        widget=forms.TextInput(),
    )
    password1 = forms.CharField(
        label="Password",
        help_text="",
        widget=forms.PasswordInput(),
    )
    password2 = forms.CharField(
        label="Confirm Password",
        help_text="",
        widget=forms.PasswordInput(),
    )

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                f"Username {username} already exists, please choose another."
            )
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                f"Email {email} already exists, please choose another."
            )
        return email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tenant"].queryset = Tenant.objects.filter(is_active=True).order_by("name")
        self.fields["store"].queryset = Store.objects.filter(
            is_active=True,
            tenant__is_active=True,
        ).select_related("tenant").order_by("name")
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)

    def clean(self):
        cleaned_data = super().clean()
        tenant = cleaned_data.get("tenant")
        store = cleaned_data.get("store")
        if tenant and store and store.tenant_id != tenant.id:
            self.add_error("store", _("Selected store does not belong to the chosen tenant."))
        return cleaned_data


class UserActivationForm(forms.Form):
    branch = forms.ModelChoiceField(
        label=_("Branch"),
        queryset=Branch.objects.none(),
        empty_label=_("Select a branch"),
    )

    def __init__(self, *args, **kwargs):
        store = kwargs.pop("store", None)
        tenant = kwargs.pop("tenant", None)
        super().__init__(*args, **kwargs)
        branches = Branch.objects.filter(is_active=True).select_related("store")
        if store:
            branches = branches.filter(store=store)
        elif tenant:
            branches = branches.filter(store__tenant=tenant)
        self.fields["branch"].queryset = branches
        apply_tailwind_classes(self.fields["branch"])


class BranchSettingsForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "code", "address", "contact_phone", "contact_email", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)


class BranchEmployeeForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.none(), label=_("Employee"))
    role = forms.ChoiceField(choices=BranchMember.ROLE_CHOICES, label=_("Role"))

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop("tenant", None)
        branch = kwargs.pop("branch", None)
        super().__init__(*args, **kwargs)
        self._tenant = tenant
        self._branch = branch

        queryset = User.objects.none()
        if tenant:
            queryset = (
                User.objects
                .filter(tenant_memberships__tenant=tenant)
                .distinct()
                .order_by("username")
            )
        if branch:
            queryset = queryset.exclude(id__in=branch.memberships.values_list("user_id", flat=True))
        self.fields["user"].queryset = queryset

        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)

    def clean_user(self):
        user = self.cleaned_data["user"]
        if self._tenant and not TenantMember.objects.filter(tenant=self._tenant, user=user).exists():
            raise forms.ValidationError(_("Selected user must belong to the active tenant."))
        if self._branch and BranchMember.objects.filter(branch=self._branch, user=user).exists():
            raise forms.ValidationError(_("Selected user is already assigned to this branch."))
        return user
