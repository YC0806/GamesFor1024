from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("riskhunter", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="riskscenario",
            name="technique_tip",
        ),
        migrations.RemoveField(
            model_name="riskscenario",
            name="created_at",
        ),
        migrations.AlterField(
            model_name="riskscenario",
            name="risk_label",
            field=models.BooleanField(
                help_text=(
                    "Whether the content is non-compliant/risky (True) or compliant (False)."
                )
            ),
        ),
        migrations.AlterModelOptions(
            name="riskscenario",
            options={"ordering": ["-id"]},
        ),
    ]

