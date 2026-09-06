from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QMessageBox as _QT_MSG_BOX

from .qt_compat import (
    MSGBOX_OK as _MSGBOX_OK,
    MSGBOX_ICON_WARNING as _MSGBOX_ICON_WARNING,
    MSGBOX_ICON_CRITICAL as _MSGBOX_ICON_CRITICAL,
    MSGBOX_ICON_INFORMATION as _MSGBOX_ICON_INFORMATION,
    QT_NON_MODAL as _QT_NON_MODAL,
    QT_WA_DELETE_ON_CLOSE as _QT_WA_DELETE_ON_CLOSE,
    QGIS_INFO,
    QGIS_WARNING,
    QGIS_CRITICAL,
)

MESSAGE_BAR_DURATION_SEC = 7


def _msgbox_attr(name):
    try:
        return getattr(_QT_MSG_BOX, name)
    except AttributeError:
        std = getattr(_QT_MSG_BOX, "StandardButton", None)
        if std is not None and hasattr(std, name):
            return getattr(std, name)
        raise


def notify_from_parent_chain(parent, title, text, level):
    """If any ancestor implements _notify(), show there and return True."""
    w = parent
    seen = set()
    while w is not None and id(w) not in seen:
        seen.add(id(w))
        fn = getattr(w, "_notify", None)
        if callable(fn):
            fn(title, text, level)
            return True
        w = w.parent()
    return False


def notify_fallback_dialog(parent, title, text, level, duration_sec=MESSAGE_BAR_DURATION_SEC):
    """Non-modal QMessageBox that closes after duration_sec (no iface / messageBar)."""
    dlg = _QT_MSG_BOX(parent)
    dlg.setWindowTitle(str(title))
    dlg.setText(str(text))
    if level == QGIS_WARNING:
        dlg.setIcon(_MSGBOX_ICON_WARNING)
    elif level == QGIS_CRITICAL:
        dlg.setIcon(_MSGBOX_ICON_CRITICAL)
    else:
        dlg.setIcon(_MSGBOX_ICON_INFORMATION)
    dlg.setStandardButtons(_MSGBOX_OK)
    dlg.setModal(False)
    dlg.setWindowModality(_QT_NON_MODAL)
    dlg.setAttribute(_QT_WA_DELETE_ON_CLOSE, True)
    dlg.show()
    QTimer.singleShot(max(1, int(duration_sec)) * 1000, dlg.close)


class LookaheadMessageBoxProxy:
    """See module docstring."""

    def __getattr__(self, name):
        return _msgbox_attr(name)

    def information(self, parent, title, text, *args, **kwargs):
        if parent is not None and notify_from_parent_chain(parent, title, text, QGIS_INFO):
            return kwargs.get("defaultButton", _MSGBOX_OK)
        return _QT_MSG_BOX.information(parent, title, text, *args, **kwargs)

    def warning(self, parent, title, text, *args, **kwargs):
        if parent is not None and notify_from_parent_chain(parent, title, text, QGIS_WARNING):
            return kwargs.get("defaultButton", _MSGBOX_OK)
        return _QT_MSG_BOX.warning(parent, title, text, *args, **kwargs)

    def critical(self, parent, title, text, *args, **kwargs):
        if parent is not None and notify_from_parent_chain(parent, title, text, QGIS_CRITICAL):
            return kwargs.get("defaultButton", _MSGBOX_OK)
        return _QT_MSG_BOX.critical(parent, title, text, *args, **kwargs)

    def question(self, parent, title, text, *args, **kwargs):
        return _QT_MSG_BOX.question(parent, title, text, *args, **kwargs)


QMessageBox = LookaheadMessageBoxProxy()
