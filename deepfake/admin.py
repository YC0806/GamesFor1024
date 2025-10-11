from django.contrib import admin

from .models import DeepfakeQuestion


@admin.register(DeepfakeQuestion)
class DeepfakeQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "real_img", "ai_img")
    search_fields = ("real_img", "ai_img", "analysis")
    ordering = ("id",)
