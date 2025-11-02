from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PlayerMBTIRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_code", models.CharField(db_index=True, max_length=16)),
                ("player_name", models.CharField(max_length=128)),
                ("department", models.CharField(blank=True, max_length=128)),
                ("mbti", models.CharField(max_length=4)),
                ("consent", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Player MBTI Record",
                "verbose_name_plural": "Player MBTI Records",
            },
        ),
        migrations.AddIndex(
            model_name="playermbtirecord",
            index=models.Index(fields=["session_code", "player_name"], name="mbtispy_play_session_f59773_idx"),
        ),
    ]

