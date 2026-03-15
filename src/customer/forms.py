from django import forms

from store.form_utils import BASE_INPUT_CLASSES, apply_tailwind_classes

from .models import Customer, CustomerPayment


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        exclude = ["tenant"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for visible in self.visible_fields():
            apply_tailwind_classes(visible.field)

        self.fields["name"].widget.attrs.update(
            {"placeholder": "Customer name", "autocomplete": "off"}
        )
        self.fields["phone"].widget.attrs.update(
            {"placeholder": "Customer phone", "autocomplete": "off"}
        )
        self.fields["address"].widget.attrs.update(
            {"placeholder": "Address", "autocomplete": "off"}
        )


class CustomerPaymentForm(forms.ModelForm):
    class Meta:
        model = CustomerPayment
        fields = ["payment_amount", "payment_method", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_amount"].widget.attrs.update(
            {"class": BASE_INPUT_CLASSES, "min": "0.01", "step": "0.01"}
        )
        self.fields["payment_method"].widget.attrs.update({"class": BASE_INPUT_CLASSES})
        self.fields["note"].widget.attrs.update({"class": BASE_INPUT_CLASSES, "rows": 2})
