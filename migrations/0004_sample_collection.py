from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("x32_recorder_voice_plugin", "0003_channels"),
    ]

    operations = [
        migrations.AddField(
            model_name="voicesettings",
            name="collect_samples",
            field=models.BooleanField(
                default=False,
                help_text="Speichert bei jeder Erkennung und jedem Beinahe-Treffer einen kurzen Clip des "
                "Sprach-Kanals (ca. 4 s) - als Trainingsmaterial: echte Ansagen als Positiv-, "
                "Fehlauslöser als Negativbeispiele. Geschrieben wird erst, wenn keine Aufnahme "
                "und keine Wiedergabe läuft.",
                verbose_name="Sprachbeispiele sammeln",
            ),
        ),
        migrations.AddField(
            model_name="voicesettings",
            name="near_miss_percent",
            field=models.IntegerField(
                default=50,
                help_text="Wahrscheinlichkeit, ab der ein nicht ausgelöster Befehl als Beinahe-Treffer "
                "gesammelt wird - so landen auch knapp verpasste Ansagen im Material.",
                verbose_name="Beinahe-Treffer ab (%)",
            ),
        ),
        migrations.AddField(
            model_name="voicesettings",
            name="samples_max_mb",
            field=models.IntegerField(
                default=500,
                help_text="Darüber werden die ältesten noch nicht bewerteten Clips gelöscht, "
                "Beinahe-Treffer zuerst.",
                verbose_name="Speicherplatz für Sprachbeispiele (MB)",
            ),
        ),
        migrations.AlterField(
            model_name="voicesettings",
            name="udp_port",
            field=models.IntegerField(
                default=47100,
                help_text="Lokaler Port, auf dem der Controller das Audio schickt "
                "(bei mehreren Sprach-Kanälen die folgenden Ports dazu).",
                verbose_name="UDP-Port",
            ),
        ),
    ]
