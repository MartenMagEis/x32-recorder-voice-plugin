"""Evaluate a trained microWakeWord model against the band's own audio - the yardstick for "is
this model good enough", independent of whichever trainer produced it.

    python training/evaluate.py --model models/tapedeck_record.json \
        --negatives data/negatives --positives data/positives_real/tapedeck_record \
        [--dump-false-accepts out/fa_clips]

- Negatives (rehearsal vocal tracks, 16 kHz mono WAV): every activation is a false accept.
  Reported as false accepts per hour for a range of probability cutoffs, so you can see what a
  different cutoff would do without retraining.
- Positives (real recordings of the phrase, one clip per file): recall = share of clips that
  trigger. Each clip is padded with 1 s of silence on both sides, as in a live stream.
- --dump-false-accepts writes 3 s around each false accept (at the model's own cutoff) as WAV -
  feed those back into the trainer as extra negatives ("user negatives") for the next run.

Needs numpy + pymicro-wakeword (same as the plugin's worker).
"""
import argparse
import json
import os
import wave

import numpy as np
from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures

CUTOFFS = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.99]
FEATURE_STEP_S = 0.010
MERGE_S = 2.0


def read_wav16(path):
    with wave.open(path) as w:
        if w.getframerate() != 16000 or w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f'{path}: need 16 kHz mono 16-bit')
        return np.frombuffer(w.readframes(w.getnframes()), dtype='<i2')


def probabilities(model_path, pcm):
    """Per-feature-step probability trace (the model's own sliding-window mean, as on the Pi)."""
    model = MicroWakeWord.from_config(model_path)
    features = MicroWakeWordFeatures()
    probs = []
    for i in range(0, len(pcm), 16000):
        for f in features.process_streaming(pcm[i:i + 16000].tobytes()):
            p = model.process_streaming_prob(f)
            probs.append(0.0 if p is None else p)
    return np.array(probs, dtype=np.float32), model.probability_cutoff


def count_events(probs, cutoff):
    """Activations above cutoff, merged within MERGE_S - one spoken phrase = one event."""
    events, last = [], -1e9
    for idx in np.flatnonzero(probs > cutoff):
        t = idx * FEATURE_STEP_S
        if t - last > MERGE_S:
            events.append(t)
        last = t
    return events


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True, help='the model .json (next to its .tflite)')
    p.add_argument('--negatives')
    p.add_argument('--positives')
    p.add_argument('--dump-false-accepts')
    args = p.parse_args()

    name = json.load(open(args.model)).get('wake_word', os.path.basename(args.model))
    print(f'Model: {name}')

    if args.negatives:
        files = sorted(f for f in os.listdir(args.negatives) if f.endswith('.wav'))
        hours = 0.0
        counts = {c: 0 for c in CUTOFFS}
        own_cutoff = None
        if args.dump_false_accepts:
            os.makedirs(args.dump_false_accepts, exist_ok=True)
        for n, f in enumerate(files, 1):
            pcm = read_wav16(os.path.join(args.negatives, f))
            hours += len(pcm) / 16000 / 3600
            probs, own_cutoff = probabilities(args.model, pcm)
            for c in CUTOFFS:
                counts[c] += len(count_events(probs, c))
            if args.dump_false_accepts:
                for t in count_events(probs, own_cutoff):
                    a = max(0, int((t - 2.0) * 16000))
                    clip = pcm[a:a + 3 * 16000]
                    out = os.path.join(args.dump_false_accepts, f'{os.path.splitext(f)[0]}_{t:07.1f}s.wav')
                    with wave.open(out, 'wb') as w:
                        w.setnchannels(1)
                        w.setsampwidth(2)
                        w.setframerate(16000)
                        w.writeframes(clip.tobytes())
            if n % 20 == 0:
                print(f'  ... {n}/{len(files)} files, {hours:.1f} h', flush=True)
        print(f'\nNegatives: {hours:.1f} h band audio')
        print('  cutoff   false accepts   per hour')
        for c in CUTOFFS:
            mark = '   <- model default' if own_cutoff is not None and abs(c - own_cutoff) < 1e-6 else ''
            print(f'  {c:5.2f}    {counts[c]:8d}       {counts[c] / max(hours, 1e-9):7.3f}{mark}')

    if args.positives:
        files = sorted(f for f in os.listdir(args.positives) if f.endswith('.wav'))
        peaks = []
        for f in files:
            pcm = read_wav16(os.path.join(args.positives, f))
            pad = np.zeros(16000, dtype='<i2')
            probs, own_cutoff = probabilities(args.model, np.concatenate([pad, pcm, pad]))
            peaks.append((f, float(probs.max()) if probs.size else 0.0))
        print(f'\nPositives: {len(files)} real clips')
        print('  cutoff   recall')
        for c in CUTOFFS:
            hit = sum(1 for _, peak in peaks if peak > c)
            print(f'  {c:5.2f}    {hit}/{len(peaks)} ({100 * hit / max(len(peaks), 1):.0f} %)')
        missed = [f for f, peak in peaks if peak <= own_cutoff]
        if missed:
            print('  missed at model default cutoff: ' + ', '.join(missed[:20]))


if __name__ == '__main__':
    main()
