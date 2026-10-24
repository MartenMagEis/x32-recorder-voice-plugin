"""Django-side tests - run inside an x32-recorder checkout with this plugin enabled:

    uv run python x32recorder/manage.py test x32_recorder_voice_plugin
"""
import json

from django.test import Client, TestCase

from recorder.models import RecordingTemplate

from ..models import VoiceSettings, VoiceTemplateSettings


class TemplateSettingsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.template = RecordingTemplate.objects.create(name="Band", channel_count=4)

    def block(self, template_id=None):
        url = "/api/plugins/template-config/" + (f"?template_id={template_id}" if template_id else "")
        return next(b for b in self.client.get(url).json()["plugins"] if b["plugin"] == "x32_recorder_voice_plugin")

    def test_shows_up_in_template_editor_with_four_channel_fields(self):
        block = self.block()
        self.assertEqual(block["title"], "Sprachsteuerung")
        self.assertEqual({f["name"]: f["type"] for f in block["fields"]}, {
            "enabled": "bool", "channel_1": "channel", "channel_2": "channel",
            "channel_3": "channel", "channel_4": "channel",
        })
        self.assertEqual(block["values"], {
            "enabled": False, "channel_1": None, "channel_2": None, "channel_3": None,
            "channel_4": None, "channels": [],
        })

    def save(self, **data):
        url = f"/api/plugins/template-config/{self.template.id}/x32_recorder_voice_plugin/"
        return self.client.patch(url, data=json.dumps(data), content_type="application/json")

    def test_save_and_validation(self):
        self.assertEqual(self.save(enabled=True, channel_1=None).status_code, 400)
        self.assertEqual(self.save(enabled=True, channel_1=15).status_code, 200)
        values = self.block(self.template.id)["values"]
        self.assertEqual((values["enabled"], values["channel_1"], values["channels"]), (True, 15, [15]))

    def test_several_channels_without_gaps_or_duplicates(self):
        self.assertEqual(self.save(enabled=True, channel_1=None, channel_2=14, channel_3=15,
                                   channel_4=14).status_code, 200)
        values = self.block(self.template.id)["values"]
        self.assertEqual(values["channels"], [14, 15])
        self.assertEqual((values["channel_1"], values["channel_2"], values["channel_3"]), (14, 15, None))

    def test_settings_removed_with_template(self):
        VoiceTemplateSettings.objects.create(template=self.template, enabled=True, channels=[3])
        self.template.delete()
        self.assertFalse(VoiceTemplateSettings.objects.exists())


class AppSettingsTests(TestCase):
    """Calls plugin_config directly - the generic /api/plugins/<name>/config/ endpoint also needs
    the plugin registered in plugins/registry.json, which a test environment doesn't have."""

    def test_config_lists_models_and_status(self):
        from .. import plugin_config

        fields = {f["name"]: f for f in plugin_config.get_config_schema()["fields"]}
        self.assertEqual(fields["model_start"]["type"], "choice")
        self.assertIn("okay_nabu", [c[0] for c in fields["model_start"]["choices"]])
        self.assertEqual(fields["install"]["type"], "action")
        self.assertIn("Nicht installiert", plugin_config.get_config_values()["install_status"])

    def test_update(self):
        from .. import plugin_config

        plugin_config.update_config_values({"enabled": True, "model_marker": "okay_nabu", "recent": "ignored"})
        settings = VoiceSettings.get_solo()
        self.assertEqual((settings.enabled, settings.model_marker), (True, "okay_nabu"))
