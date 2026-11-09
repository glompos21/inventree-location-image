"""Django admin integration for the stock location image plugin."""

from django.contrib import admin

from .models import LocationImage


@admin.register(LocationImage)
class LocationImageAdmin(admin.ModelAdmin):
    """Admin view for stock location images."""

    list_display = ('location', 'uploaded_by', 'updated')
    raw_id_fields = ('location', 'uploaded_by')
    readonly_fields = ('updated',)
