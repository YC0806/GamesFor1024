from django.db import models


class RiskScenario(models.Model):
    """A textual scenario for the Risk Hunter compliance review game."""

    title = models.CharField(
        max_length=255,
        help_text="Short name or identifier for the scenario presented to the player.",
    )
    content = models.TextField(
        help_text="AI generated content that needs to be reviewed for compliance.",
    )
    risk_label = models.BooleanField(
        help_text="Whether the content is non-compliant/risky (True) or compliant (False).",
    )
    analysis = models.TextField(
        help_text="Explanation shown after answering that highlights the risk signals.",
    )

    class Meta:
        ordering = ["-id"]

    def __str__(self) -> str:  # pragma: no cover - trivial representation
        return self.title
