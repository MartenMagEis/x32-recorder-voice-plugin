from django.db import migrations, models


def _bump_old_default(apps, schema_editor):
    # The old 1 s only covered the recognition delay, not the whole "Tape deck, marker" - move
    # installs still on that default to the new one; a hand-picked value stays as it is.
    VoiceSettings = apps.get_model("x32_recorder_voice_plugin", "VoiceSettings")
    VoiceSettings.objects.filter(announcement_ms=1000).update(announcement_ms=2500)


class Migration(migrations.Migration):

    dependencies = [
        ("x32_recorder_voice_plugin", "0001_initial"),
    ]

    operations = [
        migrations.RenameField("voicesettings", "marker_offset_ms", "announcement_ms"),
        migrations.AlterField(
            model_name="voicesettings",
            name="announcement_ms",
            field=models.IntegerField(
                default=2500,
                help_text="Ein Befehl wird erst erkannt, wenn er ausgesprochen ist. Song-Ende und "
                "Sondermarker werden um so viel vorverlegt, der Song-Start bleibt nach der Ansage - "
                "so ist die Ansage auf keinem ausgeschnittenen Song.",
                verbose_name="Länge der Ansage (ms)",
            ),
        ),
        migrations.RunPython(_bump_old_default, migrations.RunPython.noop),
    ]
