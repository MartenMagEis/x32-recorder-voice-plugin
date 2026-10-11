"""Export the band's own rehearsal vocal tracks as wake-word negatives (16 kHz mono WAV chunks).

Singing, talking between songs and the band bleeding into the vocal mics are exactly what the
models must *not* react to - the strongest single lever against false triggers. Runs on the
recorder Pi (where the recordings are), with the plugin's own .venv (needs numpy):

    cd ~/x32-recorder/plugins/x32_recorder_voice_plugin
    nice -n 19 .venv/bin/python training/export_negatives.py --out /mnt/32recorder/wakeword_training/negatives

Picks every non-deleted recording >= 10 min and, in it, every track whose file name contains one of
--names (default: the singers of the bands on the test Pi). Writes 5-minute chunks, skips
near-silent ones. Re-running skips chunks that already exist.
"""
import argparse
import os
import sqlite3
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from voice_worker.resample import Decimator, to_pcm16  # noqa: E402

DEFAULT_NAMES = ["Lukas", "Tobi", "Marten", "Felix", "Jessi", "Pia", "Julia"]
CHUNK_S = 300
SILENCE_DBFS = -60.0


def recordings(db_path, recordings_dir, min_s):
    db = sqlite3.connect(db_path)
    rows = db.execute(
        "SELECT id, uuid, name FROM recorder_recording "
        "WHERE source = 'recorder' AND raw_deleted = 0 AND duration >= ? ORDER BY id",
        (int(min_s * 1e6),),
    ).fetchall()
    for rid, uid, name in rows:
        uid = uid.replace('-', '')
        folder = os.path.join(recordings_dir, f"{uid[:8]}-{uid[8:12]}-{uid[12:16]}-{uid[16:20]}-{uid[20:]}")
        if os.path.isdir(folder):
            yield rid, name, folder


def read_24bit(w, frames):
    raw = w.readframes(frames)
    if not raw:
        return None
    ch = w.getnchannels()
    b = np.frombuffer(raw, dtype=np.uint8)
    b = b[: len(b) - len(b) % (3 * ch)].reshape(-1, 3)
    x = b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)
    x = np.where(x & 0x800000, x - 0x1000000, x).astype(np.float32) / 8388608.0
    return x.reshape(-1, ch)[:, 0]  # stereo file: left side is enough


def export_track(path, out_prefix):
    written = skipped = 0
    with wave.open(path) as w:
        if w.getsampwidth() != 3 or w.getframerate() != 48000:
            print(f"  skip (format): {path}")
            return 0, 0
        dec = Decimator()
        index = 0
        while True:
            x = read_24bit(w, 48000 * CHUNK_S)
            if x is None or x.size == 0:
                break
            target = f"{out_prefix}_{index:03d}.wav"
            index += 1
            if os.path.exists(target):
                dec.process(x)  # keep the filter state continuous
                continue
            y = dec.process(x)
            rms = 20 * np.log10(np.sqrt(np.mean(np.square(y))) + 1e-12)
            if rms < SILENCE_DBFS:
                skipped += 1
                continue
            with wave.open(target + '.tmp', 'wb') as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(16000)
                out.writeframes(to_pcm16(y))
            os.replace(target + '.tmp', target)
            written += 1
    return written, skipped


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='/home/pi/x32-recorder/x32recorder/db.sqlite3')
    p.add_argument('--recordings', default='/mnt/32recorder/recordings')
    p.add_argument('--out', required=True)
    p.add_argument('--names', nargs='+', default=DEFAULT_NAMES)
    p.add_argument('--min-minutes', type=float, default=10)
    args = p.parse_args()
    os.makedirs(args.out, exist_ok=True)

    total_written = 0
    for rid, name, folder in recordings(args.db, args.recordings, args.min_minutes * 60):
        for f in sorted(os.listdir(folder)):
            if not f.endswith('.wav') or 'Git' in f:
                continue
            if not any(n in f for n in args.names):
                continue
            prefix = os.path.join(args.out, f"rec{rid}_{os.path.splitext(f)[0]}")
            written, skipped = export_track(os.path.join(folder, f), prefix)
            total_written += written
            print(f"rec {rid} {f}: {written} chunks, {skipped} silent skipped", flush=True)
    print(f"done: {total_written} new chunks of {CHUNK_S // 60} min in {args.out}")


if __name__ == '__main__':
    main()
