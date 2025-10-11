from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("deepfake", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="deepfakequestion",
            options={"ordering": ["id"]},
        ),
        migrations.RenameField(
            model_name="deepfakequestion",
            old_name="real_image_path",
            new_name="real_img",
        ),
        migrations.RenameField(
            model_name="deepfakequestion",
            old_name="fake_image_path",
            new_name="ai_img",
        ),
        migrations.RenameField(
            model_name="deepfakequestion",
            old_name="key_flaw",
            new_name="analysis",
        ),
        migrations.RemoveField(
            model_name="deepfakequestion",
            name="prompt",
        ),
        migrations.RemoveField(
            model_name="deepfakequestion",
            name="technique_tip",
        ),
        migrations.AlterField(
            model_name="deepfakequestion",
            name="ai_img",
            field=models.CharField(
                help_text="Filesystem or CDN path to the AI-generated image.",
                max_length=512,
            ),
        ),
        migrations.AlterField(
            model_name="deepfakequestion",
            name="analysis",
            field=models.TextField(
                blank=True,
                help_text="Detailed cues explaining why the AI image is inconsistent.",
            ),
        ),
        migrations.AlterField(
            model_name="deepfakequestion",
            name="real_img",
            field=models.CharField(
                help_text="Filesystem or CDN path to the authentic image.",
                max_length=512,
            ),
        ),
    ]
