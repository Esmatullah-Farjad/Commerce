from datetime import date
import math
from django.shortcuts import redirect, render, get_object_or_404
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils.translation import activate
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Count,F, ExpressionWrapper, DecimalField
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import render_to_string

from decimal import Decimal



from store.filters import ProductsFilter, SalesDetailsFilter
from .models import BaseUnit, Category, Customer, ExchangeRate, OtherIncome, Expense, Products, SalesDetails, SalesProducts
from .forms import BaseUnitForm, CustomerForm, CustomerPaymentForm, ExchangeRateForm, OtherIncomeForm, ExpenseForm, PurchaseForm, RegistrationForm
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import authenticate, login, logout
import jdatetime


import json
from django.http import HttpResponse, JsonResponse

# Create your views here.
def switch_language(request, lang_code):
    if lang_code in dict(settings.LANGUAGES):  # ✅ Ensure the language is valid
        activate(lang_code)
        request.session['django_language'] = lang_code  # ✅ Store in session
        # ✅ Store the language in a cookie
        response = redirect(request.META.get('HTTP_REFERER', '/'))
        response.set_cookie('django_language', lang_code, max_age=31536000)  # 1 year
        return response
    return redirect('/')

def root_view(request):
    if request.user.is_authenticated:  # Check if the user is authenticated
        return redirect('home')  # Redirect to the 'home' page
    else:
        return redirect("landing")

def landing(request):    
    return render(request, "landing-page.html")

def Home(request):
    if not request.user.is_authenticated:
        return redirect("landing")
    order_products = Products.objects.filter(num_of_packages__lt=10)
    today_date = date.today()
    sales_details = (
        SalesDetails.objects
        .filter(user=request.user, created_at__date=today_date)
        .aggregate(
            total_sale=Sum('total_amount'),
            total_paid=Sum('paid_amount'),
            total_unpaid=Sum('unpaid_amount'),
            total_customer=Count('customer', distinct=True)  # Ensure distinct customers are counted
        )
    )
    
    top_packages = (
        SalesProducts.objects
        .filter(sale_detail__user=request.user, sale_detail__created_at__date=today_date)
        .values('product__name','product__category__name')  # Group by product name
        .annotate(total_package_qty=Sum('package_qty'))  # Calculate total package quantity for each product
        .order_by('-total_package_qty')[:10]  # Order by total package quantity in descending order
    )
    context = {
        'top_packages':top_packages,
        'sales_details':sales_details,
        'order_products':order_products
    }
    return render(request, 'home.html', context)

def signin(request):
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST.get('password')
        user = authenticate(request, username=email, email=email, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, _("Welcome !"))
            return redirect('home')
        else:
            messages.error(request, _("Invalid username or password"))
    return render(request, 'auth/login.html')

def signup(request):
    form = RegistrationForm()
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("The user has been registered successfully"))
            
        else:
            messages.error(request, _("Something Went wrong. Please fix the below error !"))
           
    register_form = form
    context = {
        'form':register_form
    }
    return render(request, 'auth/register.html', context)

def signout(request):
    logout(request) 
    return redirect('sign-in') 

# views.py


def purchase(request):
    form = PurchaseForm()
    if request.method == 'POST':
        form = PurchaseForm(request.POST, request.FILES)

        if form.is_valid():
            cd = form.cleaned_data
            package_contain = cd['package_contain']
            package_purchase_price = cd['package_purchase_price']
            num_of_packages = cd['num_of_packages']
            package_sale_price_afn = cd['package_sale_price']
            purchase_unit = cd['purchase_unit']

            # Calculate USD equivalent of AFN sale price (for USD products)
            usd_package_sale_price = None
            rate = ExchangeRate.objects.last()
            usd_rate = rate.usd_to_afn if rate else Decimal('1')

            if purchase_unit and purchase_unit.code.lower() == 'usd':
                usd_package_sale_price = round(Decimal(package_sale_price_afn) / usd_rate, 2)

            # Basic calculations
            total_package_price = Decimal(package_purchase_price) * num_of_packages
            stock = package_contain * num_of_packages
            item_sale_price = round(Decimal(package_sale_price_afn) / package_contain, 2)

            product = form.save(commit=False)
            product.total_package_price = total_package_price
            product.stock = stock
            product.item_sale_price = item_sale_price
            product.usd_package_sale_price = usd_package_sale_price
            product.user = request.user
            product.save()

            messages.success(request, "Product added successfully!")
            return redirect('purchase')
        else:
            messages.error(request, f"Something went wrong. Please fix the below errors: {form.errors}")

    purchase = Products.objects.all().order_by('-id')

    # Pagination
    p = Paginator(purchase, 14)
    page_number = request.GET.get('page')
    page_obj = p.get_page(page_number or 1)

    context = {
        'category': Category.objects.all(),
        'page_obj': page_obj,
        'num': range(1, 100),
        'form': form
    }
    return render(request, 'purchase/purchase.html', context)



