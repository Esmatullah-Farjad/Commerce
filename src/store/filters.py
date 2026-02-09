import django_filters
from .models import Products,Category, SalesDetails
from django import forms

class ProductsFilter(django_filters.FilterSet):
    category = django_filters.ModelMultipleChoiceFilter(
        queryset = Category.objects.all(),
        widget=forms.SelectMultiple(attrs={"class": "input-field"})
    )
    class Meta:
        model = Products
        fields = ["category"]

    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop("tenant", None)
        super().__init__(*args, **kwargs)
        if tenant:
            if Category.objects.filter(tenant=tenant).exists():
                self.filters["category"].queryset = Category.objects.filter(tenant=tenant)
            else:
                self.filters["category"].queryset = Category.objects.filter(tenant__isnull=True)


# filters.py
import django_filters
import jdatetime
from datetime import datetime, timedelta
from .models import SalesDetails

class SalesDetailsFilter(django_filters.FilterSet):
    from_date = django_filters.CharFilter(method='filter_from_date')
    to_date = django_filters.CharFilter(method='filter_to_date')

    class Meta:
        model = SalesDetails
        fields = []

    def _convert_jalali_to_gregorian(self, jalali_str):
        try:
            year, month, day = map(int, jalali_str.split('-'))
            jalali_date = jdatetime.date(year, month, day)
            gregorian = jalali_date.togregorian()
            return datetime(gregorian.year, gregorian.month, gregorian.day)
        except Exception:
            return None

    def filter_from_date(self, queryset, name, value):
        date = self._convert_jalali_to_gregorian(value)
        if date:
            return queryset.filter(created_at__gte=date)
        return queryset

    def filter_to_date(self, queryset, name, value):
        date = self._convert_jalali_to_gregorian(value)
        if date:
            return queryset.filter(created_at__lt=(date + timedelta(days=1)))
        return queryset
