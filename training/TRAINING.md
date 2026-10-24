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

> **Vor jedem langen Lauf den Windows-Standby pausieren** - sonst schläft der PC nach 45 min ohne
> Eingabe ein und das Training friert ein. Aus WSL:
> `cd /mnt/c && powercfg.exe /change standby-timeout-ac 0 && powercfg.exe /change hibernate-timeout-ac 0`.
> Wenn alles fertig ist, wieder zurückstellen (vorher 45/46 min):
> `powercfg.exe /change standby-timeout-ac 45 && powercfg.exe /change hibernate-timeout-ac 46`.

In einem WSL-Terminal (Ubuntu):

```bash
nvidia-smi                       # muss die Grafikkarte zeigen - sonst zuerst den NVIDIA-Treiber für WSL installieren
curl -fsSL https://claude.ai/install.sh | bash      # Claude Code in WSL installieren (falls noch nicht)
git clone https://github.com/MartenMagEis/x32-recorder-voice-plugin.git ~/voice-plugin
cd ~/voice-plugin && claude
```

Dann zu Claude sagen:

> Lies `training/TRAINING.md` und arbeite den Abschnitt "Auftrag für Claude Code" ab.

## Die Phrasen (festgelegt 2026-10-12)

Pro Befehl eine Phrase, alle mit demselben ungewöhnlichen Vorwort "Tape deck" (kommt in Songtexten
und Gesprächen praktisch nie vor), die Befehlswörter klanglich möglichst verschieden (andere Vokale,
andere Anlaute, verschiedene Silbenzahl). Bewusst **nicht** "start"/"stop" (zu ähnlich) und nicht
"end" (würde man im Eifer für das Song-Ende sagen und damit die ganze Aufnahme beenden):

| Befehl | Phrase | Modellname |
|---|---|---|
| Aufnahme starten | "Tape deck, record" | `tapedeck_record` |
| Aufnahme stoppen | "Tape deck, finish" | `tapedeck_finish` |
| Marker | "Tape deck, marker" | `tapedeck_marker` |
| Nächster Song | "Tape deck, next song" | `tapedeck_next_song` |

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

## Automatisch gesammelte Sprachbeispiele

Mit **"Sprachbeispiele sammeln"** in den Plugin-Einstellungen legt der Pi bei jeder Erkennung und
jedem Beinahe-Treffer einen 4-s-Clip des Sprach-Kanals ab (16 kHz, WAV + JSON), unter
`/mnt/32recorder/wakeword_training/auto/<modellname>/`. Echte Ansagen werden so zu
Positivbeispielen, Fehlauslöser zu Negativbeispielen - beides genau aus euren Mikros und eurem Raum.
Beinahe-Treffer fangen außerdem einen Teil der *verpassten* Ansagen ein (Hinweis "danach erkannt",
wenn kurz darauf derselbe Befehl erkannt wurde, oder "kurz danach Marker von Hand gesetzt").

Bewerten:
- Wer mag, hört Clips auf dem Pi an (Button **"Sprachbeispiele anhören und bewerten"** in den
  Plugin-Einstellungen) - diese Bewertung gilt immer.
- Den Rest erledigt `training/label_clips.py` auf dem PC: Whisper transkribiert jeden Clip und
  vergleicht mit der Phrase des Modells; Unklares wird am Ende aufgelistet.

```bash
rsync -av pi@rec-pi:/mnt/32recorder/wakeword_training/auto/ ~/wakeword_data/auto/
pip install faster-whisper      # in der Trainings-venv, nutzt die GPU
python training/label_clips.py --samples ~/wakeword_data/auto --out ~/wakeword_data
```

Ergebnis: Positive landen als `auto_*.wav` in `positives_real/<modellname>/` (neben den von Hand
aufgenommenen, gleiche Regel: mindestens 1/3 nur zur Bewertung, nie ins Training), Negative in
`negatives_auto/<modellname>/` - Letztere sind die wertvollsten Gegenbeispiele überhaupt (genau das,
was das Modell bisher verwechselt hat) und gehören wie die `--dump-false-accepts`-Clips ins Training.

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
2. **Phrasen:** stehen fest (Tabelle oben). Englische Schreibweise, die Trainingsstimmen sind
   englisch; als Varianten z.B. "Tape deck record", "Tapedeck, record!" mit aufnehmen.
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

