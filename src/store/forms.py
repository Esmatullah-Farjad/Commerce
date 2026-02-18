from django import forms
from django import forms
from .models import BaseUnit, Branch, CustomerPayment, ExchangeRate, OtherIncome, Products, Customer, Expense, Store, Tenant, Category
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

BASE_INPUT_CLASSES = (
    "w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm "
    "text-slate-900 shadow-sm transition focus:border-primary-500 "
    "focus:ring-2 focus:ring-primary-200"
)
BASE_SELECT_CLASSES = (
    "w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm "
    "text-slate-900 shadow-sm transition focus:border-primary-500 "
    "focus:ring-2 focus:ring-primary-200"
)
BASE_TEXTAREA_CLASSES = (
    "w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm "
    "text-slate-900 shadow-sm transition focus:border-primary-500 "
    "focus:ring-2 focus:ring-primary-200"
)
CHECKBOX_CLASSES = "h-4 w-4 rounded border-slate-300 text-primary-600 focus:ring-primary-500"


def apply_tailwind_classes(field):
    widget = field.widget
    if isinstance(widget, forms.CheckboxInput):
        classes = CHECKBOX_CLASSES
    elif isinstance(widget, forms.Select):
        classes = BASE_SELECT_CLASSES
    elif isinstance(widget, forms.Textarea):
        classes = BASE_TEXTAREA_CLASSES
    else:
        classes = BASE_INPUT_CLASSES
    existing = widget.attrs.get("class", "")
    widget.attrs["class"] = f"{existing} {classes}".strip()


def _tenant_or_global_qs(model, tenant):
    if tenant and model.objects.filter(tenant=tenant).exists():
        return model.objects.filter(tenant=tenant)
    return model.objects.filter(tenant__isnull=True)

# forms.py
class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Products
        exclude = ['tenant', 'stock', 'total_package_price', 'item_sale_price', 'usd_package_sale_price', 'currency_category']
    
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop("tenant", None)
        super(PurchaseForm, self).__init__(*args, **kwargs)
        if tenant:
            self.fields["category"].queryset = _tenant_or_global_qs(Category, tenant)
            self.fields["unit"].queryset = _tenant_or_global_qs(BaseUnit, tenant)
            self.fields["purchase_unit"].queryset = self.fields["purchase_unit"].queryset.filter(tenant=tenant)
        if "unit" in self.fields:
            self.fields["unit"].label_from_instance = (
                lambda obj: f"{obj.name} (Base: {obj.base_unit.name})"
                if obj.base_unit
                else f"{obj.name} (Base: {obj.name})"
            )
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)
            visible.field.widget.attrs['placeholder'] = _(visible.field.label)

class ExchangeRateForm(forms.ModelForm):
    class Meta:
        model = ExchangeRate
        exclude = ["tenant"]
        widgets = {
            "usd_to_afn": forms.NumberInput(
                attrs={"step": "0.01", "class": BASE_INPUT_CLASSES}
            ),
        }
