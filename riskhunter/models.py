from django.db import models


class RiskScenario(models.Model):
    """A textual scenario for the Risk Hunter compliance review game."""

    class RiskLabel(models.TextChoices):
        COMPLIANT = "compliant", "内容合规"
        NON_COMPLIANT = "non_compliant", "内容不合规"
        DATA_LEAK = "data_leak", "客户数据泄露"
        MISINFORMATION = "misinformation", "虚假信息"

    title = models.CharField(
        max_length=255,
        help_text="Short name or identifier for the scenario presented to the player.",
    )
    content = models.TextField(
        help_text="AI generated content that needs to be reviewed for compliance.",
    )
    risk_label = models.CharField(
        max_length=32,
        choices=RiskLabel.choices,
        help_text="Expected classification of the risk contained in the content.",
    )
    analysis = models.TextField(
        help_text="Explanation shown after answering that highlights the risk signals.",
    )
    technique_tip = models.TextField(
        help_text="Actionable tip that helps players identify similar compliance risks.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover - trivial representation
        return self.title
