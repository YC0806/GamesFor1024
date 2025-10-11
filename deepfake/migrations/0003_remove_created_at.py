from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("deepfake", "0002_align_with_csv"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="deepfakequestion",
            name="created_at",
        ),
    ]
