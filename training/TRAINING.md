# Eigene Wake-Words trainieren

Ziel: ein microWakeWord-Modell pro Befehl (Start, Stopp, Marker, Nächster Song), trainiert auf eure
Phrasen und gezielt **gegen eure Proben** (Gesang, Gerede, Bandgeräusche im Mikro). Ergebnis pro
Befehl: `<name>.json` + `<name>.tflite` (ca. 50-300 KB) für den Ordner `wakewords/` des Plugins.

## Wo und womit

- **Auf dem Gaming-PC, in WSL2** (Ubuntu), mit NVIDIA-Grafikkarte. Der Trainer läuft nur unter Linux;
  auf der CPU braucht ein Modell 8-14 Stunden, mit GPU deutlich weniger. Platzbedarf ca. 15-25 GB.
- **Claude Code in WSL starten, nicht unter Windows** - dann laufen Trainer, GPU-Zugriff und Dateien
  im selben Linux, ohne Umwege über Windows-Pfade (die zudem deutlich langsamer sind).

## So startest du

In einem WSL-Terminal (Ubuntu):

```bash
nvidia-smi                       # muss die Grafikkarte zeigen - sonst zuerst den NVIDIA-Treiber für WSL installieren
curl -fsSL https://claude.ai/install.sh | bash      # Claude Code in WSL installieren (falls noch nicht)
git clone https://github.com/MartenMagEis/x32-recorder-voice-plugin.git ~/voice-plugin
cd ~/voice-plugin && claude
```

Dann zu Claude sagen:

> Lies `training/TRAINING.md` und arbeite den Abschnitt "Auftrag für Claude Code" ab.

## Vorher: Phrasen festlegen

Pro Befehl eine Phrase, alle mit demselben ungewöhnlichen Vorwort, die Befehlswörter klanglich
möglichst verschieden (andere Vokale, andere Anlaute, verschiedene Silbenzahl). Empfehlung:

| Befehl | Phrase | Modellname |
|---|---|---|
| Aufnahme starten | "Tape deck, record" | `tapedeck_record` |
| Aufnahme stoppen | "Tape deck, finish" | `tapedeck_finish` |
| Marker | "Tape deck, marker" | `tapedeck_marker` |
| Nächster Song | "Tape deck, next song" | `tapedeck_next_song` |

(Steht noch nicht endgültig fest - Claude fragt vor dem Training danach.)

## Eigene Aufnahmen der Band (empfohlen)

Die Modelle werden mit künstlichen Stimmen (Piper-TTS) trainiert. Echte Aufnahmen von euch sind
trotzdem wertvoll - **vor allem als Prüfstein**: nur damit lässt sich messen, ob das Modell eure
Stimmen, eure Mikros und euren Raum wirklich erkennt. So aufnehmen:

- In einer Probe eine Aufnahme mit der normalen Vorlage starten.
- Jede Person spricht **in ihr eigenes Gesangsmikro** jede Phrase ca. 15-mal, mit ca. 2 s Pause
  dazwischen. Abwechseln: normal, laut, leise, schnell, beiläufig - so wie man es in der Probe
  wirklich sagen würde. Gern auch ein paar Mal, während jemand anderes leise klimpert.
- Eine Phrase nach der anderen (erst alle "record", dann alle "finish", ...), und vorher einen
  Sondermarker mit dem Namen der Phrase setzen - dann lässt sich die Aufnahme sauber zuordnen.
- Auf dem Pi pro Person und Phrase in Clips schneiden:
  `.venv/bin/python training/split_phrases.py <kanal>.wav --out <ziel>/<modellname> --prefix <person>`
  (vorher den Abschnitt der Phrase z.B. mit Audacity herausschneiden, oder die Aufnahme pro Phrase
  separat machen).

Ca. 2/3 der Clips können zusätzlich ins Training (als echte Positivbeispiele, falls der Trainer das
unterstützt), mindestens 1/3 bleibt **immer** draußen und dient nur der Bewertung.

## Was "mehrere Durchläufe" heißt

Kein blindes Wiederholen - jeder Durchlauf wird mit `training/evaluate.py` gemessen, und je nach
Ergebnis wird **gezielt eine Stellschraube** geändert:

