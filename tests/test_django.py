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

    def test_shows_up_in_template_editor_with_channel_field(self):
        block = self.block()
        self.assertEqual(block["title"], "Sprachsteuerung")
        self.assertEqual({f["name"]: f["type"] for f in block["fields"]}, {"enabled": "bool", "channel_no": "channel"})
        self.assertEqual(block["values"], {"enabled": False, "channel_no": None})

    def test_save_and_validation(self):
        url = f"/api/plugins/template-config/{self.template.id}/x32_recorder_voice_plugin/"
        bad = self.client.patch(url, data=json.dumps({"enabled": True, "channel_no": None}),
                                content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        ok = self.client.patch(url, data=json.dumps({"enabled": True, "channel_no": 15}),
                               content_type="application/json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.block(self.template.id)["values"], {"enabled": True, "channel_no": 15})

    def test_settings_removed_with_template(self):
        VoiceTemplateSettings.objects.create(template=self.template, enabled=True, channel_no=3)
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
