#!/usr/bin/env bash
# Zweiter Durchlauf eines fertigen Modells: Fehlauslöser auf dem TRAININGS-Anteil des Probenaudios
# suchen (niedrige Schwelle, damit auch knappe Stellen dabei sind), als dichte user_negatives
# dazunehmen, Negativ-Merkmale neu, Training, Export, Bewertung auf dem zurückgehaltenen Anteil.
# Die Prüfdaten bleiben dabei unberührt.
#   training/refine_model.sh <modellname> [such-schwelle, Standard 0.7]
set -euo pipefail
MODEL="$1"; MINE_CUTOFF="${2:-0.7}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAINER="${TRAINER:-$HOME/src/microwakeword-trainer}"
DATA="${DATA:-$HOME/wakeword_data}"
OUT="$TRAINER/training/output/$MODEL"
cd "$TRAINER"

# vorherige Version sichern
V="$(grep -E '^version:' "$REPO/training/configs/$MODEL.yaml" | awk '{print $2}')"
mkdir -p "$OUT/v$V"
cp "${MODEL}_mww.tflite" "${MODEL}_mww.json" "$OUT/v$V/"
cp -r "$OUT/model" "$OUT/v$V/" 2>/dev/null || true

# Fehlauslöser suchen
python3 - "$OUT/v$V/${MODEL}_mww.json" "$OUT/mine.json" "$MINE_CUTOFF" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])); c["micro"]["probability_cutoff"] = float(sys.argv[3])
json.dump(c, open(sys.argv[2], "w"), indent=2)
PY
cp "$OUT/v$V/${MODEL}_mww.tflite" "$OUT/"
rm -rf "$OUT/user_negatives"
echo "== Suche Fehlauslöser (Schwelle $MINE_CUTOFF) im Trainingsanteil  $(date)"
.venv/bin/python "$REPO/training/evaluate.py" --model "$OUT/mine.json" \
    --negatives "$DATA/split/train" --dump-false-accepts "$OUT/user_negatives" | grep -v '\.\.\.'
echo "user_negatives: $(ls "$OUT/user_negatives" | wc -l) Clips"

sed -i -E "s/^version: .*/version: $((V + 1))/" "$REPO/training/configs/$MODEL.yaml"
rm -f "$OUT/mww_features/negative_train.npy" "$OUT/mww_features/negative_val.npy"
"$REPO/training/train_model.sh" "$MODEL" features train export
