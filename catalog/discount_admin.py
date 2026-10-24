from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils import timezone
from unfold.admin import ModelAdmin
from .discount_models import DiscountCode


class DiscountCodeForm(forms.ModelForm):
    class Meta:model=DiscountCode;fields='__all__'
    def clean(self):
        data=super().clean()
        if not data.get('all_products') and not any(data.get(field) for field in ['teachers','courses','payment_items','bundles']):
            raise ValidationError('Select at least one teacher, course, package or payment-page product, or enable all products.')
        return data


@admin.register(DiscountCode)
class DiscountCodeAdmin(ModelAdmin):
    form=DiscountCodeForm
    list_display=['code','name','discount_label','minimum_amount','minimum_basis','scope_label','allowed_user','validity','active']
    list_filter=['active','discount_type','all_products','minimum_basis']
    search_fields=['code','name','allowed_user__email']
    autocomplete_fields=['teachers','courses','payment_items','bundles','allowed_user']
    list_select_related=['allowed_user']
    readonly_fields=['created_at']
    list_per_page=25
    fieldsets=(
        ('Code & value',{'fields':('code','name','active',('discount_type','value'))}),
        ('Eligible products',{'fields':('all_products','teachers','courses','payment_items','bundles'),'description':'Selected products are used only when all products is turned off. Discounts do not apply to donations or free trials.'}),
        ('Minimum purchase',{'fields':('minimum_amount','minimum_basis'),'description':'For example: 20% off eligible products costing at least 100 CAD. Choose whether the minimum is checked for each product or for their combined subtotal.'}),
        ('Customer & validity',{'fields':('allowed_user',('starts_at','ends_at'),'created_at')}),
    )
    @admin.display(description='Discount')
    def discount_label(self,obj):return f'{obj.value:g}%' if obj.discount_type=='percentage' else f'{obj.value:.2f} CAD'
    @admin.display(description='Products')
    def scope_label(self,obj):return 'All paid products' if obj.all_products else 'Selected products'
    @admin.display(description='Currently valid',boolean=True)
    def validity(self,obj):
        now=timezone.now()
        return obj.active and (not obj.starts_at or obj.starts_at<=now) and (not obj.ends_at or now<obj.ends_at)
