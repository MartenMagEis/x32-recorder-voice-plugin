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

    def test_samples_land_next_to_the_recordings(self):
        from .. import plugin_config

        path = plugin_config.get_config_values()["samples_path"].replace("\\", "/")
        self.assertTrue(path.endswith("/wakeword_training/auto"), path)


class SampleReviewTests(TestCase):
    """The review page's backend: listing with database hints, labels, deleting, audio."""

    def setUp(self):
        import datetime
        import tempfile

        from django.test import override_settings
        from django.utils import timezone

        from recorder.models import Recording, RecordingMarker

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(RECORDING_PATH=tmp.name + "/recordings/")
        override.enable()
        self.addCleanup(override.disable)
        self.folder = __import__("pathlib").Path(tmp.name) / "wakeword_training" / "auto" / "tapedeck_marker"
        self.folder.mkdir(parents=True)

        started = timezone.now() - datetime.timedelta(minutes=10)
        self.recording = Recording.objects.create(state=Recording.STOPPED, channels=[0], started_at=started)
        kept = RecordingMarker.objects.create(recording=self.recording, timestamp=datetime.timedelta(seconds=60),
                                              marker_type=1)
        RecordingMarker.objects.create(recording=self.recording, timestamp=datetime.timedelta(seconds=125),
                                       marker_type=1)  # by hand, 5 s after the near miss below
        at = lambda s: (started + datetime.timedelta(seconds=s)).isoformat()
        self.write("a_erkannt", {"time": at(60), "kind": "erkannt", "marker_ids": [kept.id]})
        self.write("b_erkannt", {"time": at(90), "kind": "erkannt", "marker_ids": [kept.id + 100]})
        self.write("c_beinahe", {"time": at(120), "kind": "beinahe"})
        self.client = Client()

    def write(self, name, meta):
        meta = {"command": "marker", "model": "tapedeck_marker", "channel_no": 15, "probability": 0.7,
                "label": None, "hints": [], "recording_id": self.recording.id, **meta}
        (self.folder / f"{name}.json").write_text(json.dumps(meta), encoding="utf-8")
        (self.folder / f"{name}.wav").write_bytes(b"RIFF")

    def listing(self, all_=False):
        return self.client.get("/plugins/x32_recorder_voice_plugin/samples/api/list/" + ("?all=1" if all_ else "")).json()["samples"]

    def test_lists_newest_first_with_db_hints(self):
        rows = {r["id"].split("/")[-1]: r for r in self.listing()}
        self.assertEqual(list(rows), ["c_beinahe", "b_erkannt", "a_erkannt"])
        self.assertEqual(rows["a_erkannt"]["db_hints"], [])
        self.assertEqual(rows["b_erkannt"]["db_hints"], ["Marker später gelöscht"])
        self.assertEqual(rows["c_beinahe"]["db_hints"], ["kurz danach Marker von Hand gesetzt"])
        # stored for the training PC, which has no database
        stored = json.loads((self.folder / "c_beinahe.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["db_hints"], ["kurz danach Marker von Hand gesetzt"])

    def post(self, action, **data):
        return self.client.post(f"/plugins/x32_recorder_voice_plugin/samples/api/{action}/",
                                data=json.dumps(data), content_type="application/json")

    def test_label_hides_from_open_list_and_delete_removes(self):
        self.assertEqual(self.post("label", id="tapedeck_marker/a_erkannt", label="positiv").status_code, 200)
        self.assertEqual(len(self.listing()), 2)
        self.assertEqual(len(self.listing(all_=True)), 3)
        self.assertEqual(self.post("label", id="tapedeck_marker/a_erkannt", label="kaputt").status_code, 400)
        self.assertEqual(self.post("delete", id="tapedeck_marker/b_erkannt").status_code, 200)
        self.assertFalse((self.folder / "b_erkannt.wav").exists())

    def test_rejects_paths_outside_the_samples_folder(self):
        self.assertEqual(self.post("delete", id="../../recordings/x").status_code, 400)
        resp = self.client.get("/plugins/x32_recorder_voice_plugin/samples/audio/../../../settings.py")
        self.assertEqual(resp.status_code, 404)

    def test_audio_and_page(self):
        resp = self.client.get("/plugins/x32_recorder_voice_plugin/samples/audio/tapedeck_marker/a_erkannt")
        self.assertEqual((resp.status_code, resp["Content-Type"]), (200, "audio/wav"))
        resp.close()
        page = self.client.get("/plugins/x32_recorder_voice_plugin/samples/")
        self.assertContains(page, "Sprachbeispiele")
