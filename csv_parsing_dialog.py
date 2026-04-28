import os

from qgis.PyQt import QtWidgets

from . import plugin_settings
from .lookahead_messages import QMessageBox


def load_saved_csv_mapping():
    mapping = plugin_settings.get_csv_parsing()
    return mapping if isinstance(mapping, dict) else None


def save_csv_mapping(mapping):
    plugin_settings.set_csv_parsing(mapping)


class CsvParsingDialog(QtWidgets.QDialog):
    """Simple dialog for importing line/sequence mapping from CSV."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CSV Parsing Helper")
        self.resize(560, 190)

        root = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel(
            "Select CSV file and set columns for Sequence and Line.\n"
            "Header lines default is 0 for files without a header."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        file_row = QtWidgets.QHBoxLayout()
        file_row.addWidget(QtWidgets.QLabel("CSV file:"))
        self.file_edit = QtWidgets.QLineEdit(self)
        self.file_edit.setPlaceholderText("No file selected")
        file_row.addWidget(self.file_edit, 1)
        browse_btn = QtWidgets.QPushButton("Browse...", self)
        browse_btn.clicked.connect(self._browse_file)
        file_row.addWidget(browse_btn)
        root.addLayout(file_row)

        grid = QtWidgets.QGridLayout()
        root.addLayout(grid)
        grid.addWidget(QtWidgets.QLabel("Sequence column (0-based):"), 0, 0)
        self.seq_col_spin = QtWidgets.QSpinBox(self)
        self.seq_col_spin.setRange(0, 200)
        self.seq_col_spin.setValue(0)
        grid.addWidget(self.seq_col_spin, 0, 1)

        grid.addWidget(QtWidgets.QLabel("Line column (0-based):"), 1, 0)
        self.line_col_spin = QtWidgets.QSpinBox(self)
        self.line_col_spin.setRange(0, 200)
        self.line_col_spin.setValue(1)
        grid.addWidget(self.line_col_spin, 1, 1)

        grid.addWidget(QtWidgets.QLabel("Header lines to skip:"), 2, 0)
        self.header_spin = QtWidgets.QSpinBox(self)
        self.header_spin.setRange(0, 5000)
        self.header_spin.setValue(0)
        grid.addWidget(self.header_spin, 2, 1)

        actions = QtWidgets.QHBoxLayout()
        actions.addStretch()
        cancel_btn = QtWidgets.QPushButton("Cancel", self)
        apply_btn = QtWidgets.QPushButton("Apply", self)
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self.accept)
        actions.addWidget(cancel_btn)
        actions.addWidget(apply_btn)
        root.addLayout(actions)

        self._load_saved()

    def _load_saved(self):
        saved = load_saved_csv_mapping()
        if not saved:
            return
        self.file_edit.setText(str(saved.get("file_path", "") or ""))
        for key, spin in (
            ("col_sequence", self.seq_col_spin),
            ("col_line", self.line_col_spin),
            ("header_lines", self.header_spin),
        ):
            try:
                spin.setValue(int(saved.get(key, spin.value())))
            except (TypeError, ValueError):
                pass

    def _browse_file(self):
        start_dir = ""
        current = self.file_edit.text().strip()
        if current:
            start_dir = current if os.path.isdir(
                current) else os.path.dirname(current)
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select CSV file",
            start_dir,
            "CSV Files (*.csv *.txt);;All Files (*)",
        )
        if file_path:
            self.file_edit.setText(file_path)

    def get_mapping(self):
        return {
            "file_path": self.file_edit.text().strip(),
            "col_sequence": int(self.seq_col_spin.value()),
            "col_line": int(self.line_col_spin.value()),
            "header_lines": int(self.header_spin.value()),
        }

    def accept(self):
        mapping = self.get_mapping()
        if not mapping.get("file_path"):
            QMessageBox.warning(self, "CSV Import",
                                "Please choose a CSV file.")
            return
        save_csv_mapping(mapping)
        super().accept()