### Stand 2026-10-24 - alle vier Modelle ausgeliefert

| Modell | Version | Schwelle | Fehlauslöser/h (10,4 h Probe) | Erkennung TTS | echte Ansagen | Verwechslung mit anderen Befehlen |
|---|---|---|---|---|---|---|
| `tapedeck_record` | 2 | 0,93 | 0,00 | 100 % | - | 0/900 |
| `tapedeck_finish` | 1 | 0,90 | 0,29 (Doppel-Ansage-Sicherung!) | 99 % | - | 1/900 |
| `tapedeck_marker` | 3 | 0,95 | 0,10 | 99 % | 4/4 (Marten, 19.10.) | 0/900 |
| `tapedeck_next_song` | 2 | 0,95 | 0,10 | 100 % | - | 2/900 |

**Gemeinsame Einstellungen** (Details in `configs/<modell>.yaml`, Trainer-Änderungen in `trainer.patch`):
interkelstar/microwakeword-trainer 8fdbadc + Patch, microWakeWord a70bd74, TF 2.21, mixednet
(Standard-Architektur), 15 000 + 3 000 Piper-Clips aus 9 englischen Stimmen (libritts_r und vctk mit
zufälligem Sprecher), Raumhall (MIT-RIRs) + Probenaudio als Hintergrund (SNR 3-25 dB), Negative:
Befehls-ähnliche Phrasen + 24,2 h Probenaudio (Fenster je 1 s) + 100k allgemeine Fenster
(kahrendt/microwakeword); positive_class_weight 1,5, sliding_window 10.

**Durchlauf 2** (`refine_model.sh`): Fehlauslöser des Vormodells auf dem *Trainings*anteil des
Probenaudios (Schwelle 0,7) als dichte `user_negatives`, plus TTS-Clips der jeweils anderen drei
Befehle als Negative (bis 500 knappe + 150 zufällige je Befehl). Bei record, marker (v2->v3) und
next_song ein klarer Gewinn; bei finish nicht (v2 mit 10k Schritten 1,8/h, mit 20k 0,86/h), daher
finish v1. Schritte: record 10 000, finish 10 000, marker v3 und next_song v2 20 000 (mit 10 000
blieb das größere Datenset untertrainiert - beste Epoche war jeweils die letzte).

**Datenaufteilung:** nach ganzen Aufnahmen, zurückgehalten rec78, rec92, rec94 (10,4 h, beide
Besetzungen); `prepare_data.sh`. Echte Ansagen: `~/wakeword_data/positives_real/<modell>/`.

**Messfallen** (beim nächsten Mal beachten):
- Die ersten ~0,5 s nach Start des Frontends sind unbrauchbar (bis 0,99 auf Bandaudio) - evaluate.py
  zählt die ersten 2 s nicht, der Detektor im Plugin löst in den ersten 2 s nach einem Reset nicht aus.
- Clips in digitaler Stille (Nullen) bewerten die Modelle anders als in Raumrauschen: next_song v2
  schien mit Null-Polsterung 15 % der anderen Befehle zu erkennen, in Raumrauschen 0-0,7 %.
  `cross_check.py --beds <heldout>` polstert deshalb mit echtem Raumklang. Falls der Abgriff am X32
  hinter Gate/Mute sitzt, kommen live tatsächlich Nullen - dann im Betrieb beobachten.
- Die Fehlauslöser-Rate schwankt stark zwischen Proben (marker v1: 0,48/h auf dem Prüfanteil, 1,57/h
  auf dem Trainingsanteil). 10 h Prüfaudio lösen 0,1/h nur grob auf (= 1 Ereignis).
- Zwei Trainings gleichzeitig: beide lesen ~12 GB per mmap, der Rechner hat 15 GB - dann 500-800 ms
  statt ~30 ms pro Schritt. Immer nacheinander.
- Windows Update hat einen Lauf per automatischem Neustart abgebrochen: Updates während des
  Trainings pausieren.

**Offen:** echte Ansagen für record, finish und next song aufnehmen (siehe oben) und damit die
Erkennung messen; finish ggf. mit weniger Verwechslungs-Negativen erneut versuchen.
