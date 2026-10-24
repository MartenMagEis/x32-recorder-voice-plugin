"""App-wide settings on x32-recorder's Settings page (plugin_config.py convention)."""
import os

from recorder.plugin_support import describe_model_fields, model_instance_values

from . import sample_store, supervisor
from .models import VoiceSettings

MODEL_FIELDS = ["model_start", "model_stop", "model_marker", "model_next"]
FIELDS = [
    "enabled",
    "listen_while_idle",
    *MODEL_FIELDS,
    "stop_needs_confirmation",
    "confirm_window_s",
    "dedup_ms",
    "announcement_ms",
    "collect_samples",
    "near_miss_percent",
    "samples_max_mb",
    "udp_port",
]

# Bundled with pymicro-wakeword - stand-ins until the band's own phrases are trained.
BUILTIN_MODELS = ["okay_nabu", "hey_jarvis", "hey_mycroft", "alexa"]


def _model_choices():
    choices = [["", "– keins –"]]
    folder = supervisor.PLUGIN_DIR / "wakewords"
    if folder.is_dir():
        for name in sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json")):
            choices.append([name, f"{name} (eigenes Modell)"])
    choices += [[m, f"{m} (Beispielmodell)"] for m in BUILTIN_MODELS]
    return choices


def _status_text():
    status = supervisor.read_status()
    if not status:
        return "Worker läuft nicht"
    text = f"{status.get('state')} (Stand {status.get('updated', '?')[11:]})"
    if status.get("template"):
        channels = ", ".join(str(c) for c in status.get("channels") or [])
        text += f" - Vorlage '{status['template']}', Kanal {channels}"
    if status.get("samples_pending"):
        text += f" - {status['samples_pending']} Sprachbeispiel(e) warten aufs Speichern"
    if status.get("error"):
        text += f" - Fehler: {status['error']}"
    return text


def _recent_text():
    status = supervisor.read_status() or {}
    lines = [f"{r['time']}  {r['command']} ({r['probability']}): {r['result']}" for r in status.get("recent", [])]
    return "\n".join(lines) or "–"


def get_config_schema():
    fields = describe_model_fields(VoiceSettings, FIELDS)
    choices = _model_choices()
    for f in fields:
        if f["name"] in MODEL_FIELDS:
            f["type"] = "choice"
            f["choices"] = choices
    fields += [
        {"name": "install_status", "label": "Erkennung (eigene Python-Umgebung)", "type": "string",
         "help_text": "numpy + pymicro-wakeword, getrennt von x32-recorder installiert.", "readonly": True},
        {"name": "install", "label": "Erkennung neu installieren / aktualisieren", "type": "action",
         "help_text": "Normalerweise nicht nötig - beim ersten Aktivieren wird automatisch installiert. "
                      "Nur für ein Update der Erkennung oder nach einer fehlgeschlagenen Installation.",
         "readonly": False},
        {"name": "samples_path", "label": "Ablage der Sprachbeispiele", "type": "string", "readonly": True,
         "help_text": "Pro Modell ein Ordner mit WAV + JSON je Clip - für das Training z.B. per rsync holen."},
        {"name": "worker_status", "label": "Status", "type": "string", "help_text": "", "readonly": True},
        {"name": "recent", "label": "Letzte Erkennungen", "type": "string", "help_text": "", "readonly": True},
    ]
    return {"fields": fields}


def get_config_values():
    values = model_instance_values(VoiceSettings.get_solo(), FIELDS)
    folder = sample_store.samples_dir()
    values.update(install_status=supervisor.install_status_text(), worker_status=_status_text(),
                  recent=_recent_text(), samples_path=str(folder) if folder else "")
    return values


def update_config_values(data):
    settings = VoiceSettings.get_solo()
    for key, value in data.items():
        if key in FIELDS:
            setattr(settings, key, value)
    settings.full_clean()
    settings.save()
    return get_config_values()


def handle_config_action(action_name, data):
    if action_name == "install":
        supervisor.start_install()
