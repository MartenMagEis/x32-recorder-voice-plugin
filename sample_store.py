"""Django side of the collected voice samples (written by voice_worker/samples.py): where they
live, listing them for the review page with hints from the database, and storing labels.

The labels and hints are written into each clip's JSON sidecar - that is what
training/label_clips.py reads on the training PC, which has no access to the database."""
import datetime
import json
import os
from pathlib import Path

from recorder.models import Recording, RecordingMarker
from recorder.storage import get_recording_path, recording_storage_unavailable

LABELS = ("positiv", "negativ", "unklar")
# A marker set by hand this soon after a near miss suggests the command was said but missed.
MANUAL_MARKER_WINDOW_S = 15.0

HINT_MARKER_DELETED = "Marker später gelöscht"
HINT_MANUAL_MARKER = "kurz danach Marker von Hand gesetzt"


def samples_dir():
    """<recordings medium>/wakeword_training/auto - next to the recordings, on the same (big)
    drive, beside the training data export_negatives.py writes. None while a configured
    recordings drive is missing, so nothing lands on the SD card's empty mount point instead."""
    if recording_storage_unavailable():
        return None
    return Path(get_recording_path()).resolve().parent / "wakeword_training" / "auto"


def resolve(rel):
    """Absolute base path (without extension) for a clip id like 'tapedeck_marker/2026...', or
    None if it would point outside the samples folder or doesn't exist."""
    folder = samples_dir()
    if folder is None or not rel:
        return None
    base = (folder / rel).resolve()
    if folder.resolve() not in base.parents or not base.with_suffix(".json").is_file():
        return None
    return base


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, meta):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _all_clips(folder):
    clips = []
    for json_path in folder.glob("*/*.json"):
        meta = _read(json_path)
        if meta is not None and json_path.with_suffix(".wav").is_file():
            clips.append((json_path, meta))
    return clips


def _db_hints(clips):
    """{json_path: [hint, ...]} from what the database knows now - computed on every listing,
    since markers get deleted or added long after the rehearsal."""
    voice_marker_ids = {i for _, m in clips for i in m.get("marker_ids") or []}
    recording_ids = {m.get("recording_id") for _, m in clips if m.get("recording_id")}
    recordings = {r.id: r for r in Recording.objects.filter(id__in=recording_ids)}
    markers = {}
    for marker in RecordingMarker.objects.filter(recording_id__in=recordings):
        markers.setdefault(marker.recording_id, []).append(marker)

    hints = {}
    for json_path, meta in clips:
        found = []
        recording = recordings.get(meta.get("recording_id"))
        if recording is not None:
            own = meta.get("marker_ids") or []
            existing = {m.id for m in markers.get(recording.id, [])}
            if own and not set(own) <= existing:
                found.append(HINT_MARKER_DELETED)
            if meta.get("kind") == "beinahe" and recording.started_at:
                at = datetime.datetime.fromisoformat(meta["time"]) - recording.started_at
                window = datetime.timedelta(seconds=MANUAL_MARKER_WINDOW_S)
                if any(at <= m.timestamp <= at + window and m.id not in voice_marker_ids
                       for m in markers.get(recording.id, [])):
                    found.append(HINT_MANUAL_MARKER)
        hints[json_path] = found
    return hints


def list_samples(only_open=True):
    folder = samples_dir()
    if folder is None or not folder.is_dir():
        return []
    clips = _all_clips(folder)
    db_hints = _db_hints(clips)
    rows = []
    for json_path, meta in clips:
        if meta.get("db_hints") != db_hints[json_path]:
            meta["db_hints"] = db_hints[json_path]
            _write(json_path, meta)
        if only_open and meta.get("label"):
            continue
        rows.append({"id": json_path.relative_to(folder).with_suffix("").as_posix(), **meta})
    rows.sort(key=lambda r: r.get("time", ""), reverse=True)
    return rows


def set_label(rel, label):
    base = resolve(rel)
    if base is None or label not in LABELS + (None,):
        return False
    path = base.with_suffix(".json")
    meta = _read(path) or {}
    meta["label"] = label
    meta["label_by"] = "Prüfliste" if label else None
    _write(path, meta)
    return True


def delete(rel):
    base = resolve(rel)
    if base is None:
        return False
    for suffix in (".wav", ".json"):
        try:
            base.with_suffix(suffix).unlink()
        except FileNotFoundError:
            pass
    return True
