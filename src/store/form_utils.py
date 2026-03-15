from django import forms
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


def apply_placeholders(form):
    for visible in form.visible_fields():
        apply_tailwind_classes(visible.field)
        visible.field.widget.attrs["placeholder"] = _(visible.field.label)
