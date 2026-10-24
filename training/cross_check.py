"""Do the command models trigger on each other's phrases? Runs every model over the held-out
synthetic clips of every command (positive_test of the trainer, never used for training) and
prints the share that fires at each model's own cutoff - the diagonal is recall, everything else
should be ~0. Real recordings in --real/<model>/ are included as an extra column group if present.

    python training/cross_check.py --trainer ~/src/microwakeword-trainer --models wakewords \
        [--real ~/wakeword_data/positives_real] [--n 200]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate import probabilities, read_wav16  # noqa: E402

NAMES = ["tapedeck_record", "tapedeck_finish", "tapedeck_marker", "tapedeck_next_song"]


def peaks(model, files, beds=None):
    """Peak probability per clip. With beds, each clip sits in 1 s of quiet real room sound on
    both sides (as the trainer pads its training clips) instead of digital silence - zeros are a
    value no microphone delivers, and models trained with room-sound padding can react oddly to
    them (next_song v2 rated its own training negatives 0.83 with zero padding)."""
    rng = np.random.default_rng(0)
    out = []
    for f in files:
        clip = read_wav16(f).astype(np.float32)
        n = len(clip) + 32000
        if beds:
            bed = beds[rng.integers(len(beds))]
            start = rng.integers(0, len(bed) - n)
            seg = bed[start:start + n].astype(np.float32)
            seg *= 800.0 / (np.abs(seg).max() or 1.0)
        else:
            seg = np.zeros(n, dtype=np.float32)
        seg[16000:16000 + len(clip)] += clip
        x = np.clip(seg, -32768, 32767).astype('<i2')
        out.append(float(probabilities(model, x)[0].max()))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--trainer', required=True)
    p.add_argument('--models', required=True, help='folder with <name>.json + .tflite')
    p.add_argument('--real')
    p.add_argument('--n', type=int, default=200)
    p.add_argument('--beds', help='folder of long 16 kHz WAVs (e.g. held-out rehearsal audio) to pad '
                                  'clips with quiet real room sound instead of digital silence')
    a = p.parse_args()
    beds = None
    if a.beds:
        names = sorted(f for f in os.listdir(a.beds) if f.endswith('.wav'))[::10][:12]
        beds = [read_wav16(os.path.join(a.beds, f)) for f in names]

    models = {n: os.path.join(a.models, n + '.json') for n in NAMES
              if os.path.isfile(os.path.join(a.models, n + '.json'))}
    sets = {}
    for n in NAMES:
        d = os.path.join(a.trainer, 'training', 'output', n, 'positive_test')
        if os.path.isdir(d):
            sets[f'{n[9:]} (TTS)'] = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith('.wav'))[:a.n]
        if a.real:
            d = os.path.join(a.real, n)
            if os.path.isdir(d) and os.listdir(d):
                sets[f'{n[9:]} (echt)'] = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith('.wav'))

    print('Anteil ausgelöst bei der Schwelle des Modells (Zeile = Modell, Spalte = gesprochene Phrase)\n')
    print(f'{"Modell":24s}' + ''.join(f'{s:>20s}' for s in sets))
    for n, m in models.items():
        cut = json.load(open(m))['micro']['probability_cutoff']
        row = []
        for s, files in sets.items():
            pk = peaks(m, files, None if s.endswith('(echt)') else beds)  # real clips bring their own room
            row.append(f'{sum(x > cut for x in pk)}/{len(pk)}')
        print(f'{n[9:] + f" ({cut})":24s}' + ''.join(f'{r:>20s}' for r in row), flush=True)


if __name__ == '__main__':
    main()
