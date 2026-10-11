"""Per-template settings shown in x32-recorder's template editor - see its
plugins/PLUGIN_DEVELOPMENT.md ("Einstellungen pro Vorlage")."""
from django.core.exceptions import ValidationError

from recorder.plugin_support import describe_model_fields, model_instance_values

from .models import VoiceTemplateSettings

FIELDS = ["enabled", "channel_no"]


def get_template_config_schema():
    return {
        "title": "Sprachsteuerung",
        "fields": describe_model_fields(VoiceTemplateSettings, FIELDS, type_overrides={"channel_no": "channel"}),
    }


def get_template_config_values(template):
    if template is None:
        return model_instance_values(VoiceTemplateSettings(), FIELDS)
    settings = VoiceTemplateSettings.objects.filter(template=template).first() or VoiceTemplateSettings()
    return model_instance_values(settings, FIELDS)


def update_template_config_values(template, data):
    enabled = bool(data.get("enabled"))
    channel_no = data.get("channel_no")
    channel_no = None if channel_no in (None, "") else int(channel_no)
    if enabled and channel_no is None:
        raise ValidationError("Für die Sprachsteuerung bitte einen Sprach-Kanal wählen.")
    if channel_no is not None and not 1 <= channel_no <= 64:
        raise ValidationError("Ungültiger Kanal.")
    VoiceTemplateSettings.objects.update_or_create(
        template=template, defaults={"enabled": enabled, "channel_no": channel_no}
    )