| Messergebnis | Änderung für den nächsten Durchlauf |
|---|---|
| Zu viele Fehlauslöser auf den Probenaufnahmen | die Fehlauslöser-Clips (`--dump-false-accepts`) als zusätzliche Negativbeispiele dazu; `negative_class_weight` erhöhen; ggf. höhere Schwelle |
| Echte Ansagen werden nicht erkannt | Schwelle senken (geht ohne Neutraining, steht im .json); `positive_class_weight` erhöhen; mehr/andere TTS-Stimmen; eigene Aufnahmen mit ins Training |
| Beides schlecht | Phrase zu kurz oder zu ähnlich zu Gesungenem - Phrase ändern |

Zielwerte pro Modell: **höchstens ca. 0,1 Fehlauslöser pro Stunde** Probenaudio (also ca. 1 in 10
Stunden) und **mindestens 90 % Erkennung** eurer echten Ansagen. Für "finish" (Stopp) darf es
strenger sein, da hilft zusätzlich die Doppel-Ansage-Sicherung im Plugin.

Realistisch: ein bis drei Durchläufe pro Phrase, nach dem ersten Modell geht es schneller, weil die
Einstellungen dann für die übrigen drei passen.

---

## Auftrag für Claude Code

Du richtest auf diesem Rechner (WSL2, NVIDIA-GPU) das Training von microWakeWord-Modellen ein und
trainierst die Modelle für das x32-recorder-Sprachplugin. Arbeite schrittweise und frag nach, bevor
du lange Läufe startest.

1. **Umgebung prüfen:** `nvidia-smi` in WSL, freier Platz (>= 25 GB), Python-Version. TensorFlow muss
   die GPU sehen - das prüfen, bevor irgendein langer Lauf startet.
2. **Phrasen klären:** die Tabelle oben dem Nutzer zeigen und die endgültigen Phrasen + Modellnamen
   bestätigen lassen. Englische Schreibweise (die Trainingsstimmen sind englisch).
3. **Trainer einrichten:** einen aktuellen, gepflegten microWakeWord-Trainer wählen, z.B.
   `interkelstar/microwakeword-trainer` (konfigurationsgesteuert, unterstützt eigene Negativbeispiele
   in `training/output/<modell>/user_negatives/`) oder das offizielle Notebook aus
   `OHF-Voice/micro-wake-word`. Dessen README genau lesen - die Dokumentation einzelner Forks
   widerspricht sich (z.B. Namen der Startskripte); im Zweifel die Dateien im Repo maßgeblich nehmen.
   Englische Piper-Stimmen, mehrere Sprecher (männlich/weiblich).
4. **Daten holen** (der Pi ist im Heimnetz bzw. per VPN als `rec-pi` erreichbar, Nutzer `pi`):
   `rsync -av pi@rec-pi:/mnt/32recorder/wakeword_training/ ~/wakeword_data/`
   - `negatives/`: ca. 50 h Gesangsspuren der Proben als 16-kHz-WAV-Abschnitte (5 min). Für das
     Training einen Teil (z.B. 70 %) als `user_negatives` verwenden, den Rest **zurückhalten** für die
     Bewertung - sonst misst evaluate.py auf Daten, die das Modell schon kennt.
   - `positives_real/<modellname>/`: echte Ansagen der Band, falls schon aufgenommen (siehe oben).
5. **Erst ein Modell** (das für "Aufnahme starten") komplett durchziehen: Training, Export, dann
   bewerten:
   `python training/evaluate.py --model <name>.json --negatives <zurückgehaltene negatives> --positives ~/wakeword_data/positives_real/<name> --dump-false-accepts fa/<name>`
   (braucht `numpy` und `pymicro-wakeword`, am besten in einer eigenen venv). Ergebnis dem Nutzer
   zeigen, Stellschraube nach der Tabelle oben wählen, ggf. wiederholen. Dann die übrigen drei.
6. **Abliefern:** `<name>.json` + `.tflite` nach `wakewords/` in diesem Repo, im JSON `wake_word` auf
   die lesbare Phrase setzen und den Dateinamen der .tflite im JSON prüfen. Committen und pushen
   (Modelle sind klein). Auf dem Pi: `git pull` im Plugin-Ordner
   (`~/x32-recorder/plugins/x32_recorder_voice_plugin`), danach sind die Modelle in den
   Plugin-Einstellungen auswählbar.
7. Kurz notieren (in dieser Datei unten), mit welchen Einstellungen das finale Modell entstanden ist
   und welche Messwerte es erreicht hat - für spätere Nachtrainings.

## Trainings-Protokoll

(noch leer)