def products_display(request):
    product = Products.objects.all().order_by('-id')
    p = Paginator(product, 14)
    page_number = request.GET.get('page')
    try:
        page_obj = p.get_page(page_number)
    except PageNotAnInteger:
        page_obj = p.page(1)
    except EmptyPage:
        page_obj = p.page(p.num_pages)
    # paginator end
    context = {'page_obj':page_obj,'flag':'list'}
    return render(request, 'purchase/product.html', context)

def update_products(request, pid):
    product = get_object_or_404(Products, pk=pid)

    form = PurchaseForm(instance=product)
    if request.method == 'POST':
        form = PurchaseForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            package_purchase_price = form.cleaned_data['package_purchase_price']
            package_contain = form.cleaned_data.get('package_contain')
            num_of_packages = form.cleaned_data.get('num_of_packages')
            package_sale_price = form.cleaned_data.get('package_sale_price')

            total_package_price = int(num_of_packages) * int(package_purchase_price)
            total_items = int(package_contain) * int(num_of_packages)
            item_sale_price = round((package_sale_price / package_contain), 3) if package_contain else 0

            product = form.save(commit=False)
            product.total_items = total_items
            product.item_sale_price = item_sale_price
            product.total_package_price = total_package_price
            product.save()

            messages.success(request, "Product updated successfully.")
            return redirect("products_display")
        else:
            messages.error(request, f"Form has error: {form.errors}")

    context = {
        'product': product,
        'form': form
    }
    return render(request, 'purchase/purchase.html', context)

def delete_products(request, pid):
    product = get_object_or_404(Products, pk=pid)
    if product:
        product.delete()
        messages.success(request, _("Product deleted successfully"))
    return redirect("products_display")

def products_view(request):
    categories = Category.objects.all()
    customer = request.session.get('customer', {})
    customer_list = []
    products_queryset = Products.objects.select_related('category')

    products_filter = ProductsFilter(
        request.GET,
        request=request,
        queryset=products_queryset
    )

    # Handle session customer data
    if customer:  
        customer_list = list(customer.values())[0]

    # # Pagination
    # paginator = Paginator(products_filter.qs, 10)  # Show 10 products per page
    # page_number = request.GET.get('page')
    # page_obj = paginator.get_page(page_number)
    context = {
        'products': products_filter.qs,
        'categories': categories,
        'filter_form': products_filter,
        'customer': customer_list
    }
    return render(request, 'sale/product_view.html', context)

def check_customer(request):
    code = request.GET.get("code")
    try:
        existing_customer = Customer.objects.get(id=code)
        customer_session = request.session.get('customer', {})
        customer_session[existing_customer.id] = existing_customer.name
        request.session['customer'] = customer_session
        form = CustomerForm(instance=existing_customer)
    except Customer.DoesNotExist:
        form = CustomerForm(initial={"code": code})
    return render(request, "partials/_customer_form.html", {"form": form})

def create_customer(request):
    form = CustomerForm()
    if request.method == 'POST':
        if 'ignore' in request.POST:
            customer, created = Customer.objects.get_or_create(
            name="متفرقه",
            phone="0000000",  # Put phone in quotes if it's a CharField
            defaults={"address": "------"}
            )

            existing_customer = get_object_or_404(Customer, pk=customer.id)
            customer_session = request.session.get('customer', {})
            customer_session[existing_customer.id] = existing_customer.name
            request.session['customer'] = customer_session
            return redirect('products-view')
            
        else:
            form = CustomerForm(request.POST)
            if form.is_valid():
               
                new_customer = form.save()
                # Add to session
                customer_session = request.session.get('customer', {})
                customer_session[new_customer.id] = new_customer.name
                request.session['customer'] = customer_session
                # Notify user
                messages.success(request, _("Customer has been added successfully."))
                return redirect('products-view')
            else:
                messages.error(request, _("Something went wrong. Please fix the errors below."))
                print(f"Form errors: {form.errors}")

                
    else:
        form=CustomerForm()
        
    context = {
        'form':form
    }
    return render(request, 'sale/product_view.html', context)

