from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deepfake", "0003_remove_created_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeepfakeImage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "img_path",
                    models.CharField(
                        help_text="Filesystem or CDN path to the image used in the selection challenge.",
                        max_length=512,
                    ),
                ),
                (
                    "ai_generated",
                    models.BooleanField(
                        help_text="Whether the image is AI-generated (True) or a real photo (False)."
                    ),
                ),
                (
                    "analysis",
                    models.TextField(
                        blank=True,
                        help_text="Optional notes explaining the artifacts or verification tips.",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
