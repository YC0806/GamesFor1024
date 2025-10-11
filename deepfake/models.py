from django.db import models


class DeepfakeQuestion(models.Model):
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
        return f"Deepfake dataset #{self.pk}"
