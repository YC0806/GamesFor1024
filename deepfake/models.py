from django.db import models


class DeepfakePair(models.Model):
    """A pair of images used in the Spot the DeepFake game."""

    real_img = models.CharField(
        max_length=512,
        help_text="Filesystem or CDN path to the authentic image.",
    )
    ai_img = models.CharField(
        max_length=512,
        help_text="Filesystem or CDN path to the AI-generated image.",
    )
    analysis = models.TextField(
        blank=True,
        help_text="Detailed cues explaining why the AI image is inconsistent.",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover - trivial representation
        return f"Deepfake pair #{self.pk}"


class DeepfakeSelection(models.Model):
    """A single image labelled as real or AI-generated for selection challenges."""

    img_path = models.CharField(
        max_length=512,
        help_text="Filesystem or CDN path to the image used in the selection challenge.",
    )
    ai_generated = models.BooleanField(
        help_text="Whether the image is AI-generated (True) or a real photo (False)."
    )
    analysis = models.TextField(
        blank=True,
        help_text="Optional notes explaining the artifacts or verification tips.",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover - trivial representation
        label = "AI" if self.ai_generated else "Real"
        return f"{label} selection image #{self.pk}"
