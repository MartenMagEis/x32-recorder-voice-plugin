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
export REPO_DIR="$REPO"

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
# frühere Fehlauslöser bleiben drin, neue kommen dazu
mkdir -p "$OUT/user_negatives"
echo "== Suche Fehlauslöser (Schwelle $MINE_CUTOFF) im Trainingsanteil  $(date)"
.venv/bin/python "$REPO/training/evaluate.py" --model "$OUT/mine.json" \
    --negatives "$DATA/split/train" --dump-false-accepts "$OUT/user_negatives" | grep -v '\.\.\.'
echo "user_negatives: $(ls "$OUT/user_negatives" | wc -l) Clips"

# Die anderen Befehle: deren TTS-Trainingsclips (nie die Prüfclips) als gezielte Negativbeispiele -
# bis zu 500, bei denen dieses Modell schon anschlägt (> 0.3), plus 150 zufällige. Unter den
# ~60 Negativphrasen gingen sie sonst unter: record v1 löste bei 10 % der "Tape deck, marker" aus
# (über 0.3 bei 46 %). Ziel ist ha_tts_negative/ - dort mit Rauschvarianten statt 10-ms-Raster
# gefenstert, sonst reicht der Arbeitsspeicher nicht.
rm -rf "$OUT/ha_tts_negative" && mkdir -p "$OUT/ha_tts_negative"
echo "== Suche Verwechslungen mit den anderen Befehlen  $(date)"
.venv/bin/python - "$OUT/mine.json" "$TRAINER/training/output" "$MODEL" "$OUT/ha_tts_negative" <<'PY'
import os, random, shutil, sys
import numpy as np
sys.path.insert(0, os.path.join(os.environ.get("REPO_DIR", ""), "training"))
from evaluate import probabilities, read_wav16
model, outroot, me, dest = sys.argv[1:5]
random.seed(1)
pad = np.zeros(16000, dtype="<i2")
for other in sorted(os.listdir(outroot)):
    d = os.path.join(outroot, other, "positive_train")
    if other == me or not other.startswith("tapedeck_") or not os.path.isdir(d):
        continue
    files = sorted(f for f in os.listdir(d) if f.endswith(".wav"))
    random.shuffle(files)
    hard, picked = 0, files[:150]
    for f in files[150:3150]:
        if probabilities(model, np.concatenate([pad, read_wav16(os.path.join(d, f)), pad]))[0].max() > 0.3:
            hard += 1
            if hard <= 500:
                picked.append(f)
    for f in picked:
        shutil.copy(os.path.join(d, f), os.path.join(dest, f"{other}_{f}"))
    print(f"  {other}: {hard} von 3000 schlagen an (> 0.3), {len(picked)} Clips übernommen", flush=True)
PY
echo "Verwechslungs-Negative: $(ls "$OUT/ha_tts_negative" | wc -l) Clips"

sed -i -E "s/^version: .*/version: $((V + 1))/" "$REPO/training/configs/$MODEL.yaml"
rm -f "$OUT/mww_features/negative_train.npy" "$OUT/mww_features/negative_val.npy"
"$REPO/training/train_model.sh" "$MODEL" features train export
