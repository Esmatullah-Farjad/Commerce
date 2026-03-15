from django import forms
from django.utils.translation import gettext_lazy as _

from client.forms import RegistrationForm, UserActivationForm
from customer.forms import CustomerForm, CustomerPaymentForm

from .form_utils import BASE_INPUT_CLASSES, apply_placeholders, apply_tailwind_classes
from .models import (
    BaseUnit,
    Branch,
    Category,
    ExchangeRate,
    Expense,
    OtherIncome,
    Products,
    PurchaseUnit,
    Store,
)


def _tenant_or_global_qs(model, tenant):
    if tenant and model.objects.filter(tenant=tenant).exists():
        return model.objects.filter(tenant=tenant)
    return model.objects.filter(tenant__isnull=True)


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Products
        exclude = [
            "tenant",
            "stock",
            "total_package_price",
            "item_sale_price",
            "usd_package_sale_price",
            "currency_category",
        ]

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop("tenant", None)
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields["category"].queryset = _tenant_or_global_qs(Category, tenant)
            self.fields["unit"].queryset = _tenant_or_global_qs(BaseUnit, tenant)
            self.fields["purchase_unit"].queryset = PurchaseUnit.objects.all()
        if "unit" in self.fields:
            self.fields["unit"].label_from_instance = (
                lambda obj: f"{obj.name} (Base: {obj.base_unit.name})"
                if obj.base_unit
                else f"{obj.name} (Base: {obj.name})"
            )
        apply_placeholders(self)


class ExchangeRateForm(forms.ModelForm):
    class Meta:
        model = ExchangeRate
        exclude = ["tenant"]
        widgets = {
            "usd_to_afn": forms.NumberInput(
                attrs={"step": "0.01", "class": BASE_INPUT_CLASSES}
            ),
        }


class OtherIncomeForm(forms.ModelForm):
    class Meta:
        model = OtherIncome
        field = "__all__"
        exclude = ("tenant", "branch")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_created"].widget = forms.DateInput(
            attrs={
                "type": "date",
                "class": BASE_INPUT_CLASSES,
            }
        )
        if "date_created" in self.fields:
            self.fields["date_created"].widget.attrs.update(
                {
                    "class": f"jalali-date-picker {BASE_INPUT_CLASSES}",
                    "autocomplete": "off",
                }
            )
        apply_placeholders(self)


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = "__all__"
        exclude = ("tenant", "branch")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_created"].widget = forms.DateInput(
            attrs={
                "type": "date",
                "class": BASE_INPUT_CLASSES,
            }
        )
        if "date_created" in self.fields:
            self.fields["date_created"].widget.attrs.update(
                {
                    "class": f"jalali-date-picker {BASE_INPUT_CLASSES}",
                    "autocomplete": "off",
                }
            )
        apply_placeholders(self)


class BaseUnitForm(forms.ModelForm):
    class Meta:
        model = BaseUnit
        fields = "__all__"
        exclude = ("tenant",)

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop("tenant", None)
        super().__init__(*args, **kwargs)
        if tenant:
            queryset = _tenant_or_global_qs(BaseUnit, tenant).order_by("name")
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            self.fields["base_unit"].queryset = queryset
        apply_placeholders(self)


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

        apply_placeholders(self)

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
