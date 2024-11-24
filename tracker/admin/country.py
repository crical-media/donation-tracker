from django.contrib.admin import register, ModelAdmin

from tracker import models

from .util import CustomModelAdmin


@register(models.Country)
class CountryAdmin(CustomModelAdmin):
    search_fields = ('name',)


@register(models.CountryRegion)
class CountryRegionAdmin(CustomModelAdmin):
    autocomplete_fields = ('country',)
    list_display = (
        'name',
        'country',
    )
    list_display_links = ('country',)
    search_fields = (
        'name',
        'country__name',
    )
    list_filter = ('country',)
    autocomplete_fields = ('country',)
    fieldsets = [
        (
            None,
            {
                'fields': ['name', 'country'],
            },
        ),
    ]
