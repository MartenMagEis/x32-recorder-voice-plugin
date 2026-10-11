# Sprachsteuerung für x32-recorder

Plugin für [x32-recorder](https://github.com/tobire42/x32-recorder): Aufnahme starten und stoppen,
Marker setzen und zum nächsten Song der Setlist springen - per Sprachbefehl, komplett lokal auf dem
Pi, ohne Cloud.

Erkannt werden keine freien Sätze, sondern **feste Phrasen** mit
[microWakeWord](https://github.com/OHF-Voice/micro-wake-word) - ein kleines Modell pro Befehl (das
Aktivierungswort steckt in der Phrase, z.B. "Recorder Start"). Auf einem Raspberry Pi 3B kosten vier
Modelle zusammen rund 12 % eines CPU-Kerns.

## Befehle

| Befehl | Wirkung |
|---|---|
| Start | Startet eine Aufnahme mit der zuletzt gewählten Vorlage (Kanäle, Gerät, Namensschema wie im Recorder) |
| Stopp | Beendet die laufende Aufnahme - standardmäßig nur, wenn zweimal innerhalb von 5 s gesagt |
| Marker | Wie der Marker-Button: Song-Start bzw. Song-Ende |
| Nächster Song | Beendet den offenen Song und startet den nächsten aus der Setlist der Vorlage |

Marker werden um die Erkennungszeit zurückdatiert (einstellbar), damit sie dort sitzen, wo das Wort
gesprochen wurde.

## Einrichten

1. In x32-recorder unter **Einstellungen → Plugins** die GitHub-URL dieses Repos hinzufügen und
   aktivieren, Dienste neu starten (die Datenbank-Tabellen legt der Neustart selbst an).
2. Pro Befehl ein Wake-Word-Modell wählen und **Aktiviert** einschalten. Beim ersten Aktivieren
   installiert das Plugin selbst eine eigene Python-Umgebung (`.venv` im Plugin-Ordner, ca. 60 MB,
   braucht einmalig Internet) mit numpy und pymicro-wakeword - bewusst getrennt von x32-recorder,
   dessen `uv sync` sie sonst bei jedem Update wieder entfernen würde. Der Knopf **"Erkennung neu
   installieren / aktualisieren"** ist nur für ein Update oder nach einer fehlgeschlagenen
   Installation nötig.
3. Im **Vorlagen-Editor** bei den gewünschten Vorlagen "Sprachsteuerung" einschalten und den
   **Sprach-Kanal** wählen (das Mikrofon, in das die Befehle gesprochen werden - bei Stereo-Paaren
   ist jede Seite einzeln wählbar).

Zugehört wird während einer Aufnahme und - wenn "Auch ohne laufende Aufnahme zuhören" an ist - auch
dazwischen, auf dem Audiogerät der letzten Aufnahme. Während des Zurückspielens ins Pult gibt es
kein Audio. Soundcheck-Aufnahmen werden ignoriert.

Status und die letzten Erkennungen stehen in den Plugin-Einstellungen.

## Wake-Word-Modelle

Mitgeliefert sind nur die Beispielmodelle von pymicro-wakeword ("okay_nabu", "hey_jarvis",
"hey_mycroft", "alexa") - zum Ausprobieren. Für den echten Einsatz eigene Phrasen trainieren
(z.B. "Recorder Start", "Recorder Stop", "Recorder Mark", "Recorder Next"): mit dem
[microWakeWord-Trainer](https://github.com/OHF-Voice/micro-wake-word) (synthetische Sprache, keine
eigenen Aufnahmen nötig) und am besten mit Probenaufnahmen der eigenen Band als Gegenbeispiele -
das senkt Fehlauslöser durch Gesang am stärksten. Das Ergebnis (`<name>.json` + `.tflite`) in den
Ordner `wakewords/` legen, danach ist es in den Einstellungen auswählbar.

Tipps für robuste Phrasen: mindestens 3-4 Silben, die Befehle untereinander klanglich deutlich
verschieden, keine Wörter, die in euren Songtexten vorkommen.

## Aufbau

- **Django-Teil** (läuft im x32-recorder-Prozess): Einstellungen (`plugin_config.py`), Abschnitt im
  Vorlagen-Editor (`plugin_template_config.py`), Installation und Überwachung des Workers
  (`supervisor.py`).
- **Worker** (`voice_worker/`, eigener Prozess mit niedriger Priorität, ohne Django): fordert beim
  Controller den Sprach-Kanal per Audio-Abgriff an (`/api/audio-taps/`), taktet von 48 auf 16 kHz
  herunter (mit Tiefpass), lässt die Modelle laufen und löst die Befehle über die REST-API aus
  (`/recordings/start_from_template/`, `/stop/`, `/marker_action/`).

## Tests

```bash
# Worker (im Plugin-Ordner, braucht numpy):
python -m unittest tests.test_worker
# Django-Teil (in einem x32-recorder-Checkout mit aktiviertem Plugin):
uv run python x32recorder/manage.py test x32_recorder_voice_plugin
```
