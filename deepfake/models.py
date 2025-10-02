from django.db import models


class DeepfakeQuestion(models.Model):
    """A pair of images used in the Spot the DeepFake game."""

    prompt = models.CharField(
        max_length=255,
        help_text="Short description of the scenario shown to the player.",
    )
    real_image_path = models.CharField(
        max_length=512,
        help_text="Filesystem or CDN path to the authentic image.",
    )
    fake_image_path = models.CharField(
        max_length=512,
        help_text="Filesystem or CDN path to the AI-generated counterfeit image.",
    )
    key_flaw = models.TextField(
        blank=True,
        help_text="Explanation of the critical flaw that reveals the fake image.",
    )
    technique_tip = models.TextField(
        help_text="One-sentence technique that helps players identify deepfakes.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - trivial representation
        return self.prompt
