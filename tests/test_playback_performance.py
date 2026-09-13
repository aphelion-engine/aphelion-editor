"""Playback responsiveness and memory-budget regressions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel
from core.audio import AudioData, FrameWithAudio
from core.cache import FrameCache, _estimate_bytes
from core.preferences.models import PerformanceSettings, AppPreferences
from core.project import Project
from render.frame_evaluator import FrameEvaluationWorker
from ui.widgets.viewport import ViewportWidget


class PlaybackPerformanceTests(unittest.TestCase):
    def test_busy_playback_emits_completed_frames_but_scrubbing_skips_them(self):
        for playing, expected in ((True,[0,1]), (False,[1])):
            project = SimpleNamespace(fps=30)
            worker = FrameEvaluationWorker(project)
            worker.set_playing(playing)
            worker.set_max_prefetch(0)
            def evaluate(node, frame):
                if frame == 0:
                    worker.request_frame(node,1)
                return np.zeros((2,2,3),np.float32)
            project.evaluate_node = evaluate
            emitted = []
            def ready(node, frame, result):
                emitted.append(frame)
                if frame == 1:
                    worker._running = False
            worker.frame_ready.connect(ready, Qt.ConnectionType.DirectConnection)
            worker.request_frame("viewer",0)
            worker.run()
            self.assertEqual(emitted,expected)

    def test_audio_payloads_obey_cache_budget(self):
        payload = FrameWithAudio(np.zeros((256,256,3),np.float32),
            AudioData(np.zeros((1600,2),np.float32),48000))
        self.assertEqual(_estimate_bytes(payload),payload.frame.nbytes+payload.audio.samples.nbytes)
        cache = FrameCache(1)
        cache.set(("v",0,"frame"),payload)
        cache.set(("v",1,"frame"),payload)
        self.assertEqual(cache.entry_count,1)
        self.assertIsNone(cache.get(("v",0,"frame")))
        self.assertLessEqual(cache.size_mb,1)

    def test_cached_preview_does_not_wait_for_renderer(self):
        project = Project("busy")
        locked, release = threading.Event(), threading.Event()
        def hold():
            with project._eval_lock:
                locked.set()
                release.wait(5)
        thread = threading.Thread(target=hold)
        thread.start()
        self.assertTrue(locked.wait(2))
        try:
            self.assertIsNone(project.cached_preview_frame("viewer",0))
        finally:
            release.set()
            thread.join()

    def test_audio_lookahead_never_evaluates_video_on_ui_thread(self):
        audio = AudioData(np.zeros(10,np.float32),48000)
        project = SimpleNamespace(active_viewer="v", cached_preview_frame=Mock(return_value=None),
                                  evaluate_node=Mock(side_effect=AssertionError("UI evaluation")))
        viewport = SimpleNamespace(project=project,_queued_audio_until_frame=None,
                                   _audio_prefetch_frames=4,_audio_engine=Mock())
        ViewportWidget._feed_smoother_preview_audio(viewport,0,audio)
        self.assertEqual(viewport._queued_audio_until_frame,1)
        project.evaluate_node.assert_not_called()
        viewport._audio_engine.feed_audio.assert_called_once_with(audio)

    def test_adaptive_preview_reduces_resolution_and_restores_on_pause(self):
        project = Project("adaptive")
        viewport = SimpleNamespace(project=project,_playback_active=True,
            _performance=PerformanceSettings(),_adaptive_width=None,_last_adaptation=0,
            _worker=SimpleNamespace(last_render_seconds=0.2))
        viewport._sync_playback_proxy_override = lambda: ViewportWidget._sync_playback_proxy_override(viewport)
        before = project.get_preview_settings().max_width
        ViewportWidget._adapt_preview(viewport)
        self.assertLess(project.get_preview_settings().max_width,before)
        viewport._playback_active = False
        viewport._sync_playback_proxy_override()
        self.assertEqual(project.get_preview_settings().max_width,before)

    def test_adaptive_preference_round_trip(self):
        for enabled in (True,False):
            settings = PerformanceSettings(adaptive_preview_enabled=enabled)
            self.assertEqual(PerformanceSettings.from_dict(settings.to_dict()),settings)


class PerformanceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preferences_preset_and_tooltips(self):
        from ui.dialogs.preferences_dialog import PreferencesDialog
        from config.keybinds import KeybindStore
        dialog = PreferencesDialog(AppPreferences(),KeybindStore())
        try:
            dialog._use_low_lag_preset()
            self.assertEqual(dialog._proxy_width.value(),640)
            self.assertTrue(dialog._adaptive_preview.isChecked())
            self.assertTrue(dialog._proxy_override_enabled.isChecked())
            self.assertEqual(dialog._max_prefetch.value(),1)
            for name in ("_frame_cache_mb","_proxy_width","_adaptive_preview","_max_prefetch"):
                self.assertTrue(getattr(dialog,name).toolTip())
        finally:
            dialog.close()

    def test_project_setting_labels_have_help(self):
        from ui.dialogs.project_settings_dialog import ProjectSettingsDialog
        dialog = ProjectSettingsDialog(Project("help"))
        labels = {label.text():label for label in dialog.findChildren(QLabel)}
        self.assertIn("processing",labels["Width"].toolTip())
        dialog.close()