def old_customer(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    customer_session = request.session.get('customer', {})
    customer_session[customer.id] = customer.name
    request.session['customer'] = customer_session
    messages.success(request, _("Customer has been selected successfully."))
    return redirect('products-view')

def search_products(request):
    search = request.GET.get('search')
    products = Products.objects.select_related('category')
    product_list = (
        products.filter(category__name__istartswith=search) | products.filter(name__istartswith=search)
    )
    context = {
        'products':product_list
    }
    return render(request, 'partials/_search_list.html', context)


def remove_cart_item(request, pid):
    cart = request.session.get('cart', {})
    # Find the key of the item with the specified product_id
    item_key_to_remove = None
    for item_key, item in cart.items():
        if str(item['product_id']) == pid:
            item_key_to_remove = item_key
            break

    # Remove the item from the cart if found
    if item_key_to_remove:
        del cart[item_key_to_remove]

        # Update the session
        request.session['cart'] = cart
    return redirect('cart-view')

# Add to Cart
def add_to_cart(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON body'}, status=400)

        # Extract data
        product_id = data.get('product_id')
        item_quantity = data.get('item_quantity', 0)
        package_quantity = data.get('package_quantity', 0)
        item_price = data.get('item_price', 0)
        package_price = data.get('package_price', 0)

        # Validate product existence
        product = Products.objects.filter(id=product_id).first()
        if not product:
            return JsonResponse({'status': 'error', 'message': 'Product not found'}, status=404)

        # Retrieve cart from session and update it
        cart = request.session.get('cart', {})
        cart[str(product_id)] = {
            'product_id': product_id,
            'item_quantity': item_quantity,
            'package_quantity': package_quantity,
            'item_price': item_price,
            'package_price': package_price,
        }
        request.session['cart'] = cart  # Save updated cart back into session

        return JsonResponse({"status": 200, "message": "success", "cart_length": len(cart)})
    
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def print_invoice(request, sales_id):
    sales_details = get_object_or_404(SalesDetails, bill_number=sales_id)
    
    sales_product = SalesProducts.objects.filter(sale_detail=sales_details)

    calculate = sales_product.aggregate(
        total_amount=Sum('total_price')
    )
    context = {
        'sales_details':sales_details,
        'sales_products':sales_product,
        'calculate':calculate
    }
    return render(request, 'partials/_print_invoice.html', context)

def cart_view(request):
    # Retrieve cart and customer from session
    cart = request.session.get('cart', {})
    customer_session = request.session.get('customer', {})
    cart_details = []
    product_update_stock = []
    grand_total = 0
    pre_unpaid_amount = 0
    total = 0

    if not cart:
        return render(request, 'sale/cart_view.html', {'cart_details': [], 'grand_total': 0, 'customer': None})

    # Fetch all products at once
    product_ids = [item['product_id'] for item in cart.values()]
    products = Products.objects.filter(pk__in=product_ids).select_related()
    product_mapping = {product.id: product for product in products}

    # Build cart details
    for item in cart.values():
        product = product_mapping.get(safe_int(item.get('product_id')))
        if not product:
            continue

        item_quantity = safe_int(item.get('item_quantity'))
        package_quantity = safe_int(item.get('package_quantity'))
        item_price = float(item.get('item_price'))
        package_price = float(item.get('package_price'))

        # Calculate stock updates
        package_contain = safe_int(product.package_contain, 1)  # Default to 1 to avoid division by zero
        sold_stock = (package_quantity * package_contain) + item_quantity
        new_stock = safe_int(product.stock) - sold_stock
        product.stock = new_stock
        product.num_of_packages = new_stock // package_contain
        product.num_items = new_stock % package_contain
        product_update_stock.append(product)

        # Calculate subtotal and cart details
        sub_total = round((item_quantity * item_price) + (package_quantity * package_price),2)
        grand_total = math.ceil(grand_total + sub_total)
        cart_details.append({
            'product': product,
            'item_quantity': item_quantity,
            'package_quantity': package_quantity,
            'item_price': item_price,
            'package_price': package_price,
            'sub_total': sub_total,
        })

    # Retrieve customer instance
    customer_instance = None
    if customer_session:
        customer_pk = list(customer_session.keys())[0]
        customer_instance = Customer.objects.filter(pk=customer_pk).first() 
        if customer_instance:
            pre_unpaid = SalesDetails.objects.filter(customer=customer_instance).aggregate(
                total_unpaid=Sum('unpaid_amount')
            )
            pre_unpaid_amount = pre_unpaid['total_unpaid'] or 0
    total = grand_total
    grand_total = grand_total + pre_unpaid_amount
    # Handle sale submission
    if request.method == 'POST':
        try:
            paid_amount = safe_int(request.POST.get('paid', 0))
            unpaid_amount = grand_total - paid_amount
           
            SalesDetails.objects.filter(customer=customer_instance, unpaid_amount__gt=0).update(unpaid_amount=0)
            # Create SalesDetails instance
            with transaction.atomic():
                sales_details = SalesDetails.objects.create(
                    user = request.user,
                    customer=customer_instance,
                    total_amount=grand_total,
                    paid_amount=paid_amount,
                    unpaid_amount=unpaid_amount,
                )
                
                # Bulk update product stock
                Products.objects.bulk_update(product_update_stock, ['stock', 'num_of_packages', 'num_items'])

                # Bulk create SalesProducts
                sales_products = [
                    SalesProducts(
                        sale_detail=sales_details,
                        product=item['product'],  # Directly use the product instance
                        item_price=item['item_price'],
                        package_price=item['package_price'],
                        item_qty=item['item_quantity'],
                        package_qty=item['package_quantity'],
                        total_price=item['sub_total'],
                    ) for item in cart_details
                ]
                SalesProducts.objects.bulk_create(sales_products)

            # Clear cart after successful sale
            request.session['cart'] = {}
            request.session['customer'] = {}
            messages.success(request, "Products have been sold successfully!")
            return redirect("print-invoice",sales_details)
        except Exception as e:
            # Roll back the transaction and handle the error gracefully
            messages.error(request, f"An error occurred: {str(e)}")

    context = {
        'cart_details': cart_details,
        'grand_total': grand_total,
        'pre_unpaid_amount':pre_unpaid_amount,
        'customer': customer_instance,
        'total':total
    }
    return render(request, 'sale/cart_view.html', context)

def sold_products_view(request):
    sales_details = SalesDetails.objects.select_related("customer").prefetch_related(
       "sale_detail"
    )
    if request.method == 'POST':
        bill_number = request.POST.get('bill-number')
        if bill_number:
            sales_details=sales_details.filter(bill_number=bill_number)

    context = {
        'sold_products':sales_details
    }
    return render(request, 'sale/sold_products_view.html', context)

def sold_product_detail(request, pk):
    sales_id = get_object_or_404(SalesDetails, pk=pk)
   
    sales_products = SalesProducts.objects.filter(sale_detail=pk).select_related('product')

    context = {
        'sales_products':sales_products,
        'sales_info':sales_id,
    }
    return render(request, 'sale/sold_products_detail.html', context)

def return_items(request, pk):
    # Get the returned product or raise 404
    returned_product = get_object_or_404(SalesProducts, id=pk)
    
    # Calculate new quantities
    returned_pkg = safe_int(returned_product.package_qty)
    returned_item = safe_int(returned_product.item_qty)
    product = returned_product.product  # Get the related product
    
    # Use atomic transaction to prevent race conditions
    with transaction.atomic():
        # Update product quantities
        product.num_of_packages = safe_int(product.num_of_packages) + returned_pkg
        product.num_items = safe_int(product.num_items) + returned_item
        product.save() 
        returned_product.delete()
        return HttpResponse('', headers={'HX-Trigger': 'returnSuccess'})

    



# dashboard contaner view
def income(request):
    form = OtherIncomeForm()
    today_date = date.today()
    other_income = OtherIncome.objects.filter(date_created=today_date)
    if request.method == 'POST':
        form = OtherIncomeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("Income has been added successfully"))
        else:
            messages.error(request, _("Something went wrong. Please try again"))
    context = {
        'form':form,
        'other_income':other_income
    }
    return render(request, 'partials/management/_income-view.html', context)

def expense(request):
    form = ExpenseForm()
    today_date = date.today()
    expenses = Expense.objects.filter(date_created=today_date).order_by('-id')
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("Expense has been added successfully"))
        else:
            messages.error(request, _("Something went wrong. Please try again"))
    context = {
        'form': form,
        'expenses': expenses
    }
    return render(request, 'partials/management/_expense-view.html', context)

