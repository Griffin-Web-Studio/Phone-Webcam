"""Copy text to the system clipboard through Qt, from any thread.

The web engine's own copy does nothing on some Wayland setups, and the page
cannot use the async clipboard API, because pywebview's Qt backend throws on
the permission request it raises.
"""

from qtpy.QtCore import QObject, Signal, Slot
from qtpy.QtGui import QGuiApplication


class Clipboard(QObject):
    """Create on the GUI thread. `copy` is then safe from any thread."""

    _requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        # The slot lives on this object's thread, so a signal emitted from a
        # worker thread is queued and runs on the GUI thread.
        self._requested.connect(self._set)

    def copy(self, text: str) -> None:
        self._requested.emit(text)

    @Slot(str)
    def _set(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
