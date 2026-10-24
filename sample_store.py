"""Django side of the collected voice samples (written by voice_worker/samples.py)."""
from pathlib import Path

from recorder.storage import get_recording_path, recording_storage_unavailable


def samples_dir():
    """<recordings medium>/wakeword_training/auto - next to the recordings, on the same (big)
    drive, beside the training data export_negatives.py writes. None while a configured
    recordings drive is missing, so nothing lands on the SD card's empty mount point instead."""
    if recording_storage_unavailable():
        return None
    return Path(get_recording_path()).resolve().parent / "wakeword_training" / "auto"