def summary(request):
    sales = SalesDetails.objects.all().order_by('-created_at')
    sales_filter = SalesDetailsFilter(request.GET, queryset=sales)
    filtered_sales = sales_filter.qs
    totals = filtered_sales.aggregate(
        total_paid_amount=Sum('paid_amount'),
        total_unpaid_amount=Sum('unpaid_amount'),
        total_sale_value=Sum(
            ExpressionWrapper(
                F('paid_amount') + F('unpaid_amount'),
                output_field=DecimalField()
            )
        )
    )
    total_customers = filtered_sales.aggregate(
        total_customer=Count('customer', distinct=True)
    )

    def _parse_jalali_date(value):
        try:
            year, month, day = map(int, value.split('-'))
            jalali_date = jdatetime.date(year, month, day)
            return jalali_date.togregorian()
        except Exception:
            return None

    from_date = _parse_jalali_date(request.GET.get('from_date', ''))
    to_date = _parse_jalali_date(request.GET.get('to_date', ''))

    income_qs = OtherIncome.objects.all()
    expense_qs = Expense.objects.all()

    if from_date:
        income_qs = income_qs.filter(date_created__gte=from_date)
        expense_qs = expense_qs.filter(date_created__gte=from_date)
    if to_date:
        income_qs = income_qs.filter(date_created__lte=to_date)
        expense_qs = expense_qs.filter(date_created__lte=to_date)

    income_totals = income_qs.aggregate(total_amount=Sum('amount'))
    expense_totals = expense_qs.aggregate(total_amount=Sum('amount'))

    # Access values
    total_paid = totals['total_paid_amount'] or 0
    total_unpaid = totals['total_unpaid_amount'] or 0
    total_value = totals['total_sale_value'] or 0
    total_customer = total_customers['total_customer'] or 0
    total_income = income_totals['total_amount'] or 0
    total_expense = expense_totals['total_amount'] or 0
    net_balance = total_income - total_expense
    context= {
        "sales": filtered_sales,
        "filter":sales_filter,
        "total_paid": total_paid,
        "total_unpaid": total_unpaid,
        "total_value" :total_value,
        "total_customer": total_customer,
        "total_income": total_income,
        "total_expense": total_expense,
        "net_balance": net_balance,
    }
    return render(request, 'partials/management/_summary-view.html',context)
