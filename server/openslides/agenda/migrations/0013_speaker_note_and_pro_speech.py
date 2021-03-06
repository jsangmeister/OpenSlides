# Generated by Django 2.2.20 on 2021-04-19 10:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agenda", "0012_list_of_speakers_closed_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="speaker",
            name="note",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="speaker",
            name="pro_speech",
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
    ]
