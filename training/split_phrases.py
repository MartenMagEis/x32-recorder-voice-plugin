"""Cut a recording in which someone says a phrase several times (with pauses) into one 16 kHz mono
clip per utterance - for the "real voices" test set (and optionally as extra training positives).

Works on the recorder's own channel WAVs (48 kHz 24-bit) as well as on 16 kHz phone/laptop
recordings:

    python training/split_phrases.py ch13_Lukas.wav --out data/positives_real/tapedeck_record --prefix lukas

Detection is plain energy-based: an utterance is a stretch louder than --threshold-db (relative to
the loudest part) that's between 0.3 and 3 s long; pauses must be >= 0.5 s. Check the result by
listening to a few clips - the band playing in the background during the recording would fool it.
"""
import argparse
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from voice_worker.resample import Decimator, to_pcm16  # noqa: E402


def load_16k(path):
    with wave.open(path) as w:
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    if width == 3:
        b = np.frombuffer(raw, dtype=np.uint8)
        b = b[: len(b) - len(b) % 3].reshape(-1, 3)
        x = b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)
        x = np.where(x & 0x800000, x - 0x1000000, x).astype(np.float32) / 8388608.0
    elif width == 2:
        x = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
    else:
        raise ValueError(f'{path}: unsupported sample width {width}')
    x = x.reshape(-1, ch)[:, 0]
    if rate == 48000:
        return Decimator().process(x)
    if rate == 16000:
        return x
    raise ValueError(f'{path}: need 48 or 16 kHz (got {rate})')


def split(x, threshold_db, min_len=0.3, max_len=3.0, min_pause=0.5, margin=0.25):
    frame = 160  # 10 ms
    n = len(x) // frame
    energy = 20 * np.log10(np.sqrt(np.mean(np.square(x[: n * frame].reshape(n, frame)), axis=1)) + 1e-9)
    loud = energy > energy.max() + threshold_db
    segments, start, quiet = [], None, 0
    for i, is_loud in enumerate(loud):
        if is_loud:
            if start is None:
                start = i
            quiet = 0
        elif start is not None:
            quiet += 1
            if quiet * 0.01 >= min_pause:
                end = i - quiet + 1
                if min_len <= (end - start) * 0.01 <= max_len:
                    segments.append((start, end))
                start, quiet = None, 0
    pad = int(margin / 0.01)
    return [(max(0, a - pad) * frame, min(n, b + pad) * frame) for a, b in segments]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('wav')
    p.add_argument('--out', required=True)
    p.add_argument('--prefix', required=True, help='e.g. the speaker name')
    p.add_argument('--threshold-db', type=float, default=-30.0)
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)
    x = load_16k(args.wav)
    segments = split(x, args.threshold_db)
    for n, (a, b) in enumerate(segments, 1):
        with wave.open(os.path.join(args.out, f'{args.prefix}_{n:03d}.wav'), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(to_pcm16(x[a:b]))
    print(f'{len(segments)} clips -> {args.out}')


if __name__ == '__main__':
    main()