class RegistrationForm(UserCreationForm):
    tenant = forms.ModelChoiceField(
        label=_("Tenant"),
        queryset=Tenant.objects.filter(is_active=True).order_by("name"),
        empty_label=_("Select a tenant"),
    )
    store = forms.ModelChoiceField(
        label=_("Store"),
        queryset=Store.objects.filter(is_active=True, tenant__is_active=True).select_related("tenant").order_by("name"),
        empty_label=_("Select a store"),
    )

    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'password1',
            'password2',
        ]
        labels = {
            'username': _('Username'),
            'first_name': _('First Name'),
            'last_name': _('Last Name'),
            'email': _('Email'),
            'password1': _('Password'),
            'password2': _('Confrim Password')
        }
        username = forms.CharField(
        label='Username',
        help_text='',   # remove default long text
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-teal-600 focus:ring-2 focus:ring-teal-200'
        })
    )

    password1 = forms.CharField(
        label='Password',
        help_text='',   # remove default password rules block
        widget=forms.PasswordInput(attrs={
            'class': 'w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-teal-600 focus:ring-2 focus:ring-teal-200'
        })
    )

    password2 = forms.CharField(
        label='Confirm Password',
        help_text='',
        widget=forms.PasswordInput(attrs={
            'class': 'w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm focus:border-teal-600 focus:ring-2 focus:ring-teal-200'
        })
    )

    def clean_username(self):
        """check if username already exists"""
        username = self.cleaned_data.get('username')
        qs = User.objects.filter(username__iexact=username)
        if qs.exists():
            raise forms.ValidationError(f"Username {username} already exists, please choose another.")
        return username

    def clean_email(self):
        """check if email already exists"""
        email = self.cleaned_data.get('email')
        qs = User.objects.filter(email__iexact=email)
        if qs.exists():
            raise forms.ValidationError(f"Email {email} already exists, please choose another.")
        return email

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tenant"].queryset = Tenant.objects.filter(is_active=True).order_by("name")
        self.fields["store"].queryset = Store.objects.filter(is_active=True, tenant__is_active=True).select_related("tenant").order_by("name")
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

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        exclude = ["tenant"]
    def __init__(self, *args, **kwargs):
        super(CustomerForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)


class OtherIncomeForm(forms.ModelForm):
    class Meta:
        model = OtherIncome
        field = "__all__"
        exclude = ("tenant", "branch")

        
    def __init__(self, *args, **kwargs):
        super(OtherIncomeForm, self).__init__(*args, **kwargs)
        self.fields['date_created'].widget = forms.DateInput(
                attrs={
                    'type': 'date',  # HTML5 date input type
                    'class': BASE_INPUT_CLASSES,  # Additional class for styling
                }
            )
        # Add the 'jalali-date-picker' class to the date_created field
        if 'date_created' in self.fields:
            self.fields['date_created'].widget.attrs.update({
                'class': f"jalali-date-picker {BASE_INPUT_CLASSES}",
                'autocomplete': 'off',  # Disable browser autocomplete
            })
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)
            visible.field.widget.attrs['placeholder'] = _(visible.field.label)


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = "__all__"
        exclude = ("tenant", "branch")

    def __init__(self, *args, **kwargs):
        super(ExpenseForm, self).__init__(*args, **kwargs)
        self.fields['date_created'].widget = forms.DateInput(
                attrs={
                    'type': 'date',
                    'class': BASE_INPUT_CLASSES,
                }
            )
        if 'date_created' in self.fields:
            self.fields['date_created'].widget.attrs.update({
                'class': f"jalali-date-picker {BASE_INPUT_CLASSES}",
                'autocomplete': 'off',
            })
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)
            visible.field.widget.attrs['placeholder'] = _(visible.field.label)


class BaseUnitForm(forms.ModelForm):
    class Meta:
        model = BaseUnit
        fields = "__all__"
        exclude = ("tenant",)

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop("tenant", None)
        super(BaseUnitForm, self).__init__(*args, **kwargs)
        if tenant:
            queryset = _tenant_or_global_qs(BaseUnit, tenant).order_by("name")
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            self.fields["base_unit"].queryset = queryset
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)
            visible.field.widget.attrs['placeholder'] = _(visible.field.label)

