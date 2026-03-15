from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Customer(models.Model):
    tenant = models.ForeignKey(
        "client.Tenant",
        on_delete=models.CASCADE,
        related_name="customers",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200, null=True, blank=True, default="Walk-in Customer")
    phone = models.IntegerField(null=True, blank=True, default=0)
    address = models.CharField(max_length=200, null=True, blank=True, default="------")

    class Meta:
        db_table = "store_customer"

    def __str__(self):
        return self.name or f"Customer #{self.id}"


class CustomerPayment(models.Model):
    PAYMENT_METHOD = [
        ("cash", "Cash"),
        ("bank_transfer", "Bank Transfer"),
        ("hesab_pay", "Hesab Pay"),
        ("hawala", "Hawala"),
    ]

    tenant = models.ForeignKey(
        "client.Tenant",
        on_delete=models.CASCADE,
        related_name="customer_payments",
        null=True,
        blank=True,
    )
    branch = models.ForeignKey(
        "client.Branch",
        on_delete=models.SET_NULL,
        related_name="customer_payments",
        null=True,
        blank=True,
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    payment_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(max_length=255, choices=PAYMENT_METHOD, default="cash")
    note = models.TextField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "store_customerpayment"

    def clean(self):
        super().clean()
        if self.customer_id and self.tenant_id and self.customer.tenant_id != self.tenant_id:
            raise ValidationError({"customer": _("Customer must belong to the selected tenant.")})
        if self.branch_id and self.tenant_id and self.branch.store.tenant_id != self.tenant_id:
            raise ValidationError({"branch": _("Branch must belong to the selected tenant.")})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        customer_name = self.customer.name if self.customer else "Deleted Customer"
        return f"{customer_name} - {self.get_payment_method_display()} - {self.payment_amount}"
