from django.contrib import admin

from .models import DeepfakeQuestion


@admin.register(DeepfakeQuestion)
class DeepfakeQuestionAdmin(admin.ModelAdmin):
    list_display = ("prompt", "created_at")
    search_fields = ("prompt", "technique_tip", "key_flaw")
    ordering = ("-created_at",)
