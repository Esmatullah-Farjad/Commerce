from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
# Create your models here.


class Tenant(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
        unique_together = ("tenant", "code")

    def __str__(self):
        return self.name


class Branch(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, null=True, blank=True)
    address = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
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
        unique_together = ("branch", "user")

    def __str__(self):
        return f"{self.user.username} @ {self.branch}"


class Category(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="categories", null=True, blank=True)
    name = models.CharField(max_length=50)
    description = models.CharField(max_length=200)

    def __str__(self):
        return self.name
    
class BaseUnit(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="base_units", null=True, blank=True)
    name = models.CharField(max_length=50)
    is_weight_base = models.BooleanField(default=False)
    conversion_to_base = models.FloatField(
        null=True, blank=True,
        help_text= _("Conversion factor to the base unit (e.g., 7 for Sir if base is KG). Leave blank if conversion is product-specific.")

        )
    
    def __str__(self):
        return f"{self.name} {self.conversion_to_base}"
    
class PurchaseUnit(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="purchase_units", null=True, blank=True)
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=50)

    def __str__(self):
        return self.name



class ExchangeRate(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="exchange_rates", null=True, blank=True)
    usd_to_afn = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

from decimal import Decimal

class Products(models.Model):
    NUMBER_CHOICES = [(i, str(i)) for i in range(1, 201)]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="products", null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    code = models.IntegerField(null=True, default=0)
    name = models.CharField(max_length=100)
    unit = models.ForeignKey(BaseUnit, on_delete=models.CASCADE, null=True, blank=True)
    purchase_unit = models.ForeignKey(PurchaseUnit, on_delete=models.CASCADE, null=True, blank=True)

    package_contain = models.PositiveBigIntegerField(choices=NUMBER_CHOICES)
    package_purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)  # entered in USD or AFN
    package_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)  # entered in AFN (display)

    usd_package_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # ← added
    num_of_packages = models.IntegerField(default=1)
    total_package_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, default=0)
    item_sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, default=0)  # in AFN

    num_items = models.IntegerField(default=0, null=True, blank=True)
    stock = models.IntegerField()
    image = models.ImageField(default='default.png', upload_to='item_images')
    description = models.TextField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_product_code_per_tenant"),
        ]

    def __str__(self):
        return self.name

    @property
    def latest_usd_rate(self):
        rate = ExchangeRate.objects.filter(tenant=self.tenant).last() if self.tenant_id else ExchangeRate.objects.last()
        return rate.usd_to_afn if rate else Decimal('1')

    def is_usd_unit(self):
        return self.purchase_unit and self.purchase_unit.code.lower() == 'usd'

    @property
    def dynamic_afn_sale_price(self):
        """
        For USD products: convert stored USD sale price to current AFN.
        For AFN products: return stored AFN price.
        """
        if self.is_usd_unit() and self.usd_package_sale_price:
            return round(self.usd_package_sale_price * self.latest_usd_rate, 2)
        return self.package_sale_price or Decimal('0')

    
class Customer(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="customers", null=True, blank=True)
    name = models.CharField(max_length=200, null=True, blank=True, default="متفرقه")
    phone = models.IntegerField(null=True, blank=True, default=0000000)
    address = models.CharField(max_length=200, null=True, blank=True,default="------")

    def __str__(self):
        return self.name or f"Customer #{self.id}"


class BillNumberTracker(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="bill_tracker", null=True, blank=True)
    current_number = models.PositiveIntegerField(default=1001)

    @classmethod
    def get_next_bill_number(cls, tenant):
        # Get or create the tracker instance
        tracker, created = cls.objects.get_or_create(tenant=tenant)
        # Increment the counter
        next_number = tracker.current_number
        tracker.current_number += 1
        tracker.save()
        return next_number   


class SalesDetails(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sales_details", null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, related_name="sales_details", null=True, blank=True)
    user = models.ForeignKey(User, related_name='user',null=True, blank=True, on_delete=models.SET_NULL)
    bill_number = models.CharField(max_length=100, editable=False, default="")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="customer")
    total_amount = models.CharField(max_length=200,null=True, blank=True)
    paid_amount = models.CharField(max_length=200,null=True, blank=True, default="0")
    unpaid_amount = models.CharField(max_length=200,null=True, blank=True, default="0")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "bill_number"], name="uniq_bill_per_tenant"),
        ]

    def save(self, *args, **kwargs):
        # Generate a unique bill number if not already set
        if not self.bill_number:
            self.bill_number = str(BillNumberTracker.get_next_bill_number(self.tenant))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.bill_number

class SalesProducts(models.Model):
    sale_detail = models.ForeignKey(SalesDetails, related_name='sale_detail',on_delete=models.CASCADE)
    product = models.ForeignKey(Products, related_name='produts', null=True,blank=True, on_delete=models.SET_NULL)
    item_price = models.CharField(max_length=200, null=True, blank=True)
    package_price = models.CharField(max_length=200, null=True, blank=True)
    item_qty = models.CharField(max_length=200, null=True, blank=True)
    package_qty = models.CharField(max_length=200, null=True, blank=True)
    total_price = models.CharField(max_length=200, null=True, blank=True)
    
    def __str__(self):
        return f"bill number {self.sale_detail}"
    


class OtherIncome(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="other_incomes", null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, related_name="other_incomes", null=True, blank=True)
    date_created = models.DateField()
    source = models.CharField(max_length=255)  # like 'Commission', 'Asset Sale'
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.source

class Expense(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="expenses", null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, related_name="expenses", null=True, blank=True)
    date_created = models.DateField()
    category = models.CharField(max_length=255)  # like 'Rent', 'Salaries', 'Car Fare'
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.category
    
class CustomerPayment(models.Model):
    PAYMENT_METHOD = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('hesab_pay', 'Hesab Pay'),
        ('hawala', 'Hawala'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="customer_payments", null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, related_name="customer_payments", null=True, blank=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,   
        null=True,                   
        blank=True,
        related_name='payments'
    )
    payment_amount = models.IntegerField()
    payment_method = models.CharField(max_length=255, choices=PAYMENT_METHOD, default='cash')
    note = models.TextField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        customer_name = self.customer.name if self.customer else "Deleted Customer"
        return f"{customer_name} - {self.get_payment_method_display()} - {self.payment_amount}"


class BranchStock(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stock_levels")
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="branch_stocks")
    stock = models.IntegerField(default=0)
    num_of_packages = models.IntegerField(default=0)
    num_items = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("branch", "product")

    def __str__(self):
        return f"{self.branch} - {self.product.name}"


class StockTransfer(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    from_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stock_transfers_out")
    to_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stock_transfers_in")
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="stock_transfers")
    quantity = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="requested_transfers")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_transfers")
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.product.name}: {self.from_branch} -> {self.to_branch}"
