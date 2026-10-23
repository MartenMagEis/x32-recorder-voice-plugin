#!/usr/bin/env bash
# Wie setup_mww.sh, aber ohne sudo/apt und mit uv statt python3-venv (auf diesem Rechner fehlen pip/venv).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
UV=~/.local/bin/uv
[[ -d .venv ]] || $UV venv --python 3.10 .venv
MWW_REF="a70bd740d4e79ee8a8bb3db843fe862b88d5d6b0"   # derselbe Stand wie in setup_mww.sh
# Nicht per pip aus git: die Unterpakete (layers/, audio/) haben kein __init__.py und fehlen dann.
# Stattdessen den Quellstand auschecken und per .pth einbinden.
MWW_SRC="$HOME/src/mww_pinned"
if [[ ! -d "$MWW_SRC/microwakeword" ]]; then
    mkdir -p "$MWW_SRC" && git -C "$MWW_SRC" init -q
    git -C "$MWW_SRC" fetch -q --depth 1 https://github.com/kahrendt/microWakeWord.git "$MWW_REF"
    git -C "$MWW_SRC" checkout -q FETCH_HEAD
fi
echo "$MWW_SRC" > "$(ls -d .venv/lib/python3.*/site-packages)/mww_pinned.pth"
$UV pip install --python .venv/bin/python \
    audiomentations audio_metadata datasets webrtcvad-wheels ai-edge-litert \
    "tensorflow[and-cuda]>=2.16" \
    "pymicro-features>=2.0" "scipy>=1.10.0" "tqdm>=4.65.0" "huggingface_hub>=0.20.0" \
    "PyYAML>=6.0" "numpy>=1.24.0,<2.0" "mmap_ninja>=0.8" "requests>=2.28" \
    pymicro-wakeword pip setuptools wheel
mkdir -p training/piper_binary
if [[ ! -f training/piper_binary/piper/piper ]]; then
    wget -q -O training/piper_binary/piper.tar.gz \
        "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"
    tar -xzf training/piper_binary/piper.tar.gz -C training/piper_binary && rm training/piper_binary/piper.tar.gz
fi
cat > run_mww.sh <<'RUN'
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/.venv/bin/activate"
# TensorFlow findet die per pip installierten CUDA-Bibliotheken nicht von selbst
NV="$(ls -d "$SCRIPT_DIR"/.venv/lib/python3.*/site-packages/nvidia/*/lib | tr '\n' ':')"
export LD_LIBRARY_PATH="${NV}/usr/lib/wsl/lib:${LD_LIBRARY_PATH:-}"
exec python "$SCRIPT_DIR/train_mww.py" "$@"
RUN
chmod +x run_mww.sh
.venv/bin/python - <<'PY'
import tensorflow as tf, numpy, microwakeword, pymicro_features, mmap_ninja, audiomentations
print("TF", tf.__version__, "numpy", numpy.__version__)
print("GPUs:", tf.config.list_physical_devices("GPU"))
PY
echo SETUP_DONE
