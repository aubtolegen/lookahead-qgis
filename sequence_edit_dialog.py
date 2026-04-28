import copy
import math
import os
import threading
import zipfile
from datetime import datetime, timedelta
import logging  # Added for logging
from xml.sax.saxutils import escape

from qgis.core import (
    QgsDistanceArea,
    QgsFeature,
    QgsGeometry,
    QgsPalLayerSettings,
    QgsPoint,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsRuleBasedLabeling,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt import QtCore, QtWidgets
from qgis.gui import (
    QgsMapCanvas,
    QgsMapTool,
    QgsRubberBand,
    QgsVertexMarker,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                                 QTableWidget, QTableWidgetItem, QAbstractItemView,
                                 QLabel, QHeaderView, QComboBox,
                                 QSizePolicy, QApplication, QFileDialog, QDoubleSpinBox,
                                 QSlider, QMenu, QCheckBox, QShortcut)

from .finalize_map_canvas_host import FinalizeMapCanvasHost
from .lookahead_messages import QMessageBox
from .lookahead_sim_speeds import shooting_speed_knots, shooting_speed_mps
from qgis.PyQt.QtGui import QColor, QFont, QKeySequence

# --- Logger ---
log = logging.getLogger("lookahead_planner")

try:
    _QT_WAIT_CURSOR = Qt.CursorShape.WaitCursor
except AttributeError:
    _QT_WAIT_CURSOR = Qt.WaitCursor

try:
    _QT_ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight
    _QT_ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft
    _QT_ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    _QT_ALIGN_VCENTER = Qt.AlignmentFlag.AlignVCenter
except AttributeError:
    _QT_ALIGN_RIGHT = Qt.AlignRight
    _QT_ALIGN_LEFT = Qt.AlignLeft
    _QT_ALIGN_CENTER = Qt.AlignCenter
    _QT_ALIGN_VCENTER = Qt.AlignVCenter

try:
    _QT_HEADER_RESIZE_TO_CONTENTS = QHeaderView.ResizeMode.ResizeToContents
    _QT_HEADER_STRETCH = QHeaderView.ResizeMode.Stretch
except AttributeError:
    _QT_HEADER_RESIZE_TO_CONTENTS = QHeaderView.ResizeToContents
    _QT_HEADER_STRETCH = QHeaderView.Stretch

try:
    _QSP_POLICY = QSizePolicy.Policy
    _QSP_EXPANDING = _QSP_POLICY.Expanding
    _QSP_PREFERRED = _QSP_POLICY.Preferred
    _QSP_FIXED = _QSP_POLICY.Fixed
except AttributeError:
    _QSP_EXPANDING = QSizePolicy.Expanding
    _QSP_PREFERRED = QSizePolicy.Preferred
    _QSP_FIXED = QSizePolicy.Fixed

try:
    _QT_MOUSE_LEFT = Qt.MouseButton.LeftButton
    _QT_MOUSE_RIGHT = Qt.MouseButton.RightButton
except AttributeError:
    _QT_MOUSE_LEFT = Qt.LeftButton
    _QT_MOUSE_RIGHT = Qt.RightButton

try:
    _QT_WINDOW_MAXIMIZE_BUTTON_HINT = Qt.WindowType.WindowMaximizeButtonHint
except AttributeError:
    _QT_WINDOW_MAXIMIZE_BUTTON_HINT = Qt.WindowMaximizeButtonHint

try:
    _QT_ITEM_IS_EDITABLE = Qt.ItemFlag.ItemIsEditable
except AttributeError:
    _QT_ITEM_IS_EDITABLE = Qt.ItemIsEditable

try:
    _QT_COLOR_WHITE = Qt.GlobalColor.white
except AttributeError:
    _QT_COLOR_WHITE = Qt.white

try:
    _QT_NO_CONTEXT_MENU = Qt.ContextMenuPolicy.NoContextMenu
except AttributeError:
    _QT_NO_CONTEXT_MENU = Qt.NoContextMenu

try:
    _QT_HORIZONTAL = Qt.Orientation.Horizontal
except AttributeError:
    _QT_HORIZONTAL = Qt.Horizontal

try:
    _QT_KEY_ESCAPE = Qt.Key.Key_Escape
except AttributeError:
    _QT_KEY_ESCAPE = Qt.Key_Escape

try:
    _QT_WIDGET_WITH_CHILDREN_SHORTCUT = Qt.ShortcutContext.WidgetWithChildrenShortcut
except AttributeError:
    _QT_WIDGET_WITH_CHILDREN_SHORTCUT = Qt.WidgetWithChildrenShortcut

try:
    _QAIV_SELECT_ROWS = QAbstractItemView.SelectionBehavior.SelectRows
    _QAIV_SINGLE_SELECTION = QAbstractItemView.SelectionMode.SingleSelection
    _QAIV_NO_EDIT_TRIGGERS = QAbstractItemView.EditTrigger.NoEditTriggers
except AttributeError:
    _QAIV_SELECT_ROWS = QAbstractItemView.SelectRows
    _QAIV_SINGLE_SELECTION = QAbstractItemView.SingleSelection
    _QAIV_NO_EDIT_TRIGGERS = QAbstractItemView.NoEditTriggers

try:
    _QSLIDER_TICKS_BELOW = QSlider.TickPosition.TicksBelow
except AttributeError:
    _QSLIDER_TICKS_BELOW = QSlider.TicksBelow

try:
    _QT_TOOLBTN_INSTANT_POPUP = QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
except AttributeError:
    _QT_TOOLBTN_INSTANT_POPUP = QtWidgets.QToolButton.InstantPopup


def _pop_wait_cursor_if_busy():
    if QApplication.overrideCursor() is not None:
        QApplication.restoreOverrideCursor()


def _xlsx_column_letter(col_index):
    """0-based column index to Excel column letters (0 -> A, 26 -> AA)."""
    n = col_index + 1
    letters = []
    while n:
        n, r = divmod(n - 1, 26)
        letters.append(chr(65 + r))
    return "".join(reversed(letters))


def _safe_xlsx_sheet_name(name):
    """Excel sheet names: max 31 chars; cannot contain []:*?/\\"""
    for c in "[]:*?/\\":
        name = name.replace(c, "_")
    name = name.strip() or "Sheet1"
    return name[:31]


def write_xlsx_stdlib(file_path, sheet_name, headers, data_rows):
    """
    Minimal .xlsx (Office Open XML) using only the standard library.
    Works in QGIS's bundled Python without pip-installed xlsxwriter.
    """
    sheet_name = _safe_xlsx_sheet_name(sheet_name)
    sn_esc = escape(sheet_name)

    def row_xml(row_idx_1based, values):
        cells = []
        for col_idx, val in enumerate(values):
            ref = f"{_xlsx_column_letter(col_idx)}{row_idx_1based}"
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cells.append(f'<c r="{ref}" t="n"><v>{val}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(val))}</t></is></c>'
                )
        return f'<row r="{row_idx_1based}">{"".join(cells)}</row>'

    rows_xml = [row_xml(1, headers)]
    for i, row in enumerate(data_rows, start=2):
        rows_xml.append(row_xml(i, row))

    sheet_body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheetData>"
        f"{''.join(rows_xml)}</sheetData></worksheet>"
    )

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""
    rels_root = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        f'<sheet name="{sn_esc}" sheetId="1" r:id="rId1"/>'
        "</sheets></workbook>"
    )
    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""

    with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels_root)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_body)


# --- Define constants for column indices ---
COL_SEQ_NUM = 0  # New
COL_LINE_NUM = 1
COL_START_SP = 2
COL_END_SP = 3
COL_START_TIME = 4
COL_END_TIME = 5
COL_DURATION = 6
COL_SPEED = 7
COL_DIRECTION = 8
COL_LINE_CHANGE = 9

# Single source of truth: table column order = clipboard = XLSX header row.
SEQUENCE_EDITOR_TABLE_HEADERS = (
    "Seq",
    "Line",
    "Start SP",
    "End SP",
    "Start Time",
    "End Time",
    "Duration",
    "Speed (kn)",
    "Direction",
    "Line Change",
)


def _sequence_editor_header_list():
    return list(SEQUENCE_EDITOR_TABLE_HEADERS)


def _sequence_editor_row_strings(table_widget, row_idx):
    """Cell texts for one row in ``SEQUENCE_EDITOR_TABLE_HEADERS`` order (same as on-screen table)."""
    n = len(SEQUENCE_EDITOR_TABLE_HEADERS)
    ncol = table_widget.columnCount()
    out = []
    for col_idx in range(n):
        if col_idx >= ncol:
            out.append("")
            continue
        widget = table_widget.cellWidget(row_idx, col_idx)
        if isinstance(widget, QComboBox):
            out.append(widget.currentText())
        else:
            item = table_widget.item(row_idx, col_idx)
            out.append(item.text() if item else "")
    return out


def _xlsx_coerce_row_for_export(row_strings):
    """
    Build one XLSX row: same text as the table where kept as string, but Excel numbers for:
    columns 0–3 (Seq, Line, Start SP, End SP) when they parse; column COL_SPEED (knots) as float
    when it parses; otherwise keep the displayed string (e.g. N/A).
    """
    out = []
    for col_idx, val_str in enumerate(row_strings):
        if col_idx < 4 and val_str:
            try:
                out.append(float(val_str) if "." in val_str else int(val_str))
            except ValueError:
                out.append(val_str)
        elif col_idx == COL_SPEED and val_str and val_str.strip().upper() != "N/A":
            try:
                out.append(float(val_str))
            except ValueError:
                out.append(val_str)
        else:
            out.append(val_str)
    return out


# --- ENHANCED custom_deepcopy (using copy constructor for QgsGeometry) ---
def custom_deepcopy(obj, memo=None):
    """Custom deepcopy function that handles QgsPointXY, QgsPoint, and QgsGeometry objects."""
    if memo is None:
        memo = {}
    obj_id = id(obj)
    if obj_id in memo:
        return memo[obj_id]

    if isinstance(obj, QgsGeometry):
        new_geom = QgsGeometry(obj)  # Use copy constructor
        memo[obj_id] = new_geom
        return new_geom
    elif isinstance(obj, QgsPointXY):
        new_point = QgsPointXY(obj.x(), obj.y())
        memo[obj_id] = new_point
        return new_point
    elif isinstance(obj, QgsPoint):
        new_point = QgsPoint(obj.x(), obj.y())
        memo[obj_id] = new_point
        return new_point
    elif isinstance(obj, dict):
        new_dict = {}
        memo[obj_id] = new_dict
        for k, v in obj.items():
            new_dict[custom_deepcopy(k, memo)] = custom_deepcopy(v, memo)
        return new_dict
    elif isinstance(obj, list):
        new_list = []
        memo[obj_id] = new_list
        for item in obj:
            new_list.append(custom_deepcopy(item, memo))
        return new_list
    elif isinstance(obj, tuple):
        new_tuple_elements = [custom_deepcopy(item, memo) for item in obj]
        new_tuple = tuple(new_tuple_elements)
        memo[obj_id] = new_tuple  # Cache the tuple itself
        return new_tuple
    else:
        # Use standard deepcopy for other types, but be careful
        try:
            new_obj = copy.deepcopy(obj, memo)
            memo[obj_id] = new_obj
            return new_obj
        except (TypeError, NotImplementedError):
            # If deepcopy fails, return the object itself (shallow copy for this element)
            # This might happen for complex QGIS objects or external library objects
            memo[obj_id] = obj
            return obj
# --- END ENHANCED custom_deepcopy ---


def _vector_layer_alive(lyr):
    """True if lyr is a valid QgsVectorLayer C++ wrapper (not deleted after project refresh)."""
    if lyr is None:
        return False
    try:
        return isinstance(lyr, QgsVectorLayer) and lyr.isValid()
    except RuntimeError:
        return False


def _parent_canvas_color_or_default(widget, default_color):
    """Best-effort parent iface canvas color for embedded map canvases."""
    try:
        parent = widget.parent() if widget is not None else None
        iface = getattr(parent, "iface", None)
        if iface is None:
            return default_color
        canvas = iface.mapCanvas()
        if canvas is None:
            return default_color
        return canvas.canvasColor()
    except Exception:
        return default_color


