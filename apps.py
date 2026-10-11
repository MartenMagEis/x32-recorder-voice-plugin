import threading

from django.apps import AppConfig

from recorder.plugin_support import should_start_background_work


class VoicePluginConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # Must match the folder name this repo gets cloned into by x32-recorder's plugin system
    # (derived from the GitHub URL) - "x32-recorder-voice-plugin" -> "x32_recorder_voice_plugin".
    name = "x32_recorder_voice_plugin"
    verbose_name = "Sprachsteuerung"

    def ready(self):
        if not should_start_background_work():
            return
        from .supervisor import run_supervisor

        threading.Thread(target=run_supervisor, daemon=True, name="voice-supervisor").start()
