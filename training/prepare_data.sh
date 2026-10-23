#!/usr/bin/env bash
# Teilt das Probenaudio nach ganzen Aufnahmen in Trainings- und Prüfanteil und hängt es für ein
# Modell in den Trainer ein. Ganze Aufnahmen, nicht einzelne Abschnitte: die vier Gesangsmikros
# einer Probe hören über das Übersprechen dasselbe - sonst kennt das Modell die Prüfdaten schon.
#   training/prepare_data.sh <modellname> [trainer-ordner] [daten-ordner]
set -euo pipefail
MODEL="$1"
TRAINER="${2:-$HOME/src/microwakeword-trainer}"
DATA="${3:-$HOME/wakeword_data}"
HELDOUT_RECS="rec78 rec92 rec94"     # ca. 30 %, beide Besetzungen vertreten

mkdir -p "$DATA/split/train" "$DATA/split/heldout"
find "$DATA/split" -type l -delete
for f in "$DATA"/negatives/*.wav; do
    rec="$(basename "$f" | cut -d_ -f1)"
    if [[ " $HELDOUT_RECS " == *" $rec "* ]]; then d=heldout; else d=train; fi
    ln -s "$f" "$DATA/split/$d/"
done
echo "train:   $(ls "$DATA/split/train" | wc -l) Abschnitte"
echo "heldout: $(ls "$DATA/split/heldout" | wc -l) Abschnitte"

OUT="$TRAINER/training/output/$MODEL"
BG="$TRAINER/training/background/rehearsal"
mkdir -p "$OUT" "$BG"
ln -sfn "$DATA/split/train" "$OUT/rehearsal_negatives"
# echter Ordner mit Datei-Links: der Trainer sucht hier rekursiv und folgt dabei keinen Ordner-Links
find "$BG" -type l -delete
ln -s "$DATA"/split/train/*.wav "$BG/"
