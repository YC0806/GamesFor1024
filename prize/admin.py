from django.contrib import admin

from .models import Prize


@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "stock")
    list_filter = ("stock",)
    search_fields = ("name",)
    ordering = ("name",)
