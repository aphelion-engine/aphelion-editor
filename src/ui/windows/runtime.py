"""Process-lifetime owner for the Qt app and editor session."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from config.constants import APP_NAME, APP_ORGANIZATION, APP_VERSION
from core.boot import BootMode, BootRequest, RecentProjectsStore
from ui.windows.session import ApplicationSession
from utils.logging_setup import get_logger
from utils.paths import resource_path

_LOG = get_logger("runtime")
APP_ICON_PATH: Path = resource_path("icon.ico")


class AphelionRuntime:
    """Owns ``QApplication`` + ``ApplicationSession`` for the process lifetime.

    Keeping strong Python references here prevents the launcher/bootloader
    from being garbage-collected (which looks like the window vanishing).
    """

    def __init__(self) -> None:
        self._app: QApplication | None = None
        self._session: ApplicationSession | None = None

    @property
    def app(self) -> QApplication:
        """Return the live Qt application.

        Raises:
            RuntimeError: When called before ``run``.
        """
        if self._app is None:
            raise RuntimeError("QApplication has not been created")
        return self._app

    @property
    def session(self) -> ApplicationSession:
        """Return the live application session.

        Raises:
            RuntimeError: When called before ``run``.
        """
        if self._session is None:
            raise RuntimeError("ApplicationSession has not been created")
        return self._session

    def run(self, argv: list[str] | None = None) -> int:
        """Create the app, start the session, and enter the event loop.

        Parameters:
            argv: Process arguments; defaults to ``sys.argv``.

        Returns:
            Process exit code from ``QApplication.exec``.
        """
        args, initial_request = parse_boot_args(list(sys.argv if argv is None else argv))
        self._app = build_application(args)
        # Parent the session to QApplication so Qt and Python both retain it.
        self._session = ApplicationSession(
            self._app,
            recent=RecentProjectsStore(),
            parent=self._app,
        )
        _LOG.info("Runtime ready — starting session")
        self._session.start(initial_request=initial_request)
        _LOG.info("Entering Qt event loop")
        code = int(self._app.exec())
        _LOG.info("Event loop exited with code %s", code)
        return code


def build_application(argv: list[str]) -> QApplication:
    """Construct the shared ``QApplication`` with Aphelion identity."""
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationVersion(APP_VERSION)
    # Window handoffs briefly leave zero top-level windows.
    app.setQuitOnLastWindowClosed(False)
    apply_application_icon(app)
    return app


def apply_application_icon(app: QApplication) -> None:
    """Set the process icon when the bundled asset exists."""
    if not APP_ICON_PATH.is_file():
        _LOG.warning("Application icon missing: %s", APP_ICON_PATH)
        return
    app.setWindowIcon(QIcon(str(APP_ICON_PATH.resolve())))


def parse_boot_args(argv: list[str]) -> tuple[list[str], BootRequest | None]:
    """Strip Aphelion flags from argv and return an optional boot request."""
    args = list(argv)
    initial_request: BootRequest | None = None
    if "--new" in args:
        args.remove("--new")
        initial_request = BootRequest(mode=BootMode.NEW)
    return args, initial_request
