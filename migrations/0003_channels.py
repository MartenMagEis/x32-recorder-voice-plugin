from django.db import migrations, models


def _to_list(apps, schema_editor):
    VoiceTemplateSettings = apps.get_model("x32_recorder_voice_plugin", "VoiceTemplateSettings")
    for row in VoiceTemplateSettings.objects.exclude(channel_no=None):
        row.channels = [row.channel_no]
        row.save(update_fields=["channels"])


def _to_single(apps, schema_editor):
    VoiceTemplateSettings = apps.get_model("x32_recorder_voice_plugin", "VoiceTemplateSettings")
    for row in VoiceTemplateSettings.objects.all():
        row.channel_no = row.channels[0] if row.channels else None
        row.save(update_fields=["channel_no"])


class Migration(migrations.Migration):

    dependencies = [
        ("x32_recorder_voice_plugin", "0002_announcement_ms"),
    ]

    operations = [
        migrations.AddField(
            model_name="voicetemplatesettings",
            name="channels",
            field=models.JSONField(
                blank=True, default=list,
                help_text="Mikrofone, in die Befehle gesprochen werden (Kanalnummern, höchstens 4).",
                verbose_name="Sprach-Kanäle",
            ),
        ),
        migrations.RunPython(_to_list, _to_single),
        migrations.RemoveField(model_name="voicetemplatesettings", name="channel_no"),
    ]