class CustomerPaymentForm(forms.ModelForm):
    class Meta:
        model = CustomerPayment
        fields = ["payment_amount", "payment_method", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        base = "w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-gray-900 focus:outline-none focus:ring-2 focus:ring-gray-900/10"
        self.fields["payment_amount"].widget.attrs.update({"class": base, "min": "0.01", "step": "0.01"})
        self.fields["payment_method"].widget.attrs.update({"class": base})
        self.fields["note"].widget.attrs.update({"class": base, "rows": 2})


class InventoryTransferForm(forms.Form):
    SCOPE_CHOICES = [
        ("store", _("Store")),
        ("branch", _("Branch")),
    ]
    product = forms.ModelChoiceField(queryset=Products.objects.none(), label=_("Product"))
    from_scope = forms.ChoiceField(choices=SCOPE_CHOICES, label=_("From"))
    to_scope = forms.ChoiceField(choices=SCOPE_CHOICES, label=_("To"))
    from_store = forms.ModelChoiceField(queryset=Store.objects.none(), required=False, label=_("From Store"))
    from_branch = forms.ModelChoiceField(queryset=Branch.objects.none(), required=False, label=_("From Branch"))
    to_store = forms.ModelChoiceField(queryset=Store.objects.none(), required=False, label=_("To Store"))
    to_branch = forms.ModelChoiceField(queryset=Branch.objects.none(), required=False, label=_("To Branch"))
    package_qty = forms.IntegerField(min_value=0, label=_("Package Quantity"), initial=0)
    item_qty = forms.IntegerField(min_value=0, label=_("Item Quantity"), initial=0)

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop("tenant", None)
        fixed_from_scope = kwargs.pop("fixed_from_scope", None)
        fixed_from_store = kwargs.pop("fixed_from_store", None)
        fixed_from_branch = kwargs.pop("fixed_from_branch", None)
        super().__init__(*args, **kwargs)
        self.fixed_from_scope = fixed_from_scope
        self.fixed_from_store = fixed_from_store
        self.fixed_from_branch = fixed_from_branch
        if tenant:
            self.fields["product"].queryset = Products.objects.filter(tenant=tenant).order_by("name")
            self.fields["from_store"].queryset = Store.objects.filter(tenant=tenant, is_active=True).order_by("name")
            self.fields["to_store"].queryset = Store.objects.filter(tenant=tenant, is_active=True).order_by("name")
            self.fields["from_branch"].queryset = Branch.objects.filter(store__tenant=tenant, is_active=True).order_by("name")
            self.fields["to_branch"].queryset = Branch.objects.filter(store__tenant=tenant, is_active=True).order_by("name")

        if fixed_from_scope:
            self.fields["from_scope"].required = False
            self.fields["from_scope"].initial = fixed_from_scope
            self.fields["from_scope"].widget.attrs["disabled"] = True
        if fixed_from_store:
            self.fields["from_store"].required = False
            self.fields["from_store"].initial = fixed_from_store.id
            self.fields["from_store"].widget.attrs["disabled"] = True
        if fixed_from_branch:
            self.fields["from_branch"].required = False
            self.fields["from_branch"].initial = fixed_from_branch.id
            self.fields["from_branch"].widget.attrs["disabled"] = True

        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)
            visible.field.widget.attrs['placeholder'] = _(visible.field.label)

    def clean(self):
        cleaned = super().clean()
        from_scope = cleaned.get("from_scope")
        to_scope = cleaned.get("to_scope")
        from_store = cleaned.get("from_store")
        from_branch = cleaned.get("from_branch")
        to_store = cleaned.get("to_store")
        to_branch = cleaned.get("to_branch")
        package_qty = cleaned.get("package_qty") or 0
        item_qty = cleaned.get("item_qty") or 0

        if self.fixed_from_scope:
            from_scope = self.fixed_from_scope
            from_store = self.fixed_from_store
            from_branch = self.fixed_from_branch
            cleaned["from_scope"] = from_scope
            cleaned["from_store"] = from_store
            cleaned["from_branch"] = from_branch

        if from_scope == to_scope and from_store == to_store and from_branch == to_branch:
            self.add_error("to_scope", _("From and To locations must be different."))

        if from_scope == "store" and not from_store:
            self.add_error("from_store", _("Select a source store."))
        if from_scope == "branch" and not from_branch:
            self.add_error("from_branch", _("Select a source branch."))
        if to_scope == "store" and not to_store:
            self.add_error("to_store", _("Select a destination store."))
        if to_scope == "branch" and not to_branch:
            self.add_error("to_branch", _("Select a destination branch."))

        if package_qty == 0 and item_qty == 0:
            self.add_error("package_qty", _("Quantity must be greater than 0."))
        return cleaned
