#!/usr/bin/env bash
# Ein Modell komplett: GPU-Vorabprüfung, alle Trainer-Phasen, Bewertung auf zurückgehaltenem Probenaudio.
#   training/train_model.sh <modellname> [phase ...]      (ohne Phasen: alle; z.B. "features train export")
# Am besten in tmux:  tmux new -s mww 'training/train_model.sh tapedeck_marker'
set -euo pipefail
MODEL="$1"; shift || true
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAINER="${TRAINER:-$HOME/src/microwakeword-trainer}"
DATA="${DATA:-$HOME/wakeword_data}"
CFG="$REPO/training/configs/$MODEL.yaml"
LOG="${LOG_DIR:-$HOME/mww_logs}/$MODEL-$(date +%Y%m%d-%H%M).log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "== $MODEL  $(date)  Log: $LOG"

# Windows wach halten, solange dieses Skript läuft (unter WSL): ein PowerShell-Prozess hält eine
# Wachhalte-Anforderung und endet, sobald seine Eingabe schließt - also auch bei Abbruch oder Absturz.
# Die Energiespareinstellungen selbst bleiben unverändert.
if command -v powershell.exe >/dev/null; then
    AWAKE_PS='$t = Add-Type -PassThru -Name P -Namespace W -MemberDefinition ([char]91 + "DllImport(""kernel32.dll"")] public static extern uint SetThreadExecutionState(uint f);")
[void]$t::SetThreadExecutionState([uint32]2147483649); [void][Console]::In.ReadToEnd()'
    exec {AWAKE_FD}> >(cd /mnt/c && powershell.exe -NoProfile -NonInteractive \
        -EncodedCommand "$(printf '%s' "$AWAKE_PS" | iconv -t UTF-16LE | base64 -w0)" >/dev/null 2>&1)
fi

cd "$TRAINER"
source .venv/bin/activate
NV="$(ls -d "$TRAINER"/.venv/lib/python3.*/site-packages/nvidia/*/lib | tr '\n' ':')"
export LD_LIBRARY_PATH="${NV}/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
python -c "
import tensorflow as tf, sys
g = tf.config.list_physical_devices('GPU'); print('GPU:', g)
sys.exit(0 if g else 'Abbruch: TensorFlow sieht keine GPU')" 2>&1 | grep -E "GPU:|Abbruch"

# Allgemeine Negativdaten (mehrere GB) nur einmal für alle Modelle laden
mkdir -p training/hf_shared/hf_cache training/hf_shared/hf_audio "training/output/$MODEL/mww_features"
for d in hf_cache hf_audio; do ln -sfn "$TRAINER/training/hf_shared/$d" "training/output/$MODEL/mww_features/$d"; done

if [[ $# -eq 0 ]]; then
    time ./run_mww.sh --config "$CFG"
else
    for phase in "$@"; do time ./run_mww.sh --config "$CFG" --phase "$phase"; done
fi

echo "== Bewertung  $(date)"
# Synthetische Prüf-Clips (Piper, nicht im Training): nur Plausibilitätsprüfung, KEIN Ersatz für echte Ansagen
SYN="training/output/$MODEL/eval_synthetic"; rm -rf "$SYN"; mkdir -p "$SYN"
SYN_FILES=("$TRAINER/training/output/$MODEL/positive_test"/*.wav)   # kein "ls | head": SIGPIPE + pipefail bricht ab
ln -s "${SYN_FILES[@]:0:500}" "$SYN/"
POS="$SYN"; [[ -n "$(ls "$DATA/positives_real/$MODEL"/*.wav 2>/dev/null)" ]] && POS="$DATA/positives_real/$MODEL"
echo "Positive aus: $POS"
FA="$DATA/fa/$MODEL"; rm -rf "$FA"
time python "$REPO/training/evaluate.py" --model "${MODEL}_mww.json" \
    --negatives "$DATA/split/heldout" --positives "$POS" --dump-false-accepts "$FA"
echo "== FERTIG $MODEL  $(date)"
