import jdatetime
from django import template
from django.utils.timezone import localtime

register = template.Library()

@register.filter
def jalali(datetime_obj):
    if not datetime_obj:
        return ""
    local_dt = localtime(datetime_obj)
    return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d')