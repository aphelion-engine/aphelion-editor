"""Regression tests for viewport results across backward timeline jumps."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication

from core.nodes import ViewerNode
from core.project import Project
from ui.widgets.viewport import ViewportWidget


def _application() -> QApplication:
    """Return the process QApplication required by QWidget tests."""
    current: object | None = QApplication.instance()
    if isinstance(current, QApplication):
        return current
    return QApplication([])


class ViewportResultPolicyTests(unittest.TestCase):
    """Exercise result ordering without a live media decoder."""

    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        """Keep one QApplication alive for the test class."""
        cls.app = _application()

    def setUp(self) -> None:
        """Create an isolated project and stop its background worker."""
        self.project: Project = Project(name="viewport-regression")
        self.viewer_id: str = self.project.add_node(ViewerNode(), "viewer")
        self.viewport: ViewportWidget = ViewportWidget(self.project)
        self.viewport._worker.stop()

    def tearDown(self) -> None:
        """Release the viewport after each test."""
        self.viewport.close()

    def test_backward_seek_replaces_the_displayed_frame(self) -> None:
        """A lower requested frame must not be rejected as stale."""
        self._present(frame_number=100, pixel_value=100)
        self._present(frame_number=20, pixel_value=20)

    def test_loop_wrap_accepts_zero_and_rejects_old_future_result(self) -> None:
        """Looping to zero must ignore a late result from the prior cycle."""
        self._present(frame_number=200, pixel_value=200)
        self._present(frame_number=0, pixel_value=0)
        future: np.ndarray = np.full((8, 8, 3), 1.0, dtype=np.float32)
        self.viewport._on_frame_ready(self.viewer_id, 200, future)
        self.assertEqual(self._displayed_pixel(), 0)

    def _present(self, *, frame_number: int, pixel_value: int) -> None:
        """Deliver one exact requested result to the viewport.

        ``pixel_value`` is a 0-255 display value; the pipeline contract is
        float32 in ``[0, 1]``, so the fixture is built in that domain and the
        assertion compares against the quantized display value.
        """
        self.project.set_frame(frame_number)
        self.viewport._pending_request = (self.viewer_id, frame_number)
        frame: np.ndarray = np.full(
            (8, 8, 3), pixel_value / 255.0, dtype=np.float32
        )
        self.viewport._on_frame_ready(self.viewer_id, frame_number, frame)
        self.assertEqual(self._displayed_pixel(), pixel_value)

    def _displayed_pixel(self) -> int:
        """Return the first displayed channel value as a 0-255 uint8 level."""
        frame: np.ndarray | None = self.viewport._image_buffer
        self.assertIsNotNone(frame)
        assert frame is not None
        return int(frame[0, 0, 0])


if __name__ == "__main__":
    unittest.main()
