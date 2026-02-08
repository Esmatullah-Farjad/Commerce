from django import forms
from django import forms
from .models import BaseUnit, CustomerPayment, ExchangeRate, OtherIncome, Products, Customer, Expense
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

# forms.py
class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Products
        exclude = ['tenant', 'stock', 'total_package_price', 'item_sale_price', 'usd_package_sale_price']
    
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop("tenant", None)
        super(PurchaseForm, self).__init__(*args, **kwargs)
        if tenant:
            self.fields["category"].queryset = self.fields["category"].queryset.filter(tenant=tenant)
            self.fields["unit"].queryset = self.fields["unit"].queryset.filter(tenant=tenant)
            self.fields["purchase_unit"].queryset = self.fields["purchase_unit"].queryset.filter(tenant=tenant)
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
    client_name = forms.CharField(
        label=_('Client Name'),
        help_text=_('Your company or client name.'),
    )
    store_name = forms.CharField(
        label=_('Main Store Name'),
        help_text=_('The main store or brand name.'),
    )
    branch_name = forms.CharField(
        label=_('Main Branch Name'),
        help_text=_('Your primary branch or location name.'),
    )
    branch_address = forms.CharField(
        label=_('Branch Address'),
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
    )

    class Meta:
        model = User
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'client_name',
            'store_name',
            'branch_name',
            'branch_address',
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
        self.fields['client_name'].widget = forms.TextInput(attrs={'class': BASE_INPUT_CLASSES})
        self.fields['store_name'].widget = forms.TextInput(attrs={'class': BASE_INPUT_CLASSES})
        self.fields['branch_name'].widget = forms.TextInput(attrs={'class': BASE_INPUT_CLASSES})
        self.fields['branch_address'].widget.attrs.update({'class': BASE_TEXTAREA_CLASSES})
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)

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
        super(BaseUnitForm, self).__init__(*args, **kwargs)
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
        self.fields["payment_amount"].widget.attrs.update({"class": base, "min": "1"})
        self.fields["payment_method"].widget.attrs.update({"class": base})
        self.fields["note"].widget.attrs.update({"class": base, "rows": 2})
