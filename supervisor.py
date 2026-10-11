"""Django side of the plugin: installs the worker's own Python environment and keeps the worker
process (voice_worker/) running while voice control is enabled.

Why a separate environment: the worker needs numpy and pymicro-wakeword, which must not go into
x32-recorder's own venv - its `uv sync` on every update would remove them again. Why a separate
process: wake-word detection is continuous CPU work and must run at low priority, never inside
the web server.
"""
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from django.db import close_old_connections

logger = logging.getLogger(__name__)

PLUGIN_DIR = Path(__file__).resolve().parent
APP_NAME = PLUGIN_DIR.name
VENV_DIR = PLUGIN_DIR / ".venv"
INSTALLED_MARKER = VENV_DIR / ".voice-worker-installed"
REQUIREMENTS = PLUGIN_DIR / "requirements-worker.txt"
STATUS_FILE = PLUGIN_DIR / "status.json"
WORKER_LOG = PLUGIN_DIR / "worker.log"
INSTALL_LOG = PLUGIN_DIR / "install.log"
PID_FILE = PLUGIN_DIR / "worker.pid"

CHECK_INTERVAL_S = 5
CRASH_BACKOFF_S = 60
MAX_LOG_BYTES = 2 * 1024 * 1024

_install = {"state": "idle", "message": ""}
_install_lock = threading.Lock()


def venv_python():
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def is_installed():
    return INSTALLED_MARKER.exists() and venv_python().exists()


def install_status_text():
    if _install["state"] == "running":
        return "Installation läuft..."
    if _install["state"] == "failed":
        return f"Installation fehlgeschlagen: {_install['message']} (Details: install.log)"
    return "Installiert" if is_installed() else "Nicht installiert"


def _find_uv():
    return shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")


def start_install():
    """Create .venv and install requirements-worker.txt in the background (a few minutes on a
    Pi - numpy and pymicro-wakeword come as prebuilt wheels)."""
    with _install_lock:
        if _install["state"] == "running":
            return
        _install.update(state="running", message="")

    def run():
        uv = _find_uv()
        steps = [
            [uv, "venv", str(VENV_DIR)],
            [uv, "pip", "install", "--python", str(venv_python()), "-r", str(REQUIREMENTS)],
        ]
        try:
            with open(INSTALL_LOG, "w", encoding="utf-8") as log:
                for cmd in steps:
                    log.write("$ " + " ".join(cmd) + "\n")
                    log.flush()
                    subprocess.run(cmd, cwd=PLUGIN_DIR, stdout=log, stderr=subprocess.STDOUT, check=True)
            INSTALLED_MARKER.touch()
            _install.update(state="done", message="")
        except Exception as e:  # uv missing, no network, ... - shown on the Settings page
            _install.update(state="failed", message=str(e)[:200])

    threading.Thread(target=run, daemon=True).start()


def read_status():
    try:
        import json

        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


# --- worker process -------------------------------------------------------------------------


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _kill_orphan():
    """A worker left over from a previous web-server process (restart, crash) would otherwise
    keep running with the old code next to the new one."""
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return
    if pid > 0 and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                if not _pid_alive(pid):
                    break
                time.sleep(0.1)
        except OSError:
            pass
    PID_FILE.unlink(missing_ok=True)


def _web_port():
    from recorder.models import RecorderSettings

    return RecorderSettings.get_solo().web_port or 8000


def _start_worker():
    if WORKER_LOG.exists() and WORKER_LOG.stat().st_size > MAX_LOG_BYTES:
        WORKER_LOG.unlink()
    env = dict(os.environ)
    env.update(
        RECORDER_API=f"http://127.0.0.1:{_web_port()}/api",
        VOICE_PLUGIN_NAME=APP_NAME,
        VOICE_STATUS_FILE=str(STATUS_FILE),
        PYTHONUNBUFFERED="1",
    )
    kwargs = {}
    if sys.platform != "win32":
        kwargs["preexec_fn"] = lambda: os.nice(10)  # never compete with the audio threads
    log = open(WORKER_LOG, "a", encoding="utf-8")
    proc = subprocess.Popen([str(venv_python()), "-m", "voice_worker"], cwd=PLUGIN_DIR, env=env,
                            stdout=log, stderr=subprocess.STDOUT, **kwargs)
    PID_FILE.write_text(str(proc.pid))
    logger.info("Voice worker started (PID %s)", proc.pid)
    return proc


def _stop_worker(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    PID_FILE.unlink(missing_ok=True)
    logger.info("Voice worker stopped")


def run_supervisor():
    from .models import VoiceSettings

    _kill_orphan()
    proc = None
    started_at = 0.0
    hold_until = 0.0
    while True:
        try:
            close_old_connections()
            want = VoiceSettings.get_solo().enabled and is_installed()
            now = time.monotonic()
            if proc is not None and proc.poll() is not None:
                logger.warning("Voice worker exited with %s", proc.returncode)
                PID_FILE.unlink(missing_ok=True)
                if now - started_at < 30:
                    hold_until = now + CRASH_BACKOFF_S  # crashing right away - don't spin
                proc = None
            if want and proc is None and now >= hold_until:
                proc = _start_worker()
                started_at = now
            elif not want and proc is not None:
                _stop_worker(proc)
                proc = None
        except Exception:
            logger.exception("Voice supervisor error")
        time.sleep(CHECK_INTERVAL_S)
