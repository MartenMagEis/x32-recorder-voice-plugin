from django.db import models


class VoiceSettings(models.Model):
    """App-wide settings (singleton), shown on x32-recorder's Settings page via plugin_config.py.
    Which channel to listen to is per template - see VoiceTemplateSettings."""

    enabled = models.BooleanField(
        "Aktiviert", default=False,
        help_text="Hauptschalter. Zusätzlich muss die Sprachsteuerung in der jeweiligen Vorlage "
                   "eingeschaltet und ein Kanal gewählt sein."
    )
    listen_while_idle = models.BooleanField(
        "Auch ohne laufende Aufnahme zuhören", default=True,
        help_text="Nötig für den Befehl 'Start'. Hört dann auf dem Audiogerät der letzten Aufnahme "
                   "mit (wie die Pegelanzeige)."
    )
    model_start = models.CharField("Wake-Word für 'Aufnahme starten'", max_length=128, blank=True, default="")
    model_stop = models.CharField("Wake-Word für 'Aufnahme stoppen'", max_length=128, blank=True, default="")
    model_marker = models.CharField("Wake-Word für 'Marker'", max_length=128, blank=True, default="",
                                    help_text="Wie der Marker-Button: Song-Start bzw. Song-Ende.")
    model_next = models.CharField("Wake-Word für 'Nächster Song'", max_length=128, blank=True, default="",
                                  help_text="Beendet den offenen Song und startet den nächsten der Setlist.")
    stop_needs_confirmation = models.BooleanField(
        "Stopp nur nach Wiederholung", default=True,
        help_text="'Stopp' muss innerhalb des Bestätigungsfensters zweimal erkannt werden - ein "
                   "versehentlich beendete Aufnahme ist der teuerste Fehlauslöser."
    )
    confirm_window_s = models.IntegerField("Bestätigungsfenster (s)", default=5)
    dedup_ms = models.IntegerField(
        "Zusammenfassen (ms)", default=1500,
        help_text="Erkennungen desselben Befehls innerhalb dieser Zeit zählen als ein Wort."
    )
    announcement_ms = models.IntegerField(
        "Länge der Ansage (ms)", default=2500,
        help_text="Ein Befehl wird erst erkannt, wenn er ausgesprochen ist. Song-Ende und "
                   "Sondermarker werden um so viel vorverlegt, der Song-Start bleibt nach der Ansage - "
                   "so ist die Ansage auf keinem ausgeschnittenen Song."
    )
    collect_samples = models.BooleanField(
        "Sprachbeispiele sammeln", default=False,
        help_text="Speichert bei jeder Erkennung und jedem Beinahe-Treffer einen kurzen Clip des "
                   "Sprach-Kanals (ca. 4 s) - als Trainingsmaterial: echte Ansagen als Positiv-, "
                   "Fehlauslöser als Negativbeispiele. Geschrieben wird erst, wenn keine Aufnahme "
                   "und keine Wiedergabe läuft."
    )
    near_miss_percent = models.IntegerField(
        "Beinahe-Treffer ab (%)", default=50,
        help_text="Wahrscheinlichkeit, ab der ein nicht ausgelöster Befehl als Beinahe-Treffer "
                   "gesammelt wird - so landen auch knapp verpasste Ansagen im Material."
    )
    samples_max_mb = models.IntegerField(
        "Speicherplatz für Sprachbeispiele (MB)", default=500,
        help_text="Darüber werden die ältesten noch nicht bewerteten Clips gelöscht, "
                   "Beinahe-Treffer zuerst."
    )
    udp_port = models.IntegerField("UDP-Port", default=47100,
                                   help_text="Lokaler Port, auf dem der Controller das Audio schickt "
                                             "(bei mehreren Sprach-Kanälen die folgenden Ports dazu).")

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class VoiceTemplateSettings(models.Model):
    """Per-template part, edited in x32-recorder's template editor (plugin_template_config.py)."""

    template = models.OneToOneField(
        "recorder.RecordingTemplate", on_delete=models.CASCADE, related_name="+"
    )
    enabled = models.BooleanField(
        "Sprachsteuerung", default=False,
        help_text="Befehle per Sprache: Start, Stopp, Marker, Nächster Song."
    )
    channels = models.JSONField(
        "Sprach-Kanäle", default=list, blank=True,
        help_text="Mikrofone, in die Befehle gesprochen werden (Kanalnummern, höchstens 4)."
    )
