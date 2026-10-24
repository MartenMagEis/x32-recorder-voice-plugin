"""Per-template settings shown in x32-recorder's template editor - see its
plugins/PLUGIN_DEVELOPMENT.md ("Einstellungen pro Vorlage")."""
from django.core.exceptions import ValidationError

from recorder.plugin_support import describe_model_fields, model_instance_values

from .models import VoiceTemplateSettings

# The controller serves at most 4 audio taps at once - one per channel.
MAX_CHANNELS = 4
CHANNEL_FIELDS = [f"channel_{i}" for i in range(1, MAX_CHANNELS + 1)]


def _channel_field(index):
    if index == 1:
        return {
            "name": "channel_1", "label": "Sprach-Kanal", "type": "channel", "readonly": False,
            "help_text": "Mikrofon, in das die Befehle gesprochen werden (z.B. ein Gesangs- oder "
                         "Talkback-Mikro).",
        }
    return {
        "name": f"channel_{index}", "label": f"Weiterer Sprach-Kanal ({index})", "type": "channel",
        "readonly": False,
        "help_text": "" if index < MAX_CHANNELS else (
            "Nicht übertreiben: jeder Kanal kostet auf dem Pi 3B gut 10 % eines CPU-Kerns, und jedes "
            "weitere Mikro hört mehr Gesang mit - das macht Fehlauslöser wahrscheinlicher. Nur Mikros "
            "wählen, in die wirklich Befehle gesprochen werden."
        ),
    }


def get_template_config_schema():
    return {
        "title": "Sprachsteuerung",
        "fields": describe_model_fields(VoiceTemplateSettings, ["enabled"])
        + [_channel_field(i) for i in range(1, MAX_CHANNELS + 1)],
    }


def _values(settings):
    values = model_instance_values(settings, ["enabled"])
    channels = list(settings.channels or [])
    for i, name in enumerate(CHANNEL_FIELDS):
        values[name] = channels[i] if i < len(channels) else None
    # For consumers that just want the list (the worker).
    values["channels"] = channels
    return values


def get_template_config_values(template):
    if template is None:
        return _values(VoiceTemplateSettings())
    return _values(VoiceTemplateSettings.objects.filter(template=template).first() or VoiceTemplateSettings())


def update_template_config_values(template, data):
    enabled = bool(data.get("enabled"))
    channels = []
    for name in CHANNEL_FIELDS:
        value = data.get(name)
        if value in (None, ""):
            continue
        channel_no = int(value)
        if not 1 <= channel_no <= 64:
            raise ValidationError("Ungültiger Kanal.")
        if channel_no not in channels:
            channels.append(channel_no)
    if enabled and not channels:
        raise ValidationError("Für die Sprachsteuerung bitte mindestens einen Sprach-Kanal wählen.")
    VoiceTemplateSettings.objects.update_or_create(
        template=template, defaults={"enabled": enabled, "channels": channels}
    )