def returned(request):
    bill_query = request.GET.get('bill')
    customer_query = request.GET.get('customer')
    sales = SalesDetails.objects.select_related('customer').order_by('-created_at')
    if bill_query:
        sales = sales.filter(bill_number__icontains=bill_query)
    if customer_query:
        sales = sales.filter(customer__name__icontains=customer_query)
    recent_sales = sales[:30]
    context = {
        "recent_sales": recent_sales,
        "bill_query": bill_query or "",
        "customer_query": customer_query or "",
    }
    return render(request, 'partials/management/_return-view.html', context)

def base_unit(request):
    form = BaseUnitForm()
    base_units = BaseUnit.objects.all()
    if request.method == 'POST':
        form = BaseUnitForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("Unit has been saved successfully"))
            return redirect('base-unit')
        else:
            messages.error(request, _("Something went wrong. Please try again"))
    else:
        form = form
    context = {
        'form':form,
        'base_units':base_units
    }
    return render(request, 'partials/management/_base_unit-view.html',context)

def update_base_unit(request, unit_id):
    baseunit = get_object_or_404(BaseUnit, pk=unit_id)
    base_units = BaseUnit.objects.all()
    if request.method == 'POST':
        form = BaseUnitForm(request.POST, instance=baseunit)
        if form.is_valid():
            form.save()
            messages.success(request, _("Unit has been updated successfully"))
            return redirect('base-unit')
        else:
            messages.error(request, _("Something went wrong. Please try again"))
    else:
        form = BaseUnitForm(instance=baseunit)

    context = {
        'form': form,
        'base_units': base_units
    }
    return render(request, 'partials/management/_base_unit-view.html', context)