class TurnMapTool(QgsMapTool):
    """Map tool for selecting turns and dragging the blue detour circle."""

    def __init__(self, canvas, click_callback, press_callback=None, move_callback=None, release_callback=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.click_callback = click_callback
        self.press_callback = press_callback
        self.move_callback = move_callback
        self.release_callback = release_callback
        self._press_pos = None
        self._moved = False

    def canvasPressEvent(self, e):
        pt = self.toMapCoordinates(e.pos())
        self._press_pos = pt
        self._moved = False
        if callable(self.press_callback):
            self.press_callback(pt)

    def canvasMoveEvent(self, e):
        pt = self.toMapCoordinates(e.pos())
        if self._press_pos is not None:
            if math.hypot(pt.x() - self._press_pos.x(), pt.y() - self._press_pos.y()) > 1e-6:
                self._moved = True
        if callable(self.move_callback):
            self.move_callback(pt)

    def canvasReleaseEvent(self, e):
        pt = self.toMapCoordinates(e.pos())
        if callable(self.release_callback):
            self.release_callback(pt)
        if callable(self.click_callback) and not self._moved:
            self.click_callback(pt)
        self._press_pos = None
        self._moved = False


class AcquisitionCalendarMapTool(QgsMapTool):
    """Map tool for hover and click inspection on the acquisition timeline."""

    def __init__(
        self,
        canvas,
        hover_callback=None,
        click_callback=None,
        ruler_press_callback=None,
        ruler_move_callback=None,
        ruler_release_callback=None,
    ):
        super().__init__(canvas)
        self.canvas = canvas
        self.hover_callback = hover_callback
        self.click_callback = click_callback
        self.ruler_press_callback = ruler_press_callback
        self.ruler_move_callback = ruler_move_callback
        self.ruler_release_callback = ruler_release_callback
        self._ruler_drag = False

    def canvasMoveEvent(self, e):
        e.accept()
        pt = self.toMapCoordinates(e.pos())
        if self._ruler_drag and callable(self.ruler_move_callback):
            self.ruler_move_callback(pt)
            return
        if callable(self.hover_callback):
            self.hover_callback(pt)

    def canvasPressEvent(self, e):
        e.accept()
        pt = self.toMapCoordinates(e.pos())
        if e.button() == _QT_MOUSE_RIGHT:
            self._ruler_drag = True
            if callable(self.ruler_press_callback):
                self.ruler_press_callback(pt)
            return
        if e.button() == _QT_MOUSE_LEFT and callable(self.click_callback):
            self.click_callback(pt)

    def canvasReleaseEvent(self, e):
        e.accept()
        if e.button() == _QT_MOUSE_RIGHT:
            self._ruler_drag = False
            if callable(self.ruler_release_callback):
                self.ruler_release_callback(self.toMapCoordinates(e.pos()))


class SequenceEditDialog(QDialog):
    """ Dialog for viewing, editing sequence, directions, and timing. """

    def __init__(self, initial_sequence_info, recalculation_context, recalculation_callback, parent=None):
        """ Constructor for the Sequence Edit Dialog. """
        super().__init__(parent)
        self.setWindowTitle("Edit Survey Sequence")
        self.setWindowFlag(_QT_WINDOW_MAXIMIZE_BUTTON_HINT, True)
        self.setMinimumSize(950, 600)

        # Store initial data, context, and callback
        self.original_sequence_info = custom_deepcopy(initial_sequence_info)
        self.current_sequence_info = custom_deepcopy(initial_sequence_info)

        # --- ADD DEBUG LOG ---
        log.debug(
            "[SequenceEditDialog.__init__] Received initial sequence info:")
        log.debug(f"  Sequence: {self.current_sequence_info.get('seq')}")
        log.debug(f"  State: {self.current_sequence_info.get('state')}")
        log.debug(
            f"  Directions from state: {self.current_sequence_info.get('state', {}).get('line_directions')}")
        # --- END DEBUG LOG ---

        # Dict with params, data, layers, cache, methods
        self.recalculation_context = recalculation_context
        # Callback to update main widget's cost/state
        self.recalculation_callback = recalculation_callback

        # --- Get Start Sequence Number (Requirement 3) ---
        try:
            self.start_seq_num = int(self.recalculation_context.get(
                "sim_params", {}).get("start_sequence_number", 1))
        except (ValueError, TypeError):
            log.warning(
                "Could not parse start_sequence_number from context, defaulting to 1.")
            self.start_seq_num = 1
        log.debug(
            f"SequenceEditDialog using start sequence number: {self.start_seq_num}")

        # Full segment: start/end include run-in & run-out. Table shows production (shooting) only.
        self.segment_timings = {}

        # --- UI Elements ---
        self.layout = QVBoxLayout(self)

        self.tabs = QtWidgets.QTabWidget()
        self.layout.addWidget(self.tabs)

        self.seq_tab = QtWidgets.QWidget()
        self.seq_layout = QVBoxLayout(self.seq_tab)
        self.tabs.addTab(self.seq_tab, "Sequence Editor")

        self.turn_tab = QtWidgets.QWidget()
        self.turn_layout = QVBoxLayout(self.turn_tab)
        self.tabs.addTab(self.turn_tab, "Individual Turn Editor")

        self.calendar_tab = QtWidgets.QWidget()
        self.calendar_layout = QVBoxLayout(self.calendar_tab)
        self.tabs.addTab(self.calendar_tab, "Acquisition Calendar")

        # Table Widget
        self.tableWidget = QTableWidget()
        # --- MODIFIED: Column count and headers (Requirement 3) ---
        self.tableWidget.setColumnCount(len(SEQUENCE_EDITOR_TABLE_HEADERS))
        self.tableWidget.setHorizontalHeaderLabels(
            _sequence_editor_header_list())

        # Adjust column widths (Updated indices - Requirement 3)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_SEQ_NUM, _QT_HEADER_RESIZE_TO_CONTENTS)  # New
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_LINE_NUM, _QT_HEADER_RESIZE_TO_CONTENTS)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_START_SP, _QT_HEADER_RESIZE_TO_CONTENTS)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_END_SP, _QT_HEADER_RESIZE_TO_CONTENTS)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_START_TIME, _QT_HEADER_STRETCH)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_END_TIME, _QT_HEADER_STRETCH)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_DURATION, _QT_HEADER_RESIZE_TO_CONTENTS)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_SPEED, _QT_HEADER_RESIZE_TO_CONTENTS)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_DIRECTION, _QT_HEADER_RESIZE_TO_CONTENTS)
        self.tableWidget.horizontalHeader().setSectionResizeMode(
            COL_LINE_CHANGE, _QT_HEADER_RESIZE_TO_CONTENTS)

        self.tableWidget.setSelectionBehavior(_QAIV_SELECT_ROWS)
        self.tableWidget.setSelectionMode(_QAIV_SINGLE_SELECTION)
        self.tableWidget.setEditTriggers(_QAIV_NO_EDIT_TRIGGERS)
        self.seq_layout.addWidget(self.tableWidget)

        # Bottom Controls Layout
        self.bottomControlLayout = QHBoxLayout()

        # Move Buttons
        self.moveButtonLayout = QHBoxLayout()
        self.upButton = QPushButton("Move Up")
        self.downButton = QPushButton("Move Down")
        self.moveButtonLayout.addStretch()
        self.moveButtonLayout.addWidget(self.upButton)
        self.moveButtonLayout.addWidget(self.downButton)
        self.moveButtonLayout.addStretch()
        # Add move buttons to bottom layout
        self.bottomControlLayout.addLayout(self.moveButtonLayout)

        # Copy / Export buttons
        self.copyButton = QPushButton("Copy to Clipboard")
        self.bottomControlLayout.addWidget(self.copyButton)

        # Export Button (Requirement 4)
        self.exportButton = QPushButton("Export XLSX")
        self.bottomControlLayout.addWidget(
            self.exportButton)  # Add export button

        # Add the combined bottom layout
        self.seq_layout.addLayout(self.bottomControlLayout)

        # Info Labels (Line-only + Total)
        self.lineTimeLabel = QLabel("Estimated Line Time: --- hours")
        self.lineTimeLabel.setSizePolicy(_QSP_EXPANDING, _QSP_PREFERRED)
        self.seq_layout.addWidget(self.lineTimeLabel)

        self.lineChangeTimeLabel = QLabel(
            "Estimated Line Change Time: --- hours")
        self.lineChangeTimeLabel.setSizePolicy(_QSP_EXPANDING, _QSP_PREFERRED)
        self.seq_layout.addWidget(self.lineChangeTimeLabel)

        self.timeLabel = QLabel("Estimated Total Time: --- hours")
        self.timeLabel.setSizePolicy(_QSP_EXPANDING, _QSP_PREFERRED)
        self.seq_layout.addWidget(self.timeLabel)

        # Turn Editor Setup
        self.turn_history = []  # History stack for Undo functionality
        # set when user selects a turn (for drag tool CRS)
        self._turn_editor_path_layer = None
        self._setup_turn_tab()
        self._setup_calendar_tab()

        # Submit / Cancel Buttons
        self.buttonBoxLayout = QHBoxLayout()
        self.btn_submit_main = QPushButton("Submit")
        self.btn_cancel_main = QPushButton("Cancel")
        # Keep the main action button width stable (Submit/Close swap).
        self._main_action_btn_width = self.btn_submit_main.sizeHint().width()
        self.btn_submit_main.setFixedWidth(self._main_action_btn_width)
        self.buttonBoxLayout.addStretch()
        self.buttonBoxLayout.addWidget(self.btn_cancel_main)
        self.buttonBoxLayout.addWidget(self.btn_submit_main)
        self.layout.addLayout(self.buttonBoxLayout)

        self.btn_submit_main.clicked.connect(self.on_accept)
        self.btn_cancel_main.clicked.connect(self.reject)

        self._posiview_overlay = None
        self._init_posiview_finalize_overlay()

        self.tabs.currentChanged.connect(self._on_main_tab_changed)

        # --- Connect Signals ---
        self.upButton.clicked.connect(self.move_up)
        self.downButton.clicked.connect(self.move_down)
        self.copyButton.clicked.connect(self.copy_table_to_clipboard)
        self.exportButton.clicked.connect(
            self.export_to_xlsx)  # Connect export button
        self.tableWidget.itemSelectionChanged.connect(
            self.update_button_states)

        # --- Initial Population ---
        self.run_full_timing_calculation_and_update(show_message=False)
        self.update_button_states()

    def _init_posiview_finalize_overlay(self):
        try:
            from .tracking_finalize_overlay import PosiViewFinalizeOverlay
        except Exception as e:
            log.debug("PosiView overlay unavailable: %s", e)
            self._posiview_overlay = None
            return
        try:
            self._posiview_overlay = PosiViewFinalizeOverlay(
                self, self.canvas, self.calendar_canvas)
        except Exception as e:
            log.warning("PosiView finalize overlay init failed: %s", e)
            self._posiview_overlay = None
            return
        self._posiview_overlay.set_enabled(True)

    def _calculate_segment_times(self, sequence, directions):
        """
        Internal helper to calculate detailed start/end/duration for each line segment.
        ``start``/``end`` span run-in + shooting + run-out; the table shows production only.
        Returns a dictionary: {line_num: {'start': dt, 'end': dt, 'turn': s, 'runin': s, 'line': s, 'total_segment': s}}
        Returns None on failure.
        """
        timings = {}
        if not sequence:
            return timings

        # ... (Retrieve context safely - code remains the same) ...
        sim_params = self.recalculation_context.get("sim_params")
        line_data = self.recalculation_context.get("line_data")
        required_layers = self.recalculation_context.get("required_layers")
        turn_cache = self.recalculation_context.get("turn_cache")
        _get_cached_turn = self.recalculation_context.get("_get_cached_turn")
        _find_runin_geom = self.recalculation_context.get("_find_runin_geom")
        _calculate_runin_time = self.recalculation_context.get(
            "_calculate_runin_time")
        _get_next_exit_state = self.recalculation_context.get(
            "_get_next_exit_state")
        _get_entry_details = self.recalculation_context.get(
            "_get_entry_details")

        if not all([sim_params, line_data, required_layers, turn_cache is not None,
                    _get_cached_turn, _find_runin_geom, _calculate_runin_time,
                    _get_next_exit_state, _get_entry_details]):
            _pop_wait_cursor_if_busy()
            QMessageBox.critical(
                self, "Context Error", "Missing required context for timing calculation. Cannot proceed.")
            log.error("Error: Missing context for segment time calculation.")
            return None

        current_time = sim_params.get('start_datetime', datetime.now())
        current_state = {}
        total_cost_seconds = 0.0
        custom_turns = self.current_sequence_info.get("custom_turns", {})

        try:
            log.debug("--- Calculating Segment Times ---")
            # --- Process First Line ---
            line_num = sequence[0]
            is_reciprocal = (directions.get(line_num) == 'high_to_low')
            line_info = line_data.get(line_num)
            if not line_info:
                raise ValueError(f"Line data not found for line {line_num}")

            line_time_s = line_info.get(
                'length', 0) / shooting_speed_mps(sim_params, bool(is_reciprocal))

            runin_geom = _find_runin_geom(
                required_layers['runins'], line_num, "End" if is_reciprocal else "Start", sim_params.get('run_in_length_meters', 500))
            runin_time_s = (
                _calculate_runin_time(runin_geom, sim_params, is_reciprocal)
                if runin_geom
                else 0.0
            )

            runout_geom = _find_runin_geom(
                required_layers['runins'], line_num, "Start" if is_reciprocal else "End", sim_params.get('run_out_length_meters', 0))
            runout_time_s = (
                _calculate_runin_time(runout_geom, sim_params, is_reciprocal)
                if runout_geom
                else 0.0
            )

            segment_start_time = current_time
            segment_duration_s = runin_time_s + line_time_s + runout_time_s
            segment_end_time = segment_start_time + \
                timedelta(seconds=segment_duration_s)
            total_segment_time = segment_duration_s

            log.debug(f"  Line {line_num} (First): Start={segment_start_time.strftime('%H:%M:%S')}, RunIn={runin_time_s:.1f}s, Line={line_time_s:.1f}s, RunOut={runout_time_s:.1f}s, End={segment_end_time.strftime('%H:%M:%S')}")

            timings[line_num] = {
                'start': segment_start_time, 'end': segment_end_time,
                'turn': 0.0,
                'runin': runin_time_s,
                'runout': runout_time_s,
                'line': line_time_s,
                'total_segment': total_segment_time
            }
            current_time = segment_end_time
            total_cost_seconds += total_segment_time

            current_exit_pt, current_exit_hdg = _get_next_exit_state(
                line_num, is_reciprocal, line_data, sim_params)
            if current_exit_pt is None or current_exit_hdg is None:
                raise ValueError(
                    f"Could not determine exit state after first line {line_num}")
            current_state = {'exit_pt': current_exit_pt,
                             'exit_hdg': current_exit_hdg}

            for i in range(len(sequence) - 1):
                from_line = sequence[i]
                line_num = sequence[i + 1]
                from_is_reciprocal = (
                    directions.get(from_line) == 'high_to_low')
                is_reciprocal = (directions.get(line_num) == 'high_to_low')

                line_info = line_data.get(line_num)
                if not line_info:
                    raise ValueError(
                        f"Line data not found for line {line_num}")

                p_entry, h_entry = _get_entry_details(
                    line_info, is_reciprocal, sim_params)
                exit_pt = current_state['exit_pt']
                exit_hdg = current_state['exit_hdg']

                if not p_entry or h_entry is None or not exit_pt or exit_hdg is None:
                    raise ValueError(
                        f"Missing turn data for {from_line}->{line_num}")

                turn_key = f"{from_line}_{line_num}"
                turn_override = custom_turns.get(turn_key, {})
                custom_radius = turn_override.get("radius")
                custom_flip = turn_override.get("flip", False)
                nudge_dx = float(turn_override.get("nudge_dx", 0) or 0)
                nudge_dy = float(turn_override.get("nudge_dy", 0) or 0)
                mid_loop_count = int(
                    turn_override.get("mid_loop_count", 0) or 0)
                mid_loop_side = int(turn_override.get("mid_loop_side", 1) or 1)
                mid_loop_dx = float(turn_override.get("mid_loop_dx", 0) or 0)
                mid_loop_dy = float(turn_override.get("mid_loop_dy", 0) or 0)

                custom_mode_text = turn_override.get("mode")
                mode_key = sim_params.get("acquisition_mode_key", "teardrop")
                turn_mode_override = mode_key
                if custom_mode_text == "Teardrop":
                    turn_mode_override = "teardrop"
                elif custom_mode_text == "Racetrack":
                    turn_mode_override = "racetrack"

                turn_geom, turn_length, turn_time_s = _get_cached_turn(
                    from_line,
                    line_num,
                    from_is_reciprocal,
                    is_reciprocal,
                    exit_pt,
                    exit_hdg,
                    p_entry,
                    h_entry,
                    sim_params,
                    turn_cache,
                    turn_mode=turn_mode_override,
                    custom_radius=custom_radius,
                    custom_flip=custom_flip,
                    nudge_dx=nudge_dx,
                    nudge_dy=nudge_dy,
                    mid_loop_count=mid_loop_count,
                    mid_loop_side=mid_loop_side,
                    mid_loop_dx=mid_loop_dx,
                    mid_loop_dy=mid_loop_dy,
                )
                if turn_geom is None or turn_time_s is None:
                    raise ValueError(
                        f"Turn calculation failed for {from_line}->{line_num}")

                line_time_s = line_info.get(
                    'length', 0) / shooting_speed_mps(sim_params, bool(is_reciprocal))

                runin_geom = _find_runin_geom(
                    required_layers['runins'], line_num, "End" if is_reciprocal else "Start", sim_params.get('run_in_length_meters', 500))
                runin_time_s = (
                    _calculate_runin_time(
                        runin_geom, sim_params, is_reciprocal)
                    if runin_geom
                    else 0.0
                )

                runout_geom = _find_runin_geom(
                    required_layers['runins'], line_num, "Start" if is_reciprocal else "End", sim_params.get('run_out_length_meters', 0))
                runout_time_s = (
                    _calculate_runin_time(
                        runout_geom, sim_params, is_reciprocal)
                    if runout_geom
                    else 0.0
                )

                segment_start_time = current_time + \
                    timedelta(seconds=turn_time_s)
                segment_duration_s = runin_time_s + line_time_s + runout_time_s
                segment_end_time = segment_start_time + \
                    timedelta(seconds=segment_duration_s)
                total_segment_time = turn_time_s + segment_duration_s

                log.debug(f"  Line {line_num}: PrevEnd={current_time.strftime('%H:%M:%S')}, Turn={turn_time_s:.1f}s, Start={segment_start_time.strftime('%H:%M:%S')}, RunIn={runin_time_s:.1f}s, Line={line_time_s:.1f}s, RunOut={runout_time_s:.1f}s, End={segment_end_time.strftime('%H:%M:%S')}")

                timings[line_num] = {
                    'start': segment_start_time, 'end': segment_end_time,
                    'turn': turn_time_s,
                    'runin': runin_time_s,
                    'runout': runout_time_s,
                    'line': line_time_s,
                    'total_segment': total_segment_time
                }
                current_time = segment_end_time
                total_cost_seconds += total_segment_time

                current_exit_pt, current_exit_hdg = _get_next_exit_state(
                    line_num, is_reciprocal, line_data, sim_params)
                if current_exit_pt is None or current_exit_hdg is None:
                    raise ValueError(
                        f"Could not determine exit state after line {line_num}")
                current_state = {'exit_pt': current_exit_pt,
                                 'exit_hdg': current_exit_hdg}

            log.debug(
                f"Total Calculated Cost: {total_cost_seconds:.1f} seconds")
            self.current_sequence_info['cost'] = total_cost_seconds
            log.debug("--- Finished Calculating Segment Times ---")
            return timings

        except Exception as e:

            QMessageBox.warning(self, "Timing Error",
                                f"Could not calculate segment times:\n{e}")
            return None

    def run_full_timing_calculation_and_update(self, show_message=True):
        """Calculates timings for all segments and updates the table and total time label."""
        QApplication.setOverrideCursor(_QT_WAIT_CURSOR)
        calculation_ok = False
        try:
            sequence = self.current_sequence_info.get('seq', [])
            directions = self.current_sequence_info.get(
                'state', {}).get('line_directions', {})

            if not sequence:
                log.warning("Cannot calculate timing, sequence is empty.")
                self.timeLabel.setText("Estimated Total Time: No Sequence")
                self.populate_table()  # Clear table
                return False

            log.info("Running full timing calculation...")
            new_timings = self._calculate_segment_times(sequence, directions)

            if new_timings is not None:
                self.segment_timings = new_timings  # Update stored timings
                self.populate_table()  # Update table with new timings
                self.update_time_label()  # Update total time label
                if show_message:
                    _pop_wait_cursor_if_busy()
                    QMessageBox.information(
                        self, "Calculation Complete", "Timings updated.")
                calculation_ok = True
                log.info("Timing calculation successful.")
            else:
                # Error handled/shown in _calculate_segment_times
                self.timeLabel.setText("Estimated Total Time: Error")
                log.error("Timing calculation failed.")

        finally:
            _pop_wait_cursor_if_busy()
        return calculation_ok  # Return success/failure

    def populate_table(self):
        """ Fills the table including Sequence numbers, SPs and formatted duration. """
        sequence = self.current_sequence_info.get('seq', [])
        directions = self.current_sequence_info.get(
            'state', {}).get('line_directions', {})
        # DEBUG
        log.debug(f"[populate_table] Using directions map: {directions}")
        line_data_map = self.recalculation_context.get(
            "line_data", {})  # Get line_data from context

        self.tableWidget.blockSignals(True)
        self.tableWidget.setRowCount(len(sequence))
        dt_format = "%Y-%m-%d %H:%M"  # Table / export (no seconds)

        def _format_hhmm(seconds_value):
            try:
                total_seconds = max(0, int(round(float(seconds_value))))
            except Exception:
                return "N/A"
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours:02d}:{minutes:02d}"

        # --- Store combos and their desired indices ---
        # List to hold dictionaries {'combo': QComboBox, 'index': int, 'row': int, 'line': int}
        combos_to_set = []

        sim_params = self.recalculation_context.get("sim_params") or {}

        for i, line_num in enumerate(sequence):
            line_specific_data = line_data_map.get(
                line_num, {})  # Get data for this line

            # --- Sequence Number (Requirement 3) ---
            seq_num_val = self.start_seq_num + i
            seq_item = QTableWidgetItem(str(seq_num_val))
            seq_item.setTextAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)
            seq_item.setFlags(seq_item.flags() & ~_QT_ITEM_IS_EDITABLE)
            self.tableWidget.setItem(i, COL_SEQ_NUM, seq_item)
            # ---

            # Line Number
            line_str = str(line_num)
            # Remove legacy suffixes for cache backward compatibility
            if line_str.endswith('_0'):
                line_str = line_str[:-2]
            line_item = QTableWidgetItem(line_str)
            line_item.setTextAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)
            line_item.setFlags(line_item.flags() & ~_QT_ITEM_IS_EDITABLE)
            self.tableWidget.setItem(i, COL_LINE_NUM, line_item)

            # --- Get SP based on Direction (Requirement 1 - Ensure consistency) ---
            direction_str = directions.get(
                line_num, 'low_to_high')  # Get stored direction
            # DEBUG
            log.debug(
                f"  Row {i}, Line {line_num}: Fetched direction = '{direction_str}'")
            is_reciprocal = (direction_str == 'high_to_low')
            # Fetch SPs based on the *stored* direction
            start_sp_val = line_specific_data.get(
                'highest_sp') if is_reciprocal else line_specific_data.get('lowest_sp')
            end_sp_val = line_specific_data.get(
                'lowest_sp') if is_reciprocal else line_specific_data.get('highest_sp')
            start_sp_str = str(
                start_sp_val) if start_sp_val is not None else "N/A"
            end_sp_str = str(end_sp_val) if end_sp_val is not None else "N/A"

            start_sp_item = QTableWidgetItem(start_sp_str)
            start_sp_item.setTextAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)
            start_sp_item.setFlags(
                start_sp_item.flags() & ~_QT_ITEM_IS_EDITABLE
            )
            self.tableWidget.setItem(i, COL_START_SP, start_sp_item)

            end_sp_item = QTableWidgetItem(end_sp_str)
            end_sp_item.setTextAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)
            end_sp_item.setFlags(end_sp_item.flags() & ~_QT_ITEM_IS_EDITABLE)
            self.tableWidget.setItem(i, COL_END_SP, end_sp_item)
            # ---

            # Timing Items
            start_time_str, end_time_str, duration_str_hhmm, line_change_str_hhmm = "N/A", "N/A", "N/A", ""
            line_timing = self.segment_timings.get(line_num)
            if line_timing:
                # Production window only (no run-in / run-out in displayed times; turns are between rows).
                runin_s = float(line_timing.get("runin") or 0)
                line_s = float(line_timing.get("line") or 0)
                shoot_start = line_timing["start"] + timedelta(seconds=runin_s)
                shoot_end = shoot_start + timedelta(seconds=line_s)
                start_time_str = shoot_start.strftime(dt_format)
                end_time_str = shoot_end.strftime(dt_format)
                try:
                    segment_delta = shoot_end - shoot_start
                    total_seconds = segment_delta.total_seconds()
                except TypeError:
                    total_seconds = -1  # Indicate error if dates are not valid

                if total_seconds >= 0:
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    # Format HH:MM
                    duration_str_hhmm = f"{hours:02d}:{minutes:02d}"
                else:
                    duration_str_hhmm = "Error"

                # Line Change is transition time between current line and next line:
                # current run-out + next turn + next run-in.
                if i < len(sequence) - 1:
                    next_line_num = sequence[i + 1]
                    next_timing = self.segment_timings.get(next_line_num)
                    if next_timing:
                        line_change_seconds = (
                            float(line_timing.get("runout") or 0.0)
                            + float(next_timing.get("turn") or 0.0)  # noqa: W503
                            + float(next_timing.get("runin") or 0.0)  # noqa: W503
                        )
                        line_change_str_hhmm = _format_hhmm(
                            line_change_seconds)
            else:
                log.warning(
                    f"No timing info found for line {line_num} during table population.")

            start_item = QTableWidgetItem(start_time_str)
            start_item.setFlags(start_item.flags() & ~_QT_ITEM_IS_EDITABLE)
            self.tableWidget.setItem(i, COL_START_TIME, start_item)
            end_item = QTableWidgetItem(end_time_str)
            end_item.setFlags(end_item.flags() & ~_QT_ITEM_IS_EDITABLE)
            self.tableWidget.setItem(i, COL_END_TIME, end_item)
            duration_item = QTableWidgetItem(duration_str_hhmm)
            duration_item.setFlags(
                duration_item.flags() & ~_QT_ITEM_IS_EDITABLE
            )
            self.tableWidget.setItem(i, COL_DURATION, duration_item)
            duration_item.setTextAlignment(
                _QT_ALIGN_CENTER | _QT_ALIGN_VCENTER)  # Center align duration

            try:
                speed_kn = shooting_speed_knots(
                    sim_params, bool(is_reciprocal))
                speed_str = f"{float(speed_kn):.2f}"
            except Exception:
                speed_str = "N/A"
            speed_item = QTableWidgetItem(speed_str)
            speed_item.setFlags(speed_item.flags() & ~_QT_ITEM_IS_EDITABLE)
            speed_item.setTextAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)
            self.tableWidget.setItem(i, COL_SPEED, speed_item)

            # --- Direction ComboBox (Create and store for deferred index setting) ---
            combo = QComboBox()
            combo.addItems(["Low to High", "High to Low"])
            combo.setProperty("row", i)
            combo.setProperty("line_id", line_num)
            combo.currentIndexChanged.connect(self.direction_changed)
            self.tableWidget.setCellWidget(i, COL_DIRECTION, combo)

            # Determine the correct index and store it
            direction_index = 1 if is_reciprocal else 0
            combos_to_set.append(
                {'combo': combo, 'index': direction_index, 'row': i, 'line': line_num})
            # --- End Direction ComboBox creation ---

            line_change_item = QTableWidgetItem(line_change_str_hhmm)
            line_change_item.setFlags(
                line_change_item.flags() & ~_QT_ITEM_IS_EDITABLE)
            self.tableWidget.setItem(i, COL_LINE_CHANGE, line_change_item)
            line_change_item.setTextAlignment(
                _QT_ALIGN_CENTER | _QT_ALIGN_VCENTER)

        # --- Set ComboBox Indices AFTER the loop ---
        log.debug(
            f"Setting ComboBox indices for {len(combos_to_set)} rows after loop...")
        for item_info in combos_to_set:
            combo_widget = item_info['combo']
            target_index = item_info['index']
            log.debug(
                f"  Row {item_info['row']}, Line {item_info['line']}: Setting index to {target_index}")
            combo_widget.setCurrentIndex(target_index)
            # Optional: Check if it worked immediately (less critical now)
            # log.debug(f"  Row {item_info['row']}, Line {item_info['line']}: Actual index after set: {combo_widget.currentIndex()}, Text: '{combo_widget.currentText()}'")
        # --- End deferred setting ---

        self.tableWidget.blockSignals(False)
        self.tableWidget.resizeRowsToContents()
        self._relax_table_column_widths()

    def _relax_table_column_widths(self, extra_px=18):
        """Size columns to contents, then add a small visual breathing room."""
        self.tableWidget.resizeColumnsToContents()
        for col in range(self.tableWidget.columnCount()):
            base_width = self.tableWidget.columnWidth(col)
            self.tableWidget.setColumnWidth(col, base_width + extra_px)

    def direction_changed(self, index):
        """ Handles direction ComboBox changes and triggers recalculation. """
        sender_combo = self.sender()
        if not sender_combo:
            return

        row = sender_combo.property("row")
        line_id = sender_combo.property("line_id")
        if line_id is None:
            return

        new_direction_text = sender_combo.currentText()
        new_direction_str = new_direction_text.lower().replace(" ", "_")

        QtCore.QTimer.singleShot(0, lambda: self._apply_direction_change(
            line_id, new_direction_str, row))

    def _apply_direction_change(self, line_id, new_direction_str, row):
        """ Actually applies the direction change and triggers UI update. """
        if 'state' in self.current_sequence_info and 'line_directions' in self.current_sequence_info['state']:
            directions = self.current_sequence_info['state']['line_directions']
            sequence = self.current_sequence_info.get('seq', [])

            if directions.get(line_id) != new_direction_str:
                directions[line_id] = new_direction_str
                log.info(
                    f"Direction updated for line {line_id} to {new_direction_str}")

                # Ripple effect
                if row is not None and row >= 0 and row < len(sequence):
                    for j in range(row + 1, len(sequence)):
                        prev_line = sequence[j - 1]
                        curr_line = sequence[j]

                        base_prev = str(prev_line).split('_')[0]
                        base_curr = str(curr_line).split('_')[0]

                        prev_dir = directions.get(prev_line, 'low_to_high')
                        prev_is_recip = (prev_dir == 'high_to_low')

                        if base_prev == base_curr:
                            curr_is_recip = prev_is_recip
                        else:
                            curr_is_recip = not prev_is_recip

                        directions[curr_line] = 'high_to_low' if curr_is_recip else 'low_to_high'

                # Trigger dynamic map redraw (which includes recalculation)
                self._trigger_redraw()
        else:
            log.error(
                f"Error: Could not update direction state for line {line_id}")

    # --- Export to XLSX (Requirement 4) ---
    def copy_table_to_clipboard(self):
        """Copy the current sequence table (with headers) as tab-separated text."""
        row_count = self.tableWidget.rowCount()
        if row_count == 0:
            QMessageBox.information(self, "Copy", "Table is empty.")
            return

        lines = ["\t".join(_sequence_editor_header_list())]
        for row in range(row_count):
            lines.append(
                "\t".join(_sequence_editor_row_strings(self.tableWidget, row)))

        QApplication.clipboard().setText("\n".join(lines))
        log.info("Copied %s sequence rows to clipboard.", row_count)

    def export_to_xlsx(self):
        """Export the sequence table to .xlsx in the same column order and cell text as the UI table."""
        log.debug("Export to XLSX button clicked.")

        now = datetime.now()
        default_filename = f"Shooting_Plan_{now.strftime('%Y%m%d_%H%M%S')}.xlsx"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Shooting Plan", default_filename, "Excel Files (*.xlsx)"
        )

        if not save_path:
            log.info("XLSX export cancelled by user.")
            return

        if not save_path.lower().endswith(".xlsx"):
            save_path += ".xlsx"

        headers = _sequence_editor_header_list()
        n_expected = len(headers)
        ncol = self.tableWidget.columnCount()
        if ncol != n_expected:
            log.warning(
                "Sequence table has %s columns but export expects %s; extra columns are ignored, missing padded empty.",
                ncol,
                n_expected,
            )

        data_rows = []
        for row_idx in range(self.tableWidget.rowCount()):
            row_strs = _sequence_editor_row_strings(self.tableWidget, row_idx)
            data_rows.append(_xlsx_coerce_row_for_export(row_strs))

        try:
            write_xlsx_stdlib(save_path, "Shooting Plan", headers, data_rows)
            log.info("Successfully exported shooting plan to %s", save_path)
            opened = False
            try:
                # Nav_Toolbox open_linelog.py: COM, xlMaximized, HWND foreground, delayed raise.
                opened = open_workbook_in_excel(save_path, maximize=True)
            except Exception as ex:
                log.debug("Auto-open in Excel skipped: %s", ex)
            if opened:
                log.info("Export OK; workbook opened in Excel: %s", save_path)
            else:
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Shooting plan saved to:\n{save_path}\n\n"
                    "Excel did not open automatically — open the file manually if needed.\n"
                    "(Install pywin32 in QGIS Python for the same auto-open as Nav_Toolbox.)",
                )
        except Exception as e:
            log.exception("Error exporting data to XLSX: %s", e)
            QMessageBox.critical(
                self, "Export Error", f"An error occurred while exporting to XLSX:\n{e}"
            )

    # --- Movement and Update Methods (Adjusted for new column indices) ---

    def move_up(self):
        """ Moves row up, updates internal sequence, recalculates timings. """
        currentRow = self.tableWidget.currentRow()
        if currentRow > 0:
            seq = self.current_sequence_info['seq']
            seq.insert(currentRow - 1, seq.pop(currentRow))
            log.debug(f"Internal sequence updated: {seq}")
            if self.run_full_timing_calculation_and_update(show_message=False):
                self.tableWidget.selectRow(currentRow - 1)
                self._post_timing_refresh()

    def move_down(self):
        """ Moves row down, updates internal sequence, recalculates timings. """
        currentRow = self.tableWidget.currentRow()
        rowCount = self.tableWidget.rowCount()
        if currentRow < rowCount - 1 and currentRow != -1:
            seq = self.current_sequence_info['seq']
            seq.insert(currentRow + 1, seq.pop(currentRow))
            log.debug(f"Internal sequence updated: {seq}")
            if self.run_full_timing_calculation_and_update(show_message=False):
                self.tableWidget.selectRow(currentRow + 1)
                self._post_timing_refresh()

    def update_button_states(self):
        """ Enables/disables Up/Down buttons based on selection. """
        currentRow = self.tableWidget.currentRow()
        rowCount = self.tableWidget.rowCount()
        self.upButton.setEnabled(currentRow > 0)
        self.downButton.setEnabled(
            currentRow != -1 and currentRow < rowCount - 1)

    def update_time_label(self):
        """Updates line-only and total time labels."""
        cost_seconds = self.current_sequence_info.get('cost')
        if cost_seconds is None or cost_seconds < 0:
            self.lineTimeLabel.setText("Estimated Line Time: Error")
            self.lineChangeTimeLabel.setText(
                "Estimated Line Change Time: Error")
            self.timeLabel.setText("Estimated Total Time: Error")
            return
        line_seconds = 0.0
        line_change_seconds = 0.0
        sequence = self.current_sequence_info.get('seq', []) or []
        for idx, line_num in enumerate(sequence):
            timing = self.segment_timings.get(line_num) or {}
            line_seconds += float(timing.get('line') or 0.0)
            if idx < len(sequence) - 1:
                next_line_num = sequence[idx + 1]
                next_timing = self.segment_timings.get(next_line_num) or {}
                line_change_seconds += (
                    float(timing.get('runout') or 0.0)
                    + float(next_timing.get('turn') or 0.0)  # noqa: W503
                    + float(next_timing.get('runin') or 0.0)  # noqa: W503
                )
        line_hours = line_seconds / 3600.0
        line_change_hours = line_change_seconds / 3600.0
        cost_hours = cost_seconds / 3600.0
        self.lineTimeLabel.setText(
            f"Estimated Line Time: {line_hours:.2f} hours")
        self.lineChangeTimeLabel.setText(
            f"Estimated Line Change Time: {line_change_hours:.2f} hours")
        self.timeLabel.setText(f"Estimated Total Time: {cost_hours:.2f} hours")

    def on_accept(self):
        """ Run final recalculation before accepting to ensure consistency. """
        log.info("Accepting sequence edit dialog.")
        if self.run_full_timing_calculation_and_update(show_message=False):
            super().accept()
        else:
            QMessageBox.warning(
                self, "Accept Failed", "Final timing calculation failed. Cannot accept.")

    def get_final_sequence_info(self):
        """ Returns the potentially modified sequence info dictionary. """
        # Ensure the cost is up-to-date before returning
        # Recalculates cost if needed via run_full... called by other methods
        self.update_time_label()
        return self.current_sequence_info

    def _setup_turn_tab(self):
        """ Initialize the components and map canvas for the Turn Editor. """
        # Map Canvas
        self.canvas = QgsMapCanvas(self.turn_tab)
        try:
            self.canvas.setDestinationCrs(QgsProject.instance().crs())
        except Exception:
            pass
        # Get canvas color from QGIS interface if available
        canvas_color = _parent_canvas_color_or_default(self, _QT_COLOR_WHITE)
        self.canvas.setCanvasColor(canvas_color)
        self.canvas.enableAntiAliasing(True)
        self._turn_map_host = FinalizeMapCanvasHost(self.canvas, self.turn_tab)
        self.turn_layout.addWidget(self._turn_map_host, stretch=1)

        # Editor controls (Full Extent on same row as other actions, left of Selected Turn)
        edit_layout = QHBoxLayout()
        self.btn_turn_full_extent = QPushButton("Full Extent")
        self.btn_turn_full_extent.setToolTip(
            "Zoom the Turn Editor map to the combined extent of visible lookahead layers."
        )
        edit_layout.addWidget(self.btn_turn_full_extent)
        self.lbl_selected_turn = QLabel("Selected Turn: None")
        edit_layout.addWidget(self.lbl_selected_turn)

        edit_layout.addWidget(QLabel("Radius (m):"))
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setDecimals(0)
        self.spin_radius.setMaximum(5000)
        self.spin_radius.setSingleStep(50.0)
        self.spin_radius.setMinimumWidth(92)
        edit_layout.addWidget(self.spin_radius)

        self.btn_apply_turn = QPushButton("Apply")
        edit_layout.addWidget(self.btn_apply_turn)

        edit_layout.addWidget(QLabel("Shape:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Racetrack", "Teardrop"])
        edit_layout.addWidget(self.combo_mode)

        self.btn_flip_left = QPushButton("Flip Left")
        self.btn_flip_left.setToolTip(
            "Set flip=False for this leg (one Dubins branch). Symmetric layouts can look like Flip Right."
        )
        edit_layout.addWidget(self.btn_flip_left)

        self.btn_flip_right = QPushButton("Flip Right")
        self.btn_flip_right.setToolTip(
            "Set flip=True for this leg (the other Dubins branch). Use Undo to revert; there is no partial unflip."
        )
        edit_layout.addWidget(self.btn_flip_right)

        self.btn_undo = QPushButton("Undo")
        edit_layout.addWidget(self.btn_undo)

        edit_layout.addStretch()
        self.turn_layout.addLayout(edit_layout)

        # Map Tools initialization
        self.turn_tool = TurnMapTool(self.canvas, self._on_turn_clicked)

        self.btn_apply_turn.clicked.connect(self.apply_turn_edits)
        self.combo_mode.activated.connect(self.apply_turn_edits)
        self.btn_flip_left.clicked.connect(self.set_turn_sense_left)
        self.btn_flip_right.clicked.connect(self.set_turn_sense_right)
        self.btn_undo.clicked.connect(self.undo_turn_edits)

        self.canvas.setMapTool(self.turn_tool)
        self.selected_turn_feat = None
        self.selected_turn_key = None
        self.rubber_band = None
        self._turn_radius_circle_rb = None
        self.spin_radius.valueChanged.connect(
            self._on_turn_radius_spin_for_handles)
        self.btn_turn_full_extent.clicked.connect(self._turn_zoom_full_extent)
        QtCore.QTimer.singleShot(0, self._sync_turn_editor_button_widths)

        QtCore.QTimer.singleShot(
            100, lambda: self._refresh_canvas_layers(reset_extent=True))

    def _setup_calendar_tab(self):
        """Initialize the Acquisition Calendar tab."""
        self.calendar_canvas = QgsMapCanvas(self.calendar_tab)
        try:
            self.calendar_canvas.setDestinationCrs(QgsProject.instance().crs())
        except Exception:
            pass
        # Avoid the canvas consuming RMB for a context menu so the ruler gets press/move/release.
        self.calendar_canvas.setContextMenuPolicy(_QT_NO_CONTEXT_MENU)
        canvas_color = _parent_canvas_color_or_default(self, _QT_COLOR_WHITE)
        self.calendar_canvas.setCanvasColor(canvas_color)
        self.calendar_canvas.enableAntiAliasing(True)
        self._calendar_map_host = FinalizeMapCanvasHost(
            self.calendar_canvas, self.calendar_tab)
        self.calendar_layout.addWidget(self._calendar_map_host, stretch=1)

        self.calendar_layer_actions = {}
        self.calendar_segments = []
        self.calendar_total_duration_s = 0
        self.calendar_playback_speed = 1
        self.calendar_is_playing = False
        self.calendar_hover_distance = None
        self.calendar_hover_seconds = None
        self.calendar_hover_segment = None

        timeline_layout = QHBoxLayout()
        self.lbl_calendar_start = QLabel("---")
        _f_cal_bold = QFont(self.lbl_calendar_start.font())
        _f_cal_bold.setBold(True)
        self.lbl_calendar_start.setFont(_f_cal_bold)
        timeline_layout.addWidget(self.lbl_calendar_start)

        self.slider_calendar = QSlider(_QT_HORIZONTAL)
        self.slider_calendar.setRange(0, 0)
        self.slider_calendar.setTickPosition(_QSLIDER_TICKS_BELOW)
        self.slider_calendar.setSingleStep(60)
        self.slider_calendar.setPageStep(3600)
        # Keep the timeline ruler visually slimmer so control rows stay compact.
        self.slider_calendar.setFixedHeight(16)
        timeline_layout.addWidget(self.slider_calendar, stretch=1)

        self.lbl_calendar_end = QLabel("---")
        self.lbl_calendar_end.setFont(QFont(_f_cal_bold))
        timeline_layout.addWidget(self.lbl_calendar_end)
        self.calendar_layout.addLayout(timeline_layout)

        controls_layout = QHBoxLayout()
        self.btn_calendar_layers = QtWidgets.QToolButton()
        self.btn_calendar_layers.setText("Layers")
        self.btn_calendar_layers.setPopupMode(_QT_TOOLBTN_INSTANT_POPUP)
        self.btn_calendar_layers.setMinimumWidth(
            self.btn_calendar_layers.sizeHint().width() + 10)
        self.btn_calendar_layers.setToolTip(
            "Toggle visible layers in Acquisition Calendar.")
        controls_layout.addWidget(self.btn_calendar_layers)

        self.btn_calendar_full_extent = QPushButton("Full Extent")
        self.btn_calendar_full_extent.setToolTip(
            "Zoom to full extent of visible layers.")
        controls_layout.addWidget(self.btn_calendar_full_extent)

        _f_cal_compact = QFont(_f_cal_bold)
        _f_cal_compact.setPointSize(max(7, _f_cal_compact.pointSize() - 1))

        self.lbl_calendar_current = QLabel("Vessel: ---")
        self.lbl_calendar_current.setFont(_f_cal_compact)

        self.lbl_calendar_cursor = QLabel("Marker: hover path")
        self.lbl_calendar_cursor.setFont(_f_cal_compact)
        self.lbl_calendar_cursor.setToolTip(
            "Left-click on the path: jump the timeline to that time.\n"
            "Right-drag: ruler on the map (snaps to path and segment ends). Distance appears to the right.\n"
            "Esc while the calendar map is focused: clear the ruler line."
        )
        calendar_status_box = QtWidgets.QWidget()
        calendar_status_layout = QVBoxLayout(calendar_status_box)
        calendar_status_layout.setContentsMargins(0, 0, 0, 0)
        calendar_status_layout.setSpacing(0)
        calendar_status_layout.addWidget(self.lbl_calendar_current)
        calendar_status_layout.addWidget(self.lbl_calendar_cursor)
        controls_layout.addWidget(calendar_status_box, stretch=1)

        self.lbl_calendar_distance = QLabel("—")
        self.lbl_calendar_distance.setFont(QFont(_f_cal_bold))
        self.lbl_calendar_distance.setMinimumWidth(96)
        self.lbl_calendar_distance.setAlignment(
            _QT_ALIGN_LEFT | _QT_ALIGN_VCENTER)
        self.lbl_calendar_distance.setToolTip(
            "Straight-line ruler distance (right-drag on map).")
        controls_layout.addWidget(self.lbl_calendar_distance, stretch=0)

        self.btn_calendar_play = QPushButton("Play")
        controls_layout.addWidget(self.btn_calendar_play)

        self.btn_calendar_speed = QPushButton("1x")
        controls_layout.addWidget(self.btn_calendar_speed)

        self.btn_calendar_next_segment = QPushButton("Next Segment")
        self.btn_calendar_next_segment.setToolTip(
            "Jump timeline to the start of the next segment.")
        controls_layout.addWidget(self.btn_calendar_next_segment)

        self.chk_calendar_realtime = QCheckBox("Real-time 1x")
        self.chk_calendar_realtime.setChecked(False)
        self.chk_calendar_realtime.setToolTip(
            "When enabled, 1x ≈ real-world time (1 s on timeline per 1 real second).\n"
            "When disabled, playback uses a fast preview mode."
        )
        controls_layout.addWidget(self.chk_calendar_realtime)

        self.chk_calendar_follow = QCheckBox("Follow")
        self.chk_calendar_follow.setToolTip(
            "While playback is running, keep the vessel in view with a smoothed camera and a higher refresh rate.\n"
            "Available only during Play (checkbox is disabled while paused)."
        )
        controls_layout.addWidget(self.chk_calendar_follow)

        # Align Play/Speed widths with the main Close/Submit button.
        self._sync_calendar_button_widths()

        self.calendar_layout.addLayout(controls_layout)

        self.calendar_layers_menu = QMenu(self)
        self.btn_calendar_layers.setMenu(self.calendar_layers_menu)
        self._build_calendar_layer_menu()

        self.calendar_current_marker = QgsVertexMarker(self.calendar_canvas)
        self.calendar_current_marker.setColor(QColor(255, 0, 0))
        self.calendar_current_marker.setFillColor(QColor(255, 0, 0, 110))
        self.calendar_current_marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
        self.calendar_current_marker.setIconSize(14)
        self.calendar_current_marker.setPenWidth(3)
        # Above PosiView PositionMarker clones (typical z ≈ 100) so playback/hover markers stay visible.
        try:
            self.calendar_current_marker.setZValue(250000.0)
        except Exception:
            pass
        self.calendar_current_marker.hide()

        self.calendar_hover_marker = QgsVertexMarker(self.calendar_canvas)
        self.calendar_hover_marker.setColor(QColor(255, 170, 0))
        self.calendar_hover_marker.setFillColor(QColor(255, 170, 0, 70))
        self.calendar_hover_marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self.calendar_hover_marker.setIconSize(12)
        self.calendar_hover_marker.setPenWidth(2)
        try:
            self.calendar_hover_marker.setZValue(250001.0)
        except Exception:
            pass
        self.calendar_hover_marker.hide()

        self._calendar_measure_start = None
        self._calendar_measure_rubber = QgsRubberBand(
            self.calendar_canvas, QgsWkbTypes.LineGeometry)
        self._calendar_measure_rubber.setColor(QColor(40, 160, 40, 220))
        self._calendar_measure_rubber.setWidth(2)
        self._calendar_measure_rubber.hide()

        self.calendar_tool = AcquisitionCalendarMapTool(
            self.calendar_canvas,
            hover_callback=self._on_calendar_hover,
            click_callback=self._on_calendar_click,
            ruler_press_callback=self._on_calendar_ruler_press,
            ruler_move_callback=self._on_calendar_ruler_move,
            ruler_release_callback=self._on_calendar_ruler_release,
        )
        self.calendar_canvas.setMapTool(self.calendar_tool)

        self._calendar_ruler_escape_shortcut = QShortcut(
            QKeySequence(_QT_KEY_ESCAPE), self.calendar_canvas)
        self._calendar_ruler_escape_shortcut.setContext(
            _QT_WIDGET_WITH_CHILDREN_SHORTCUT)
        self._calendar_ruler_escape_shortcut.activated.connect(
            self._clear_calendar_ruler)

        self.calendar_play_timer = QtCore.QTimer(self)
        self.calendar_play_timer.setInterval(120)
        self.calendar_play_timer.timeout.connect(
            self._advance_calendar_playback)

        self.calendar_pulse_timer = QtCore.QTimer(self)
        self.calendar_pulse_timer.setInterval(500)
        self.calendar_pulse_timer.timeout.connect(self._pulse_calendar_marker)
        self.calendar_pulse_timer.start()
        self._calendar_pulse_big = False

        self.btn_calendar_play.clicked.connect(self._toggle_calendar_playback)
        self.btn_calendar_speed.clicked.connect(self._cycle_calendar_speed)
        self.btn_calendar_next_segment.clicked.connect(
            self._calendar_jump_next_segment)
        self.chk_calendar_realtime.toggled.connect(
            self._on_calendar_realtime_toggled)
        self.btn_calendar_full_extent.clicked.connect(
            self._calendar_zoom_full_extent)
        self.chk_calendar_follow.toggled.connect(
            self._on_calendar_follow_toggled)
        self.slider_calendar.valueChanged.connect(
            self._on_calendar_slider_changed)
        self._update_calendar_speed_button_label()

        QtCore.QTimer.singleShot(
            100, lambda: self._refresh_acquisition_calendar(reset_extent=True))
        QtCore.QTimer.singleShot(
            120, lambda: self._on_main_tab_changed(self.tabs.currentIndex()))
        QtCore.QTimer.singleShot(180, self._sync_calendar_button_widths)

        self._update_calendar_follow_checkbox_enabled()

    def _update_calendar_follow_checkbox_enabled(self):
        """Follow only applies while Play is active; grey out the checkbox otherwise."""
        ch = getattr(self, "chk_calendar_follow", None)
        if ch is None:
            return
        try:
            ch.setEnabled(bool(getattr(self, "calendar_is_playing", False)))
        except Exception:
            pass

    def _sync_turn_editor_button_widths(self):
        """Turn editor push buttons: width from label (+ padding), like Layers/Full Extent on Calendar."""
        pad = 14
        for b in (
            self.btn_turn_full_extent,
            self.btn_apply_turn,
            self.btn_flip_left,
            self.btn_flip_right,
            self.btn_undo,
        ):
            try:
                w = int(b.sizeHint().width()) + pad
                b.setFixedWidth(max(48, w))
                b.setSizePolicy(_QSP_FIXED, _QSP_FIXED)
            except Exception:
                pass

    def _sync_calendar_button_widths(self):
        """Keep Play/Speed the same width as Submit/Close."""
        try:
            w = int(self.btn_submit_main.width() or 0)
        except Exception:
            w = 0
        if w <= 0:
            try:
                w = int(getattr(self, "_main_action_btn_width", 0) or 0)
            except Exception:
                w = 0
        if w <= 0:
            return
        try:
            self.btn_calendar_play.setFixedWidth(w)
            self.btn_calendar_speed.setFixedWidth(w)
        except Exception:
            pass

    def _on_main_tab_changed(self, index: int):
        """Adjust bottom buttons per active tab."""
        try:
            is_calendar = self.tabs.widget(index) is self.calendar_tab
        except Exception:
            is_calendar = False

        if not is_calendar:
            self._clear_calendar_ruler()
            self._dispose_calendar_path_preview_layer()

        # Leaving Acquisition Calendar: stop playback so it doesn't run in background.
        if not is_calendar and getattr(self, "calendar_is_playing", False):
            try:
                self.calendar_play_timer.stop()
            except Exception:
                pass
            self.calendar_is_playing = False
            try:
                self.btn_calendar_play.setText("Play")
            except Exception:
                pass
            self._update_calendar_follow_checkbox_enabled()
            self._sync_calendar_vessel_marker_playback_style()
            try:
                self.calendar_pulse_timer.start()
            except Exception:
                pass

        # Keep the button bar in the same place.
        # In Acquisition Calendar: Submit button becomes Close; Cancel is hidden.
        if is_calendar:
            try:
                self.btn_cancel_main.setVisible(False)
            except Exception:
                pass
            try:
                self.btn_submit_main.setText("Close")
            except Exception:
                pass
            try:
                self.btn_submit_main.clicked.disconnect()
            except Exception:
                pass
            self.btn_submit_main.clicked.connect(self.reject)
        else:
            try:
                self.btn_cancel_main.setVisible(True)
            except Exception:
                pass
            try:
                self.btn_submit_main.setText("Submit")
            except Exception:
                pass
            try:
                self.btn_submit_main.clicked.disconnect()
            except Exception:
                pass
            self.btn_submit_main.clicked.connect(self.on_accept)

        # After switching (and possibly changing Submit->Close), re-sync widths.
        QtCore.QTimer.singleShot(0, self._sync_calendar_button_widths)

    def _build_calendar_layer_menu(self):
        self.calendar_layers_menu.clear()
        self.calendar_layer_actions = {}
        # Show all project layers. Default visibility:
        # - OFF for everything
        # - ON for layers inside group "Lookahead" (Layer Tree)
        # - ON for the currently selected No-Go layer from main settings
        prj = QgsProject.instance()
        root = prj.layerTreeRoot()
        params = self.recalculation_context.get("sim_params", {}) or {}
        nogo = params.get("nogo_layer")
        nogo_id = None
        try:
            nogo_id = nogo.id() if nogo is not None else None
        except Exception:
            nogo_id = None

        def _is_in_lookahead_group(layer_id: str) -> bool:
            try:
                node = root.findLayer(layer_id)
            except Exception:
                return False
            if node is None:
                return False
            p = node.parent()
            while p is not None:
                try:
                    if str(p.name() or "").casefold() == "lookahead":
                        return True
                except Exception:
                    pass
                try:
                    p = p.parent()
                except Exception:
                    break
            return False

        layers = list(prj.mapLayers().values())
        layers.sort(
            key=lambda layer_obj: (
                str(layer_obj.name() or "").casefold(),
                layer_obj.id(),
            )
        )

        # Persist enabled layer names across dialog openings.
        settings = QtCore.QSettings()
        saved_enabled = settings.value(
            "lookahead/acquisition_calendar/enabled_layer_names", None)
        if isinstance(saved_enabled, str):
            # QSettings may return a comma-separated string depending on backend.
            saved_enabled = [s for s in saved_enabled.split(",") if s]
        if isinstance(saved_enabled, (list, tuple)):
            saved_enabled_set = set(str(x) for x in saved_enabled)
        else:
            saved_enabled_set = None

        for lyr in layers:
            name = lyr.name()
            action = QtWidgets.QAction(name, self.calendar_layers_menu)
            action.setCheckable(True)
            default_on = False
            try:
                # Base defaults (Lookahead group + selected No-Go layer).
                default_on = _is_in_lookahead_group(lyr.id()) or (
                    nogo_id is not None and lyr.id() == nogo_id)

                # Explicit exceptions: keep these OFF by default even if they're in Lookahead.
                off_by_default_names = {
                    "generated_deviation_lines",     # dev layer
                    "generated run-in run-out",      # runin/out layer
                    "generated_survey_lines",        # survey lines layer
                }
                if str(name or "").casefold() in off_by_default_names:
                    default_on = False

                if saved_enabled_set is not None:
                    default_on = str(name) in saved_enabled_set
            except Exception:
                default_on = False
            action.setChecked(bool(default_on))
            action.toggled.connect(self._on_calendar_layers_changed)
            self.calendar_layers_menu.addAction(action)
            self.calendar_layer_actions[lyr.id()] = action

        self._update_calendar_layers_button_text()

    def _on_calendar_layers_changed(self, _checked):
        # Save enabled layer names so the user's selection persists.
        try:
            enabled_names = []
            prj = QgsProject.instance()
            for lyr_id, action in (self.calendar_layer_actions or {}).items():
                if not action.isChecked():
                    continue
                lyr = prj.mapLayer(lyr_id)
                if lyr is not None:
                    enabled_names.append(str(lyr.name()))
            QtCore.QSettings().setValue(
                "lookahead/acquisition_calendar/enabled_layer_names", enabled_names)
        except Exception:
            pass
        self._update_calendar_layers_button_text()
        self._refresh_calendar_canvas_layers(reset_extent=False)
        self._sync_calendar_markers_with_time()
        self._clear_calendar_ruler()

    def _update_calendar_layers_button_text(self):
        try:
            enabled = sum(1 for a in (
                self.calendar_layer_actions or {}).values() if a.isChecked())
        except Exception:
            enabled = 0
        self.btn_calendar_layers.setText(f"Layers ({enabled})")

    def _refresh_acquisition_calendar(self, reset_extent=False):
        # Layers can be created after this dialog opens (e.g. Optimized_Path after Run Simulation).
        # Rebuild the menu so toggles stay in sync (checked layer names are persisted in QSettings).
        try:
            self._build_calendar_layer_menu()
        except Exception:
            pass
        self._update_calendar_speed_button_label()
        self._update_calendar_layers_button_text()
        self._refresh_calendar_canvas_layers(
            reset_extent=reset_extent, force_path_clone=True)
        self._rebuild_calendar_segments()
        self._update_calendar_slider_bounds()
        self._sync_calendar_markers_with_time()
        self._clear_calendar_ruler()

    def _dispose_calendar_path_preview_layer(self):
        """Drop in-memory Optimized_Path clone used only on the Acquisition Calendar canvas."""
        self._calendar_preview_src = None
        self._calendar_preview_fc = None
        old = getattr(self, "_calendar_optimized_path_preview_layer", None)
        self._calendar_optimized_path_preview_layer = None
        if old is not None:
            try:
                old.deleteLater()
            except Exception:
                pass

    def _calendar_tune_preview_label_settings(self, s: QgsPalLayerSettings):
        """
        Match main-map path labels: mid-path anchor + tangent rotation, with obstacle relaxation
        so the engine does not jitter labels every refresh during Play.

        Import is lazy to avoid a circular import with lookahead_dockwidget_impl (it imports this module).
        """
        from .lookahead_dockwidget_impl import LookaheadDockWidgetImpl

        LookaheadDockWidgetImpl._path_label_pin_to_segment_centroid(s)

    def _apply_calendar_preview_stable_labeling(self, layer: QgsVectorLayer):
        """
        Same segment text as the main map: labels sit at the segment mid-path with line-parallel
        rotation (stable anchor, no sliding along the curve while panning).
        """
        try:
            rules = []
            line_settings = QgsPalLayerSettings()
            line_settings.isExpression = True
            line_settings.fieldName = "to_string(\"LineNum\") || ' ' || \"Duration_hh_mm\""
            line_settings.enabled = True
            line_format = QgsTextFormat()
            line_format.setSize(5)
            line_format.setColor(QColor(0, 0, 0))
            lf = line_format.font()
            lf.setBold(True)
            line_format.setFont(lf)
            lb = QgsTextBufferSettings()
            lb.setEnabled(True)
            lb.setSize(0.5)
            lb.setColor(QColor(255, 255, 255))
            line_format.setBuffer(lb)
            line_settings.setFormat(line_format)
            self._calendar_tune_preview_label_settings(line_settings)
            line_rule = QgsRuleBasedLabeling.Rule(line_settings)
            line_rule.setFilterExpression("\"SegmentType\" = 'Line'")
            line_rule.setDescription("Line Numbers (calendar preview)")
            rules.append(line_rule)

            turn_settings = QgsPalLayerSettings()
            turn_settings.fieldName = "Duration_hh_mm"
            turn_settings.enabled = True
            turn_format = QgsTextFormat()
            turn_format.setSize(5)
            turn_format.setColor(QColor(200, 0, 0))
            tf = turn_format.font()
            tf.setBold(True)
            turn_format.setFont(tf)
            tb = QgsTextBufferSettings()
            tb.setEnabled(True)
            tb.setSize(0.5)
            tb.setColor(QColor(255, 255, 255))
            turn_format.setBuffer(tb)
            turn_settings.setFormat(turn_format)
            self._calendar_tune_preview_label_settings(turn_settings)
            try:
                mk = str(
                    (self.recalculation_context.get("sim_params") or {}).get(
                        "acquisition_mode_key", ""
                    )
                ).strip().casefold()
            except Exception:
                mk = ""
            turn_rule_desc = "Turn_Teardrop (calendar)" if mk == "teardrop" else "Turn_Racetrack (calendar)"
            turn_rule = QgsRuleBasedLabeling.Rule(turn_settings)
            turn_rule.setFilterExpression(
                "\"SegmentType\" IN ('Turn_Racetrack','Turn_Teardrop','Turn')")
            turn_rule.setDescription(turn_rule_desc)
            rules.append(turn_rule)

            runin_settings = QgsPalLayerSettings()
            runin_settings.fieldName = "Duration_hh_mm"
            runin_settings.enabled = True
            runin_format = QgsTextFormat()
            runin_format.setSize(5)
            runin_format.setColor(QColor(200, 0, 0))
            rf = runin_format.font()
            rf.setBold(True)
            runin_format.setFont(rf)
            rb = QgsTextBufferSettings()
            rb.setEnabled(True)
            rb.setSize(0.5)
            rb.setColor(QColor(255, 255, 255))
            runin_format.setBuffer(rb)
            runin_settings.setFormat(runin_format)
            self._calendar_tune_preview_label_settings(runin_settings)
            runin_rule = QgsRuleBasedLabeling.Rule(runin_settings)
            runin_rule.setFilterExpression("\"SegmentType\" = 'RunIn'")
            runin_rule.setDescription("Run-In (calendar)")
            rules.append(runin_rule)

            runout_settings = QgsPalLayerSettings()
            runout_settings.fieldName = "Duration_hh_mm"
            runout_settings.enabled = True
            runout_format = QgsTextFormat()
            runout_format.setSize(5)
            runout_format.setColor(QColor(0, 105, 92))
            rfo = runout_format.font()
            rfo.setBold(True)
            runout_format.setFont(rfo)
            rbuf = QgsTextBufferSettings()
            rbuf.setEnabled(True)
            rbuf.setSize(0.5)
            rbuf.setColor(QColor(255, 255, 255))
            runout_format.setBuffer(rbuf)
            runout_settings.setFormat(runout_format)
            self._calendar_tune_preview_label_settings(runout_settings)
            runout_rule = QgsRuleBasedLabeling.Rule(runout_settings)
            runout_rule.setFilterExpression("\"SegmentType\" = 'RunOut'")
            runout_rule.setDescription("Run-Out (calendar)")
            rules.append(runout_rule)

            root_rule = QgsRuleBasedLabeling.Rule(None)
            for rule in rules:
                root_rule.appendChild(rule)
            layer.setLabeling(QgsRuleBasedLabeling(root_rule))
            layer.setLabelsEnabled(True)
        except Exception:
            log.exception(
                "Acquisition Calendar: failed to apply stable preview labeling")

    def _calendar_get_optimized_path_canvas_layer(self, source: QgsVectorLayer, force_rebuild: bool = False):
        """
        Return a memory-layer copy of Optimized_Path for map display in this dialog only
        (project layer and main map styling stay unchanged).
        """
        if not _vector_layer_alive(source):
            return source
        try:
            if (source.name() or "") != "Optimized_Path":
                return source
        except Exception:
            return source
        try:
            fc = int(source.featureCount())
        except Exception:
            fc = -1
        prev = getattr(self, "_calendar_optimized_path_preview_layer", None)
        prev_fc = getattr(self, "_calendar_preview_fc", None)
        prev_src = getattr(self, "_calendar_preview_src", None)
        if (
            not force_rebuild
            and prev is not None  # noqa: W503
            and prev_src is source  # noqa: W503
            and prev_fc == fc  # noqa: W503
            and _vector_layer_alive(prev)  # noqa: W503
        ):
            return prev

        self._dispose_calendar_path_preview_layer()

        try:
            wkb = source.wkbType()
            crs = source.crs()
            authid = crs.authid() if crs.isValid() else QgsProject.instance().crs().authid()
            if not authid:
                authid = "EPSG:4326"
            uri = f"{QgsWkbTypes.displayExpression(wkb)}?crs={authid}"
        except Exception:
            return source

        mem = QgsVectorLayer(uri, "_CalendarPathPreview", "memory")
        try:
            valid_crs = crs if crs.isValid() else QgsProject.instance().crs()
            mem.setCrs(valid_crs)
        except Exception:
            pass
        try:
            mem.dataProvider().addAttributes(source.fields().toList())
            mem.updateFields()
        except Exception:
            log.exception(
                "Acquisition Calendar: could not copy fields to preview path layer")
            return source
        try:
            feats = [QgsFeature(f) for f in source.getFeatures()]
            mem.dataProvider().addFeatures(feats)
            mem.updateExtents()
        except Exception:
            log.exception(
                "Acquisition Calendar: could not copy features to preview path layer")
            return source
        try:
            r = source.renderer()
            if r is not None:
                mem.setRenderer(r.clone())
        except Exception:
            pass
        self._apply_calendar_preview_stable_labeling(mem)
        self._calendar_optimized_path_preview_layer = mem
        self._calendar_preview_src = source
        self._calendar_preview_fc = fc
        return mem

    def _calendar_zoom_full_extent(self):
        prj = QgsProject.instance()
        layers = []
        try:
            for lyr_id, action in (self.calendar_layer_actions or {}).items():
                if not action.isChecked():
                    continue
                lyr = prj.mapLayer(lyr_id)
                if lyr is not None:
                    layers.append(lyr)
        except Exception:
            layers = []
        if not layers:
            return
        extent = None
        for lyr in layers:
            try:
                ex = lyr.extent()
            except Exception:
                continue
            if extent is None:
                extent = ex
            else:
                extent.combineExtentWith(ex)
        if extent is not None and not extent.isEmpty():
            self.calendar_canvas.setExtent(extent)
            self.calendar_canvas.refresh()

    def _refresh_calendar_canvas_layers(self, reset_extent=False, force_path_clone=False):
        layers = []
        prj = QgsProject.instance()
        optimized_path = None
        try:
            lyrs = prj.mapLayersByName("Optimized_Path")
            optimized_path = lyrs[0] if lyrs else None
        except Exception:
            optimized_path = None

        collected_layers = []
        path_layer_checked = False
        for lyr_id, action in self.calendar_layer_actions.items():
            if not action.isChecked():
                continue
            lyr = prj.mapLayer(lyr_id)
            if lyr is None:
                continue
            try:
                if isinstance(lyr, QgsVectorLayer) and not _vector_layer_alive(lyr):
                    continue
            except RuntimeError:
                continue
            lyr_to_show = lyr
            try:
                if isinstance(lyr, QgsVectorLayer) and (lyr.name() or "") == "Optimized_Path":
                    path_layer_checked = True
                    lyr_to_show = self._calendar_get_optimized_path_canvas_layer(
                        lyr, force_rebuild=bool(
                            reset_extent or force_path_clone)
                    )
            except Exception:
                lyr_to_show = lyr
            collected_layers.append((lyr, lyr_to_show))

        if not path_layer_checked:
            self._dispose_calendar_path_preview_layer()

        try:
            root = prj.layerTreeRoot()
            if hasattr(root, "layerOrder"):
                tree_order = [layer_obj.id() for layer_obj in root.layerOrder()]
                collected_layers.sort(key=lambda item: tree_order.index(
                    item[0].id()) if item[0].id() in tree_order else 999999)
        except Exception:
            pass

        layers = [item[1] for item in collected_layers]

        if layers:
            self.calendar_canvas.setLayers(layers)
            if reset_extent:
                # Default extent is Optimized_Path when enabled; otherwise fall back to first visible layer.
                try:
                    op_enabled = (
                        optimized_path is not None
                        and optimized_path.id() in self.calendar_layer_actions  # noqa: W503
                        and self.calendar_layer_actions[optimized_path.id()].isChecked()  # noqa: W503
                        and _vector_layer_alive(optimized_path)  # noqa: W503
                    )
                except Exception:
                    op_enabled = False
                if op_enabled:
                    try:
                        optimized_path.updateExtents()
                    except Exception:
                        pass
                    self.calendar_canvas.setExtent(optimized_path.extent())
                elif _vector_layer_alive(layers[0]):
                    try:
                        layers[0].updateExtents()
                    except Exception:
                        pass
                    self.calendar_canvas.setExtent(layers[0].extent())
        else:
            self.calendar_canvas.setLayers([])
        try:
            self.calendar_canvas.clearCache()
        except Exception:
            pass
        self.calendar_canvas.refresh()
        try:
            self.calendar_canvas.repaint()
        except Exception:
            pass

    def _rebuild_calendar_segments(self):
        self.calendar_segments = []
        self.calendar_total_duration_s = 0
        path_layer = self._resolve_optimized_path_layer()
        if not path_layer:
            return

        features = []
        try:
            for feat in path_layer.getFeatures():
                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    continue
                try:
                    seq_order = int(feat.attribute("SeqOrder") or 0)
                except Exception:
                    seq_order = 0
                features.append((seq_order, feat))
        except RuntimeError:
            return

        features.sort(key=lambda item: item[0])
        for _seq_order, feat in features:
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            try:
                duration_s = max(0.0, float(
                    feat.attribute("Duration_s") or 0.0))
            except Exception:
                duration_s = 0.0
            heading_val = feat.attribute("Heading")
            try:
                heading = float(heading_val) if heading_val is not None and str(
                    heading_val) != "NULL" else None
            except Exception:
                heading = None
            start_qdt = feat.attribute("StartTime")
            end_qdt = feat.attribute("EndTime")
            start_dt = start_qdt.toPyDateTime() if hasattr(
                start_qdt, "toPyDateTime") else None
            end_dt = end_qdt.toPyDateTime() if hasattr(end_qdt, "toPyDateTime") else None
            segment = {
                "feature_id": feat.id(),
                "geometry": QgsGeometry(geom),
                "segment_type": str(feat.attribute("SegmentType") or ""),
                "line_num": feat.attribute("LineNum"),
                "start_line": feat.attribute("StartLine"),
                "end_line": feat.attribute("EndLine"),
                "duration_s": duration_s,
                "heading": heading,
                # Traversal direction hint, computed after collecting all segments.
                "reverse": False,
                "start_offset_s": self.calendar_total_duration_s,
                "end_offset_s": self.calendar_total_duration_s + duration_s,
                "start_dt": start_dt,
                "end_dt": end_dt,
            }
            self.calendar_segments.append(segment)
            self.calendar_total_duration_s += duration_s

        # Compute per-segment traversal direction to avoid back-and-forth jumps.
        self._compute_calendar_segment_directions()

    def _segment_endpoints_xy(self, geom: QgsGeometry):
        """Return (start, end) endpoints for a segment geometry as QgsPointXY."""
        if geom is None or geom.isEmpty():
            return None, None
        try:
            length = float(geom.length())
        except Exception:
            length = 0.0
        try:
            p0g = geom.interpolate(0.0)
            p1g = geom.interpolate(max(0.0, length))
            if not p0g or p0g.isEmpty() or not p1g or p1g.isEmpty():
                return None, None
            p0 = p0g.asPoint()
            p1 = p1g.asPoint()
            return QgsPointXY(p0.x(), p0.y()), QgsPointXY(p1.x(), p1.y())
        except Exception:
            return None, None

    def _compute_calendar_segment_directions(self):
        """
        For each segment, decide whether to traverse it forward or reversed to keep the
        animated marker continuous across segment boundaries (especially RunIn/RunOut).
        """
        if not self.calendar_segments:
            return
        prev_end = None
        for seg in self.calendar_segments:
            geom = seg.get("geometry")
            a, b = self._segment_endpoints_xy(geom)
            if a is None or b is None:
                seg["reverse"] = False
                continue

            if prev_end is None:
                # First segment: keep as stored; Line direction may later override by heading.
                seg["reverse"] = False
                prev_end = b
                continue

            try:
                d_start = math.hypot(a.x() - prev_end.x(),
                                     a.y() - prev_end.y())
                d_end = math.hypot(b.x() - prev_end.x(), b.y() - prev_end.y())
            except Exception:
                d_start, d_end = 0.0, 0.0

            # Choose orientation whose start is closer to previous end.
            seg["reverse"] = d_end < d_start
            prev_end = a if seg["reverse"] else b

    @staticmethod
    def _heading_from_xy(a: QgsPointXY, b: QgsPointXY):
        """QGIS-style heading: 0=N, clockwise degrees."""
        dx = b.x() - a.x()
        dy = b.y() - a.y()
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            return None
        angle_rad = math.atan2(dx, dy)
        heading_deg = (math.degrees(angle_rad) + 360.0) % 360.0
        return heading_deg

    @staticmethod
    def _angle_diff_deg(a, b):
        """Smallest absolute difference between angles in degrees."""
        if a is None or b is None:
            return None
        d = abs((a - b + 180.0) % 360.0 - 180.0)
        return d

    def _segment_should_reverse(self, segment):
        """
        Decide whether to traverse geometry backwards for time interpolation.
        This matters mainly for Line segments where the stored heading describes travel direction
        but geometry vertex order may be opposite (reciprocal lines).
        """
        if not segment:
            return False
        seg_type = str(segment.get("segment_type") or "")
        # For non-Line segments, use continuity-based orientation.
        if seg_type != "Line":
            return bool(segment.get("reverse", False))

        target_heading = segment.get("heading")
        if target_heading is None:
            return bool(segment.get("reverse", False))
        geom = segment.get("geometry")
        if geom is None or geom.isEmpty():
            return bool(segment.get("reverse", False))
        try:
            pts = geom.asPolyline()
        except Exception:
            pts = []
        if not pts or len(pts) < 2:
            return bool(segment.get("reverse", False))
        h_forward = self._heading_from_xy(
            QgsPointXY(pts[0]), QgsPointXY(pts[-1]))
        h_backward = None
        if h_forward is not None:
            h_backward = (h_forward + 180.0) % 360.0
        df = self._angle_diff_deg(target_heading, h_forward)
        db = self._angle_diff_deg(target_heading, h_backward)
        if df is None or db is None:
            return bool(segment.get("reverse", False))
        # Reverse if travel heading matches backward better than forward.
        return db + 1e-6 < df

    def _update_calendar_slider_bounds(self):
        max_seconds = int(round(self.calendar_total_duration_s))
        current_value = min(self.slider_calendar.value(), max_seconds)
        self.slider_calendar.blockSignals(True)
        self.slider_calendar.setRange(0, max_seconds)
        self.slider_calendar.setTickInterval(
            max(3600, max_seconds // 12 if max_seconds > 0 else 3600))
        self.slider_calendar.setValue(current_value)
        self.slider_calendar.blockSignals(False)

        if self.calendar_segments:
            first = self.calendar_segments[0]
            last = self.calendar_segments[-1]
            self.lbl_calendar_start.setText(first["start_dt"].strftime(
                "%Y-%m-%d %H:%M") if first["start_dt"] else "---")
            self.lbl_calendar_end.setText(last["end_dt"].strftime(
                "%Y-%m-%d %H:%M") if last["end_dt"] else "---")
        else:
            self.lbl_calendar_start.setText("---")
            self.lbl_calendar_end.setText("---")

    def _calendar_segment_at_seconds(self, seconds_from_start):
        if not self.calendar_segments:
            return None
        s = max(0.0, min(float(seconds_from_start),
                self.calendar_total_duration_s))
        for segment in self.calendar_segments:
            # Use strict boundary to avoid "sticking" on zero-duration segments.
            if s < segment["end_offset_s"] or segment is self.calendar_segments[-1]:
                return segment
        return self.calendar_segments[-1]

    def _calendar_point_for_seconds(self, seconds_from_start):
        segment = self._calendar_segment_at_seconds(seconds_from_start)
        if not segment:
            return None, None

        geom = segment["geometry"]
        if geom is None or geom.isEmpty():
            return None, segment

        seg_duration = max(0.0, float(segment["duration_s"]))
        if seg_duration <= 1e-6:
            # Zero-duration segments should not snap back to their start; show their end.
            distance = max(0.0, geom.length())
        else:
            ratio = (
                float(seconds_from_start) - segment["start_offset_s"]
            ) / seg_duration
            ratio = max(0.0, min(1.0, ratio))
            if self._segment_should_reverse(segment):
                distance = geom.length() * (1.0 - ratio)
            else:
                distance = geom.length() * ratio

        point_geom = geom.interpolate(distance)
        if point_geom is None or point_geom.isEmpty():
            return None, segment
        point = point_geom.asPoint()
        return QgsPointXY(point.x(), point.y()), segment

    def _calendar_time_text(self, seconds_from_start, segment=None):
        """Format absolute timeline time for the given offset in seconds."""
        if not self.calendar_segments:
            return "---"
        if segment is None:
            segment = self._calendar_segment_at_seconds(seconds_from_start)
        if segment is None:
            return "---"
        try:
            local_seconds = max(0.0, float(
                seconds_from_start) - float(segment.get("start_offset_s", 0.0)))
        except Exception:
            local_seconds = 0.0
        try:
            seg_duration = max(0.0, float(segment.get("duration_s") or 0.0))
        except Exception:
            seg_duration = 0.0
        local_seconds = min(local_seconds, seg_duration)

        segment_start = segment.get("start_dt")
        if segment_start:
            try:
                return (segment_start + timedelta(seconds=local_seconds)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        # Fallback to first known start if segment time attributes are missing.
        base_start = self.calendar_segments[0].get(
            "start_dt") if self.calendar_segments else None
        if base_start:
            try:
                clamped = max(0.0, min(float(seconds_from_start),
                              float(self.calendar_total_duration_s)))
                return (base_start + timedelta(seconds=clamped)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        return "---"

    def _sync_calendar_vessel_marker_playback_style(self):
        """Red vessel marker when idle; green while timeline playback is running."""
        m = getattr(self, "calendar_current_marker", None)
        if m is None:
            return
        if getattr(self, "calendar_is_playing", False):
            m.setColor(QColor(0, 145, 55))
            m.setFillColor(QColor(0, 145, 55, 118))
        else:
            m.setColor(QColor(255, 0, 0))
            m.setFillColor(QColor(255, 0, 0, 110))

    def _sync_calendar_markers_with_time(self):
        self._sync_calendar_vessel_marker_playback_style()

        # Vessel marker follows Optimized_Path segment geometry (calendar_segments), not the
        # calendar canvas layer stack — keep it visible even when all preview layers are off.
        seconds_from_start = float(self.slider_calendar.value())
        point, segment = self._calendar_point_for_seconds(seconds_from_start)
        if point is None:
            self.calendar_current_marker.hide()
            self.lbl_calendar_current.setText("Vessel: ---")
            return

        self.calendar_current_marker.setCenter(point)
        self.calendar_current_marker.show()

        self.lbl_calendar_current.setText(
            f"Vessel: {self._calendar_time_text(seconds_from_start, segment)}")
        self._calendar_follow_center_if_active(point)
        self.calendar_canvas.refresh()

    def _calendar_center_map_on_point(self, center: QgsPointXY):
        """Pan the calendar canvas so ``center`` becomes the middle of the view (same scale)."""
        if center is None:
            return
        try:
            ext = self.calendar_canvas.extent()
        except Exception:
            return
        try:
            w = float(ext.width())
            h = float(ext.height())
        except Exception:
            return
        if w <= 0.0 or h <= 0.0:
            return
        hw = w / 2.0
        hh = h / 2.0
        cx, cy = float(center.x()), float(center.y())
        try:
            self.calendar_canvas.setExtent(
                QgsRectangle(cx - hw, cy - hh, cx + hw, cy + hh))
        except Exception:
            return

    def _calendar_follow_smooth_pan_toward(self, vessel_point: QgsPointXY):
        """Ease map centre toward the vessel each frame (cinematic follow vs hard snaps)."""
        if vessel_point is None:
            return
        try:
            ext = self.calendar_canvas.extent()
        except Exception:
            return
        try:
            w = float(ext.width())
            h = float(ext.height())
        except Exception:
            return
        if w <= 0.0 or h <= 0.0:
            return
        mx = (ext.xMinimum() + ext.xMaximum()) / 2.0
        my = (ext.yMinimum() + ext.yMaximum()) / 2.0
        vx = float(vessel_point.x())
        vy = float(vessel_point.y())
        dx = vx - mx
        dy = vy - my
        dist = math.hypot(dx, dy)
        try:
            mpp = max(
                1e-18, float(self.calendar_canvas.mapSettings().mapUnitsPerPixel()))
        except Exception:
            mpp = 1.0
        # Stronger pull when the vessel is far from the map centre; gentle when almost aligned.
        pix = dist / mpp
        alpha = min(0.62, max(0.12, 0.11 + pix / 420.0))
        if dist <= mpp * 1.25:
            new_mx, new_my = vx, vy
        else:
            new_mx = mx + alpha * dx
            new_my = my + alpha * dy
        hw = w / 2.0
        hh = h / 2.0
        try:
            self.calendar_canvas.setExtent(
                QgsRectangle(new_mx - hw, new_my - hh,
                             new_mx + hw, new_my + hh)
            )
        except Exception:
            return

    def _calendar_follow_center_if_active(self, vessel_point: QgsPointXY):
        if not getattr(self, "calendar_is_playing", False):
            return
        ch = getattr(self, "chk_calendar_follow", None)
        if ch is None or not ch.isChecked():
            return
        self._calendar_follow_smooth_pan_toward(vessel_point)

    def _calendar_apply_play_timer_interval_for_follow(self):
        """
        When Follow is on, use a higher frame rate so camera easing and the marker move more fluidly.
        Simulated time per real second is kept by scaling the slider step with the interval.
        """
        ch = getattr(self, "chk_calendar_follow", None)
        follow = ch is not None and ch.isChecked()
        try:
            if getattr(self, "chk_calendar_realtime", None) and self.chk_calendar_realtime.isChecked():
                new_iv = 320 if follow else 1000
            else:
                new_iv = 50 if follow else 120
        except Exception:
            new_iv = 120
        try:
            was_running = self.calendar_play_timer.isActive()
            if was_running:
                self.calendar_play_timer.stop()
            self.calendar_play_timer.setInterval(int(new_iv))
            if was_running:
                self.calendar_play_timer.start()
        except Exception:
            pass

    def _calendar_sim_step_for_tick(self):
        """Simulated seconds advanced per play tick; scales when the play timer interval changes."""
        try:
            T = float(self.calendar_play_timer.interval())
        except Exception:
            T = 120.0
        rt = getattr(self, "chk_calendar_realtime",
                     None) and self.chk_calendar_realtime.isChecked()
        if rt:
            ref = 1000.0
            base = max(1.0, float(self.calendar_playback_speed * 1))
        else:
            ref = 120.0
            base = max(1.0, float(self.calendar_playback_speed * 30))
        return max(1, int(round(base * (T / ref))))

    def _on_calendar_follow_toggled(self, checked):
        if checked and getattr(self, "calendar_is_playing", False):
            try:
                seconds = float(self.slider_calendar.value())
            except Exception:
                seconds = 0.0
            pt, _ = self._calendar_point_for_seconds(seconds)
            if pt is not None:
                self._calendar_center_map_on_point(pt)
        self._calendar_apply_play_timer_interval_for_follow()

    def _on_calendar_slider_changed(self, _value):
        self._sync_calendar_markers_with_time()

    def _toggle_calendar_playback(self):
        if self.calendar_is_playing:
            self.calendar_play_timer.stop()
            self.calendar_is_playing = False
            self.btn_calendar_play.setText("Play")
            try:
                self.calendar_pulse_timer.start()
            except Exception:
                pass
            self._calendar_apply_play_timer_interval_for_follow()
        else:
            if self.slider_calendar.value() >= self.slider_calendar.maximum():
                self.slider_calendar.setValue(0)
            self.calendar_is_playing = True
            self.btn_calendar_play.setText("Pause")
            # Keep pulse timer running during Play so the green vessel marker still “breathes”.
            self._calendar_apply_play_timer_interval_for_follow()
            self.calendar_play_timer.start()
            self._sync_calendar_markers_with_time()
            try:
                if getattr(self, "chk_calendar_follow", None) and self.chk_calendar_follow.isChecked():
                    pt, _ = self._calendar_point_for_seconds(
                        float(self.slider_calendar.value()))
                    if pt is not None:
                        self._calendar_center_map_on_point(pt)
            except Exception:
                pass
        self._sync_calendar_vessel_marker_playback_style()
        self._update_calendar_follow_checkbox_enabled()

    def _cycle_calendar_speed(self):
        self.calendar_playback_speed *= 2
        if self.calendar_playback_speed > 16:
            self.calendar_playback_speed = 1
        self._update_calendar_speed_button_label()

    def _on_calendar_realtime_toggled(self, _checked):
        """
        Switch between fast preview and real-time-like playback.
        """
        was_playing = self.calendar_is_playing
        if was_playing:
            try:
                self.calendar_play_timer.stop()
            except Exception:
                was_playing = False

        self._calendar_apply_play_timer_interval_for_follow()

        self._update_calendar_speed_button_label()

        if was_playing:
            try:
                self.calendar_play_timer.start()
            except Exception:
                pass

    def _calendar_effective_playback_factor(self):
        """
        Return how many simulated seconds advance per one real second.
        """
        try:
            interval_ms = float(self.calendar_play_timer.interval())
        except Exception:
            interval_ms = 120.0
        interval_s = max(0.001, interval_ms / 1000.0)
        # Match _advance_calendar_playback logic for step size.
        step_s = float(self._calendar_sim_step_for_tick())
        return step_s / interval_s

    def _calendar_jump_to_segment(self, predicate):
        """
        Generic helper: jump slider to the next segment where predicate(segment) is True.
        """
        if not self.calendar_segments:
            return
        current_s = float(self.slider_calendar.value())
        best_segment = None
        best_start = None
        for seg in self.calendar_segments:
            try:
                if not predicate(seg):
                    continue
                start_s = float(seg.get("start_offset_s", 0.0))
            except Exception:
                continue
            if start_s <= current_s:
                continue
            if best_start is None or start_s < best_start:
                best_start = start_s
                best_segment = seg
        if best_segment is None:
            return
        try:
            self.slider_calendar.setValue(int(round(best_start)))
        except Exception:
            pass

    def _calendar_jump_next_segment(self):
        """
        Jump to the start of the next segment (any type) after the current time.
        """
        self._calendar_jump_to_segment(lambda _seg: True)

    def _calendar_base_speed_knots(self):
        """
        Return nominal vessel line speed from simulation settings (knots), if available.
        """
        try:
            params = self.recalculation_context.get("sim_params", {}) or {}
            l2h = float(params.get(
                "avg_shooting_speed_low_to_high_knots", 0.0) or 0.0)
            h2l = float(params.get(
                "avg_shooting_speed_high_to_low_knots", 0.0) or 0.0)
            legacy = float(params.get("avg_shooting_speed_knots", 0.0) or 0.0)
            if l2h <= 0.0:
                l2h = legacy
            if h2l <= 0.0:
                h2l = legacy
            if l2h > 0.0 and h2l > 0.0:
                return (l2h + h2l) / 2.0
            return l2h if l2h > 0.0 else (h2l if h2l > 0.0 else None)
        except Exception:
            return None

    def _update_calendar_speed_button_label(self):
        """
        Keep button compact and show equivalent speed in tooltip.
        """
        base_label = f"{self.calendar_playback_speed}x"
        self.btn_calendar_speed.setText(base_label)
        base_kn = self._calendar_base_speed_knots()
        if not base_kn:
            self.btn_calendar_speed.setToolTip("Playback speed multiplier.")
            return
        effective_kn = base_kn * self._calendar_effective_playback_factor()
        self.btn_calendar_speed.setToolTip(
            f"Playback speed: {base_label}\n"
            f"Equivalent marker speed: ~{effective_kn:.0f} kn\n"
            f"Based on line speed: {base_kn:.2f} kn."
        )

    def _advance_calendar_playback(self):
        if not self.calendar_segments:
            self._toggle_calendar_playback()
            return
        step = self._calendar_sim_step_for_tick()
        next_value = self.slider_calendar.value() + step
        if next_value >= self.slider_calendar.maximum():
            next_value = self.slider_calendar.maximum()
            self.calendar_play_timer.stop()
            self.calendar_is_playing = False
            self.btn_calendar_play.setText("Play")
            self._update_calendar_follow_checkbox_enabled()
            try:
                self.calendar_pulse_timer.start()
            except Exception:
                pass
        self.slider_calendar.setValue(next_value)

    def _pulse_calendar_marker(self):
        # Pulse without hiding: toggle size every 0.5s (runs in Pause and during Play).
        self._calendar_pulse_big = not getattr(
            self, "_calendar_pulse_big", False)
        self.calendar_current_marker.setIconSize(
            18 if self._calendar_pulse_big else 10)
        # Force repaint so pulse is visible even without other events.
        try:
            self.calendar_canvas.refresh()
            self.calendar_canvas.repaint()
        except Exception:
            pass

    def _calendar_distance_to_seconds(self, distance_from_start):
        if not self.calendar_segments:
            return None, None, None
        best = None
        cursor = 0.0
        for segment in self.calendar_segments:
            geom = segment["geometry"]
            seg_len = geom.length() if geom else 0.0
            if seg_len <= 1e-9:
                continue
            if cursor + seg_len >= distance_from_start:
                local_distance = max(
                    0.0, min(seg_len, distance_from_start - cursor))
                ratio = local_distance / seg_len if seg_len > 0 else 0.0
                # Keep click->time mapping consistent with playback direction.
                if self._segment_should_reverse(segment):
                    ratio = 1.0 - ratio
                seconds = segment["start_offset_s"] + \
                    ratio * segment["duration_s"]
                interp_distance = local_distance
                if self._segment_should_reverse(segment):
                    interp_distance = max(0.0, seg_len - local_distance)
                point_geom = geom.interpolate(interp_distance)
                if point_geom and not point_geom.isEmpty():
                    pt = point_geom.asPoint()
                    best = (seconds, QgsPointXY(pt.x(), pt.y()), segment)
                break
            cursor += seg_len
        return best if best else (None, None, None)

    def _nearest_calendar_position(self, map_point):
        if not self.calendar_segments:
            return None, None, None
        hit_geom = QgsGeometry.fromPointXY(map_point)
        best_distance = None
        cumulative_length = 0.0
        best_result = (None, None, None)
        for segment in self.calendar_segments:
            geom = segment["geometry"]
            if geom is None or geom.isEmpty():
                continue
            try:
                distance_to_geom = geom.distance(hit_geom)
                projected_distance = geom.lineLocatePoint(hit_geom)
            except Exception:
                cumulative_length += geom.length()
                continue
            if projected_distance < 0:
                cumulative_length += geom.length()
                continue
            if best_distance is None or distance_to_geom < best_distance:
                best_distance = distance_to_geom
                seg_len = max(0.0, float(geom.length() or 0.0))
                local_distance = max(0.0, min(seg_len, projected_distance))
                ratio = (local_distance / seg_len) if seg_len > 1e-9 else 0.0
                if self._segment_should_reverse(segment):
                    ratio = 1.0 - ratio
                seconds = segment["start_offset_s"] + ratio * \
                    float(segment.get("duration_s") or 0.0)

                # Marker must stay exactly at projected cursor position on geometry.
                projected_geom = geom.interpolate(local_distance)
                if projected_geom and not projected_geom.isEmpty():
                    p = projected_geom.asPoint()
                    point = QgsPointXY(p.x(), p.y())
                else:
                    point = None
                best_result = (seconds, point, segment)
            cumulative_length += geom.length()
        return best_result

    def _update_calendar_hover_ui(self, seconds_from_start, point, segment):
        if seconds_from_start is None or point is None or segment is None:
            self.calendar_hover_marker.hide()
            self.lbl_calendar_cursor.setText("Marker: hover path")
            self.calendar_canvas.refresh()
            return
        self.calendar_hover_marker.setCenter(point)
        self.calendar_hover_marker.show()
        self.lbl_calendar_cursor.setText(
            f"Marker: {self._calendar_time_text(seconds_from_start, segment)}")
        self.calendar_canvas.refresh()

    def _on_calendar_hover(self, pt):
        seconds, point, segment = self._nearest_calendar_position(pt)
        self._update_calendar_hover_ui(seconds, point, segment)

    def _on_calendar_click(self, pt):
        self._clear_calendar_ruler()
        seconds, point, segment = self._nearest_calendar_position(pt)
        self._update_calendar_hover_ui(seconds, point, segment)
        if seconds is not None:
            self.slider_calendar.setValue(int(round(seconds)))

    @staticmethod
    def _calendar_haversine_m(a: QgsPointXY, b: QgsPointXY):
        """Great-circle distance in metres (fallback when QgsDistanceArea fails)."""
        try:
            lat1 = math.radians(float(a.y()))
            lon1 = math.radians(float(a.x()))
            lat2 = math.radians(float(b.y()))
            lon2 = math.radians(float(b.x()))
        except Exception:
            return None
        R = 6371000.0
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        h = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * \
            math.cos(lat2) * math.sin(dlon / 2.0) ** 2
        try:
            c = 2.0 * math.asin(min(1.0, math.sqrt(max(0.0, h))))
        except Exception:
            return None
        return float(R * c)

    def _calendar_map_distance_m(self, a: QgsPointXY, b: QgsPointXY):
        """Distance in metres between two map points (ellipsoid / planar / haversine fallbacks)."""
        if a is None or b is None:
            return None

        try:
            crs = self.calendar_canvas.mapSettings().destinationCrs()
            is_geo = crs.isGeographic()
        except Exception:
            crs = None
            is_geo = False

        if is_geo:
            try:
                ctx = QgsProject.instance().transformContext()
                da = QgsDistanceArea()
                da.setSourceCrs(crs, ctx)
                da.setEllipsoid(QgsProject.instance().ellipsoid())
                d = float(da.measureLine(a, b))
                if d == d and d >= 0.0:
                    return d
            except Exception:
                pass
            try:
                d = self._calendar_haversine_m(a, b)
                if d is not None and d == d and d >= 0.0:
                    return d
            except Exception:
                pass

        try:
            d_plan = float(math.hypot(
                float(b.x() - a.x()), float(b.y() - a.y())))
            if crs is not None and crs.isValid():
                try:
                    from qgis.core import QgsUnitTypes
                    try:
                        from qgis.core import Qgis
                        meters_unit = Qgis.DistanceUnit.Meters
                    except ImportError:
                        meters_unit = QgsUnitTypes.DistanceUnit.DistanceMeters
                    fac = float(QgsUnitTypes.fromUnitToUnitFactor(
                        crs.mapUnits(), meters_unit))
                    if fac > 0.0 and math.isfinite(fac):
                        return float(d_plan * fac)
                except Exception:
                    pass
            return d_plan
        except Exception:
            return None

    @staticmethod
    def _format_calendar_distance_compact(meters):
        """Ruler readout: ``1.5km`` or ``550m`` only (no cm/mm)."""
        if meters is None:
            return "—"
        m = float(meters)
        if m <= 0.0:
            return "0m"
        if m >= 1000.0:
            km = m / 1000.0
            if abs(km - round(km)) < 0.05:
                return f"{int(round(km))}km"
            return f"{km:.1f}km"
        if m < 1.0:
            return "0m"
        return f"{int(round(m))}m"

    def _calendar_set_distance_readout(self, text: str):
        lbl = getattr(self, "lbl_calendar_distance", None)
        if lbl is not None:
            try:
                lbl.setText(text)
            except Exception:
                pass

    def _calendar_ruler_tolerance_map_units(self):
        """Screen-based snap radius in map units (segment ends, then path)."""
        try:
            return max(1e-12, float(self.calendar_canvas.mapSettings().mapUnitsPerPixel()) * 16.0)
        except Exception:
            return 50.0

    def _snap_calendar_ruler_point(self, pt: QgsPointXY) -> QgsPointXY:
        """
        Return the point directly without snapping to lines.
        """
        if pt is None:
            return pt
        try:
            return QgsPointXY(float(pt.x()), float(pt.y()))
        except Exception:
            return pt

    def _clear_calendar_ruler(self):
        """Remove the acquisition-calendar distance ruler overlay."""
        self._calendar_measure_start = None
        ct = getattr(self, "calendar_tool", None)
        if ct is not None:
            ct._ruler_drag = False
        rb = getattr(self, "_calendar_measure_rubber", None)
        if rb is not None:
            try:
                rb.reset(QgsWkbTypes.LineGeometry)
                rb.hide()
            except Exception:
                pass
        self._calendar_set_distance_readout("—")
        try:
            self.calendar_canvas.refresh()
        except Exception:
            pass

    def _on_calendar_ruler_press(self, pt: QgsPointXY):
        snapped = self._snap_calendar_ruler_point(pt)
        self._calendar_measure_start = QgsPointXY(snapped.x(), snapped.y())
        rb = getattr(self, "_calendar_measure_rubber", None)
        if rb is not None:
            try:
                rb.reset(QgsWkbTypes.LineGeometry)
                rb.addPoint(self._calendar_measure_start)
                rb.addPoint(self._calendar_measure_start)
                rb.show()
            except Exception:
                pass
        self._calendar_set_distance_readout("...")
        try:
            self.calendar_canvas.refresh()
        except Exception:
            pass

    def _on_calendar_ruler_move(self, pt: QgsPointXY):
        if self._calendar_measure_start is None:
            return
        end_pt = self._snap_calendar_ruler_point(pt)
        rb = getattr(self, "_calendar_measure_rubber", None)
        if rb is not None:
            try:
                rb.reset(QgsWkbTypes.LineGeometry)
                rb.addPoint(self._calendar_measure_start)
                rb.addPoint(end_pt)
                rb.show()
            except Exception:
                pass
        dist = self._calendar_map_distance_m(
            self._calendar_measure_start, end_pt)
        self._calendar_set_distance_readout(
            self._format_calendar_distance_compact(dist))
        try:
            self.calendar_canvas.refresh()
        except Exception:
            pass

    def _on_calendar_ruler_release(self, pt: QgsPointXY):
        start = self._calendar_measure_start
        self._calendar_measure_start = None
        if start is None:
            return
        end_pt = self._snap_calendar_ruler_point(pt)
        dist = self._calendar_map_distance_m(start, end_pt)
        rb = getattr(self, "_calendar_measure_rubber", None)
        if rb is not None:
            try:
                rb.reset(QgsWkbTypes.LineGeometry)
                rb.addPoint(start)
                rb.addPoint(end_pt)
                rb.show()
            except Exception:
                pass
        self._calendar_set_distance_readout(
            self._format_calendar_distance_compact(dist))
        try:
            self.calendar_canvas.refresh()
        except Exception:
            pass

    def closeEvent(self, event):
        self._clear_turn_node_overlay()
        self._clear_calendar_ruler()
        self._dispose_calendar_path_preview_layer()
        ov = getattr(self, "_posiview_overlay", None)
        if ov is not None:
            try:
                ov.teardown()
            except Exception:
                pass
            self._posiview_overlay = None
        try:
            self.calendar_play_timer.stop()
            self.calendar_pulse_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)

    def _pick_tolerance_map_units(self):
        try:
            return max(5.0, self.canvas.mapSettings().mapUnitsPerPixel() * 12.0)
        except Exception:
            return 50.0

    def _resolve_optimized_path_layer(self):
        try:
            lyrs = QgsProject.instance().mapLayersByName("Optimized_Path")
        except RuntimeError:
            return None
        if not lyrs:
            return None
        lyr = lyrs[0]
        return lyr if _vector_layer_alive(lyr) else None

    def _clear_turn_node_overlay(self):
        rb = getattr(self, "_turn_radius_circle_rb", None)
        if rb is not None:
            try:
                rb.reset(QgsWkbTypes.LineGeometry)
                rb.hide()
            except Exception:
                pass

    @staticmethod
    def _circumcenter_xy(a: QgsPointXY, b: QgsPointXY, c: QgsPointXY):
        """Return circumcenter of triangle a-b-c, or None if nearly collinear."""
        ax, ay = a.x(), a.y()
        bx, by = b.x(), b.y()
        cx, cy = c.x(), c.y()
        d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-12:
            return None
        a2 = ax * ax + ay * ay
        b2 = bx * bx + by * by
        c2 = cx * cx + cy * cy
        ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
        uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
        return QgsPointXY(ux, uy)

    def _update_turn_radius_circle_rubber(self, path_layer, center: QgsPointXY, radius_m: float):
        if center is None or radius_m <= 0.05 or not _vector_layer_alive(path_layer):
            if self._turn_radius_circle_rb:
                self._turn_radius_circle_rb.reset(QgsWkbTypes.LineGeometry)
                self._turn_radius_circle_rb.hide()
            return
        n = 48
        ring = []
        for i in range(n + 1):
            t = 2.0 * math.pi * i / n
            ring.append(
                QgsPointXY(center.x() + radius_m * math.cos(t),
                           center.y() + radius_m * math.sin(t))
            )
        circ = QgsGeometry.fromPolylineXY(ring)
        if self._turn_radius_circle_rb is None:
            self._turn_radius_circle_rb = QgsRubberBand(
                self.canvas, QgsWkbTypes.LineGeometry)
            self._turn_radius_circle_rb.setColor(QColor(60, 100, 220, 200))
            self._turn_radius_circle_rb.setWidth(2)
        self._turn_radius_circle_rb.setToGeometry(circ, path_layer)
        self._turn_radius_circle_rb.show()

    def _update_turn_node_overlay(self, feat, path_layer):
        """Radius guide ring only (no vertex handles — middle-arc edit not implemented yet)."""
        self._clear_turn_node_overlay()
        if not feat or not _vector_layer_alive(path_layer):
            return
        g = feat.geometry()
        if not g or g.isEmpty():
            return

        pts = g.asPolyline()
        center_xy = None
        if len(pts) >= 8:
            n = len(pts)
            i0, i1, i2 = n // 4, n // 2, 3 * n // 4
            center_xy = self._circumcenter_xy(
                QgsPointXY(pts[i0]), QgsPointXY(pts[i1]), QgsPointXY(pts[i2])
            )
        if center_xy is None and len(pts) >= 2:
            mid = pts[len(pts) // 2]
            center_xy = QgsPointXY(mid.x(), mid.y())
        r_guide = float(self.spin_radius.value()) if hasattr(
            self, "spin_radius") else 0.0
        if center_xy is not None and r_guide > 0:
            self._update_turn_radius_circle_rubber(
                path_layer, center_xy, r_guide)

        self.canvas.refresh()

    def _on_turn_radius_spin_for_handles(self, *_args):
        if self.selected_turn_feat and _vector_layer_alive(self._turn_editor_path_layer):
            self._update_turn_node_overlay(
                self.selected_turn_feat, self._turn_editor_path_layer)

    def _turn_editor_visible_map_layers(self):
        """Layers shown on the Turn Editor canvas."""
        layers = []
        prj = QgsProject.instance()
        root = prj.layerTreeRoot()

        def _is_layer_visible_in_toc(lyr):
            try:
                node = root.findLayer(lyr.id()) if root is not None else None
            except Exception:
                node = None
            if node is None:
                return True
            try:
                return bool(node.isVisible())
            except Exception:
                try:
                    return bool(node.itemVisibilityChecked())
                except Exception:
                    return True

        for name in ["Optimized_Path", "Generated_Survey_Lines", "Generated Run-In Run-Out"]:
            for lyr in prj.mapLayersByName(name):
                if _vector_layer_alive(lyr) and _is_layer_visible_in_toc(lyr):
                    layers.append(lyr)

        params = self.recalculation_context.get("sim_params", {})
        nogo = params.get("nogo_layer")
        if nogo and _vector_layer_alive(nogo) and _is_layer_visible_in_toc(nogo) and nogo not in layers:
            layers.append(nogo)
        return layers

    def _turn_zoom_full_extent(self):
        layers = self._turn_editor_visible_map_layers()
        if not layers:
            return
        extent = QgsRectangle()
        for lyr in layers:
            try:
                lyr.updateExtents()
                ex = lyr.extent()
                if ex and not ex.isEmpty():
                    if extent.isEmpty():
                        extent = QgsRectangle(ex)
                    else:
                        extent.combineExtentWith(ex)
            except Exception:
                continue
        if not extent.isEmpty():
            try:
                extent.scale(1.05)
            except Exception:
                pass
            self.canvas.setExtent(extent)
            self.canvas.refresh()

    def _refresh_canvas_layers(self, reset_extent=False):
        try:
            self.canvas.setDestinationCrs(QgsProject.instance().crs())
        except Exception:
            pass
        layers = self._turn_editor_visible_map_layers()

        if layers:
            self.canvas.setLayers(layers)
            if reset_extent:
                extent = QgsRectangle()
                for lyr in layers:
                    if _vector_layer_alive(lyr):
                        try:
                            lyr.updateExtents()
                            ex = lyr.extent()
                            if ex and not ex.isEmpty():
                                if extent.isEmpty():
                                    extent = QgsRectangle(ex)
                                else:
                                    extent.combineExtentWith(ex)
                        except Exception:
                            pass
                if not extent.isEmpty():
                    try:
                        extent.scale(1.05)
                    except Exception:
                        pass
                    self.canvas.setExtent(extent)
            self.canvas.clearCache()
            self.canvas.refresh()
        else:
            # Keep canvas layer list in sync when main-TOC visibility hides everything,
            # so PosiView / other overlays still repaint on a defined (last) extent.
            self.canvas.setLayers([])
            self.canvas.clearCache()
            self.canvas.refresh()

    def _sync_parent_simulation_snapshot(self):
        """Keep dock ``last_simulation_result`` aligned while the dialog is open (seq, turns, cost)."""
        parent = self.parent()
        if parent is None or not hasattr(parent, "last_simulation_result"):
            return
        snap = parent.last_simulation_result
        if snap is None:
            return
        snap["seq"] = list(self.current_sequence_info.get("seq", []))
        snap["state"] = copy.deepcopy(
            self.current_sequence_info.get("state", {}))
        snap["custom_turns"] = copy.deepcopy(
            self.current_sequence_info.get("custom_turns", {}))
        c = self.current_sequence_info.get("cost")
        if c is not None:
            snap["cost"] = c

    def _post_timing_refresh(self):
        """After segment timings are current: sync dock, optional total recalc hook, map redraw."""
        self._sync_parent_simulation_snapshot()
        if callable(self.recalculation_callback):
            try:
                self.recalculation_callback(
                    self.current_sequence_info.get("seq", []),
                    (self.current_sequence_info.get("state")
                     or {}).get("line_directions", {}),  # noqa: W503
                    self.current_sequence_info.get("custom_turns"),
                )
            except TypeError:
                self.recalculation_callback(
                    self.current_sequence_info.get("seq", []),
                    (self.current_sequence_info.get("state")
                     or {}).get("line_directions", {}),  # noqa: W503
                )
        redraw_cb = self.recalculation_context.get("redraw_callback")
        if redraw_cb:
            redraw_cb(self.current_sequence_info)
        QtCore.QTimer.singleShot(100, self._post_redraw_update)

    def _trigger_redraw(self):
        """ Forces main dock widget to re-calculate and re-draw the map with new parameters. """
        self.run_full_timing_calculation_and_update(show_message=False)
        self._post_timing_refresh()

    def _post_redraw_update(self):
        self._update_rubber_band_geometry()
        self._refresh_canvas_layers(reset_extent=False)
        self._refresh_acquisition_calendar(reset_extent=False)

    def _update_rubber_band_geometry(self):
        if not self.selected_turn_key or not self.rubber_band:
            return

        path_layer = self._resolve_optimized_path_layer()
        if not path_layer:
            return
        self._turn_editor_path_layer = path_layer
        try:
            for feat in path_layer.getFeatures():
                if str(feat.attribute("SegmentType")).startswith("Turn"):
                    start_line = feat.attribute("StartLine")
                    end_line = feat.attribute("EndLine")
                    if start_line and end_line and str(start_line) != "NULL" and str(end_line) != "NULL":
                        key = f"{start_line}_{end_line}"
                    else:
                        key = str(feat.attribute("SeqOrder"))

                    if key == self.selected_turn_key:
                        self.selected_turn_feat = feat
                        self.rubber_band.hide()
                        self.rubber_band.setToGeometry(
                            feat.geometry(), path_layer)
                        self.rubber_band.show()
                        self._update_turn_node_overlay(feat, path_layer)
                        self._refresh_selected_turn_label()
                        break
        except RuntimeError:
            pass

    def _on_turn_clicked(self, pt):
        path_layer = self._resolve_optimized_path_layer()
        if not path_layer:
            return

        tol = self._pick_tolerance_map_units()
        hit_g = QgsGeometry.fromPointXY(pt)
        best_d = tol
        closest_feat = None

        try:
            for feat in path_layer.getFeatures():
                seg_type = str(feat.attribute("SegmentType"))
                if "Turn" not in seg_type:
                    continue
                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    continue
                d_line = geom.distance(hit_g)
                if d_line < best_d:
                    best_d = d_line
                    closest_feat = feat
        except RuntimeError:
            return

        if closest_feat is not None:
            self._select_turn(closest_feat, path_layer)
        else:
            self._clear_turn_map_selection()

    def _refresh_selected_turn_label(self):
        if not self.selected_turn_feat or not self.selected_turn_key:
            self.lbl_selected_turn.setText("Selected Turn: None")
            return
        start_line = self.selected_turn_feat.attribute("StartLine")
        end_line = self.selected_turn_feat.attribute("EndLine")
        if start_line and end_line and str(start_line) != "NULL" and str(end_line) != "NULL":
            base = f"Selected Turn: L{start_line} → L{end_line}"
        else:
            seq_order = self.selected_turn_feat.attribute("SeqOrder")
            base = f"Selected Turn: Segment {seq_order}"
        td = self.current_sequence_info.get(
            "custom_turns", {}).get(self.selected_turn_key, {})
        radius = td.get("radius")
        if radius is not None:
            base += f"  ·  R={float(radius):.1f} m"
        mode = td.get("mode")
        if mode:
            base += f"  ·  {mode}"
        self.lbl_selected_turn.setText(base)

    def _select_turn(self, feat, layer):
        if not _vector_layer_alive(layer):
            return
        self.selected_turn_feat = feat
        self._turn_editor_path_layer = layer

        start_line = feat.attribute("StartLine")
        end_line = feat.attribute("EndLine")

        if start_line and end_line and str(start_line) != 'NULL' and str(end_line) != 'NULL':
            self.selected_turn_key = f"{start_line}_{end_line}"
        else:
            seq_order = feat.attribute("SeqOrder")
            self.selected_turn_key = str(seq_order)

        if not self.rubber_band:
            self.rubber_band = QgsRubberBand(
                self.canvas, QgsWkbTypes.LineGeometry)
            self.rubber_band.setColor(QColor(255, 0, 0))
            self.rubber_band.setWidth(4)

        self.rubber_band.setToGeometry(feat.geometry(), layer)

        # Set default or custom values
        sim_params = self.recalculation_context.get("sim_params", {})

        # Check if we have overrides
        custom_turns = self.current_sequence_info.get("custom_turns", {})
        turn_data = custom_turns.get(self.selected_turn_key, {})

        self.spin_radius.blockSignals(True)
        self.spin_radius.setValue(turn_data.get(
            "radius", sim_params.get("turn_radius_meters", 500)))
        self.spin_radius.blockSignals(False)

        # Set mode combo box
        global_mode = "Teardrop" if sim_params.get(
            "acquisition_mode_key", "teardrop") == "teardrop" else "Racetrack"
        saved_mode = turn_data.get("mode", global_mode)

        self.combo_mode.blockSignals(True)
        idx = self.combo_mode.findText(saved_mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self.combo_mode.blockSignals(False)

        self._update_turn_node_overlay(feat, layer)
        self._refresh_selected_turn_label()

    def _clear_turn_map_selection(self):
        self.selected_turn_feat = None
        self.selected_turn_key = None
        self._clear_turn_node_overlay()
        if self.rubber_band:
            try:
                self.rubber_band.reset(QgsWkbTypes.LineGeometry)
                self.rubber_band.hide()
            except Exception:
                pass
        self.lbl_selected_turn.setText("Selected Turn: None")

    def _save_state_for_undo(self):
        """Push custom_turns and seq for Undo (Turn Editor)."""
        if "custom_turns" not in self.current_sequence_info:
            self.current_sequence_info["custom_turns"] = {}
        self.turn_history.append(
            {
                "custom_turns": copy.deepcopy(self.current_sequence_info["custom_turns"]),
                "seq": list(self.current_sequence_info.get("seq") or []),
            }
        )

    def undo_turn_edits(self):
        """Reverts the last turn edit applied."""
        if not self.turn_history:
            QMessageBox.warning(self, "Undo", "Nothing to undo.")
            return
        snap = self.turn_history.pop()
        if isinstance(snap, dict) and "custom_turns" in snap:
            self.current_sequence_info["custom_turns"] = copy.deepcopy(
                snap["custom_turns"])
            if "seq" in snap:
                self.current_sequence_info["seq"] = list(snap["seq"])
        else:
            self.current_sequence_info["custom_turns"] = copy.deepcopy(snap)
        self._clear_turn_map_selection()
        self.populate_table()
        self._trigger_redraw()
        self._refresh_selected_turn_label()

    def apply_turn_edits(self):
        if not self.selected_turn_feat:
            QMessageBox.warning(self, "No Turn Selected",
                                "Please select a turn segment first.")
            return

        self._save_state_for_undo()
        turn_key = self.selected_turn_key
        if "custom_turns" not in self.current_sequence_info:
            self.current_sequence_info["custom_turns"] = {}

        if turn_key not in self.current_sequence_info["custom_turns"]:
            self.current_sequence_info["custom_turns"][turn_key] = {}

        self.current_sequence_info["custom_turns"][turn_key]["radius"] = self.spin_radius.value(
        )
        self.current_sequence_info["custom_turns"][turn_key]["mode"] = self.combo_mode.currentText(
        )

        self._trigger_redraw()

    def set_turn_sense_left(self):
        self._set_turn_flip(False)

    def set_turn_sense_right(self):
        self._set_turn_flip(True)

    def _set_turn_flip(self, flip_val):
        if not self.selected_turn_feat:
            QMessageBox.warning(self, "No Turn Selected",
                                "Please select a turn segment first.")
            return

        self._save_state_for_undo()
        turn_key = self.selected_turn_key
        if "custom_turns" not in self.current_sequence_info:
            self.current_sequence_info["custom_turns"] = {}

        if turn_key not in self.current_sequence_info["custom_turns"]:
            self.current_sequence_info["custom_turns"][turn_key] = {}

        self.current_sequence_info["custom_turns"][turn_key]["flip"] = flip_val

        self._trigger_redraw()

# --- Excel auto-open (was excel_open.py; inlined to reduce plugin file count) ---


def _bring_excel_hwnd_forward(hwnd: int) -> None:
    """Activate Excel without changing size (avoid SW_RESTORE — it demaximizes)."""
    if not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        SW_SHOW = 5
        user32.ShowWindow(int(hwnd), SW_SHOW)
        user32.SetForegroundWindow(int(hwnd))
    except Exception:
        pass


def _schedule_delayed_excel_foreground(
    hwnd: int, delay_s: float = 0.28, *, maximize: bool = True
) -> None:
    """Qt/QGIS repaints after COM can steal focus; raise Excel again."""

    def _go():
        _bring_excel_hwnd_forward(hwnd)
        if maximize and hwnd:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                SW_SHOWMAXIMIZED = 3
                user32.ShowWindow(int(hwnd), SW_SHOWMAXIMIZED)
                user32.SetForegroundWindow(int(hwnd))
            except Exception:
                pass

    t = threading.Timer(delay_s, _go)
    t.daemon = True
    t.start()


def open_workbook_in_excel(file_path: str, *, maximize: bool = True) -> bool:
    """
    Open file in Microsoft Excel when possible.
    Windows: win32com, Visible, optional xlMaximized, HWND foreground + delayed repeat.
    Other OS: xdg-open / open via QDesktopServices.
    """
    path = os.path.normpath(os.path.abspath(file_path))
    if not os.path.isfile(path):
        log.warning("open_workbook_in_excel: file missing: %s", path)
        return False

    if os.name == "nt":
        try:
            import win32com.client

            excel = win32com.client.Dispatch("Excel.Application")
            excel.Visible = True
            wb = excel.Workbooks.Open(path)

            if maximize:
                try:
                    excel.WindowState = -4140  # xlMinimized
                    excel.WindowState = -4137  # xlMaximized
                except Exception:
                    pass

            wb.Activate()
            if maximize:
                try:
                    excel.WindowState = -4137  # xlMaximized again after Activate
                except Exception:
                    pass

            try:
                excel_hwnd = int(excel.Hwnd)
            except Exception:
                excel_hwnd = 0
            _bring_excel_hwnd_forward(excel_hwnd)
            if maximize:
                try:
                    excel.WindowState = -4137
                except Exception:
                    pass
            _schedule_delayed_excel_foreground(excel_hwnd, maximize=maximize)
            log.info("Opened workbook in Excel via COM: %s", path)
            return True
        except ImportError:
            log.debug("pywin32 not available; using os.startfile for %s", path)
        except Exception as e:
            log.warning("Excel COM open failed (%s); trying os.startfile", e)
        try:
            os.startfile(path)
            return True
        except OSError as e:
            log.error("os.startfile failed: %s", e)
            return False

    try:
        from qgis.PyQt.QtGui import QDesktopServices
        from qgis.PyQt.QtCore import QUrl

        return QDesktopServices.openUrl(QUrl.fromLocalFile(path))
    except Exception as e:
        log.warning("Fallback open failed: %s", e)
        return False
