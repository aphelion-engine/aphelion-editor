"""Shared type aliases exposed to plugin authors.

These aliases describe the shapes plugins exchange with the host
application without requiring plugin authors to import anything from
``core``.
"""

from __future__ import annotations

import numpy as np

from core.nodes.base import ColorRgb as ColorRgb

# A plugin frame buffer: shape ``(height, width, 3)``, dtype ``float32``,
# nominal value range ``[0.0, 1.0]``. Alpha is not carried on this buffer.
Frame = np.ndarray
