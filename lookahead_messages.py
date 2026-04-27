from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QMessageBox as _QT_MSG_BOX

MESSAGE_BAR_DURATION_SEC = 4

try:
    _MSGBOX_OK = _QT_MSG_BOX.StandardButton.Ok
except AttributeError:
    _MSGBOX_OK = _QT_MSG_BOX.Ok

try:
    _MSGBOX_ICON_WARNING = _QT_MSG_BOX.Icon.Warning
    _MSGBOX_ICON_CRITICAL = _QT_MSG_BOX.Icon.Critical
    _MSGBOX_ICON_INFORMATION = _QT_MSG_BOX.Icon.Information
except AttributeError:
    _MSGBOX_ICON_WARNING = _QT_MSG_BOX.Warning
    _MSGBOX_ICON_CRITICAL = _QT_MSG_BOX.Critical
    _MSGBOX_ICON_INFORMATION = _QT_MSG_BOX.Information

try:
    _QT_NON_MODAL = Qt.WindowModality.NonModal
except AttributeError:
    _QT_NON_MODAL = Qt.NonModal

try:
    _QT_WA_DELETE_ON_CLOSE = Qt.WidgetAttribute.WA_DeleteOnClose
except AttributeError:
    _QT_WA_DELETE_ON_CLOSE = Qt.WA_DeleteOnClose


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
    if level == Qgis.Warning:
        dlg.setIcon(_MSGBOX_ICON_WARNING)
    elif level == Qgis.Critical:
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
        if parent is not None and notify_from_parent_chain(parent, title, text, Qgis.Info):
            return kwargs.get("defaultButton", _MSGBOX_OK)
        return _QT_MSG_BOX.information(parent, title, text, *args, **kwargs)

    def warning(self, parent, title, text, *args, **kwargs):
        if parent is not None and notify_from_parent_chain(parent, title, text, Qgis.Warning):
            return kwargs.get("defaultButton", _MSGBOX_OK)
        return _QT_MSG_BOX.warning(parent, title, text, *args, **kwargs)

    def critical(self, parent, title, text, *args, **kwargs):
        if parent is not None and notify_from_parent_chain(parent, title, text, Qgis.Critical):
            return kwargs.get("defaultButton", _MSGBOX_OK)
        return _QT_MSG_BOX.critical(parent, title, text, *args, **kwargs)

    def question(self, parent, title, text, *args, **kwargs):
        return _QT_MSG_BOX.question(parent, title, text, *args, **kwargs)


QMessageBox = LookaheadMessageBoxProxy()
