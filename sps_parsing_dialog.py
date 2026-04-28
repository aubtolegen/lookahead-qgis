from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QRect, QSize
from qgis.PyQt.QtGui import QFont, QPainter

from . import plugin_settings
from .lookahead_messages import QMessageBox

try:
    _QT_ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    _QT_ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight
except AttributeError:
    _QT_ALIGN_CENTER = Qt.AlignCenter
    _QT_ALIGN_RIGHT = Qt.AlignRight

try:
    _QPT_NO_WRAP = QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap
except AttributeError:
    _QPT_NO_WRAP = QtWidgets.QPlainTextEdit.NoWrap


def load_saved_sps_mapping():
    """Return last saved SPS column mapping dict or None."""
    m = plugin_settings.get_sps_parsing()
    return m if isinstance(m, dict) else None


def save_sps_mapping(mapping):
    plugin_settings.set_sps_parsing(mapping)


class _LineNumberArea(QtWidgets.QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint_event(event)


class _CodeEditor(QtWidgets.QPlainTextEdit):
    """Plain text editor with a left gutter showing line numbers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width(0)

    def line_number_area_width(self):
        digits = 1
        n = max(1, self.blockCount())
        while n >= 10:
            n //= 10
            digits += 1
        fm = self.fontMetrics()
        if hasattr(fm, "horizontalAdvance"):
            w = fm.horizontalAdvance("9")
        else:
            w = fm.width("9")
        return 8 + w * digits

    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(
                0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_number_area)
        # Match the editor palette instead of a hardcoded light gray.
        bg = self.palette().color(self.viewport().backgroundRole())
        painter.fillRect(event.rect(), bg)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(
            block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        height = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                fg = self.palette().color(self.foregroundRole())
                painter.setPen(fg.darker(130))
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 4,
                    height,
                    _QT_ALIGN_RIGHT,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1


class SpsParsingDialog(QtWidgets.QDialog):
    """Fixed-width SPS mapping dialog with line numbers and saved config."""

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SPS Parsing Helper")
        # ~30% narrower than original 980px; same height
        self.resize(686, 680)
        self._file_path = file_path
        self._lines = []
        self._result = {}

        root = QtWidgets.QVBoxLayout(self)

        info = QtWidgets.QLabel(
            "Line numbers are shown on the left. Highlight text in preview, then click a field button.\n"
            "For header skip: place cursor on first data row and click 'Set Header Lines'.\n"
            "Last successful mapping is restored automatically; change only if needed."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self.editor = _CodeEditor(self)
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(_QPT_NO_WRAP)
        font = QFont("Consolas", 9)
        self.editor.setFont(font)
        root.addWidget(self.editor, stretch=1)

        grid = QtWidgets.QGridLayout()
        root.addLayout(grid)

        self.labels = {}
        fields = [
            ("Set Header Lines", "header_lines"),
            ("Line", "col_line"),
            ("Shot Point (SP)", "col_sp"),
            ("Easting", "col_easting"),
            ("Northing", "col_northing"),
        ]
        for idx, (title, key) in enumerate(fields):
            btn = QtWidgets.QPushButton(title, self)
            lbl = QtWidgets.QLabel("-", self)
            lbl.setAlignment(_QT_ALIGN_CENTER)
            btn.clicked.connect(
                lambda _, k=key, label_widget=lbl: self._map_selection(
                    k, label_widget
                )
            )
            row = idx // 3
            col = (idx % 3) * 2
            grid.addWidget(btn, row, col)
            grid.addWidget(lbl, row, col + 1)
            self.labels[key] = lbl

        actions = QtWidgets.QHBoxLayout()
        btn_clear_saved = QtWidgets.QPushButton("Clear saved config", self)
        btn_clear_saved.setToolTip("Remove saved preplot mapping from disk")
        btn_clear_saved.clicked.connect(self._clear_saved_config)
        actions.addWidget(btn_clear_saved)
        actions.addStretch()
        cancel_btn = QtWidgets.QPushButton("Cancel", self)
        apply_btn = QtWidgets.QPushButton("Apply", self)
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self.accept)
        actions.addWidget(cancel_btn)
        actions.addWidget(apply_btn)
        root.addLayout(actions)

        self._load_file()
        self._apply_saved_mapping_to_ui()

    def _label_text_for_key(self, key):
        if key == "header_lines":
            v = self._result.get(key)
            return str(v) if v is not None else "-"
        if key not in self._result:
            return "-"
        col = self._result.get(key)
        w = self._result.get(f"{key}_width")
        if w is not None:
            return f"{col} (w:{w})"
        return str(col)

    def _apply_saved_mapping_to_ui(self):
        saved = load_saved_sps_mapping()
        if not saved:
            return
        required = ("header_lines", "col_line", "col_sp",
                    "col_easting", "col_northing")
        if not all(k in saved for k in required):
            return
        for k in required:
            self._result[k] = int(saved[k])
        width_keys = (
            "col_line_width",
            "col_sp_width",
            "col_easting_width",
            "col_northing_width",
        )
        for wk in width_keys:
            if wk in saved:
                try:
                    self._result[wk] = int(saved[wk])
                except (TypeError, ValueError):
                    pass
        for key, lbl in self.labels.items():
            lbl.setText(self._label_text_for_key(key))

    def _clear_saved_config(self):
        plugin_settings.clear_sps_parsing()
        self._result.clear()
        for lbl in self.labels.values():
            lbl.setText("-")
        QMessageBox.information(self, "Saved config",
                                "Saved preplot mapping was cleared.")

    def _load_file(self):
        try:
            with open(self._file_path, "r", encoding="latin-1", errors="replace") as f:
                self._lines = f.readlines()[:1200]
            self.editor.setPlainText("".join(self._lines))
        except Exception as e:
            QMessageBox.critical(self, "Read Error",
                                 f"Could not read file:\n{e}")

    def _map_selection(self, key, label):
        cursor = self.editor.textCursor()

        if key == "header_lines":
            line_idx = cursor.blockNumber()
            self._result[key] = max(0, int(line_idx))
            label.setText(str(self._result[key]))
            return

        if not cursor.hasSelection():
            QMessageBox.warning(self, "Selection", "Select text first.")
            return

        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        block = self.editor.document().findBlock(start)
        col_start = start - block.position()
        width = max(1, end - start)
        self._result[key] = int(col_start)
        self._result[f"{key}_width"] = int(width)
        label.setText(f"{col_start} (w:{width})")

    def get_mapping(self):
        return dict(self._result)

    def accept(self):
        required = ("header_lines", "col_line", "col_sp",
                    "col_easting", "col_northing")
        missing = [k for k in required if k not in self._result]
        if missing:
            QMessageBox.warning(
                self,
                "Missing Fields",
                "Please set all required fields:\n- " + "\n- ".join(missing),
            )
            return
        to_save = {k: self._result[k] for k in required}
        for wk in (
            "col_line_width",
            "col_sp_width",
            "col_easting_width",
            "col_northing_width",
        ):
            if wk in self._result:
                to_save[wk] = self._result[wk]
        save_sps_mapping(to_save)
        super().accept()
