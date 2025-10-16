from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("deepfake", "0004_deepfakeimage"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="DeepfakeQuestion",
            new_name="DeepfakePair",
        ),
        migrations.RenameModel(
            old_name="DeepfakeImage",
            new_name="DeepfakeSelection",
        ),
    ]
