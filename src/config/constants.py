"""Shared project defaults used across core and UI."""

APP_NAME: str = "Aphelion"
APP_ORGANIZATION: str = "Aphelion"
APP_VERSION: str = "0.1.0"

DEFAULT_FPS: int = 30
DEFAULT_WIDTH: int = 1920
DEFAULT_HEIGHT: int = 1080
DEFAULT_DURATION: float = 10.0

# Logging
DEFAULT_LOG_LEVEL: str = "INFO"
LOG_DIR_NAME: str = "logs"
LOG_FILE_NAME: str = "aphelion.log"
LOG_MAX_BYTES: int = 2_000_000
LOG_BACKUP_COUNT: int = 5

# Frame cache budget (megabytes) — proxy frames make this go much further.
# Frames are float32 (4 bytes/channel) rather than uint8 (1 byte/channel),
# so the budget is 4x a byte-for-byte uint8 equivalent to retain a similar
# number of cached proxy frames after the float pipeline migration.
FRAME_CACHE_MAX_MB: int = 2048
FRAME_CACHE_MIN_MB: int = 256
FRAME_CACHE_MAX_ALLOWED_MB: int = 16384

# Default Viewer preview width (decode-time downscale)
DEFAULT_PREVIEW_MAX_WIDTH: int = 960

# Performance preferences: bounds for user-configurable playback knobs.
# Raw-decode LRU per Video Input node — avoids re-decoding/re-seeking when
# scrubbing back over recently visited source frames or re-evaluating a
# graph after a downstream (non-source) property change invalidates the
# node-output cache but not the underlying source pixels.
DEFAULT_DECODE_CACHE_FRAMES: int = 16
MAX_DECODE_CACHE_FRAMES: int = 128

# Global ceiling on requested prefetch-ahead frames during playback,
# applied on top of the per-Viewer "Prefetch" property.
DEFAULT_MAX_PREFETCH_FRAMES: int = 4
MAX_MAX_PREFETCH_FRAMES: int = 16

# Forced decode width used only while actively playing, when the playback
# proxy override is enabled — independent of the per-Viewer proxy width so
# scrubbing/paused review can stay at full preview quality.
DEFAULT_PLAYBACK_PROXY_WIDTH: int = 640

# Graph layout: horizontal gap when inserting a node into a chain
NODE_CHAIN_GAP_PX: float = 220.0
# Auto-organize graph layout
GRAPH_LAYOUT_ORIGIN_X: float = 80.0
GRAPH_LAYOUT_ORIGIN_Y: float = 120.0
GRAPH_LAYOUT_COLUMN_GAP_PX: float = 280.0
GRAPH_LAYOUT_ROW_GAP_PX: float = 48.0
GRAPH_LAYOUT_COMPONENT_GAP_PX: float = 96.0
GRAPH_LAYOUT_GRID_PX: int = 28
# Offset applied on each successive paste at the same location
PASTE_OFFSET_PX: float = 40.0

# Autosave cadence for projects that already have a ``.aph`` path
AUTOSAVE_INTERVAL_MS: int = 30_000
