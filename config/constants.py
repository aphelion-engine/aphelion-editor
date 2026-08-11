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

# Frame cache budget (megabytes) — proxy frames make this go much further
FRAME_CACHE_MAX_MB: int = 512

# Default Viewer preview width (decode-time downscale)
DEFAULT_PREVIEW_MAX_WIDTH: int = 960

# Graph layout: horizontal gap when inserting a node into a chain
NODE_CHAIN_GAP_PX: float = 220.0
# Offset applied on each successive paste at the same location
PASTE_OFFSET_PX: float = 40.0

# Autosave cadence for projects that already have a ``.aph`` path
AUTOSAVE_INTERVAL_MS: int = 30_000