def delete_base_unit(request, unit_id):
    baseunit = get_object_or_404(BaseUnit, pk=unit_id)
    # Delete the object
    deleted_count = baseunit.delete()  # delete() returns (number_of_deleted_objects, details)
    # Check if the object was deleted successfully
    if deleted_count:
        messages.success(request, _("Unit has been deleted successfully"))
    else:
        messages.error(request, _("Unable to delete the unit"))
    
    # Redirect to the base-unit page
    return redirect('base-unit')

# stock management view

def stock_management(request):
    currency_filter = request.GET.get('currency')

    products = Products.objects.all().order_by('-id')

    if currency_filter == 'usd':
        products = products.filter(purchase_unit__code__iexact='usd')
    elif currency_filter == 'afn':
        products = products.exclude(purchase_unit__code__iexact='usd')
    else:
        products = products.all()  # No filter applied

    # Apply pagination

    p = Paginator(products, 14)
    page_number = request.GET.get('page')
    try:
        page_obj = p.get_page(page_number)
    except PageNotAnInteger:
        page_obj = p.page(1)
    except EmptyPage:
        page_obj = p.page(p.num_pages)
    exchange_rate = ExchangeRate.objects.last()
    exchange_form = ExchangeRateForm(instance=exchange_rate)
    if request.method == 'POST':
        exchange_form = ExchangeRateForm(request.POST, instance=exchange_rate)
        if exchange_form.is_valid():
            exchange_form.save()
            messages.success(request, _("Exchange rate has been updated successfully"))
        else:
            messages.error(request, _("Something went wrong. Please try again"))
            exchange_form= ExchangeRateForm(instance=exchange_rate)
    

    context = {
        'page_obj': page_obj,
        'flag': 'list',
        'currency_filter': currency_filter,
        'exchange_form': exchange_form,
    }
    return render(request, 'partials/management/_stock_management.html', context)



def customer(request):
    customers = Customer.objects.all()
    # Add customer sales details (paid, unpaid, bill count) for each customer
    if request.method == 'POST':
        phone = request.POST.get('phone')
        customers = customers.filter(phone=phone)
    customer_data = []
    for customer in customers:
        sales_data = SalesDetails.objects.filter(customer=customer).aggregate(
            total_amount=Sum('total_amount'),
            total_paid=Sum('paid_amount'),
            total_unpaid=Sum('unpaid_amount'),
            bill_count=Count('bill_number')
        )
        customer_data.append({
            'customer': customer,
            'total_amount':sales_data['total_amount'] or 0, 
            'total_paid': sales_data['total_paid'] or 0,  # Default to 0 if None
            'total_unpaid': sales_data['total_unpaid'] or 0,  # Default to 0 if None
            'bill_count': sales_data['bill_count'],
        })
    

    context = {
        'customer_data':customer_data
    }
    return render(request, 'partials/management/_customer-view.html', context)

def sales_dashboard(request):
    return redirect('summary')




