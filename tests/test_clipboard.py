"""Tests for copying from a worker thread, using Qt's offscreen platform."""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtGui import QGuiApplication  # noqa: E402

from phone_webcam.clipboard import Clipboard  # noqa: E402


def test_copy_from_a_worker_thread_reaches_the_clipboard():
    app = QGuiApplication.instance() or QGuiApplication([])
    clipboard = Clipboard()
    worker = threading.Thread(
        target=clipboard.copy, args=("sudo dnf install x",)
    )
    worker.start()
    worker.join()
    app.processEvents()
    assert QGuiApplication.clipboard().text() == "sudo dnf install x"
