from django.contrib import admin

from .models import DeepfakePair, DeepfakeSelection


@admin.register(DeepfakePair)
class DeepfakePairAdmin(admin.ModelAdmin):
    list_display = ("id", "real_img", "ai_img")
    search_fields = ("real_img", "ai_img", "analysis")
    ordering = ("id",)


@admin.register(DeepfakeSelection)
class DeepfakeSelectionAdmin(admin.ModelAdmin):
    list_display = ("id", "img_path", "ai_generated")
    list_filter = ("ai_generated",)
    search_fields = ("img_path", "analysis")
    ordering = ("id",)
