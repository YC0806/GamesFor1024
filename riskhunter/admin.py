from django.contrib import admin

from .models import RiskScenario


@admin.register(RiskScenario)
class RiskScenarioAdmin(admin.ModelAdmin):
    list_display = ("title", "risk_label")
    list_filter = ("risk_label",)
    search_fields = ("title", "content")
    ordering = ("-id",)