def create_payment(request, cid):
    customer = get_object_or_404(Customer, pk=cid)

    sales_details = (
        SalesDetails.objects
        .filter(customer=customer)
        .order_by("-id")
    )

    # totals for UI + payment box
    totals = sales_details.aggregate(
        total_amount=Sum("total_amount"),
        total_paid=Sum("paid_amount"),
        total_unpaid=Sum("unpaid_amount"),
    )
    total_amount = int(totals["total_amount"] or 0)
    total_paid = int(totals["total_paid"] or 0)
    total_due = int(totals["total_unpaid"] or 0)

    if request.method == "POST":
        form = CustomerPaymentForm(request.POST)
        if form.is_valid():
            paid_amount = int(form.cleaned_data["payment_amount"])

            if paid_amount <= 0:
                messages.error(request, "Payment amount must be greater than 0.")
                return redirect("create-payment", cid=customer.id)

            with transaction.atomic():
                # Save payment + attach customer
                payment = form.save(commit=False)
                payment.customer = customer
                payment.save()

                # Lock and update the LAST SalesDetails record only (overall unpaid stored there)
                last_sale = (
                    SalesDetails.objects
                    .select_for_update()
                    .filter(customer=customer)
                    .order_by("-id")
                    .first()
                )

                if not last_sale:
                    messages.error(request, "No sales record found for this customer.")
                    return redirect("create-payment", cid=customer.id)

                current_unpaid = int(last_sale.unpaid_amount or 0)

                if paid_amount > current_unpaid:
                    messages.error(request, f"Payment cannot be greater than unpaid amount ({current_unpaid}).")
                    return redirect("create-payment", cid=customer.id)

                last_sale.unpaid_amount = current_unpaid - paid_amount

                # Optional: also increase paid_amount on last_sale (if you use it)
                if last_sale.paid_amount is None:
                    last_sale.paid_amount = 0
                last_sale.paid_amount = int(last_sale.paid_amount) + paid_amount

                last_sale.save(update_fields=["unpaid_amount", "paid_amount"])

            messages.success(request, "Customer payment added successfully.")
            return redirect("create-payment", cid=customer.id)
    else:
        form = CustomerPaymentForm()

    context = {
        "customer": customer,
        "sales_details": sales_details,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_due": total_due,
        "has_unpaid": total_due > 0,
        "form": form,
    }
    return render(request, "partials/management/_customer-account.html", context)






# Bar code scanner view
@csrf_exempt
def get_product_by_barcode(request):
    if request.method == 'POST':
        barcode = request.POST.get('barcode')
        if not barcode:
            return JsonResponse({'status': 'error', 'message': 'No barcode provided'}, status=400)

        product = Products.objects.filter(code=barcode).first()
        if not product:
            return JsonResponse({'status': 'error', 'message': 'Product not found'}, status=404)

        return JsonResponse({
            'status': 'success',
            'product': {
                'id': product.id,
                'item_price': float(product.item_sale_price),
                'package_price': float(product.package_sale_price),
                'name': product.name,
            }
        })

    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=400)


def scanner_view(request):
    customer = request.session.get('customer', {})
    customer_list = []
    # Handle session customer data
    if customer:  
        customer_list = list(customer.values())[0]
    context = {
        'customer': customer_list
    }
    return render(request, 'sale/scanner_view.html',context)

# cart fragment for cart view

def cart_fragment(request):
    cart = request.session.get('cart', {})
    customer_session = request.session.get('customer', {})
    cart_details = []
    grand_total = 0

    if not cart:
        html = render_to_string('partials/_cart_table.html', {
            'cart_details': [],
            'grand_total': 0,
            'customer': None
        }, request=request)
        return JsonResponse({'html': html})

    # Reuse logic from cart_view
    product_ids = [item['product_id'] for item in cart.values()]
    products = Products.objects.filter(pk__in=product_ids)
    product_mapping = {product.id: product for product in products}

    for item in cart.values():
        product = product_mapping.get(safe_int(item.get('product_id')))
        if not product:
            continue

        item_quantity = safe_int(item.get('item_quantity'))
        package_quantity = safe_int(item.get('package_quantity'))
        item_price = safe_int(item.get('item_price'), 0)
        package_price = safe_int(item.get('package_price'), 0)

        sub_total = (item_quantity * item_price) + (package_quantity * package_price)
        grand_total += sub_total
        cart_details.append({
            'product': product,
            'item_quantity': item_quantity,
            'package_quantity': package_quantity,
            'item_price': item_price,
            'package_price': package_price,
            'sub_total': sub_total,
        })

    customer_instance = None
    if customer_session:
        customer_pk = list(customer_session.keys())[0]
        customer_instance = Customer.objects.filter(pk=customer_pk).first()

    html = render_to_string('partials/_cart_table.html', {
        'cart_details': cart_details,
        'grand_total': grand_total,
        'customer': customer_instance
    }, request=request)

    return JsonResponse({'html': html})
