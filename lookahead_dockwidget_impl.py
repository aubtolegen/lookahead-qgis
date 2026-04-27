import os
import sqlite3
import traceback
import logging
import math
import time
from datetime import datetime, timedelta
import sys
from collections import Counter, defaultdict
import copy
import csv # Needed for CSV export helper

# --- Set up logging ---
root_logger = logging.getLogger("lookahead_planner")
log = root_logger


class _SafeStreamHandler(logging.StreamHandler):
    """Stream handler that tolerates a missing/closed stream in embedded runtimes."""

    def emit(self, record):
        try:
            stream = getattr(self, "stream", None)
            if stream is None or not hasattr(stream, "write"):
                return
            msg = self.format(record)
            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            pass


def shutdown_obn_logging():
    """Close plugin-owned logger handlers so files are not locked on Windows."""
    plugin_logger = logging.getLogger("lookahead_planner")
    handlers = list(plugin_logger.handlers)
    for handler in handlers:
        try:
            handler.flush()
        except Exception:
            pass
        try:
            handler.close()
        except Exception:
            pass
        try:
            plugin_logger.removeHandler(handler)
        except Exception:
            pass


# Sanitize inherited handlers from previous hot-reloads / older plugin versions.
for _h in list(root_logger.handlers):
    bad_stream_handler = (
        isinstance(_h, logging.StreamHandler)
        and not isinstance(_h, _SafeStreamHandler)
        and not hasattr(getattr(_h, "stream", None), "write")
    )
    if bad_stream_handler:
        try:
            root_logger.removeHandler(_h)
        except Exception:
            pass
        try:
            _h.close()
        except Exception:
            pass

has_safe_console = any(isinstance(h, _SafeStreamHandler) for h in root_logger.handlers)
if not has_safe_console:
    console_handler = _SafeStreamHandler(stream=getattr(sys, "stderr", None))
    console_formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

root_logger.propagate = False
root_logger.setLevel(logging.DEBUG)
log.setLevel(logging.DEBUG)
log.info("Lookahead logger initialized (console logging only).")


# --- QGIS Imports ---
from qgis.core import (QgsProject, QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY,
                   QgsWkbTypes, QgsSymbol, QgsFeatureRequest, QgsMessageLog, QgsRasterLayer, Qgis,
                   QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol,
                   QgsSvgMarkerSymbolLayer, QgsSimpleMarkerSymbolLayer, QgsSimpleLineSymbolLayer, QgsSimpleFillSymbolLayer,
                   QgsVectorFileWriter, QgsRectangle, QgsMapLayerProxyModel, QgsFields,
                   QgsVectorLayerUtils, QgsRasterFileWriter, QgsRasterPipe, QgsRasterBlockFeedback,
                   QgsPoint, QgsSpatialIndex, QgsDistanceArea, QgsUnitTypes, QgsRendererCategory, QgsCategorizedSymbolRenderer,
                   QgsPointLocator, QgsFeatureSink, QgsPalLayerSettings, QgsLabelLineSettings, QgsTextFormat, QgsProperty,
                   QgsRuleBasedLabeling, QgsRuleBasedRenderer, QgsVectorLayerSimpleLabeling, QgsMarkerLineSymbolLayer,
                   QgsGeometryUtils, QgsTextBufferSettings, QgsSimpleLineSymbolLayer, QgsExpression, QgsArrowSymbolLayer, QgsSingleSymbolRenderer,QgsRendererCategory, QgsVectorLayerSimpleLabeling, QgsMapLayer)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt import QtWidgets, uic, QtCore
from qgis.PyQt.QtCore import pyqtSignal, Qt, QDateTime, QUrl
try:
    from qgis.PyQt.QtCore import QVariant
except Exception:
    from qgis.PyQt.QtCore import QMetaType

    class QVariant:  # Qt6/PyQt compatibility shim for field type enums.
        Int = QMetaType.Type.Int
        String = QMetaType.Type.QString
        Double = QMetaType.Type.Double
        DateTime = QMetaType.Type.QDateTime
        Bool = QMetaType.Type.Bool
from qgis.PyQt.QtWidgets import (
    QProgressDialog, QApplication, QFileDialog, QListWidget,
    QTableWidget, QListWidgetItem, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidgetItem, QAbstractItemView, QLabel, QHeaderView, QComboBox,
    QTextBrowser, QStackedWidget, QToolButton, QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)
from qgis.PyQt.QtGui import QColor, QIcon, QDesktopServices, QPixmap, QFont, QFontDatabase, QPalette

try:
    _QT_USER_ROLE = int(Qt.UserRole)
except AttributeError:
    _QT_USER_ROLE = int(Qt.ItemDataRole.UserRole)

try:
    _QT_TOOLBUTTON_TEXT_ONLY = Qt.ToolButtonStyle.ToolButtonTextOnly
except AttributeError:
    _QT_TOOLBUTTON_TEXT_ONLY = Qt.ToolButtonTextOnly

try:
    _QT_MENU_BUTTON_POPUP = QToolButton.ToolButtonPopupMode.MenuButtonPopup
    _QT_INSTANT_POPUP = QToolButton.ToolButtonPopupMode.InstantPopup
except AttributeError:
    _QT_MENU_BUTTON_POPUP = QToolButton.MenuButtonPopup
    _QT_INSTANT_POPUP = QToolButton.InstantPopup

try:
    _QSP_POLICY = QtWidgets.QSizePolicy.Policy
    _QSP_PREFERRED = _QSP_POLICY.Preferred
    _QSP_EXPANDING = _QSP_POLICY.Expanding
    _QSP_FIXED = _QSP_POLICY.Fixed
    _QSP_MAXIMUM = _QSP_POLICY.Maximum
except AttributeError:
    _QSP_PREFERRED = QtWidgets.QSizePolicy.Preferred
    _QSP_EXPANDING = QtWidgets.QSizePolicy.Expanding
    _QSP_FIXED = QtWidgets.QSizePolicy.Fixed
    _QSP_MAXIMUM = QtWidgets.QSizePolicy.Maximum

try:
    _QT_WAIT_CURSOR = Qt.CursorShape.WaitCursor
except AttributeError:
    _QT_WAIT_CURSOR = Qt.WaitCursor

try:
    _QT_ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft
    _QT_ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight
    _QT_ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    _QT_ALIGN_VCENTER = Qt.AlignmentFlag.AlignVCenter
except AttributeError:
    _QT_ALIGN_LEFT = Qt.AlignLeft
    _QT_ALIGN_RIGHT = Qt.AlignRight
    _QT_ALIGN_CENTER = Qt.AlignCenter
    _QT_ALIGN_VCENTER = Qt.AlignVCenter

try:
    _QFRAME_NO_FRAME = QtWidgets.QFrame.Shape.NoFrame
except AttributeError:
    _QFRAME_NO_FRAME = QtWidgets.QFrame.NoFrame

try:
    _QAIV_EXTENDED_SELECTION = QAbstractItemView.SelectionMode.ExtendedSelection
except AttributeError:
    _QAIV_EXTENDED_SELECTION = QAbstractItemView.ExtendedSelection

try:
    _QFONTDB_FIXED_FONT = QFontDatabase.SystemFont.FixedFont
except AttributeError:
    _QFONTDB_FIXED_FONT = QFontDatabase.FixedFont

try:
    _QDIALOG_ACCEPTED = QDialog.DialogCode.Accepted
except AttributeError:
    _QDIALOG_ACCEPTED = QDialog.Accepted

try:
    _QDIALOGBUTTONBOX_OK = QtWidgets.QDialogButtonBox.StandardButton.Ok
    _QDIALOGBUTTONBOX_CANCEL = QtWidgets.QDialogButtonBox.StandardButton.Cancel
except AttributeError:
    _QDIALOGBUTTONBOX_OK = QtWidgets.QDialogButtonBox.Ok
    _QDIALOGBUTTONBOX_CANCEL = QtWidgets.QDialogButtonBox.Cancel

try:
    _QFILEDIALOG_DONT_CONFIRM_OVERWRITE = QFileDialog.Option.DontConfirmOverwrite
except AttributeError:
    _QFILEDIALOG_DONT_CONFIRM_OVERWRITE = QFileDialog.DontConfirmOverwrite

try:
    _QT_SCROLLBAR_ALWAYS_OFF = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    _QT_SCROLLBAR_AS_NEEDED = Qt.ScrollBarPolicy.ScrollBarAsNeeded
except AttributeError:
    _QT_SCROLLBAR_ALWAYS_OFF = Qt.ScrollBarAlwaysOff
    _QT_SCROLLBAR_AS_NEEDED = Qt.ScrollBarAsNeeded

try:
    _QT_ELIDE_NONE = Qt.TextElideMode.ElideNone
except AttributeError:
    _QT_ELIDE_NONE = Qt.ElideNone

try:
    _QT_VERTICAL = Qt.Orientation.Vertical
except AttributeError:
    _QT_VERTICAL = Qt.Vertical

try:
    _QT_LEFT_BUTTON = Qt.MouseButton.LeftButton
except AttributeError:
    _QT_LEFT_BUTTON = Qt.LeftButton

_IS_QT6 = hasattr(Qt, "AlignmentFlag")

try:
    _QEVENT_MOUSE_MOVE = QtCore.QEvent.Type.MouseMove
    _QEVENT_MOUSE_BUTTON_PRESS = QtCore.QEvent.Type.MouseButtonPress
except AttributeError:
    _QEVENT_MOUSE_MOVE = QtCore.QEvent.MouseMove
    _QEVENT_MOUSE_BUTTON_PRESS = QtCore.QEvent.MouseButtonPress

try:
    _QT_SHIFT_MODIFIER = Qt.KeyboardModifier.ShiftModifier
    _QT_CONTROL_MODIFIER = Qt.KeyboardModifier.ControlModifier
except AttributeError:
    _QT_SHIFT_MODIFIER = Qt.ShiftModifier
    _QT_CONTROL_MODIFIER = Qt.ControlModifier

try:
    _QT_WINDOW_MODAL = Qt.WindowModality.WindowModal
except AttributeError:
    _QT_WINDOW_MODAL = Qt.WindowModal

try:
    _QT_BACKGROUND_ROLE = Qt.ItemDataRole.BackgroundRole
except AttributeError:
    _QT_BACKGROUND_ROLE = Qt.BackgroundRole

try:
    _QSTYLE_CE_ITEMVIEWITEM = QStyle.ControlElement.CE_ItemViewItem
    _QSTYLE_SE_ITEMVIEWITEMTEXT = QStyle.SubElement.SE_ItemViewItemText
    _QSTYLE_STATE_SELECTED = QStyle.StateFlag.State_Selected
except AttributeError:
    _QSTYLE_CE_ITEMVIEWITEM = QStyle.CE_ItemViewItem
    _QSTYLE_SE_ITEMVIEWITEMTEXT = QStyle.SE_ItemViewItemText
    _QSTYLE_STATE_SELECTED = QStyle.State_Selected

try:
    _QT_ELIDE_MIDDLE = Qt.TextElideMode.ElideMiddle
except AttributeError:
    _QT_ELIDE_MIDDLE = Qt.ElideMiddle

try:
    _QT_KEEP_ASPECT_RATIO = Qt.AspectRatioMode.KeepAspectRatio
    _QT_SMOOTH_TRANSFORMATION = Qt.TransformationMode.SmoothTransformation
except AttributeError:
    _QT_KEEP_ASPECT_RATIO = Qt.KeepAspectRatio
    _QT_SMOOTH_TRANSFORMATION = Qt.SmoothTransformation

try:
    _QT_TEXT_BROWSER_INTERACTION = Qt.TextInteractionFlag.TextBrowserInteraction
except AttributeError:
    _QT_TEXT_BROWSER_INTERACTION = Qt.TextBrowserInteraction

try:
    _QT_ISO_DATE = Qt.DateFormat.ISODate
except AttributeError:
    _QT_ISO_DATE = Qt.ISODate

try:
    _QT_MATCH_EXACTLY = Qt.MatchFlag.MatchExactly
except AttributeError:
    _QT_MATCH_EXACTLY = Qt.MatchExactly

try:
    _QT_RICH_TEXT = Qt.TextFormat.RichText
except AttributeError:
    _QT_RICH_TEXT = Qt.RichText

try:
    _QPALETTE_TEXT = QPalette.ColorRole.Text
    _QPALETTE_HIGHLIGHTED_TEXT = QPalette.ColorRole.HighlightedText
except AttributeError:
    _QPALETTE_TEXT = QPalette.Text
    _QPALETTE_HIGHLIGHTED_TEXT = QPalette.HighlightedText

try:
    _QGSMAPLAYERPROXYMODEL_POINTLAYER = QgsMapLayerProxyModel.Filter.PointLayer
    _QGSMAPLAYERPROXYMODEL_POLYGONLAYER = QgsMapLayerProxyModel.Filter.PolygonLayer
    _QGSMAPLAYERPROXYMODEL_VECTORLAYER = QgsMapLayerProxyModel.Filter.VectorLayer
except AttributeError:
    _QGSMAPLAYERPROXYMODEL_POINTLAYER = QgsMapLayerProxyModel.PointLayer
    _QGSMAPLAYERPROXYMODEL_POLYGONLAYER = QgsMapLayerProxyModel.PolygonLayer
    _QGSMAPLAYERPROXYMODEL_VECTORLAYER = QgsMapLayerProxyModel.VectorLayer

LINE_LIST_LEFT_TEXT_ROLE = _QT_USER_ROLE + 20
LINE_LIST_STATUS_TEXT_ROLE = _QT_USER_ROLE + 21


class LineListStatusDelegate(QStyledItemDelegate):
    """Draw left text + right-aligned status in list rows."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        left_text = index.data(LINE_LIST_LEFT_TEXT_ROLE) or opt.text or ""
        status_text = index.data(LINE_LIST_STATUS_TEXT_ROLE) or ""

        style = opt.widget.style() if opt.widget else QApplication.style()
        base_opt = QStyleOptionViewItem(opt)
        base_opt.text = ""
        style.drawControl(_QSTYLE_CE_ITEMVIEWITEM, base_opt, painter, opt.widget)

        text_rect = style.subElementRect(_QSTYLE_SE_ITEMVIEWITEMTEXT, base_opt, opt.widget)
        margin = 4
        gap = 8
        fm = opt.fontMetrics
        status_width = fm.horizontalAdvance(status_text) if status_text else 0
        left_x = text_rect.left() + margin
        right_x = text_rect.right() - margin
        status_rect = QtCore.QRect(max(left_x, right_x - status_width), text_rect.top(), status_width, text_rect.height())
        left_width = max(0, status_rect.left() - gap - left_x)
        left_rect = QtCore.QRect(left_x, text_rect.top(), left_width, text_rect.height())
        left_draw = fm.elidedText(left_text, _QT_ELIDE_MIDDLE, left_rect.width())

        painter.save()
        painter.setFont(opt.font)
        if opt.state & _QSTYLE_STATE_SELECTED:
            painter.setPen(opt.palette.color(_QPALETTE_HIGHLIGHTED_TEXT))
        else:
            painter.setPen(opt.palette.color(_QPALETTE_TEXT))
        painter.drawText(left_rect, _QT_ALIGN_VCENTER | _QT_ALIGN_LEFT, left_draw)
        if status_text:
            painter.drawText(status_rect, _QT_ALIGN_VCENTER | _QT_ALIGN_RIGHT, status_text)
        painter.restore()

# --- Compiled UI Import ---
from .lookahead_dockwidget_base_ui import Ui_OBNPlannerDockWidgetBase

# --- Import Custom Modules ---
try:
    from . import dubins_path as dubins_calc
    if not hasattr(dubins_calc, 'DECIMAL_ROUND'): dubins_calc.DECIMAL_ROUND = 7
    if not hasattr(dubins_calc, 'MAX_LINE_DISTANCE'): dubins_calc.MAX_LINE_DISTANCE = 10.0
    if not hasattr(dubins_calc, 'MAX_CURVE_ANGLE'): dubins_calc.MAX_CURVE_ANGLE = 10.0
    log.info("Successfully imported dubins_calc module.")
except ImportError as ie_dubins:
    log.critical(f"Failed to import local 'dubins_path.py': {ie_dubins}. Dubins calculations WILL FAIL.")
    class DummyDubins:
        def get_curve(*args, **kwargs): return None
        def dubins_path(*args, **kwargs): return None, [0,0,0], [0,0,0]
    dubins_calc = DummyDubins()

try:
    from . import rrt_planner
    log.info("Successfully imported rrt_planner module.")
except ImportError as ie_rrt:
    log.critical(f"Failed to import local 'rrt_planner.py': {ie_rrt}. Deviation calculations WILL FAIL.")
    rrt_planner = None

try:
    from .sequence_edit_dialog import custom_deepcopy, SequenceEditDialog
except ImportError as ie_custom:
    log.error(f"Failed to import custom_deepcopy or SequenceEditDialog: {ie_custom}")
    def custom_deepcopy(obj, memo=None): return obj
    SequenceEditDialog = None

try:
    from .optimized_path_schema import (
        build_optimized_path_attributes,
        optimized_path_field_specs,
        segment_speed_kn,
    )
except ImportError as ie_schema:
    log.error(f"Failed to import optimized_path_schema: {ie_schema}")
    build_optimized_path_attributes = None
    optimized_path_field_specs = None
    segment_speed_kn = None

try:
    from .lookahead_sim_speeds import (
        KNOTS_TO_MPS,
        shooting_speed_knots,
        shooting_speed_mps,
        turn_speed_knots,
        turn_speed_mps,
    )
except ImportError as ie_spd:
    log.error(f"Failed to import lookahead_sim_speeds: {ie_spd}")
    KNOTS_TO_MPS = 0.514444

    def shooting_speed_mps(sim_params, line_is_reciprocal):
        v = float(sim_params.get("avg_shooting_speed_mps") or 0.0)
        return v if v > 0.0 else 4.0

    def turn_speed_mps(sim_params, line_is_reciprocal):
        v = float(sim_params.get("avg_turn_speed_mps") or 0.0)
        return v if v > 0.0 else 4.0

    def shooting_speed_knots(sim_params, line_is_reciprocal):
        return shooting_speed_mps(sim_params, line_is_reciprocal) / KNOTS_TO_MPS

    def turn_speed_knots(sim_params, line_is_reciprocal):
        return turn_speed_mps(sim_params, line_is_reciprocal) / KNOTS_TO_MPS

try:
    from .sps_parsing_dialog import SpsParsingDialog
except ImportError as ie_sps_dialog:
    log.warning(f"Failed to import SpsParsingDialog: {ie_sps_dialog}")
    SpsParsingDialog = None

try:
    from .csv_parsing_dialog import CsvParsingDialog
except ImportError as ie_csv_dialog:
    log.warning(f"Failed to import CsvParsingDialog: {ie_csv_dialog}")
    CsvParsingDialog = None

try:
    from . import plugin_settings
except ImportError:
    plugin_settings = None
try:
    from .plugin_settings import DOCK_STABILITY_DEFAULTS
except ImportError:
    DOCK_STABILITY_DEFAULTS = {
        "runin_connect_tolerance_m": 10.0,
        "teardrop_loop_chord_factor": 3.5,
        "teardrop_loop_circumference_factor": 1.05,
        "teardrop_loop_min_chord_m": 5.0,
    }

from .lookahead_messages import MESSAGE_BAR_DURATION_SEC, notify_fallback_dialog, QMessageBox
from .lookahead_help import LOOKAHEAD_HELP_HTML_EN, LOOKAHEAD_HELP_HTML_RU

# --- Constants ---
try:
    NULL = QVariant()
except Exception:
    NULL = None
MAX_FLOAT = sys.float_info.max
GEOMETRY_PRECISION = 1e-6 # Tolerance for geometry comparisons/checks

class UserCancelException(Exception):
    """Raised when the user cancels a long-running operation."""
    pass

# --- Global Geometry Helper Functions ---
def _existing_wkb_types(*names):
    """Return only WKB enum members that exist in the current QGIS build."""
    values = []
    for name in names:
        value = getattr(QgsWkbTypes, name, None)
        if value is not None:
            values.append(value)
    return tuple(values)


_FALLBACK_SURFACE_TYPES = _existing_wkb_types(
    "Polygon", "PolygonZ", "PolygonM", "PolygonZM",
    "MultiPolygon", "MultiPolygonZ", "MultiPolygonM", "MultiPolygonZM",
    "Polygon25D", "MultiPolygon25D",
)
_FALLBACK_POINT_TYPES = _existing_wkb_types(
    "Point", "PointZ", "PointM", "PointZM",
    "MultiPoint", "MultiPointZ", "MultiPointM", "MultiPointZM",
    "Point25D", "MultiPoint25D",
)
_FALLBACK_LINE_TYPES = _existing_wkb_types(
    "LineString", "LineStringZ", "LineStringM", "LineStringZM",
    "MultiLineString", "MultiLineStringZ", "MultiLineStringM", "MultiLineStringZM",
    "LineString25D", "MultiLineString25D", "CompoundCurve", "CircularString",
)


def is_surface_type(wkb_type):
    """Check if a WKB type is a surface type (Polygon, MultiPolygon, etc.)."""
    try: return QgsWkbTypes.isSurface(wkb_type)
    except AttributeError:
        log.debug("Fallback check for is_surface_type")
        return wkb_type in _FALLBACK_SURFACE_TYPES

def is_point_type(wkb_type):
    """Check if a WKB type is a point type (Point, MultiPoint, etc.)."""
    try: return QgsWkbTypes.isPoint(wkb_type)
    except AttributeError:
        log.debug("Fallback check for is_point_type")
        return wkb_type in _FALLBACK_POINT_TYPES

def is_line_type(wkb_type):
    """Check if a WKB type is a line type (LineString, MultiLineString, etc.)."""
    try: return QgsWkbTypes.isCurve(wkb_type) # isCurve covers LineString, CompoundCurve etc.
    except AttributeError:
        log.debug("Fallback check for is_line_type")
        return wkb_type in _FALLBACK_LINE_TYPES


def create_vector_writer_compat(output_path, fields, wkb_type, crs, driver_name="GPKG", encoding="UTF-8"):
    """
    Build a vector writer compatible with QGIS 3.x and 4.x.
    Prefers modern create()+SaveVectorOptions and falls back to legacy constructor.
    """
    try:
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = driver_name
        options.fileEncoding = encoding
        transform_context = QgsProject.instance().transformContext()
        writer = QgsVectorFileWriter.create(output_path, fields, wkb_type, crs, transform_context, options)
        return writer
    except Exception:
        return QgsVectorFileWriter(output_path, encoding, fields, wkb_type, crs, driver_name)


def _normalize_acquisition_combo_userdata(raw):
    """
    Map QComboBox item userData to 'teardrop' | 'racetrack' | None.
    PyQt5 often returns QVariant; str(QVariant) is not a reliable mode string.
    """
    if raw is None:
        return None
    try:
        if isinstance(raw, QVariant):
            if hasattr(raw, "isValid") and not raw.isValid():
                return None
            if hasattr(raw, "value"):
                raw = raw.value()
    except Exception:
        return None
    if raw is None:
        return None
    s = str(raw).strip().casefold()
    return s if s in ("teardrop", "racetrack") else None


# --- End Global Helpers ---

class LookaheadDockWidgetImpl(QtWidgets.QDockWidget, Ui_OBNPlannerDockWidgetBase):
    """
    Main dock widget for the Lookahead (OBN lookahead planner) plugin.

    Provides UI for importing SPS data, defining parameters, generating survey lines
    (including run-ins and RRT-based deviations around No-Go zones), calculating
    headings, managing line status, simulating survey sequences (Racetrack, Teardrop),
    visualizing results, editing sequences, and exporting lookahead plans.
    """
    closingPlugin = pyqtSignal()
    last_sps_dir = os.path.expanduser("~")
    last_csv_dir = os.path.expanduser("~")
    last_gpkg_dir = os.path.expanduser("~")
    generated_lines_layer = None
    generated_runins_layer = None
    generated_turns_layer = None
    optimized_path_layer = None
    # Caches for simulation context
    last_simulation_result = None
    last_sim_params = None
    last_line_data = None # Holds potentially deviated line data
    last_required_layers = None
    last_turn_cache = None
    # Non-blocking toast duration (QGIS message bar); default from lookahead_messages.
    MESSAGE_BAR_DURATION_SEC = MESSAGE_BAR_DURATION_SEC

    @staticmethod
    def _pop_wait_cursor_if_busy():
        """Drop the app wait cursor before modal dialogs (e.g. QMessageBox.question)."""
        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

    def _refresh_map_canvas_safe(self):
        """Refresh map canvas only when iface/canvas are available and alive."""
        iface = getattr(self, "iface", None)
        if iface is None:
            return
        try:
            canvas = iface.mapCanvas()
            if canvas is not None:
                canvas.refresh()
        except Exception as e:
            log.debug("Map canvas refresh skipped: %s", e)

    def _notify(self, title, text, level=Qgis.Info):
        """Show a short, non-blocking message (message bar or timed non-modal fallback)."""
        duration = int(getattr(self.__class__, "MESSAGE_BAR_DURATION_SEC", MESSAGE_BAR_DURATION_SEC))
        text = str(text)
        iface = getattr(self, "iface", None)
        if iface is not None:
            try:
                iface.messageBar().pushMessage(title, text, level=level, duration=duration)
            except Exception as ex:
                log.warning("messageBar.pushMessage failed: %s", ex)
                notify_fallback_dialog(self, title, text, level, duration)
            return
        notify_fallback_dialog(self, title, text, level, duration)

    def _warn_select_sail_layer(self, action_hint=None):
        """Friendly guidance when Sail Lines layer is missing."""
        msg = "Select Sail Line Layer first."
        if action_hint:
            msg += f"\nThen click '{action_hint}'."
        QMessageBox.warning(self, "Sail Line Layer", msg)

    def _require_sail_layer(self, action_hint=None, *, silent=False):
        """Return selected SPS/Sail layer or None with user guidance."""
        layer = self.sps_layer_combo.currentLayer() if hasattr(self, "sps_layer_combo") else None
        if layer is not None and layer.isValid():
            return layer
        if not silent:
            self._warn_select_sail_layer(action_hint)
        return None

    # --- Initialization ---
    def __init__(self, parent=None):
        """ Constructor: Initializes UI, connects signals, sets defaults. """
        super(LookaheadDockWidgetImpl, self).__init__(parent)
        self.setupUi(self)
        self._enable_dock_scroll_content()
        # Title bar: icon before the dock title (where the active Qt/QGIS style shows it).
        _icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        if os.path.isfile(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))
        else:
            self.setWindowIcon(QIcon(":/plugins/lookahead/icon.svg"))
        log.debug("Setting up UI components...")
        # Replace placeholders with QgsMapLayerComboBoxes
        self.sps_layer_combo = self._replace_combo_with_map_layer_combo(self.spsLayerComboBox, self.horizontalLayout, _QGSMAPLAYERPROXYMODEL_VECTORLAYER)
        self.sps_layer_combo.layerChanged.connect(self._on_sps_layer_changed_line_num_bounds)
        # After project load the combo may already point at a layer without emitting layerChanged.
        QgsProject.instance().readProject.connect(
            lambda *_args: QtCore.QTimer.singleShot(0, self._sync_min_max_line_spinboxes_from_sps_layer)
        )
        self.nogo_zone_combo = self._replace_combo_with_map_layer_combo(self.noGoZoneLayerComboBox, self.horizontalLayout_5, _QGSMAPLAYERPROXYMODEL_VECTORLAYER)
        # self.closepass_combo = self._replace_combo_with_map_layer_combo(self.closePassLayerComboBox, self.horizontalLayout_6, QgsMapLayerProxyModel.PolygonLayer)
        # Setup Status Filter ComboBox (default: All — no status filter; Acquired last in list)
        self.statusFilterComboBox.clear()
        self.statusFilterComboBox.addItems(["All", "To Be Acquired", "Pending", "Acquired"])
        self.statusFilterComboBox.setCurrentIndex(0)

        # --- Setup Acquisition Mode ComboBox (with Racetrack) ---
        if hasattr(self, 'acquisitionModeComboBox'):
            self.acquisitionModeComboBox.clear()
            # Store stable keys in item data — simulation must not rely on translated/whitespace text alone.
            self.acquisitionModeComboBox.addItem("Racetrack (Default)", "racetrack")
            self.acquisitionModeComboBox.addItem("Teardrop", "teardrop")
            self.acquisitionModeComboBox.setCurrentIndex(0)
            self.acquisitionModeComboBox.currentIndexChanged.connect(
                lambda *_i: self._save_dock_settings()
            )
            log.debug("Populated Acquisition Mode ComboBox (Racetrack, Teardrop) with item data.")
        else:
            log.warning("UI Warning: acquisitionModeComboBox not found.")

        # --- Set Default Value for Start Sequence Number ---
        if hasattr(self, 'firstSeqComboBox'):
            self.firstSeqComboBox.setValue(1000) # Set default start sequence to 1
            self.firstSeqComboBox.setMinimum(100) # Ensure minimum is 100 (overrides UI if necessary)
            self.firstSeqComboBox.setMaximum(9999) # Increase max if needed
            log.debug("Set default value for firstSeqComboBox (Start Sequence #) to 1000.")
        else:
            log.error("UI Error: firstSeqComboBox not found during __init__ setup!")
        self.importSpsButton.clicked.connect(self.handle_sps_import_button)
        if hasattr(self, 'calculateHeadingsButton'):
            self.calculateHeadingsButton.clicked.connect(self.handle_calculate_headings)
            self.calculateHeadingsButton.setToolTip(
                "Recalculate Heading for all lines on the selected layer. "
                "After Import SPS, headings are filled automatically; use this if you edited shots in the table."
            )
        else:
            log.warning("UI Warning: calculateHeadingsButton not found.")
        # QPushButton.clicked passes a bool — must not bind it to refresh_line_list.
        self.applyFilterButton.clicked.connect(lambda: self.handle_apply_filter(True))
        # Auto-refresh line list when status filter changes (no manual "Refresh List" needed).
        if hasattr(self, "statusFilterComboBox"):
            self.statusFilterComboBox.currentIndexChanged.connect(
                lambda *_i: self.handle_apply_filter(True)
            )
        if hasattr(self, "removeStatusButton"):
            self.removeStatusButton.clicked.connect(self.handle_remove_status)
        else:
            log.warning("UI Warning: removeStatusButton not found.")
        if hasattr(self, "resetSequencesButton"):
            self.resetSequencesButton.clicked.connect(self.handle_reset_sequences)
            self.resetSequencesButton.setToolTip(
                "Clear the shooting-order queue (Seq numbers from Right Ctrl+click). "
                "Does not change line status or the list filter."
            )
        else:
            log.warning("UI Warning: resetSequencesButton not found.")
        self._setup_line_actions_button()
        if hasattr(self, 'markAcquiredButton'): self.markAcquiredButton.clicked.connect(self.handle_mark_acquired)
        else: log.warning("UI Warning: markAcquiredButton not found.")
        self._setup_mark_tba_actions_button()
        if hasattr(self, 'markPendingButton'): self.markPendingButton.clicked.connect(self.handle_mark_pending)
        else: log.warning("UI Warning: markPendingButton not found.")
        if hasattr(self, 'generateLinesButton'): self.generateLinesButton.clicked.connect(self.handle_generate_lines)
        else: log.warning("UI Warning: generateLinesButton not found.")
        if hasattr(self, 'calculateDeviationsButton'): self.calculateDeviationsButton.clicked.connect(self.handle_calculate_deviations)
        else: log.warning("UI Warning: calculateDeviationsButton not found.")
        self._setup_import_csv_button()
        self._normalize_action_button_rows()
        if hasattr(self, 'lineListWidget'):
            self.lineListWidget.setSelectionMode(_QAIV_EXTENDED_SELECTION)
            # Keep line/status alignment stable by using a monospaced list font.
            lw_font = QFontDatabase.systemFont(_QFONTDB_FIXED_FONT)
            if not lw_font or not lw_font.family():
                lw_font = self.lineListWidget.font()
                lw_font.setStyleHint(QFont.Monospace)
            self.lineListWidget.setFont(lw_font)
            self.lineListWidget.setHorizontalScrollBarPolicy(_QT_SCROLLBAR_ALWAYS_OFF)
            self.lineListWidget.setTextElideMode(_QT_ELIDE_NONE)
            self.lineListWidget.setItemDelegate(LineListStatusDelegate(self.lineListWidget))
        else: log.warning("UI Warning: lineListWidget not found.")
        self._selection_sequence = []
        self._selection_sequence_numbers = {}
        if hasattr(self, 'lineListWidget'):
            self.lineListWidget.itemSelectionChanged.connect(self._handle_line_list_selection_changed)
            # Allow single-click deselect on already selected items.
            self.lineListWidget.viewport().installEventFilter(self)
            if hasattr(self, '_edit_line_sp_range'):
                self.lineListWidget.itemDoubleClicked.connect(self._edit_line_sp_range)
                
        self.default_line_sp_bounds = {}
        self.custom_line_sp_bounds = {}
        self._last_generation_signature = None
        
        if hasattr(self, 'firstSeqComboBox'):
            self.firstSeqComboBox.valueChanged.connect(self._refresh_line_list_item_labels)
        if hasattr(self, 'runSimulationButton'): self.runSimulationButton.clicked.connect(self.handle_run_simulation)
        else: log.warning("UI Warning: runSimulationButton not found.")
        if hasattr(self, 'editFinalizeButton'):
            self.editFinalizeButton.clicked.connect(self.show_edit_sequence_dialog)
            #  self.editFinalizeButton.setEnabled(False) # Initially disabled
        else: log.warning("UI Warning: editFinalizeButton not found.")
        if hasattr(self, 'deviationClearanceDoubleSpinBox'):
            self.deviationClearanceDoubleSpinBox.setMinimum(-50000.0)
            self.deviationClearanceDoubleSpinBox.setMaximum(50000.0)
            self.deviationClearanceDoubleSpinBox.setDecimals(1)
            self.deviationClearanceDoubleSpinBox.setValue(80.0)
            log.debug("Set default deviation clearance to 80.0 (range allows negative per turn circumference rule)")
        else:
            log.error("UI Error: deviationClearanceDoubleSpinBox not found during __init__ setup!")
        if hasattr(self, "maxRunInDoubleSpinBox"):
            self.maxRunInDoubleSpinBox.setValue(500.0)
            log.debug("Set default max run-in length to 500.0 m")
        else:
            log.error("UI Error: maxRunInDoubleSpinBox not found during __init__ setup!")
        if hasattr(self, 'startDateTimeEdit'):
            current_datetime = datetime.now(); qdt = QtCore.QDateTime(current_datetime)
            self.startDateTimeEdit.setDateTime(qdt); log.debug(f"Set Start DateTime to {current_datetime}")
        # Min/Max Line = smallest / largest LineNum in the chosen SPS layer (field name LineNum).
        self._setup_min_max_line_tooltips()
        self._setup_directional_speed_second_row()
        self._polish_twin_spinbox_rows_layout()
        self._setup_stability_advanced_group()
        self._align_dock_form_labels()
        self._enforce_compact_dock_heights()
        self._setup_dock_help_shell()
        self._setup_dock_geometry_auto_fix()
        self._recompute_line_list_height_cap()

        # --- Auto-save settings on parameter change ---
        for widget_name in [
            'deviationClearanceDoubleSpinBox', 'maxRunInDoubleSpinBox', 'runOutDoubleSpinBox',
            'turnRadiusDoubleSpinBox', 'vesselTurnRateDoubleSpinBox',
            'acqSpeedPrimaryDoubleSpinBox', 'turnSpeedDoubleSpinBox',
            'acqSpeedHighToLowDoubleSpinBox', 'turnSpeedHighToLowDoubleSpinBox',
            'firstLineSpinBox', 'firstSeqComboBox', 
            'startLineSpinBox', 'endLineSpinBox'
        ]:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.valueChanged.connect(lambda *args: self._save_dock_settings())

        for widget_name in ['firstHeadingComboBox', 'statusFilterComboBox']:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.currentIndexChanged.connect(lambda *args: self._save_dock_settings())
                
        for widget_name in ['sps_layer_combo', 'nogo_zone_combo']:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.layerChanged.connect(lambda *args: self._save_dock_settings())

        QtCore.QTimer.singleShot(0, self._sync_min_max_line_spinboxes_from_sps_layer)
        QtCore.QTimer.singleShot(100, self._apply_saved_dock_settings)
        log.info("Lookahead dock widget initialized.")

    def _enable_dock_scroll_content(self):
        """
        Wrap dock content into a scroll area so lower controls remain reachable
        when QGIS dock stacking temporarily shrinks available height.
        """
        try:
            if getattr(self, "_dock_scroll_enabled", False):
                return
            content = self.widget()
            if content is None:
                return
            if isinstance(content, QtWidgets.QScrollArea):
                self._dock_scroll_enabled = True
                return
            scroll = QtWidgets.QScrollArea(self)
            scroll.setObjectName("lookaheadDockScrollArea")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(_QFRAME_NO_FRAME)
            scroll.setHorizontalScrollBarPolicy(_QT_SCROLLBAR_ALWAYS_OFF)
            scroll.setVerticalScrollBarPolicy(_QT_SCROLLBAR_AS_NEEDED)
            self.setWidget(scroll)
            scroll.setWidget(content)
            self._dock_scroll_enabled = True
        except Exception as e:
            log.debug("dock scroll setup: %s", e)

    def _setup_dock_geometry_auto_fix(self):
        """
        Keep dock geometry healthy when other dock widgets are opened/closed.
        This prevents the bottom controls from staying clipped until a main-window maximize.
        """
        try:
            self.setMinimumHeight(0)
            root = self.widget()
            if root is not None:
                root.setMinimumHeight(0)
                root.setSizePolicy(
                    _QSP_PREFERRED,
                    _QSP_EXPANDING,
                )
            self.visibilityChanged.connect(lambda *_: self._schedule_dock_relayout())
            self.dockLocationChanged.connect(lambda *_: self._schedule_dock_relayout())
            self.topLevelChanged.connect(lambda *_: self._schedule_dock_relayout())
            QtCore.QTimer.singleShot(0, self._schedule_dock_relayout)
        except Exception as e:
            log.debug("dock auto-fix setup: %s", e)

    def _schedule_dock_relayout(self):
        QtCore.QTimer.singleShot(0, self._force_dock_relayout)
        QtCore.QTimer.singleShot(60, self._force_dock_relayout)
        QtCore.QTimer.singleShot(180, self._force_dock_relayout)

    def _force_dock_relayout(self):
        try:
            if not self.isVisible():
                return
            root = self.widget()
            if root is not None:
                lay = root.layout()
                if lay is not None:
                    lay.invalidate()
                    lay.activate()
                root.adjustSize()
                root.updateGeometry()
            self._recompute_line_list_height_cap()
            self.adjustSize()
            self.updateGeometry()

            mw = self.window()
            if isinstance(mw, QtWidgets.QMainWindow):
                target_h = max(self.minimumSizeHint().height(), self.sizeHint().height(), 420)
                try:
                    mw.resizeDocks([self], [target_h], _QT_VERTICAL)
                except Exception:
                    pass
        except Exception as e:
            log.debug("dock relayout: %s", e)

    def _build_generation_signature(self):
        """
        Build a lightweight fingerprint of inputs that affect generated lookahead lines.
        If this changes, simulation should request re-generation first.
        """
        try:
            sps_layer = self.sps_layer_combo.currentLayer() if hasattr(self, 'sps_layer_combo') else None
            sps_layer_id = sps_layer.id() if sps_layer and sps_layer.isValid() else None
            sps_layer_name = sps_layer.name() if sps_layer and sps_layer.isValid() else None

            line_selection = []
            if hasattr(self, 'lineListWidget'):
                for i in range(self.lineListWidget.count()):
                    item = self.lineListWidget.item(i)
                    if item is None:
                        continue
                    line_id = str(item.data(_QT_USER_ROLE))
                    base_ln = item.data(_QT_USER_ROLE + 2)
                    status = str(item.data(_QT_USER_ROLE + 1)).strip().upper()
                    line_selection.append((line_id, str(base_ln), status))

            custom_bounds_items = tuple(
                sorted((str(k), tuple(v)) for k, v in (self.custom_line_sp_bounds or {}).items())
            )

            sig = (
                sps_layer_id,
                sps_layer_name,
                float(self.maxRunInDoubleSpinBox.value()) if hasattr(self, 'maxRunInDoubleSpinBox') else 500.0,
                float(self.runOutDoubleSpinBox.value()) if hasattr(self, 'runOutDoubleSpinBox') else 0.0,
                int(self.startLineSpinBox.value()) if hasattr(self, 'startLineSpinBox') else None,
                int(self.endLineSpinBox.value()) if hasattr(self, 'endLineSpinBox') else None,
                str(self.statusFilterComboBox.currentText()) if hasattr(self, 'statusFilterComboBox') else "",
                tuple(sorted(line_selection)),
                custom_bounds_items,
            )
            return sig
        except Exception as e:
            log.warning("Failed to build generation signature: %s", e)
            return None

    def _needs_regeneration_before_simulation(self):
        """
        True when simulation inputs no longer match the last successful Generate Lookahead Lines run.
        """
        def _layer_ok(lyr):
            if not lyr:
                return False
            try:
                return lyr.isValid()
            except RuntimeError:
                return False

        lines_layer_valid = hasattr(self, 'generated_lines_layer') and _layer_ok(self.generated_lines_layer)
        runins_layer_valid = hasattr(self, 'generated_runins_layer') and _layer_ok(self.generated_runins_layer)
        if not lines_layer_valid or not runins_layer_valid:
            return True

        current_sig = self._build_generation_signature()
        return current_sig is None or current_sig != self._last_generation_signature
        
    def generate_turn_segments(self, start_pt, start_heading, end_pt, end_heading):
        """Calculates a turn using the mode selected in UI."""
        try:
            radius = self.turnRadiusDoubleSpinBox.value()
            max_line_dist = 10.0 
            
            # Try to determine the mode. If there's no combo box, use teardrop as fallback
            turn_mode = "teardrop" 
            if hasattr(self, 'turnTypeComboBox'):
                turn_mode = self.turnTypeComboBox.currentText().lower()

            # Call updated Dubins calculator
            return dubins_calc.get_curve(
                start_pt.x(), start_pt.y(), start_heading,
                end_pt.x(), end_pt.y(), end_heading,
                radius,
                max_line_dist,
                turn_mode=turn_mode
            )
        except Exception as e:
            log.error(f"Turn generation error: {e}")
            return None, None, None

    def _setup_directional_speed_second_row(self):
        """
        Replace the single ``horizontalLayout_15`` row with a 2×3 grid so Low→High and High→Low
        shooting/turn spin boxes share one column layout (aligned positions and widths).
        """
        if getattr(self, "_speed_rows_grid", None) is not None:
            return
        if not hasattr(self, "verticalLayout") or not getattr(self, "horizontalLayout_15", None):
            return

        vl = self.verticalLayout
        h15 = self.horizontalLayout_15
        idx = -1
        for i in range(vl.count()):
            li = vl.itemAt(i)
            if li is not None and li.layout() == h15:
                idx = i
                break
        if idx < 0:
            log.warning("Could not build speed grid: horizontalLayout_15 not in verticalLayout.")
            return

        w_label = getattr(self, "label_12", None)
        w_acq_l2h = getattr(self, "acqSpeedPrimaryDoubleSpinBox", None)
        w_turn_l2h = getattr(self, "turnSpeedDoubleSpinBox", None)
        if w_label is None or w_acq_l2h is None or w_turn_l2h is None:
            log.warning("Speed grid: missing label_12 or primary speed spin boxes.")
            return

        while h15.count():
            h15.takeAt(0)
        vl.takeAt(idx)
        h15.setParent(None)
        h15.deleteLater()
        self.horizontalLayout_15 = None

        w_label.setText("Low→High")
        w_label.setToolTip("Shooting and turn speeds while acquiring Low→High along the sail line.")
        w_label.setAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)

        def _mk_spin():
            w = QtWidgets.QDoubleSpinBox(self.dockWidgetContents)
            w.setDecimals(1)
            w.setMinimum(3.0)
            w.setMaximum(7.0)
            w.setSingleStep(0.1)
            w.setSuffix(" knots")
            return w

        self.acqSpeedHighToLowDoubleSpinBox = _mk_spin()
        self.acqSpeedHighToLowDoubleSpinBox.setObjectName("acqSpeedHighToLowDoubleSpinBox")
        self.acqSpeedHighToLowDoubleSpinBox.setToolTip("Shooting speed (knots) for High→Low line acquisition.")
        self.acqSpeedHighToLowDoubleSpinBox.setValue(w_acq_l2h.value())

        self.turnSpeedHighToLowDoubleSpinBox = _mk_spin()
        self.turnSpeedHighToLowDoubleSpinBox.setObjectName("turnSpeedHighToLowDoubleSpinBox")
        self.turnSpeedHighToLowDoubleSpinBox.setToolTip(
            "Turn / run-in / run-out speed (knots) when the line is shot High→Low."
        )
        self.turnSpeedHighToLowDoubleSpinBox.setValue(w_turn_l2h.value())

        w_acq_l2h.setToolTip("Shooting speed (knots) for Low→High line acquisition.")
        w_turn_l2h.setToolTip("Turn / run-in / run-out speed (knots) when the line is shot Low→High.")

        lab_h2l = QtWidgets.QLabel("High→Low", self.dockWidgetContents)
        lab_h2l.setObjectName("label_speed_direction_h2l")
        lab_h2l.setAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)
        lab_h2l.setToolTip("Shooting and turn speeds while acquiring High→Low (reciprocal) along the sail line.")
        self.label_speed_direction_h2l = lab_h2l

        holder = QtWidgets.QWidget(self.dockWidgetContents)
        holder.setObjectName("speedRowsWidget")
        grid = QtWidgets.QGridLayout(holder)
        grid.setObjectName("gridLayout_speed_directions")
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        _lbl_align = _QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER
        grid.addWidget(w_label, 0, 0, _lbl_align)
        grid.addWidget(w_acq_l2h, 0, 1)
        grid.addWidget(w_turn_l2h, 0, 2)
        grid.addWidget(lab_h2l, 1, 0, _lbl_align)
        grid.addWidget(self.acqSpeedHighToLowDoubleSpinBox, 1, 1)
        grid.addWidget(self.turnSpeedHighToLowDoubleSpinBox, 1, 2)

        vl.insertWidget(idx, holder)
        self._speed_rows_holder = holder
        self._speed_rows_grid = grid

    def _polish_twin_spinbox_rows_layout(self):
        """
        Twin rows (min/max lines, turn radius/rate, shooting/turn speeds): same layout —
        _QSP_MAXIMUM, equal stretch in the row, compact caps vs. a single spinbox.

        Min/max LineNum can reach 7 digits (UI max); cap is at least half_w but wide enough
        for «9999999» so values stay readable.
        """
        ref = getattr(self, "firstLineSpinBox", None)
        ref_w = 108
        if ref is not None:
            ref_w = max(ref.sizeHint().width(), ref.minimumWidth(), 88)
        # Half the standard single spinbox width; lower threshold for 'm' / 'knots' suffixes.
        half_w = max(72, ref_w // 2)

        fm = self.fontMetrics()
        if hasattr(fm, "horizontalAdvance"):
            _adv = fm.horizontalAdvance
        else:
            _adv = fm.width
        line_cap = max(half_w, _adv("9999999") + 36)

        pol_pair = QtWidgets.QSizePolicy(
            _QSP_EXPANDING, _QSP_FIXED
        )
        pol_pair.setHorizontalStretch(1)

        for w in (
            getattr(self, "startLineSpinBox", None),
            getattr(self, "endLineSpinBox", None),
        ):
            if w is None:
                continue
            w.setMinimumWidth(0)
            w.setMaximumWidth(16777215)
            w.setSizePolicy(pol_pair)

        for w in (
            getattr(self, "turnRadiusDoubleSpinBox", None),
            getattr(self, "vesselTurnRateDoubleSpinBox", None),
            getattr(self, "acqSpeedPrimaryDoubleSpinBox", None),
            getattr(self, "turnSpeedDoubleSpinBox", None),
            getattr(self, "acqSpeedHighToLowDoubleSpinBox", None),
            getattr(self, "turnSpeedHighToLowDoubleSpinBox", None),
            getattr(self, "firstLineSpinBox", None),
            getattr(self, "firstSeqComboBox", None),
        ):
            if w is None:
                continue
            w.setMinimumWidth(0)
            w.setMaximumWidth(16777215)
            w.setSizePolicy(pol_pair)

        for lay_name in (
            "horizontalLayout_2",
            "horizontalLayout_10",
            "horizontalLayout_12",
            "horizontalLayout_13",
        ):
            lay = getattr(self, lay_name, None)
            if lay is None or lay.count() < 3:
                continue
            lay.setStretch(0, 0)
            lay.setStretch(1, 1)
            lay.setStretch(2, 1)

        g_speed = getattr(self, "_speed_rows_grid", None)
        if g_speed is not None:
            g_speed.setColumnStretch(0, 0)
            g_speed.setColumnStretch(1, 1)
            g_speed.setColumnStretch(2, 1)

        # Same minimum width for all four knot spinboxes so columns line up in the speed grid.
        _speed_widgets = [
            getattr(self, "acqSpeedPrimaryDoubleSpinBox", None),
            getattr(self, "turnSpeedDoubleSpinBox", None),
            getattr(self, "acqSpeedHighToLowDoubleSpinBox", None),
            getattr(self, "turnSpeedHighToLowDoubleSpinBox", None),
        ]
        _speed_widgets = [w for w in _speed_widgets if w is not None]
        if len(_speed_widgets) >= 2:
            try:
                _mw = max(w.minimumSizeHint().width() for w in _speed_widgets)
            except Exception:
                _mw = 80
            _mw = max(_mw, 80)
            for w in _speed_widgets:
                w.setMinimumWidth(_mw)

    def _align_dock_form_labels(self):
        """Same minimum width for all left labels so control columns line up (single vs twin rows)."""
        names = (
            "label",
            "label_2",
            "label_4",
            "label_5",
            "label_17",
            "label_15",
            "label_7",
            "label_9",
            "label_10",
            "label_11",
            "label_12",
            "label_speed_direction_h2l",
            "label_14",
        )
        labels = []
        for n in names:
            w = getattr(self, n, None)
            if w is not None and isinstance(w, QtWidgets.QLabel):
                labels.append(w)
        for w in getattr(self, "_stability_row_labels", None) or []:
            if isinstance(w, QtWidgets.QLabel):
                labels.append(w)
        if not labels:
            return
        fm = self.fontMetrics()
        max_w = 0
        for w in labels:
            t = w.text()
            if hasattr(fm, "horizontalAdvance"):
                max_w = max(max_w, fm.horizontalAdvance(t))
            else:
                max_w = max(max_w, fm.width(t))
        # Set a fixed width for the left column (labels) so inputs start closer to the center
        col_w = max(max_w + 12, 160)
        self._dock_label_column_width = col_w
        for w in labels:
            w.setMinimumWidth(col_w)
            w.setAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)

    def _enforce_compact_dock_heights(self):
        """
        Vertical density for the dock: no extra stretch between rows, list does not
        eat vertical space (QListWidget defaults to Expanding vertically).
        """
        try:
            root = self.widget()
            if root is None:
                root = self

            # Qt6 styles in QGIS 4 tend to over-compress fixed-height controls.
            # Keep layout compact but avoid hard-fixed heights to prevent clipped/missing rows.
            if _IS_QT6:
                main_layout = getattr(self, "verticalLayout", None)
                if main_layout is not None:
                    main_layout.setSpacing(4)
                    main_layout.setContentsMargins(4, 4, 4, 4)
                v2 = getattr(self, "verticalLayout_2", None)
                if v2 is not None:
                    v2.setSpacing(4)
                lw = getattr(self, "lineListWidget", None)
                if lw is not None:
                    lw.setMinimumHeight(140)
                    lw.setMaximumHeight(16777215)
                return

            pol_btn = QtWidgets.QSizePolicy(
                _QSP_PREFERRED, _QSP_FIXED
            )
            pol_input = QtWidgets.QSizePolicy(
                _QSP_EXPANDING, _QSP_FIXED
            )

            def _fix_vertical_only(w):
                sp = w.sizePolicy()
                sp.setVerticalPolicy(_QSP_FIXED)
                sp.setHorizontalPolicy(_QSP_EXPANDING)
                w.setSizePolicy(sp)

            main_layout = getattr(self, "verticalLayout", None)
            if main_layout is not None:
                main_layout.setSpacing(0)
                main_layout.setContentsMargins(1, 1, 1, 1)

            v2 = getattr(self, "verticalLayout_2", None)
            if v2 is not None:
                v2.setSpacing(0)

            for name in (
                "horizontalLayout_8", "horizontalLayout", "horizontalLayout_2", "horizontalLayout_4",
                "horizontalLayout_5", "horizontalLayout_19", "horizontalLayout_refresh_status",
                "horizontalLayout_7", "horizontalLayout_6", "horizontalLayout_18", "horizontalLayout_10",
                "horizontalLayout_12", "horizontalLayout_13", "horizontalLayout_14",
                "horizontalLayout_17", "horizontalLayout_finalize"
            ):
                lay = getattr(self, name, None)
                if lay is not None:
                    lay.setSpacing(6)
                    lay.setContentsMargins(0, 2, 0, 2)

            g_speed = getattr(self, "_speed_rows_grid", None)
            if g_speed is not None:
                g_speed.setHorizontalSpacing(6)
                g_speed.setVerticalSpacing(2)
                g_speed.setContentsMargins(0, 2, 0, 2)

            lw = getattr(self, "lineListWidget", None)
            if lw is not None:
                # Keep list compact; full dock now scrolls if needed.
                lw.setMinimumHeight(110)
                lw.setMaximumHeight(16777215)
                lw.setSizePolicy(
                    _QSP_PREFERRED, _QSP_EXPANDING
                )
                lw.setSpacing(2)

            compact_h = 22
            for w in self.findChildren(QtWidgets.QPushButton):
                w.setFixedHeight(compact_h)
                w.setSizePolicy(pol_btn)
            for w in self.findChildren(QtWidgets.QComboBox):
                w.setFixedHeight(compact_h)
                w.setSizePolicy(pol_input)
            for w in self.findChildren(QtWidgets.QSpinBox):
                w.setFixedHeight(compact_h)
                _fix_vertical_only(w)
            for w in self.findChildren(QtWidgets.QDoubleSpinBox):
                w.setFixedHeight(compact_h)
                _fix_vertical_only(w)
            for w in self.findChildren(QtWidgets.QDateTimeEdit):
                w.setFixedHeight(compact_h)
                w.setSizePolicy(pol_input)
                # Match base_ui: full date+time must stay clickable (hours not clipped).
                try:
                    mw = max(232, int(w.minimumWidth()))
                    w.setMinimumWidth(mw)
                except (TypeError, ValueError):
                    w.setMinimumWidth(232)
            for w in self.findChildren(QgsMapLayerComboBox):
                w.setFixedHeight(compact_h)
                w.setMinimumHeight(0)
                w.setSizePolicy(pol_input)

            for w in self.findChildren(QtWidgets.QLabel):
                try:
                    w.setContentsMargins(0, 0, 0, 0)
                    w.setFixedHeight(compact_h)
                    w.setSizePolicy(pol_btn)
                except Exception:
                    pass

            # Stylesheet beats many QGIS/Fusion default paddings on the content widget.
            root.setStyleSheet(
                "QWidget#dockWidgetContents{font-size:9pt;}"
                "QWidget#dockWidgetContents QLabel{margin:0px;padding:0px;}"
                "QWidget#dockWidgetContents QPushButton{min-height:20px;max-height:22px;padding:2px 4px;margin:0px;}"
                "QWidget#dockWidgetContents QComboBox{min-height:20px;max-height:22px;padding:2px 4px;margin:0px;}"
                "QWidget#dockWidgetContents QSpinBox,QWidget#dockWidgetContents QDoubleSpinBox{"
                "min-height:20px;max-height:22px;padding:2px 4px;margin:0px;}"
                "QWidget#dockWidgetContents QDateTimeEdit{min-height:20px;padding:2px 4px;margin:0px;}"
                "QWidget#dockWidgetContents QListWidget{padding:0px;margin:0px;}"
                "QWidget#dockWidgetContents QListWidget::item{padding:2px 4px;margin:0px;}"
            )
        except Exception as e:
            log.debug("compact dock layout: %s", e)

    def _recompute_line_list_height_cap(self):
        """Deprecated cap logic (kept for compatibility): no forced list cap."""
        return

    def _setup_dock_help_shell(self):
        """
        Wrap existing dock form in a stack: page 0 = controls, page 1 = HTML help.
        Top bar: 'Lookahead (How To)' with blue link; in help mode — title + × to close.
        """
        if getattr(self, "_lookahead_help_shell_done", False):
            return
        vl = getattr(self, "verticalLayout", None)
        if vl is None:
            return
        try:
            chunks = []
            while vl.count():
                chunks.append(vl.takeAt(0))

            header = QtWidgets.QWidget()
            header.setObjectName("lookaheadDockHeader")
            hdr_outer = QtWidgets.QHBoxLayout(header)
            hdr_outer.setContentsMargins(2, 2, 2, 2)
            hdr_outer.setSpacing(4)

            self._lookahead_title_stack = QStackedWidget()
            self._lookahead_title_stack.setSizePolicy(
                _QSP_EXPANDING, _QSP_FIXED
            )

            _hdr_icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
            _hdr_pm = QPixmap()
            if os.path.isfile(_hdr_icon_path):
                _hdr_pm = QPixmap(_hdr_icon_path)
            else:
                _hdr_pm = QPixmap(":/plugins/lookahead/icon.svg")
            if not _hdr_pm.isNull():
                _hdr_pm = _hdr_pm.scaled(
                    20, 20, _QT_KEEP_ASPECT_RATIO, _QT_SMOOTH_TRANSFORMATION
                )

            def _header_icon_label():
                il = QLabel()
                il.setFixedSize(20, 20)
                il.setScaledContents(True)
                if not _hdr_pm.isNull():
                    il.setPixmap(_hdr_pm)
                else:
                    il.hide()
                return il

            page_normal = QtWidgets.QWidget()
            lay_n = QtWidgets.QHBoxLayout(page_normal)
            lay_n.setContentsMargins(0, 0, 0, 0)
            lay_n.setSpacing(6)
            lay_n.addWidget(_header_icon_label())
            lay_n.addStretch(1)
            self._lookahead_header_caption = QLabel()
            self._lookahead_header_caption.setText(
                '<a href="howto" style="color:#2563eb;text-decoration:underline;">How&nbsp;To</a>'
            )
            self._lookahead_header_caption.setTextFormat(_QT_RICH_TEXT)
            self._lookahead_header_caption.setTextInteractionFlags(_QT_TEXT_BROWSER_INTERACTION)
            self._lookahead_header_caption.setOpenExternalLinks(False)
            self._lookahead_header_caption.linkActivated.connect(lambda _u: self._show_dock_help(True))
            self._lookahead_header_caption.setMinimumHeight(22)
            self._lookahead_header_caption.setAlignment(_QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)
            lay_n.addWidget(self._lookahead_header_caption, 0, _QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)

            page_help = QtWidgets.QWidget()
            lay_h = QtWidgets.QHBoxLayout(page_help)
            lay_h.setContentsMargins(0, 0, 0, 0)
            lay_h.setSpacing(6)
            lay_h.addWidget(_header_icon_label())
            lbl_h = QLabel("How to use Lookahead")
            lbl_h.setStyleSheet("font-weight:bold;")
            lbl_h.setMinimumHeight(22)
            lay_h.addWidget(lbl_h)
            lay_h.addStretch(1)
            close_tb = QToolButton()
            close_tb.setObjectName("lookaheadHelpCloseBtn")
            close_tb.setText("\u00D7")
            close_tb.setToolTip("Close help")
            close_tb.setAutoRaise(True)
            close_tb.setFixedSize(26, 22)
            close_tb.clicked.connect(lambda: self._show_dock_help(False))
            lay_h.addWidget(close_tb, 0, _QT_ALIGN_RIGHT | _QT_ALIGN_VCENTER)

            self._lookahead_title_stack.addWidget(page_normal)
            self._lookahead_title_stack.addWidget(page_help)
            hdr_outer.addWidget(self._lookahead_title_stack, 1)

            vl.addWidget(header)

            stack = QStackedWidget()
            stack.setObjectName("lookaheadHelpStack")
            form_host = QtWidgets.QWidget()
            fl = QVBoxLayout(form_host)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.setSpacing(0)

            for it in chunks:
                sub_lay = it.layout()
                w = it.widget()
                sp = it.spacerItem()
                if sub_lay is not None:
                    fl.addLayout(sub_lay)
                elif w is not None:
                    fl.addWidget(w)
                elif sp is not None:
                    fl.addItem(sp)

            browser = QTextBrowser()
            browser.setObjectName("lookaheadHelpBrowser")
            browser.setHorizontalScrollBarPolicy(_QT_SCROLLBAR_ALWAYS_OFF)
            browser.setOpenLinks(False)
            browser.setOpenExternalLinks(False)
            browser.setReadOnly(True)
            browser.setHtml(LOOKAHEAD_HELP_HTML_EN)
            browser.anchorClicked.connect(self._on_help_browser_anchor)

            stack.addWidget(form_host)
            stack.addWidget(browser)
            vl.addWidget(stack, 1)

            self._lookahead_help_stack = stack
            self._lookahead_help_browser = browser
            self._lookahead_saved_window_title = self.windowTitle() or "Lookahead"

            root = self.widget()
            if root is not None:
                ss = root.styleSheet() or ""
                root.setStyleSheet(
                    ss
                    + "QTextBrowser#lookaheadHelpBrowser{font-size:9pt;border:1px solid #ccc;"
                    "border-radius:3px;padding:8px;background:#fafafa;}"
                )

            self._lookahead_help_shell_done = True
        except Exception as e:
            log.warning("dock help shell failed: %s", e)

    def _on_help_browser_anchor(self, url):
        """Switch help language (lang://en / lang://ru); other URLs open externally."""
        try:
            u = QUrl(url) if not isinstance(url, QUrl) else url
            if u.scheme() == "lang":
                host = (u.host() or "").lower()
                br = getattr(self, "_lookahead_help_browser", None)
                if br is None:
                    return
                if host == "ru":
                    br.setHtml(LOOKAHEAD_HELP_HTML_RU)
                elif host == "en":
                    br.setHtml(LOOKAHEAD_HELP_HTML_EN)
                return
            if not self._is_allowed_help_url(u):
                log.warning("Blocked unsafe help URL: %s", u.toString())
                return
            QDesktopServices.openUrl(u)
        except Exception as e:
            log.debug("help browser anchor: %s", e)

    @staticmethod
    def _is_allowed_help_url(url):
        """Allow only explicit safe external links from help content."""
        try:
            u = QUrl(url) if not isinstance(url, QUrl) else url
            scheme = (u.scheme() or "").lower()
            if scheme not in ("https", "mailto"):
                return False
            if scheme == "mailto":
                return True
            host = (u.host() or "").lower()
            allowed_hosts = {
                "qgis.org",
                "www.qgis.org",
                "plugins.qgis.org",
                "github.com",
                "raw.githubusercontent.com",
            }
            return host in allowed_hosts
        except Exception:
            return False

    def _show_help_dialog_qt6(self, _url=None):
        try:
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("Lookahead — How To")
            dlg.resize(650, 750)
            try:
                dlg.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
            except AttributeError:
                dlg.setWindowFlag(Qt.WindowMaximizeButtonHint, True)

            lay = QtWidgets.QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)

            browser = QTextBrowser(dlg)
            browser.setHorizontalScrollBarPolicy(_QT_SCROLLBAR_ALWAYS_OFF)
            browser.setOpenLinks(False)
            browser.setOpenExternalLinks(False)
            browser.setReadOnly(True)
            browser.setHtml(LOOKAHEAD_HELP_HTML_EN)

            def _on_anchor(url):
                u = QUrl(url) if not isinstance(url, QUrl) else url
                if u.scheme() == "lang":
                    host = (u.host() or "").lower()
                    if host == "ru":
                        browser.setHtml(LOOKAHEAD_HELP_HTML_RU)
                    elif host == "en":
                        browser.setHtml(LOOKAHEAD_HELP_HTML_EN)
                    return
                if not self._is_allowed_help_url(u):
                    log.warning("Blocked unsafe help URL: %s", u.toString())
                    return
                QDesktopServices.openUrl(u)

            browser.anchorClicked.connect(_on_anchor)
            lay.addWidget(browser)

            dlg.exec()
        except Exception as e:
            log.warning("dock help dialog (Qt6) failed: %s", e)

    def _show_dock_help(self, show_help):
        if not getattr(self, "_lookahead_help_stack", None):
            return
        try:
            self._lookahead_help_stack.setCurrentIndex(1 if show_help else 0)
            self._lookahead_title_stack.setCurrentIndex(1 if show_help else 0)
            base = getattr(self, "_lookahead_saved_window_title", None) or "Lookahead"
            self.setWindowTitle("Lookahead — How To" if show_help else base)
            if show_help:
                br = getattr(self, "_lookahead_help_browser", None)
                if br is not None:
                    br.setHtml(LOOKAHEAD_HELP_HTML_EN)
        except Exception as e:
            log.warning("dock help toggle: %s", e)

    def _restore_map_layer_combo_by_name(self, combo, layer_name):
        if not layer_name or combo is None:
            return
        try:
            combo.blockSignals(True)
            for lyr in QgsProject.instance().mapLayers().values():
                try:
                    if lyr.isValid() and lyr.name() == layer_name:
                        combo.setLayer(lyr)
                        return
                except Exception:
                    continue
        finally:
            combo.blockSignals(False)

    def _collect_dock_settings(self):
        def _layer_name(combo):
            try:
                lyr = combo.currentLayer()
                return lyr.name() if lyr is not None and lyr.isValid() else None
            except Exception:
                return None

        d = {
            "last_sps_dir": getattr(self, "last_sps_dir", "") or "",
            "last_csv_dir": getattr(self, "last_csv_dir", "") or "",
            "last_gpkg_dir": getattr(self, "last_gpkg_dir", "") or "",
        }
        if hasattr(self, "startLineSpinBox"):
            d["start_line"] = self.startLineSpinBox.value()
        if hasattr(self, "endLineSpinBox"):
            d["end_line"] = self.endLineSpinBox.value()
        if hasattr(self, "statusFilterComboBox"):
            d["status_filter_index"] = self.statusFilterComboBox.currentIndex()
            d["status_filter_text"] = self.statusFilterComboBox.currentText()
        if hasattr(self, "deviationClearanceDoubleSpinBox"):
            d["deviation_clearance"] = self.deviationClearanceDoubleSpinBox.value()
        if hasattr(self, "acquisitionModeComboBox"):
            am = self.acquisitionModeComboBox
            d["acquisition_mode_index"] = am.currentIndex()
            d["acquisition_mode_key"] = "teardrop" if am.currentIndex() == 1 else "racetrack"
        if hasattr(self, "maxRunInDoubleSpinBox"):
            d["max_run_in"] = self.maxRunInDoubleSpinBox.value()
        if hasattr(self, "runOutDoubleSpinBox"):
            d["run_out"] = self.runOutDoubleSpinBox.value()
        if hasattr(self, "turnRadiusDoubleSpinBox"):
            d["turn_radius"] = self.turnRadiusDoubleSpinBox.value()
        if hasattr(self, "vesselTurnRateDoubleSpinBox"):
            d["vessel_turn_rate"] = self.vesselTurnRateDoubleSpinBox.value()
        if hasattr(self, "firstLineSpinBox"):
            d["first_line"] = self.firstLineSpinBox.value()
        if hasattr(self, "firstSeqComboBox"):
            d["first_seq"] = self.firstSeqComboBox.value()
        if hasattr(self, "firstHeadingComboBox"):
            d["first_heading_index"] = self.firstHeadingComboBox.currentIndex()
        if hasattr(self, "acqSpeedPrimaryDoubleSpinBox"):
            d["acq_speed"] = self.acqSpeedPrimaryDoubleSpinBox.value()
        if hasattr(self, "turnSpeedDoubleSpinBox"):
            d["turn_speed"] = self.turnSpeedDoubleSpinBox.value()
        if hasattr(self, "acqSpeedHighToLowDoubleSpinBox"):
            d["acq_speed_high_to_low"] = self.acqSpeedHighToLowDoubleSpinBox.value()
        if hasattr(self, "turnSpeedHighToLowDoubleSpinBox"):
            d["turn_speed_high_to_low"] = self.turnSpeedHighToLowDoubleSpinBox.value()
        if hasattr(self, "startDateTimeEdit"):
            d["start_datetime_iso"] = self.startDateTimeEdit.dateTime().toString(_QT_ISO_DATE)
        if hasattr(self, "sps_layer_combo"):
            d["sps_layer_name"] = _layer_name(self.sps_layer_combo)
        if hasattr(self, "nogo_zone_combo"):
            d["nogo_layer_name"] = _layer_name(self.nogo_zone_combo)
        d["stability"] = self._collect_stability_dict()
        return d

    def _collect_stability_dict(self):
        out = dict(DOCK_STABILITY_DEFAULTS)
        for key, spin in getattr(self, "_stability_spins", {}).items():
            if spin is not None:
                try:
                    out[key] = float(spin.value())
                except (TypeError, ValueError):
                    pass
        return out

    def _apply_stability_from_dict(self, raw):
        spins = getattr(self, "_stability_spins", None)
        if not spins:
            return
        merged = dict(DOCK_STABILITY_DEFAULTS)
        if isinstance(raw, dict):
            for k in merged:
                if k in raw:
                    try:
                        merged[k] = float(raw[k])
                    except (TypeError, ValueError):
                        pass
        blockers = []
        for w in spins.values():
            if w is not None:
                blockers.append(w)
        for w in blockers:
            w.blockSignals(True)
        try:
            if spins.get("runin_connect_tolerance_m"):
                spins["runin_connect_tolerance_m"].setValue(merged["runin_connect_tolerance_m"])
            if spins.get("teardrop_loop_chord_factor"):
                spins["teardrop_loop_chord_factor"].setValue(merged["teardrop_loop_chord_factor"])
            if spins.get("teardrop_loop_circumference_factor"):
                spins["teardrop_loop_circumference_factor"].setValue(
                    merged["teardrop_loop_circumference_factor"]
                )
            if spins.get("teardrop_loop_min_chord_m"):
                spins["teardrop_loop_min_chord_m"].setValue(merged["teardrop_loop_min_chord_m"])
        finally:
            for w in blockers:
                w.blockSignals(False)

    def _get_stability_settings(self):
        """Current stability tuning (run-in tolerance, teardrop heuristics)."""
        return self._collect_stability_dict()

    def _setup_stability_advanced_group(self):
        """Advanced tuning; collapsed by default so the line list keeps vertical space."""
        self._stability_row_labels = []
        gb = QtWidgets.QGroupBox()
        gb.setObjectName("stabilityAdvancedGroupBox")
        gb.setTitle("Stability (Advanced)")
        gb.setCheckable(True)
        gb.setChecked(False)
        gb.setFlat(True)
        gb.setToolTip(
            "Optional. Expand only if: run-in lines do not match survey ends, or teardrop gives "
            "spurious loop warnings in the log. Uses map units — best with a projected CRS in meters."
        )
        holder = QtWidgets.QWidget()
        holder.setObjectName("stabilityAdvancedHolder")
        inner = QtWidgets.QVBoxLayout(holder)
        inner.setSpacing(1)
        inner.setContentsMargins(0, 0, 0, 0)
        outer = QtWidgets.QVBoxLayout(gb)
        # Tight layout: no frame (flat group box), minimal gap to rows/buttons below.
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(holder)
        holder.setVisible(False)
        gb.toggled.connect(holder.setVisible)

        pol_stab = QtWidgets.QSizePolicy(
            _QSP_EXPANDING, _QSP_FIXED
        )
        pol_stab.setHorizontalStretch(1)

        def _add_row(label, spin, tip):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(4)
            row.setContentsMargins(0, 0, 0, 1)
            lab = QtWidgets.QLabel(label)
            lab.setToolTip(tip)
            lab.setWordWrap(False)
            spin.setToolTip(tip)
            spin.setSizePolicy(pol_stab)
            spin.setMinimumWidth(0)
            spin.setMaximumWidth(16777215)
            row.addWidget(lab)
            row.addWidget(spin, 1)
            row.setStretch(0, 0)
            row.setStretch(1, 1)
            inner.addLayout(row)
            self._stability_row_labels.append(lab)

        self._stability_spins = {}

        s_runin = QtWidgets.QDoubleSpinBox()
        s_runin.setRange(0.05, 500.0)
        s_runin.setDecimals(2)
        s_runin.setSingleStep(0.5)
        s_runin.setSuffix(" m")
        s_runin.setValue(DOCK_STABILITY_DEFAULTS["runin_connect_tolerance_m"])
        _add_row(
            "Run-In Endpoint Tol.",
            s_runin,
            "Max map distance between run-in vertex and survey line end when matching features "
            "(projected CRS, meters).",
        )
        self._stability_spins["runin_connect_tolerance_m"] = s_runin

        s_chord = QtWidgets.QDoubleSpinBox()
        s_chord.setRange(1.5, 20.0)
        s_chord.setDecimals(2)
        s_chord.setSingleStep(0.25)
        s_chord.setValue(DOCK_STABILITY_DEFAULTS["teardrop_loop_chord_factor"])
        _add_row(
            "Teardrop Loop / Chord",
            s_chord,
            "If path length exceeds this factor × straight chord, log a possible excessive Teardrop loop.",
        )
        self._stability_spins["teardrop_loop_chord_factor"] = s_chord

        s_circ = QtWidgets.QDoubleSpinBox()
        s_circ.setRange(1.0, 3.0)
        s_circ.setDecimals(3)
        s_circ.setSingleStep(0.01)
        s_circ.setValue(DOCK_STABILITY_DEFAULTS["teardrop_loop_circumference_factor"])
        _add_row(
            "Teardrop Loop / 2πR",
            s_circ,
            "Also warn if Teardrop path length exceeds this × full circle circumference (2πR).",
        )
        self._stability_spins["teardrop_loop_circumference_factor"] = s_circ

        s_minch = QtWidgets.QDoubleSpinBox()
        s_minch.setRange(0.1, 200.0)
        s_minch.setDecimals(1)
        s_minch.setSingleStep(0.5)
        s_minch.setSuffix(" m")
        s_minch.setValue(DOCK_STABILITY_DEFAULTS["teardrop_loop_min_chord_m"])
        _add_row(
            "Min Chord For Check",
            s_minch,
            "Skip the teardrop loop warning when entry–exit chord is below this (map units, meters).",
        )
        self._stability_spins["teardrop_loop_min_chord_m"] = s_minch

        for spin in self._stability_spins.values():
            spin.valueChanged.connect(lambda *args: self._save_dock_settings())

        fin = self.horizontalLayout_finalize
        parent_layout = self.verticalLayout
        inserted = False
        for i in range(parent_layout.count()):
            li = parent_layout.itemAt(i)
            if li.layout() is fin:
                parent_layout.insertWidget(i, gb)
                inserted = True
                break
        if not inserted:
            parent_layout.addWidget(gb)
        self._stability_group = gb

    def _apply_saved_dock_settings(self):
        if plugin_settings is None:
            return
        d = plugin_settings.get_dock()
        if not d:
            self._apply_stability_from_dict(None)
            return

        def _si(key, default=None):
            try:
                v = d.get(key, default)
                return int(v)
            except (TypeError, ValueError):
                return default

        def _sf(key, default=None):
            try:
                return float(d[key])
            except (KeyError, TypeError, ValueError):
                return default

        try:
            p = d.get("last_sps_dir")
            if isinstance(p, str) and p and os.path.isdir(p):
                self.last_sps_dir = p
        except Exception:
            pass
        try:
            p = d.get("last_csv_dir")
            if isinstance(p, str) and p and os.path.isdir(p):
                self.last_csv_dir = p
        except Exception:
            pass
        try:
            p = d.get("last_gpkg_dir")
            if isinstance(p, str) and p and os.path.isdir(p):
                self.last_gpkg_dir = p
        except Exception:
            pass

        def _set_combo_idx(combo, key):
            if combo is None or not combo.count():
                return
            idx = _si(key, 0)
            if idx is None:
                return
            idx = max(0, min(idx, combo.count() - 1))
            combo.setCurrentIndex(idx)

        def _apply_status_filter_combo_saved():
            combo = getattr(self, "statusFilterComboBox", None)
            if combo is None or not combo.count():
                return
            t = d.get("status_filter_text")
            if isinstance(t, str) and t.strip():
                idx = combo.findText(t.strip(), _QT_MATCH_EXACTLY)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                    return
            if "status_filter_index" not in d:
                combo.setCurrentIndex(0)
                return
            idx = _si("status_filter_index", 0)
            if idx is None:
                combo.setCurrentIndex(0)
                return
            # Legacy order was: 0 TBA, 1 Acquired, 2 Pending, 3 All
            legacy_to_new = {0: 1, 1: 3, 2: 2, 3: 0}
            new_idx = legacy_to_new.get(idx, idx)
            new_idx = max(0, min(new_idx, combo.count() - 1))
            combo.setCurrentIndex(new_idx)

        _apply_status_filter_combo_saved()
        acq = getattr(self, "acquisitionModeComboBox", None)
        if acq is not None and acq.count():
            key = d.get("acquisition_mode_key")
            if isinstance(key, str) and key.strip():
                k = key.strip().casefold()
                try:
                    acq.blockSignals(True)
                    if k == "teardrop" and acq.count() > 1:
                        acq.setCurrentIndex(1)
                    elif k == "racetrack":
                        acq.setCurrentIndex(0)
                    else:
                        _set_combo_idx(acq, "acquisition_mode_index")
                finally:
                    acq.blockSignals(False)
            else:
                _set_combo_idx(acq, "acquisition_mode_index")
        _set_combo_idx(getattr(self, "firstHeadingComboBox", None), "first_heading_index")

        v = _sf("deviation_clearance")
        if v is not None and hasattr(self, "deviationClearanceDoubleSpinBox"):
            self.deviationClearanceDoubleSpinBox.setValue(v)
        v = _sf("max_run_in")
        if v is not None and hasattr(self, "maxRunInDoubleSpinBox"):
            self.maxRunInDoubleSpinBox.setValue(v)
        v = _sf("run_out")
        if v is not None and hasattr(self, "runOutDoubleSpinBox"):
            self.runOutDoubleSpinBox.setValue(v)
        v = _sf("turn_radius")
        if v is not None and hasattr(self, "turnRadiusDoubleSpinBox"):
            self.turnRadiusDoubleSpinBox.setValue(v)
        v = _sf("vessel_turn_rate")
        if v is not None and hasattr(self, "vesselTurnRateDoubleSpinBox"):
            self.vesselTurnRateDoubleSpinBox.setValue(v)
        v = _sf("acq_speed")
        if v is not None and hasattr(self, "acqSpeedPrimaryDoubleSpinBox"):
            self.acqSpeedPrimaryDoubleSpinBox.setValue(v)
        v = _sf("turn_speed")
        if v is not None and hasattr(self, "turnSpeedDoubleSpinBox"):
            self.turnSpeedDoubleSpinBox.setValue(v)
        v_h2l_a = _sf("acq_speed_high_to_low")
        if hasattr(self, "acqSpeedHighToLowDoubleSpinBox"):
            if v_h2l_a is not None:
                self.acqSpeedHighToLowDoubleSpinBox.setValue(v_h2l_a)
            else:
                self.acqSpeedHighToLowDoubleSpinBox.setValue(self.acqSpeedPrimaryDoubleSpinBox.value())
        v_h2l_t = _sf("turn_speed_high_to_low")
        if hasattr(self, "turnSpeedHighToLowDoubleSpinBox"):
            if v_h2l_t is not None:
                self.turnSpeedHighToLowDoubleSpinBox.setValue(v_h2l_t)
            else:
                self.turnSpeedHighToLowDoubleSpinBox.setValue(self.turnSpeedDoubleSpinBox.value())

        sl = _si("start_line")
        if sl is not None and hasattr(self, "startLineSpinBox"):
            self.startLineSpinBox.setValue(sl)
        el = _si("end_line")
        if el is not None and hasattr(self, "endLineSpinBox"):
            self.endLineSpinBox.setValue(el)
        fl = _si("first_line")
        if fl is not None and hasattr(self, "firstLineSpinBox"):
            self.firstLineSpinBox.setValue(fl)
        fs = _si("first_seq")
        if fs is not None and hasattr(self, "firstSeqComboBox"):
            self.firstSeqComboBox.setValue(fs)

        iso = d.get("start_datetime_iso")
        if iso and hasattr(self, "startDateTimeEdit"):
            qdt = QtCore.QDateTime.fromString(str(iso), _QT_ISO_DATE)
            if qdt.isValid():
                self.startDateTimeEdit.setDateTime(qdt)

        nogo = d.get("nogo_layer_name")
        if nogo:
            self._restore_map_layer_combo_by_name(getattr(self, "nogo_zone_combo", None), nogo)
        spsn = d.get("sps_layer_name")
        if spsn:
            self._restore_map_layer_combo_by_name(getattr(self, "sps_layer_combo", None), spsn)

        self._apply_stability_from_dict(d.get("stability"))

        log.debug("Restored dock settings from lookahead_settings.json")

    def _save_dock_settings(self):
        if plugin_settings is None:
            return
        try:
            data = plugin_settings.load_settings()
            data["dock"] = self._collect_dock_settings()
            plugin_settings.save_settings(data)
        except Exception as e:
            log.debug("Could not save dock settings: %s", e)

    def _replace_combo_with_map_layer_combo(self, placeholder_combo, layout, layer_filter):
        """ Replaces a placeholder QComboBox with a QgsMapLayerComboBox. """
        layout.removeWidget(placeholder_combo)
        placeholder_combo.deleteLater()
        new_combo = QgsMapLayerComboBox(self)
        new_combo.setObjectName(f"{placeholder_combo.objectName()}_qgs")
        new_combo.setFilters(layer_filter)
        new_combo.setAllowEmptyLayer(True)
        new_combo.setLayer(None)
        layout.addWidget(new_combo)
        log.debug(f"Replaced {placeholder_combo.objectName()} with QgsMapLayerComboBox.")
        return new_combo

    def _apply_basic_style(self, layer, color_name, line_style='solid', width=0.6):
        """
        Apply a simple single symbol line style to a vector layer.

        Args:
            layer (QgsVectorLayer): The layer to style
            color_name (str): Color name or hex code (e.g., 'red' or '#FF0000')
            line_style (str): Line style type (e.g., 'solid', 'dash', 'dot')
            width (float): Line width in millimeters

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate input layer
            if not layer or not layer.isValid():
                log.warning(f"Cannot apply style, invalid layer")
                return False

            # Create simple line symbol
            symbol = QgsLineSymbol.createSimple({
                'color': color_name,
                'width': str(width),
                'width_unit': 'MM',
                'line_style': line_style
            })

            # Apply the symbol to the layer
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
            layer.triggerRepaint()

            log.debug(f"Applied basic style to '{layer.name()}'")
            return True

        except Exception as e:
            log.warning(f"Could not apply style to '{layer.name() if layer else 'None'}': {e}")
            return False

    def _remove_layer_by_name(self, layer_name):
        """
        Remove all layers with the specified name from the current QGIS project.

        Args:
            layer_name (str): Name of the layer(s) to remove

        Returns:
            int: Number of layers removed
        """
        try:
            # Get the project instance
            project = QgsProject.instance()

            # Find all layers with the specified name
            layers = project.mapLayersByName(layer_name)

            if not layers:
                log.debug(f"No layers named '{layer_name}' found to remove")
                return 0

            # Get the IDs of all matching layers
            layer_ids = [layer.id() for layer in layers]

            # Remove the layers from the project
            project.removeMapLayers(layer_ids)

            log.debug(f"Removed {len(layer_ids)} layer(s) named '{layer_name}'")
            return len(layer_ids)

        except Exception as e:
            log.exception(f"Error removing layers named '{layer_name}': {e}")
            return 0

    # --- General Helpers ---

    def log_message(self, message, level=logging.INFO):
        """Logs a message using the plugin's logger."""
        if level == logging.DEBUG: log.debug(message)
        elif level == logging.WARNING: log.warning(message)
        elif level == logging.ERROR: log.error(message)
        elif level == logging.CRITICAL: log.critical(message)
        else: log.info(message)
        
    def _ensure_point_xy(self, point):
        """
        Ensures a point is a QgsPointXY object, converting from other point formats if necessary.

        This function handles various point types including QgsPoint, QgsPointXY, and objects
        with x/y attributes or coordinates in lists/tuples.

        Args:
            point: Input point in any supported format

        Returns:
            QgsPointXY: Converted point, or None if conversion fails
        """
        if point is None:
            return None

        try:
            # Already correct type
            if isinstance(point, QgsPointXY):
                return point

            # QgsPoint from QGIS API
            elif isinstance(point, QgsPoint):
                return QgsPointXY(point.x(), point.y())

            # Objects with x() and y() methods
            elif hasattr(point, 'x') and hasattr(point, 'y'):
                # Handle case where x/y are methods vs. properties
                x = point.x() if callable(point.x) else point.x
                y = point.y() if callable(point.y) else point.y
                return QgsPointXY(x, y)

            # List or tuple with coordinates
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                return QgsPointXY(float(point[0]), float(point[1]))

            # Dictionary with x/y keys
            elif isinstance(point, dict) and 'x' in point and 'y' in point:
                return QgsPointXY(float(point['x']), float(point['y']))

            # Handle other cases
            else:
                log.warning(f"Could not convert {type(point)} to QgsPointXY")
                return None

        except Exception as e:
            log.exception(f"Error converting point to QgsPointXY: {e}")
            return None

    def _reverse_line_geometry(self, line_geom):
        """
        Creates a reversed version of a line geometry by reversing its vertices.

        Args:
            line_geom (QgsGeometry): Line geometry to reverse

        Returns:
            QgsGeometry: Reversed line geometry, or original if not reversible
        """
        if not line_geom or line_geom.isEmpty():
            log.warning("Cannot reverse empty geometry")
            return line_geom

        try:
            # Check if it's a line geometry
            if line_geom.type() != QgsWkbTypes.LineGeometry:
                log.warning(f"Cannot reverse non-line geometry (type: {line_geom.type()})")
                return line_geom

            # Extract vertices
            vertices = list(line_geom.vertices())

            # Need at least 2 vertices to reverse
            if len(vertices) < 2:
                return line_geom

            # For RRT compatibility: handle both QgsPoint and QgsPointXY
            points_xy = []
            for vertex in vertices:
                if isinstance(vertex, QgsPointXY):
                    points_xy.append(vertex)
                elif isinstance(vertex, QgsPoint):
                    points_xy.append(QgsPointXY(vertex.x(), vertex.y()))
                else:
                    # Handle any other point-like object
                    try:
                        points_xy.append(QgsPointXY(vertex.x(), vertex.y()))
                    except (AttributeError, TypeError):
                        log.warning(f"Skipping vertex with unsupported type: {type(vertex)}")

            # Reverse points and create new geometry
            if points_xy:
                return QgsGeometry.fromPolylineXY(list(reversed(points_xy)))
            else:
                return line_geom

        except Exception as e:
            log.exception(f"Error reversing line geometry: {e}")
            return line_geom

    # --- 1. SPS Import ---

    def _setup_import_csv_button(self):
        """Add Import CSV drop-down button after deviation lines button."""
        if hasattr(self, "_importCsvToolButton") and self._importCsvToolButton is not None:
            return
        row = getattr(self, "horizontalLayout_6", None)
        if row is None:
            log.warning("UI Warning: horizontalLayout_6 not found for Import CSV button")
            return
        self._importCsvToolButton = QToolButton(self)
        self._importCsvToolButton.setText("Import CSV")
        self._importCsvToolButton.setToolButtonStyle(_QT_TOOLBUTTON_TEXT_ONLY)
        self._importCsvToolButton.setPopupMode(_QT_MENU_BUTTON_POPUP)
        menu = QtWidgets.QMenu(self._importCsvToolButton)
        menu.addAction("Import CSV File...", self.handle_import_csv_quick)
        menu.addAction("Import CSV (Parsing)...", self.handle_import_csv_with_parsing)
        self._importCsvToolButton.setMenu(menu)
        self._importCsvToolButton.clicked.connect(self.handle_import_csv_quick)
        row.addWidget(self._importCsvToolButton)

    def _setup_mark_tba_actions_button(self):
        """
        Replace 'To Be Acquired' push button with menu button:
        - To Be Acquired
        - To Be Acq. to Acquired
        """
        old_btn = getattr(self, "markTbaButton", None)
        row = getattr(self, "horizontalLayout_7", None)
        if old_btn is None or row is None:
            log.warning("UI Warning: markTbaButton/horizontalLayout_7 not found.")
            return
        if isinstance(old_btn, QToolButton) and getattr(self, "_markTbaMenuReady", False):
            return

        idx = row.indexOf(old_btn)
        tb = QToolButton(old_btn.parentWidget())
        tb.setObjectName("markTbaButton")
        tb.setText("To Be Acquired")
        tb.setToolButtonStyle(_QT_TOOLBUTTON_TEXT_ONLY)
        tb.setPopupMode(_QT_MENU_BUTTON_POPUP)

        menu = QtWidgets.QMenu(tb)
        menu.addAction("To Be Acquired", self.handle_mark_tba)
        menu.addAction("To Be Acq. to Acquired", self.handle_mark_tba_to_acquired)
        tb.setMenu(menu)
        tb.clicked.connect(self.handle_mark_tba)

        if idx >= 0:
            row.insertWidget(idx, tb)
            row.removeWidget(old_btn)
        old_btn.deleteLater()
        self.markTbaButton = tb
        self._markTbaMenuReady = True

    def _setup_line_actions_button(self):
        """Merge Duplicate/Remove line actions into one drop-down button."""
        row = getattr(self, "horizontalLayout_refresh_status", None)
        dup_btn = getattr(self, "duplicateLineButton", None)
        rem_btn = getattr(self, "removeLineButton", None)
        if row is None:
            log.warning("UI Warning: horizontalLayout_refresh_status not found.")
            return
        if dup_btn is None and rem_btn is None:
            return
        if getattr(self, "_lineActionsButtonReady", False):
            return

        anchor = dup_btn or rem_btn
        idx = row.indexOf(anchor) if anchor is not None else -1

        actions_btn = QToolButton(self)
        actions_btn.setObjectName("lineActionsButton")
        actions_btn.setText("Line Actions")
        actions_btn.setPopupMode(_QT_INSTANT_POPUP)
        actions_btn.setToolButtonStyle(_QT_TOOLBUTTON_TEXT_ONLY)
        menu = QtWidgets.QMenu(actions_btn)
        menu.addAction("Duplicate Line", self.handle_duplicate_line)
        menu.addAction("Remove Line", self.handle_remove_line)
        actions_btn.setMenu(menu)

        if idx >= 0:
            row.insertWidget(idx, actions_btn)
        else:
            row.addWidget(actions_btn)

        if dup_btn is not None:
            row.removeWidget(dup_btn)
            dup_btn.deleteLater()
        if rem_btn is not None:
            row.removeWidget(rem_btn)
            rem_btn.deleteLater()

        self._lineActionsButton = actions_btn
        self._lineActionsButtonReady = True

    def _normalize_action_button_rows(self):
        """Unify widths/heights for action rows so drop-downs match neighbors."""
        # Rename generation row buttons per request.
        if hasattr(self, "generateLinesButton"):
            self.generateLinesButton.setText("Create Lookahead Lines")
        if hasattr(self, "calculateDeviationsButton"):
            self.calculateDeviationsButton.setText("Create Deviation Lines")

        expanding = QtWidgets.QSizePolicy(
            _QSP_EXPANDING,
            _QSP_FIXED,
        )
        # Match compact dock baseline used in _enforce_compact_dock_heights.
        uniform_h = 22

        def _normalize_row(layout_name):
            row = getattr(self, layout_name, None)
            if row is None:
                return
            for i in range(row.count()):
                it = row.itemAt(i)
                w = it.widget() if it is not None else None
                if w is None:
                    continue
                w.setSizePolicy(expanding)
                if not _IS_QT6:
                    w.setFixedHeight(uniform_h)
                if isinstance(w, QToolButton):
                    # Match QPushButton compact style as close as possible.
                    if not _IS_QT6:
                        w.setFixedHeight(uniform_h + 3)
                        w.setStyleSheet(
                            "QToolButton {"
                            "padding: 2px 10px;"
                            "margin: 0px;"
                            "}"
                            "QToolButton::menu-button {"
                            "border: none;"
                            "width: 12px;"
                            "}"
                            "QToolButton::menu-indicator {"
                            "subcontrol-origin: padding;"
                            "subcontrol-position: center right;"
                            "right: 3px;"
                            "}"
                        )
                row.setStretch(i, 1)

        # Keep these three action rows visually symmetric.
        _normalize_row("horizontalLayout_refresh_status")
        _normalize_row("horizontalLayout_7")
        _normalize_row("horizontalLayout_6")

    def _choose_csv_file(self):
        csv_filter = "CSV Files (*.csv *.txt);;All Files (*)"
        start_dir = getattr(self, "last_csv_dir", "") or getattr(self, "last_sps_dir", "")
        csv_file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV file with Sequence / Line",
            start_dir,
            csv_filter,
        )
        if not csv_file_path:
            return None
        self.last_csv_dir = os.path.dirname(csv_file_path)
        return csv_file_path

    def handle_import_csv_quick(self):
        """Quick CSV import: file picker + default mapping (seq=0, line=1, header=0)."""
        csv_file = self._choose_csv_file()
        if not csv_file:
            return
        mapping = {"col_sequence": 0, "col_line": 1, "header_lines": 0}
        self._apply_csv_sequence_import(csv_file, mapping)

    def handle_import_csv_with_parsing(self):
        """CSV import via parsing dialog (column mapping + header rows + saved file path)."""
        if CsvParsingDialog is None:
            QMessageBox.warning(self, "CSV Import", "CSV parsing dialog is not available in this build.")
            return
        # Auto-import using previously saved parsing config + file path when possible.
        try:
            saved_map = plugin_settings.get_csv_parsing() if plugin_settings else None
        except Exception:
            saved_map = None
        if isinstance(saved_map, dict):
            saved_csv = str(saved_map.get("file_path") or "").strip()
            if saved_csv and os.path.isfile(saved_csv):
                self.last_csv_dir = os.path.dirname(saved_csv)
                self._apply_csv_sequence_import(saved_csv, saved_map)
                return
            # If mapping exists but file path is empty/missing, ask for CSV every time.
            picked_csv = self._choose_csv_file()
            if not picked_csv:
                return
            saved_map = dict(saved_map)
            saved_map["file_path"] = picked_csv
            self._apply_csv_sequence_import(picked_csv, saved_map)
            return

        dlg = CsvParsingDialog(parent=self)
        if dlg.exec() != _QDIALOG_ACCEPTED:
            return
        mapping = dlg.get_mapping()
        csv_file = mapping.get("file_path")
        if csv_file:
            self.last_csv_dir = os.path.dirname(csv_file)
        self._apply_csv_sequence_import(csv_file, mapping)

    @staticmethod
    def _parse_csv_cell_to_int(value):
        txt = str(value).strip()
        if not txt:
            raise ValueError("empty")
        return int(float(txt))

    def _read_csv_sequence_mapping(self, csv_file_path, mapping):
        """Read CSV and return list[(sequence, line_num)] sorted by sequence."""
        col_seq = int(mapping.get("col_sequence", 0))
        col_line = int(mapping.get("col_line", 1))
        header_lines = max(0, int(mapping.get("header_lines", 0)))
        max_col = max(col_seq, col_line)

        rows = []
        errors = 0
        with open(csv_file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except Exception:
                # Default separator for planning CSV is TAB; also supports comma/semicolon/pipe via sniff.
                dialect = csv.excel_tab
            reader = csv.reader(f, dialect=dialect)
            for idx, row in enumerate(reader):
                if idx < header_lines:
                    continue
                if not row or all(not str(c).strip() for c in row):
                    continue
                if len(row) <= max_col:
                    errors += 1
                    continue
                try:
                    seq_num = self._parse_csv_cell_to_int(row[col_seq])
                    line_num = self._parse_csv_cell_to_int(row[col_line])
                except Exception:
                    errors += 1
                    continue
                rows.append((seq_num, line_num))
        if errors:
            log.info("CSV import skipped %s row(s) due to parse issues", errors)
        rows.sort(key=lambda x: x[0])
        return rows

    def _set_status_for_line_nums(self, line_nums, new_status):
        """Bulk-update Status for provided base line numbers."""
        combo = getattr(self, "sps_layer_combo", None)
        target_layer = combo.currentLayer() if combo is not None else None
        if not target_layer:
            raise ValueError("No SPS layer selected")
        try:
            if not target_layer.isValid():
                raise ValueError("Selected SPS layer is invalid")
        except RuntimeError:
            raise ValueError("Selected SPS layer is no longer available")
        status_field_idx = target_layer.fields().lookupField("Status")
        if status_field_idx == -1:
            raise ValueError(f"Cannot find 'Status' field in layer '{target_layer.name()}'")
        unique_lines = sorted(set(int(x) for x in line_nums))
        if not unique_lines:
            return 0
        if len(unique_lines) == 1:
            line_expr = f'"LineNum" = {unique_lines[0]}'
        else:
            line_expr = '"LineNum" IN (' + ",".join(str(n) for n in unique_lines) + ")"
        req = QgsFeatureRequest().setFilterExpression(line_expr)
        req.setFlags(QgsFeatureRequest.NoGeometry)
        edit_started_here = False
        updated = 0
        try:
            if not target_layer.isEditable():
                if not target_layer.startEditing():
                    raise RuntimeError(f"Could not start editing on layer '{target_layer.name()}'")
                edit_started_here = True
            updates = {}
            for ft in target_layer.getFeatures(req):
                updates[ft.id()] = {status_field_idx: new_status}
            if not updates:
                return 0
            if not target_layer.dataProvider().changeAttributeValues(updates):
                raise RuntimeError(target_layer.dataProvider().lastError() or "Attribute update failed")
            updated = len(updates)
            if edit_started_here:
                if not target_layer.commitChanges():
                    raise RuntimeError("\n".join(target_layer.commitErrors()) or "Commit failed")
                edit_started_here = False
            target_layer.triggerRepaint()
            return updated
        except Exception:
            if edit_started_here and target_layer.isEditable():
                target_layer.rollBack()
            raise

    def _apply_csv_sequence_import(self, csv_file_path, mapping):
        """Mark imported lines as To Be Acquired and queue them in imported sequence order."""
        if not self._require_sail_layer("Import CSV"):
            return
        if not csv_file_path or not os.path.isfile(csv_file_path):
            QMessageBox.warning(self, "CSV Import", "Selected CSV file was not found.")
            return
        try:
            seq_rows = self._read_csv_sequence_mapping(csv_file_path, mapping)
        except Exception as e:
            log.exception("CSV import parse failed: %s", e)
            QMessageBox.critical(self, "CSV Import", f"Failed to parse CSV file:\n{e}")
            return
        if not seq_rows:
            QMessageBox.warning(self, "CSV Import", "No valid rows found in CSV.")
            return

        imported_line_to_seq = {}
        for seq_num, line_num in seq_rows:
            prev = imported_line_to_seq.get(line_num)
            if prev is None or seq_num < prev:
                imported_line_to_seq[line_num] = seq_num
        imported_lines = sorted(imported_line_to_seq.keys())

        try:
            updated_pts = self._set_status_for_line_nums(imported_lines, "To Be Acquired")
        except Exception as e:
            log.exception("CSV import status update failed: %s", e)
            QMessageBox.critical(self, "CSV Import", f"Failed to set status to 'To Be Acquired':\n{e}")
            return

        # CSV import always replaces any previously queued sequence numbers.
        self._selection_sequence = []
        self._selection_sequence_numbers = {}
        self.handle_apply_filter(True)
        by_base_line = {}
        if hasattr(self, "lineListWidget"):
            for i in range(self.lineListWidget.count()):
                it = self.lineListWidget.item(i)
                try:
                    base_ln = int(it.data(_QT_USER_ROLE + 2))
                except (TypeError, ValueError):
                    continue
                by_base_line.setdefault(base_ln, it)

        ordered_line_ids = []
        ordered_sequence_values = {}
        for line_num, _seq_num in sorted(imported_line_to_seq.items(), key=lambda kv: kv[1]):
            item = by_base_line.get(line_num)
            if item is None:
                continue
            line_id = str(item.data(_QT_USER_ROLE))
            ordered_line_ids.append(line_id)
            ordered_sequence_values[line_id] = int(_seq_num)
            item.setSelected(True)
        self._selection_sequence = ordered_line_ids
        self._selection_sequence_numbers = ordered_sequence_values

        self._refresh_line_list_item_labels()
        self._sync_first_line_spinbox_from_shooting_queue()

        QMessageBox.information(
            self,
            "CSV Import",
            f"Imported {len(imported_line_to_seq)} line(s) from CSV.\n"
            f"Updated {updated_pts} SPS point(s) to 'To Be Acquired'.\n"
            f"Queued {len(ordered_line_ids)} visible line(s) by imported sequence.",
        )

    def handle_sps_import_button(self):
        """
        Handles the 'Import SPS File...' button click.
        
        Opens a file dialog to select an SPS file, then processes it and
        creates a new GeoPackage layer with the imported data.
        """
        log.info("Opening file dialog for SPS import")
        
        # Configure and display file selection dialog
        sps_file_filter = "SPS Files (*.sps *.s00 *.s01 *.txt);;All Files (*)"
        sps_file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SPS Pre-plot File",
            self.last_sps_dir,
            sps_file_filter
        )
        
        # Process selection result
        if not sps_file_path:
            log.info("SPS file selection cancelled by user")
            return
            
        # Update last directory and process the file
        log.info(f"Selected SPS file: {sps_file_path}")
        self.last_sps_dir = os.path.dirname(sps_file_path)

        parse_config = None
        if SpsParsingDialog is not None:
            dlg = SpsParsingDialog(sps_file_path, parent=self)
            if dlg.exec() != _QDIALOG_ACCEPTED:
                log.info("SPS parsing dialog cancelled by user")
                return
            parse_config = dlg.get_mapping()
            log.info(f"SPS parsing dialog mapping applied: {parse_config}")

        # Delegate to parsing function
        self.parse_and_load_sps(sps_file_path, parse_config=parse_config)
    
    def parse_and_load_sps(self, sps_file_path, parse_config=None):
        """
        Parses an SPS file and loads the data into a new GeoPackage layer.
        
        Args:
            sps_file_path (str): Path to the SPS file to be parsed
            
        Returns:
            None
        """
        log.info(f"Starting SPS parsing: {sps_file_path}")
        
        # Initialize data containers
        parsed_data = []  # Will hold dictionaries of parsed points
        error_log = []    # Will hold parsing errors

        # Step 1: Parse the SPS file (skip leading non-shot rows; 0 was a bug — it fed headers into fixed columns)
        if parse_config and isinstance(parse_config, dict) and "header_lines" in parse_config:
            skip_headers = int(parse_config.get("header_lines", 0))
            log.info(f"SPS import: using dialog header skip = {skip_headers}")
        else:
            detected_skip = self._detect_sps_header_lines_to_skip(sps_file_path)
            if detected_skip is not None:
                skip_headers = detected_skip
                log.info(f"SPS import: auto-detected {skip_headers} header lines to skip")
            else:
                skip_headers = 36
                log.info("SPS import: could not auto-detect header length; skipping 36 lines (typical SPS)")

        try:
            parsed_data, error_log = self._parse_sps_file_content(
                sps_file_path, skip_headers, parse_config=parse_config
            )
        except UnicodeDecodeError as ude:
            error_msg = f"Encoding Error: Could not read file with 'latin-1'. Try another encoding? Error: {ude}"
            log.error(error_msg)
            QMessageBox.critical(self, "File Encoding Error", error_msg)
            return
        except FileNotFoundError:
            error_msg = f"Error: SPS file not found at {sps_file_path}"
            log.error(error_msg)
            QMessageBox.critical(self, "File Not Found", f"Could not find the specified SPS file:\n{sps_file_path}")
            return
        except Exception as e:
            log.exception(f"Error reading SPS file: {e}")
            QMessageBox.critical(self, "File Read Error", f"An error occurred while reading the SPS file:\n{e}")
            return
        
        # Validate parsing results
        if error_log:
            log.warning(f"SPS Parsing completed with {len(error_log)} errors/warnings")
        
        if not parsed_data:
            log.error("No valid data points parsed from the SPS file")
            QMessageBox.warning(self, "Parsing Failed", "Could not parse any valid data points from the selected SPS file")
            return
        
        log.info(f"Successfully parsed {len(parsed_data)} data points")
        
        # Step 2: Get output path from user
        output_path = self._get_output_geopackage_path()
        if not output_path:
            return  # User cancelled
        
        # Step 3: Create new GeoPackage or append to existing
        try:
            fields = self._create_sps_layer_fields()
            crs = QgsProject.instance().crs()
            if not crs.isValid():
                log.error("Project CRS is invalid. Cannot create layer")
                QMessageBox.critical(self, "Invalid CRS", 
                    "The current QGIS project CRS is invalid. Please set a valid project CRS before importing")
                return

            log.debug(f"Using CRS: {crs.authid()} for output layer")
            stem = os.path.splitext(os.path.basename(output_path))[0]

            if os.path.isfile(output_path):
                table_name = self._pick_sps_append_layer_name(output_path)
                if not table_name:
                    QMessageBox.critical(
                        self,
                        "SPS Import",
                        "The selected GeoPackage has no feature tables.\n"
                        "Choose a different file or use a new file name to create a layer.",
                    )
                    return
                points_added, append_err = self._append_sps_points_to_gpkg_layer(
                    output_path, table_name, parsed_data
                )
                if append_err:
                    log.error(append_err)
                    QMessageBox.critical(self, "SPS Import", append_err)
                    return
                log.info(f"Appended to existing GeoPackage layer '{table_name}': {points_added} point(s)")
                if points_added == 0:
                    QMessageBox.warning(
                        self,
                        "SPS Import",
                        "No new points were added (all adds may have failed). Check the log.",
                    )
                    return
                self._ensure_sps_layer_in_project(output_path, table_name)
                headings_ok = self.handle_calculate_headings(silent=True)
                extra_hdg = (
                    "\n\nHeadings were calculated automatically (same logic as Calculate Headings)."
                    if headings_ok
                    else ""
                )
                QMessageBox.information(
                    self,
                    "SPS Import",
                    f"Appended {points_added} point(s) to existing GeoPackage layer '{table_name}'.\n\n"
                    "If you see no change: refresh the layer or toggle visibility."
                    + extra_hdg,
                )
            else:
                writer = create_vector_writer_compat(
                    output_path=output_path,
                    fields=fields,
                    wkb_type=QgsWkbTypes.Point,
                    crs=crs,
                    driver_name="GPKG",
                    encoding="UTF-8",
                )
                if writer.hasError() != QgsVectorFileWriter.NoError:
                    error_msg = f"Error creating GeoPackage file: {writer.errorMessage()}"
                    log.error(error_msg)
                    QMessageBox.critical(self, "Layer Creation Error", error_msg)
                    return

                points_added = self._write_features_to_layer(writer, parsed_data, fields)
                del writer

                log.info(f"Finished writing GeoPackage. {points_added}/{len(parsed_data)} points added")

                if points_added == 0:
                    QMessageBox.critical(
                        self,
                        "SPS Import",
                        "GeoPackage was created but no features were written. Check CRS, disk access, and log file.",
                    )
                    return

                if not self._load_created_layer(output_path, layer_table_name=stem):
                    return
                headings_ok = self.handle_calculate_headings(silent=True)
                extra_hdg = (
                    "\n\nHeadings were calculated automatically (same logic as Calculate Headings)."
                    if headings_ok
                    else ""
                )
                QMessageBox.information(
                    self,
                    "SPS Import",
                    f"Imported {points_added} point(s).\n\n"
                    "If you see no points: set the QGIS project CRS to your survey grid CRS, "
                    "then right-click the layer → Zoom to Layer."
                    + extra_hdg,
                )

        except Exception as e:
            log.exception(f"SPS file processing error: {e}")
            QMessageBox.critical(self, "SPS Parse Error", f"Error processing SPS file:\n{e}")

    def _try_parse_sps_s_line_whitespace(self, line):
        """
        SPS 2.1 / Gator-style S record: tokens after splitting on whitespace.
        Example: S   9001.00   1001.00  1A1   735449.4 7205297.7   0.0
        Line and SP may be floats; easting/northing/elevation are the last three floats.
        Returns dict or None.
        """
        if not line or len(line) < 10:
            return None
        parts = line.split()
        if len(parts) < 6:
            return None
        if parts[0] not in ("S", "s"):
            return None
        try:
            line_num = int(float(parts[1]))
            sp = int(float(parts[2]))
            easting = float(parts[-3])
            northing = float(parts[-2])
            float(parts[-1])  # elevation — must be numeric
        except (ValueError, TypeError, IndexError):
            return None
        if line_num <= 0 or sp <= 0:
            return None
        if not (math.isfinite(easting) and math.isfinite(northing)):
            return None
        if abs(easting) + abs(northing) < 1.0:
            return None
        return {"line": line_num, "sp": sp, "e": easting, "n": northing}

    def _detect_sps_header_lines_to_skip(self, sps_file_path, max_scan=600):
        """
        Find the 0-based index of the first line that looks like a shot row (SPS 2.1 whitespace
        or UKOOA-style fixed columns). Returns None if nothing plausible is found.
        """
        def scan_fixed_columns(require_leading_s):
            with open(sps_file_path, "r", encoding="latin-1") as f:
                for idx, raw in enumerate(f):
                    if idx >= max_scan:
                        return None
                    line = raw.rstrip("\r\n")
                    if len(line) < 65:
                        continue
                    lst = line.lstrip()
                    if require_leading_s and lst and lst[0] not in ("S", "s"):
                        continue
                    try:
                        line_num_str = line[7:12].strip()
                        sp_str = line[17:21].strip()
                        easting_str = line[46:56].strip()
                        northing_str = line[56:66].strip()
                        if not (line_num_str and sp_str and easting_str and northing_str):
                            continue
                        line_num = int(line_num_str)
                        sp = int(sp_str)
                        easting = float(easting_str)
                        northing = float(northing_str)
                    except (ValueError, IndexError, TypeError):
                        continue
                    if line_num <= 0 or sp <= 0:
                        continue
                    if not (math.isfinite(easting) and math.isfinite(northing)):
                        continue
                    if abs(easting) + abs(northing) < 1.0:
                        continue
                    return idx
            return None

        with open(sps_file_path, "r", encoding="latin-1") as f:
            for idx, raw in enumerate(f):
                if idx >= max_scan:
                    break
                line = raw.rstrip("\r\n")
                w = self._try_parse_sps_s_line_whitespace(line)
                if w is not None:
                    return idx

        found = scan_fixed_columns(require_leading_s=True)
        if found is not None:
            return found
        return scan_fixed_columns(require_leading_s=False)

    def _try_parse_sps_line_custom_fixed(self, line, parse_config):
        """Parse using user-selected fixed-width columns from SPS parsing dialog."""
        try:
            line_col = int(parse_config.get("col_line", 0))
            line_w = int(parse_config.get("col_line_width", 0))
            sp_col = int(parse_config.get("col_sp", 0))
            sp_w = int(parse_config.get("col_sp_width", 0))
            e_col = int(parse_config.get("col_easting", 0))
            e_w = int(parse_config.get("col_easting_width", 0))
            n_col = int(parse_config.get("col_northing", 0))
            n_w = int(parse_config.get("col_northing_width", 0))
        except (TypeError, ValueError):
            return None

        if min(line_w, sp_w, e_w, n_w) <= 0:
            return None

        try:
            line_num = int(float(line[line_col:line_col + line_w].strip()))
            sp = int(float(line[sp_col:sp_col + sp_w].strip()))
            easting = float(line[e_col:e_col + e_w].strip())
            northing = float(line[n_col:n_col + n_w].strip())
        except (ValueError, TypeError, IndexError):
            return None

        if line_num <= 0 or sp <= 0:
            return None
        if not (math.isfinite(easting) and math.isfinite(northing)):
            return None
        if abs(easting) + abs(northing) < 1.0:
            return None
        return {"line": line_num, "sp": sp, "e": easting, "n": northing}

    def _parse_sps_file_content(self, sps_file_path, skip_headers=36, parse_config=None):
        """
        Parse the content of an SPS file.
        
        Args:
            sps_file_path (str): Path to the SPS file
            skip_headers (int): Number of header lines to skip
            
        Returns:
            tuple: (parsed_data, error_log) - Lists of parsed points and error messages
        """
        parsed_data = []
        error_log = []
        line_count = 0
        
        with open(sps_file_path, 'r', encoding='latin-1') as f:
            for line in f:
                line_count += 1
                
                # Skip header lines
                if line_count <= skip_headers:
                    continue
                    
                line = line.rstrip()  # Remove trailing whitespace
                if not line:
                    continue

                # Priority 1: user-selected fixed-width mapping from SPS parsing helper.
                if parse_config:
                    mapped = self._try_parse_sps_line_custom_fixed(line, parse_config)
                    if mapped is not None:
                        parsed_data.append(mapped)
                        continue

                # Priority 2: SPS 2.1 (e.g. Gator): space-separated S record with decimal line/SP
                ws = self._try_parse_sps_s_line_whitespace(line)
                if ws is not None:
                    parsed_data.append(ws)
                    continue

                # SPS header rows (H00, H26, …) — skip without UKOOA fixed-column parse (avoids false points)
                ul = line.lstrip()
                if len(ul) >= 2 and ul[0] in ("H", "h") and ul[1].isdigit():
                    continue

                # If user mapping is enabled, do not fall through to legacy hard-coded parser.
                if parse_config:
                    continue

                if len(line) < 65:
                    log.debug(f"Line {line_count}: Skipped short line")
                    error_log.append(f"Line {line_count}: Skipped short line")
                    continue

                # UKOOA-style fixed columns
                try:
                    line_num_str = line[7:12].strip()
                    sp_str = line[17:21].strip()
                    easting_str = line[46:56].strip()
                    northing_str = line[56:66].strip()

                    if not line_num_str or not sp_str or not easting_str or not northing_str:
                        raise ValueError("Missing required field(s)")

                    line_num = int(line_num_str)
                    sp = int(sp_str)
                    easting = float(easting_str)
                    northing = float(northing_str)

                    parsed_data.append({
                        "line": line_num,
                        "sp": sp,
                        "e": easting,
                        "n": northing,
                    })
                except (ValueError, IndexError, TypeError) as e:
                    error_msg = f"Line {line_count}: Error parsing '{line[:70]}...' - {e}"
                    log.warning(error_msg)
                    error_log.append(error_msg)
        
        return parsed_data, error_log
    
    def _get_output_geopackage_path(self):
        """
        Get the output GeoPackage path from the user.
        
        Returns:
            str: Selected file path or None if cancelled
        """
        gpkg_filter = "GeoPackage (*.gpkg)"
        # Avoid native "replace existing file?" dialog; we append instead and confirm below.
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save SPS as GeoPackage (new file) or choose existing to append points",
            self.last_gpkg_dir,
            gpkg_filter,
            options=_QFILEDIALOG_DONT_CONFIRM_OVERWRITE,
        )

        if not output_path:
            log.info("User cancelled saving the output layer")
            return None

        # Ensure correct extension
        if not output_path.lower().endswith(".gpkg"):
            output_path += ".gpkg"

        if os.path.isfile(output_path):
            reply = QMessageBox.question(
                self,
                "Confirm Save As",
                f"This GeoPackage already exists:\n{output_path}\n\n"
                "Do you want to append SPS data?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                log.info("User declined appending to existing GeoPackage")
                return None

        # Update last directory
        self.last_gpkg_dir = os.path.dirname(output_path)
        log.debug(f"Output GeoPackage path set to: {output_path}")

        return output_path
    
    def _create_sps_layer_fields(self):
        """
        Create and return the field definitions for the SPS layer.
        
        Returns:
            QgsFields: Field definitions for the SPS layer
        """
        fields = QgsFields()
        fields.append(QgsField("LineNum", QVariant.Int, "Integer"))
        fields.append(QgsField("SP", QVariant.Int, "Integer"))
        fields.append(QgsField("Easting", QVariant.Double, "Double"))
        fields.append(QgsField("Northing", QVariant.Double, "Double"))
        fields.append(QgsField("Status", QVariant.String, "String", 20))
        fields.append(QgsField("Heading", QVariant.Double, "Double"))
        return fields
    
    def _write_features_to_layer(self, writer, parsed_data, fields):
        """
        Write parsed data as features to the layer.
        
        Args:
            writer (QgsVectorFileWriter): The vector file writer
            parsed_data (list): The parsed point data
            fields (QgsFields): The fields definition
            
        Returns:
            int: Number of points successfully added
        """
        feature = QgsFeature(fields)
        points_added = 0
        
        for point_data in parsed_data:
            # Create point geometry
            point_xy = QgsPointXY(point_data['e'], point_data['n'])
            geometry = QgsGeometry.fromPointXY(point_xy)
            feature.setGeometry(geometry)
            
            # Set attributes (Status left NULL — user marks via Acquired / TBA / Pending)
            feature.setAttributes([
                point_data['line'],
                point_data['sp'],
                point_data['e'],
                point_data['n'],
                NULL,
                NULL
            ])
            
            # Add to layer
            if writer.addFeature(feature):
                points_added += 1
            else:
                log.warning(
                    f"Error adding feature for Line {point_data['line']}, " +
                    f"SP {point_data['sp']}: {writer.errorMessage()}"
                )
        
        return points_added

    def _gpkg_feature_table_names(self, gpkg_path):
        """List GeoPackage feature table names from gpkg_contents."""
        try:
            con = sqlite3.connect(gpkg_path)
            cur = con.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name"
            )
            names = [row[0] for row in cur.fetchall()]
            con.close()
            return names
        except Exception as e:
            log.warning(f"Could not read GeoPackage contents: {e}")
            return []

    def _sps_field_index(self, fields, name):
        idx = fields.lookupField(name)
        if idx != -1:
            return idx
        nlow = name.lower()
        for i in range(fields.count()):
            if fields.at(i).name().lower() == nlow:
                return i
        return -1

    # Triple-source preplots: sail line should use center (vessel) shots, not port/starboard.
    _CENTER_SOURCE_EXACT_TOKENS = frozenset({
        "c",
        "center",
        "centre",
        "central",
        "vessel",
        "cv",
        "2",
        "mid",
        "middle",
        "ctr",
        "cent",
        "cntr",
        "cl",
        "gc",
        "cntline",
        "centerline",
        "cnt_line",
        "gun_center",
        "vessel_center",
    })

    def _sps_source_role_field_index(self, fields):
        """
        Optional attribute marking which source a shot belongs to (P/C/S, etc.).
        If present, line geometry prefers rows tagged as center / vessel.
        """
        for fname in ("Position", "Source", "Gun", "Src", "ShotType", "Sensor"):
            idx = self._sps_field_index(fields, fname)
            if idx >= 0:
                return idx, fname
        return -1, None

    def _is_center_source_position_value(self, val):
        if val is None or val == NULL:
            return False
        t = str(val).strip().casefold()
        if not t:
            return False
        t = t.replace("-", "_").replace(" ", "_")
        if t in self._CENTER_SOURCE_EXACT_TOKENS:
            return True
        if t in ("port", "p", "starboard", "stbd", "sb", "ps", "stb"):
            return False
        if "center" in t or "centre" in t or "vessel" in t or "cntline" in t or "gun_center" in t:
            return True
        return False

    def _is_port_source_position_value(self, val):
        if val is None or val == NULL:
            return False
        t = str(val).strip().casefold()
        if not t:
            return False
        if t in ("port", "ps", "port gun", "port source"):
            return True
        if t == "p":
            return True
        return "port" in t and "star" not in t

    def _is_stbd_source_position_value(self, val):
        if val is None or val == NULL:
            return False
        t = str(val).strip().casefold()
        if not t:
            return False
        if t in ("starboard", "stbd", "sb", "stb"):
            return True
        if t == "s":
            return True
        return "starboard" in t or "stbd" in t

    @staticmethod
    def _xy_mean_xy(group_rows):
        sx = sum(r["xy"].x() for r in group_rows) / len(group_rows)
        sy = sum(r["xy"].y() for r in group_rows) / len(group_rows)
        return QgsPointXY(sx, sy)

    @staticmethod
    def _nearest_row_to_group_mean_xy(group_rows):
        """Fallback center: row closest to group centroid."""
        if not group_rows:
            return None
        cen = LookaheadDockWidgetImpl._xy_mean_xy(group_rows)
        return min(
            group_rows,
            key=lambda r: (r["xy"].x() - cen.x()) ** 2 + (r["xy"].y() - cen.y()) ** 2,
        )

    def _center_xy_for_sp_group(self, group_rows, src_idx, nx=None, ny=None):
        """Centerline anchor for one SP group (tagged center, else middle row, else centroid)."""
        if not group_rows:
            return None
        if src_idx >= 0:
            cr = [r for r in group_rows if self._is_center_source_position_value(r.get("_src"))]
            if len(cr) == 1:
                return cr[0]["xy"]
            if len(cr) > 1:
                return self._xy_mean_xy(cr)
        # Even if a role field exists but center tag is unknown/missing, for triple groups
        # pick the cross-track middle shot (P-C-S style) instead of arithmetic centroid.
        if nx is not None and ny is not None and len(group_rows) >= 3:
            cen_t = self._xy_mean_xy(group_rows)
            scored = sorted(
                group_rows,
                key=lambda r: self._cross_track_dot(r["xy"], cen_t, nx, ny),
            )
            return scored[len(scored) // 2]["xy"]
        # Stable fallback: closest shot to the group centroid.
        near = self._nearest_row_to_group_mean_xy(group_rows)
        if near is not None:
            return near["xy"]
        return self._xy_mean_xy(group_rows)

    def _single_center_tagged_row(self, group_rows, src_idx):
        """Exactly one center-tagged shot in group, or None."""
        if src_idx < 0 or not group_rows:
            return None
        cr = [r for r in group_rows if self._is_center_source_position_value(r.get("_src"))]
        return cr[0] if len(cr) == 1 else None

    def _min_sp_center_anchor_xy(self, g_low, src_idx, cen_fallback, nx, ny):
        """
        Point on the central row at min SP: single center-tagged shot; else with ≥3 shots
        and no role field, middle shot by cross-track order (P–C–S); else centroid fallback.
        """
        one = self._single_center_tagged_row(g_low, src_idx)
        if one is not None:
            return one["xy"]
        if len(g_low) >= 3:
            cen_t = self._xy_mean_xy(g_low)
            scored = sorted(
                g_low,
                key=lambda r: self._cross_track_dot(r["xy"], cen_t, nx, ny),
            )
            return scored[len(scored) // 2]["xy"]
        return cen_fallback

    def _cross_track_dot(self, xy, cen_xy, nx, ny):
        return (xy.x() - cen_xy.x()) * nx + (xy.y() - cen_xy.y()) * ny

    def _extreme_projection_t_for_group(self, group_rows, ax0, ay0, ux, uy, pick_min=True):
        """
        Along-axis extreme projection for one SP group.
        pick_min=True -> earliest point on axis; False -> latest point on axis.
        """
        if not group_rows:
            return None
        best_t = None
        for r in group_rows:
            xy = r["xy"]
            t = (xy.x() - ax0) * ux + (xy.y() - ay0) * uy
            if best_t is None:
                best_t = t
            elif pick_min and t < best_t:
                best_t = t
            elif (not pick_min) and t > best_t:
                best_t = t
        return best_t

    def _extreme_projection_t_for_edge_groups(
        self, sp_groups, sorted_sps, ax0, ay0, ux, uy, pick_min=True, edge_window=3
    ):
        """
        Robust along-axis extreme near line edges.
        Uses first/last `edge_window` SP groups so missing shots at exact min/max SP
        (common in field SPS) do not shorten the generated centerline extent.
        """
        if not sorted_sps:
            return None
        n = max(1, int(edge_window))
        edge_sps = sorted_sps[:n] if pick_min else sorted_sps[-n:]
        best_t = None
        for sp in edge_sps:
            t = self._extreme_projection_t_for_group(
                sp_groups.get(sp) or [], ax0, ay0, ux, uy, pick_min=pick_min
            )
            if t is None:
                continue
            if best_t is None:
                best_t = t
            elif pick_min and t < best_t:
                best_t = t
            elif (not pick_min) and t > best_t:
                best_t = t
        return best_t

    def _outer_xy_first_sp_endpoint(self, group_rows, src_idx, nx, ny, cen_xy, negative_side=True):
        """
        Outer-row point at min SP: prefer port, then starboard-tagged, else extreme on one cross side.
        Returns (xy, row, outer_role) with outer_role in ('port', 'stbd', 'geom') so max SP can
        use the same gun row — line bearing can flip so geometric “same side” ≠ same source.
        """
        if not group_rows:
            return None, None, "geom"
        if len(group_rows) == 1:
            return group_rows[0]["xy"], group_rows[0], "geom"
        if src_idx >= 0:
            pr = [r for r in group_rows if self._is_port_source_position_value(r.get("_src"))]
            if pr:
                r0 = pr[0]
                return r0["xy"], r0, "port"
            sr = [r for r in group_rows if self._is_stbd_source_position_value(r.get("_src"))]
            if sr:
                r0 = sr[0]
                return r0["xy"], r0, "stbd"
        best_xy = None
        best_s = None
        best_row = None
        for r in group_rows:
            s = self._cross_track_dot(r["xy"], cen_xy, nx, ny)
            if best_s is None or (negative_side and s < best_s) or (not negative_side and s > best_s):
                best_s = s
                best_xy = r["xy"]
                best_row = r
        return best_xy, best_row, "geom"

    def _outer_xy_same_role_for_sp_group(
        self, group_rows, src_idx, outer_role, nx, ny, cen_xy, ref_dot
    ):
        """
        At max SP: same source row as at min SP (port→port, stbd→stbd). If that tag is missing,
        fall back to geometric same-side (ref_dot).
        """
        if not group_rows:
            return None, None
        if len(group_rows) == 1:
            return group_rows[0]["xy"], group_rows[0]
        if src_idx >= 0 and outer_role == "port":
            pr = [r for r in group_rows if self._is_port_source_position_value(r.get("_src"))]
            if pr:
                return pr[0]["xy"], pr[0]
        if src_idx >= 0 and outer_role == "stbd":
            sr = [r for r in group_rows if self._is_stbd_source_position_value(r.get("_src"))]
            if sr:
                return sr[0]["xy"], sr[0]
        return self._outer_xy_matched_side_for_sp_group(
            group_rows, src_idx, nx, ny, cen_xy, ref_dot
        )

    def _outer_xy_matched_side_for_sp_group(self, group_rows, src_idx, nx, ny, cen_xy, ref_dot):
        """
        Fallback: same cross-track sign as ref_dot = dot(outer_min - cen_min, n) —
        outermost shot on that side (prefer port among ties).
        """
        if not group_rows:
            return None, None
        if len(group_rows) == 1:
            return group_rows[0]["xy"], group_rows[0]
        want_non_neg = ref_dot >= 0.0
        scored = []
        for r in group_rows:
            d = self._cross_track_dot(r["xy"], cen_xy, nx, ny)
            scored.append((d, r))
        on_side = [
            (abs(d), r)
            for d, r in scored
            if (want_non_neg and d > 1e-9) or (not want_non_neg and d < -1e-9)
        ]
        if not on_side:
            on_side = [(abs(d), r) for d, r in scored]
        on_side.sort(key=lambda x: -x[0])
        if src_idx >= 0:
            for ad, r in on_side:
                if self._is_port_source_position_value(r.get("_src")):
                    return r["xy"], r
        _, r = on_side[0]
        return r["xy"], r

    def _attr_rep_row_for_sp_group(self, group_rows, src_idx):
        """Row used for Status/Heading on generated line (prefer center shot)."""
        if not group_rows:
            return None
        if src_idx >= 0:
            for r in group_rows:
                if self._is_center_source_position_value(r.get("_src")):
                    return r
        return group_rows[0]

    def _centerline_geometry_meta_from_line_rows(self, rows, src_idx):
        """
        Center axis = line through centroids of min-SP and max-SP station groups
        (mean of all shots at that SP — middle of spread for triple-source).

        Endpoints: global min/max of along-axis projection t = dot(p - origin, u)
        over every shot on the line, then map back to axis points origin + t*u.
        Same rule for one shot per SP or triple-source (no special-case outer chord).
        """
        sp_groups = defaultdict(list)
        for r in rows:
            sp_groups[r["sp"]].append(r)
        sorted_sps = sorted(sp_groups.keys())
        if len(sorted_sps) < 2:
            return None

        low_sp = sorted_sps[0]
        high_sp = sorted_sps[-1]
        g_low = sp_groups[low_sp]
        g_high = sp_groups[high_sp]

        rep_low = self._attr_rep_row_for_sp_group(g_low, src_idx)
        rep_high = self._attr_rep_row_for_sp_group(g_high, src_idx)
        if rep_low is None or rep_high is None:
            return None

        center_rows = []
        if src_idx >= 0:
            center_rows = [r for r in rows if self._is_center_source_position_value(r.get("_src"))]

        # Use Orthogonal Distance Regression (PCA) for a mathematically perfect centerline.
        # This minimizes the perpendicular distance from all stations to the line,
        # perfectly balancing any slight bow/curvature in the pre-plot data.
        if len(center_rows) >= 2:
            # Perfect fit through actual center shots
            c_sps = sorted(list(set(r["sp"] for r in center_rows)))
            pts = []
            for sp in c_sps:
                pts.append(self._xy_mean_xy([r for r in center_rows if r["sp"] == sp]))
        else:
            # Fallback: Fit through the mean coordinate of each SP (balances stagger perfectly)
            pts = []
            for sp in sorted_sps:
                pts.append(self._xy_mean_xy(sp_groups[sp]))

        if len(pts) < 2:
            return None

        n = len(pts)
        mean_x = sum(p.x() for p in pts) / n
        mean_y = sum(p.y() for p in pts) / n
        
        ixx = sum((p.x() - mean_x)**2 for p in pts)
        iyy = sum((p.y() - mean_y)**2 for p in pts)
        ixy = sum((p.x() - mean_x)*(p.y() - mean_y) for p in pts)
        
        if ixx == 0 and iyy == 0:
            return None
            
        # Angle of the principal axis (line of best fit)
        angle = 0.5 * math.atan2(2 * ixy, ixx - iyy)
        ux = math.cos(angle)
        uy = math.sin(angle)
        
        # Ensure the vector points from the first SP to the last SP
        dx = pts[-1].x() - pts[0].x()
        dy = pts[-1].y() - pts[0].y()
        if (ux * dx + uy * dy) < 0:
            ux = -ux
            uy = -uy
            
        ax0 = mean_x
        ay0 = mean_y

        t_low = None
        t_high = None
        for r in rows:
            xy = r["xy"]
            t = (xy.x() - ax0) * ux + (xy.y() - ay0) * uy
            if t_low is None or t < t_low:
                t_low = t
            if t_high is None or t > t_high:
                t_high = t
        if t_low is None or t_high is None:
            return None
        line_start_xy = QgsPointXY(ax0 + t_low * ux, ay0 + t_low * uy)
        line_end_xy = QgsPointXY(ax0 + t_high * ux, ay0 + t_high * uy)

        return {
            "lowest_sp": low_sp,
            "highest_sp": high_sp,
            "rep_low": rep_low,
            "rep_high": rep_high,
            "line_start_xy": line_start_xy,
            "line_end_xy": line_end_xy,
        }

    def _pick_sps_append_layer_name(self, gpkg_path):
        """
        Choose which GPKG layer to append SPS points to.
        Prefer table matching file basename, else first point layer with LineNum+SP.
        """
        stem = os.path.splitext(os.path.basename(gpkg_path))[0]
        names = self._gpkg_feature_table_names(gpkg_path)
        if not names:
            return None
        if stem in names:
            return stem

        def open_point(uri_suffix):
            uri = f"{gpkg_path}|layername={uri_suffix}"
            vl = QgsVectorLayer(uri, uri_suffix, "ogr")
            if vl.isValid() and vl.geometryType() == QgsWkbTypes.PointGeometry:
                return vl
            return None

        for n in names:
            vl = open_point(n)
            if vl and self._sps_field_index(vl.fields(), "LineNum") >= 0 and self._sps_field_index(vl.fields(), "SP") >= 0:
                return n
        for n in names:
            vl = open_point(n)
            if vl:
                return n
        return names[0]

    def _append_sps_points_to_gpkg_layer(self, output_path, table_name, parsed_data):
        """
        Append parsed SPS points to an existing GeoPackage layer.
        Returns (points_added, error_message_or_None).
        """
        uri = f"{output_path}|layername={table_name}"
        layer = QgsVectorLayer(uri, table_name, "ogr")
        if not layer.isValid():
            return 0, f"Cannot open layer '{table_name}' in the GeoPackage."
        if layer.geometryType() != QgsWkbTypes.PointGeometry:
            return 0, f"Layer '{table_name}' is not a point layer; cannot append SPS shots."

        flds = layer.fields()
        idx_ln = self._sps_field_index(flds, "LineNum")
        idx_sp = self._sps_field_index(flds, "SP")
        idx_e = self._sps_field_index(flds, "Easting")
        idx_n = self._sps_field_index(flds, "Northing")
        idx_st = self._sps_field_index(flds, "Status")
        idx_hd = self._sps_field_index(flds, "Heading")

        if idx_ln < 0 or idx_sp < 0:
            return 0, "Target layer must have LineNum and SP fields (same as SPS import)."
        if idx_e < 0 or idx_n < 0:
            return 0, "Target layer must have Easting and Northing fields (same as SPS import)."

        if not layer.isEditable() and not layer.startEditing():
            return 0, "Could not start editing the layer (read-only file or permission denied)."

        n_attr = flds.count()
        points_added = 0

        for point_data in parsed_data:
            attrs = [NULL] * n_attr
            attrs[idx_ln] = point_data["line"]
            attrs[idx_sp] = point_data["sp"]
            attrs[idx_e] = point_data["e"]
            attrs[idx_n] = point_data["n"]
            # Status unchanged from default NULL unless layer default value applies
            if idx_hd >= 0:
                attrs[idx_hd] = NULL

            feat = QgsFeature(flds)
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point_data["e"], point_data["n"])))
            feat.setAttributes(attrs)
            if layer.addFeature(feat):
                points_added += 1
            else:
                log.warning(f"addFeature failed for Line {point_data['line']} SP {point_data['sp']}")

        if not layer.commitChanges():
            errs = layer.commitErrors()
            layer.rollBack()
            return 0, "Failed to save appended points:\n" + "\n".join(errs) if errs else "Commit failed."

        return points_added, None

    def _refresh_vector_layer_data(self, lyr):
        try:
            if hasattr(lyr, "reload"):
                lyr.reload()
            else:
                lyr.dataProvider().reloadData()
        except Exception:
            pass
        lyr.triggerRepaint()

    def _ensure_sps_layer_in_project(self, output_path, table_name):
        """Add GPKG layer to project if not already present; otherwise refresh."""
        uri = f"{output_path}|layername={table_name}"
        try:
            norm = os.path.normcase(os.path.abspath(output_path))
        except Exception:
            norm = os.path.normcase(output_path)

        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            src = lyr.source()
            base = src.split("|")[0]
            try:
                same_file = os.path.normcase(os.path.abspath(base)) == norm
            except Exception:
                same_file = False
            if not same_file:
                continue
            if "|layername=" in src:
                compact = src.replace(" ", "")
                if f"layername={table_name}" not in compact and f"layername={table_name.lower()}" not in compact.lower():
                    continue
            log.info(f"Refreshing map layer after SPS append: {lyr.name()}")
            self._refresh_vector_layer_data(lyr)
            if hasattr(self, "sps_layer_combo"):
                self.sps_layer_combo.setLayer(lyr)
                QtCore.QTimer.singleShot(0, lambda l=lyr: self._sync_min_max_line_spinboxes_from_sps_layer(l))
            return True

        layer = QgsVectorLayer(uri, table_name, "ogr")
        if not layer.isValid():
            log.error(f"Could not load layer after append: {uri}")
            return False
        self._add_layer_to_lookahead_group(layer)
        if hasattr(self, "sps_layer_combo"):
            self.sps_layer_combo.setLayer(layer)
            QtCore.QTimer.singleShot(0, lambda l=layer: self._sync_min_max_line_spinboxes_from_sps_layer(l))
        log.info(f"Layer '{table_name}' added to project after append")
        return True

    def _load_created_layer(self, output_path, layer_table_name=None):
        """
        Load the created GeoPackage layer into the QGIS project.
        
        Args:
            output_path (str): Path to the GeoPackage file
            layer_table_name (str, optional): GPKG table name; default = file basename without .gpkg
            
        Returns:
            bool: True if successful, False otherwise
        """
        if layer_table_name is None:
            layer_table_name = os.path.splitext(os.path.basename(output_path))[0]
        uri = f"{output_path}|layername={layer_table_name}"
        layer = QgsVectorLayer(uri, layer_table_name, "ogr")
        if not layer.isValid():
            layer = QgsVectorLayer(output_path, layer_table_name, "ogr")
        if not layer.isValid():
            error_msg = f"Failed to load the created layer: {output_path}"
            log.error(error_msg)
            QMessageBox.critical(self, "Layer Load Error", error_msg)
            return False
        
        self._add_layer_to_lookahead_group(layer)
        log.info(f"Layer '{layer_table_name}' added to project")
        if hasattr(self, "sps_layer_combo"):
            self.sps_layer_combo.setLayer(layer)

        nfeat = layer.featureCount()
        if nfeat == 0:
            QMessageBox.warning(
                self,
                "SPS Import",
                "The layer was added but contains no features.",
            )
            return False

        if hasattr(self, "iface") and self.iface is not None:
            try:
                canvas = self.iface.mapCanvas()
                if canvas is not None:
                    extent = layer.extent()
                    if extent is not None and not extent.isEmpty():
                        canvas.setExtent(extent)
                        canvas.refresh()
            except Exception as zoom_e:
                log.debug(f"Zoom to imported layer skipped: {zoom_e}")

        return True

    # --- 2. Line Headings Calculator ---

    def handle_calculate_headings(self, silent=False):
        """
        Calculates default headings for lines in the selected SPS layer based on
        first and last points of each line, then updates the Heading attribute.

        Headings are calculated in degrees (0-360) and rounded to 1 decimal place.
        The method uses efficient bulk updates to handle large datasets.

        Args:
            silent: If True, do not show the final success message (e.g. after SPS import).

        Returns:
            True if headings were computed and committed; False otherwise.
        """
        heading_success = False
        # Start timing for performance reporting
        log.info("Starting heading calculation process")
        start_time = time.time()

        # --- 1. VALIDATE INPUTS ---
        source_layer = self._require_sail_layer("Calculate Headings", silent=silent)
        if not source_layer:
            log.warning("No SPS/Sail layer selected for heading calculation")
            return False

        # Verify required fields exist and are of correct type
        fields = source_layer.fields()
        line_num_idx = fields.lookupField("LineNum")
        sp_idx = fields.lookupField("SP")
        heading_idx = fields.lookupField("Heading")

        field_errors = []
        if line_num_idx == -1: 
            field_errors.append("'LineNum'")
        if sp_idx == -1: 
            field_errors.append("'SP'")
        if heading_idx == -1: 
            field_errors.append("'Heading'")
        elif not fields.at(heading_idx).isNumeric(): 
            field_errors.append("'Heading' must be numeric")

        if field_errors:
            error_message = "Missing or invalid required fields: " + ", ".join(field_errors)
            log.warning(f"Field validation failed: {error_message}")
            if not silent:
                QMessageBox.warning(self, "Input Error", error_message)
            return False

        src_idx, src_role_field = self._sps_source_role_field_index(fields)
        if src_idx >= 0:
            log.info(
                "Calculate headings: using role field %r — center line through center-tagged shots "
                "(triple-source); otherwise mean XY per SP.",
                src_role_field,
            )

        # --- 2. COLLECT LINE ENDPOINTS ---
        log.debug(f"Collecting line endpoints from {source_layer.name()}")
        line_endpoints = {}
        total_features = source_layer.featureCount()

        # Set up progress dialog for endpoint collection
        progress = QProgressDialog("Analyzing lines...", "Cancel", 0, 100, self)
        progress.setWindowModality(_QT_WINDOW_MODAL)
        progress.setMinimumDuration(0 if total_features > 10000 else 1000)
        progress.show()

        # Configure feature request to sort by LineNum and SP
        request = QgsFeatureRequest()
        request.setOrderBy(QgsFeatureRequest.OrderBy([
            QgsFeatureRequest.OrderByClause("LineNum"),
            QgsFeatureRequest.OrderByClause("SP")
        ]))

        try:
            by_line_rows = defaultdict(list)
            processed = 0
            n_skipped_null_attrs = 0
            n_skipped_bad_numeric = 0
            n_skipped_bad_geom = 0

            for feature in source_layer.getFeatures(request):
                # Check for user cancellation
                if progress.wasCanceled():
                    raise UserCancelException("Operation canceled by user")

                # Update progress periodically
                processed += 1
                if processed % 10000 == 0:
                    progress.setValue(min(int(processed / total_features * 100), 99))
                    log.debug(f"Processed {processed:,} of {total_features:,} features")
                    QApplication.processEvents()

                # Extract and validate feature attributes
                line_num = feature.attribute(line_num_idx)
                sp_val = feature.attribute(sp_idx)

                if line_num is None or line_num == NULL or sp_val is None or sp_val == NULL:
                    n_skipped_null_attrs += 1
                    continue

                try:
                    line_num = int(line_num)
                    sp_val = int(sp_val)
                except (ValueError, TypeError):
                    n_skipped_bad_numeric += 1
                    continue

                geom = feature.geometry()
                if not geom or geom.isNull() or geom.type() != QgsWkbTypes.PointGeometry:
                    n_skipped_bad_geom += 1
                    continue

                row = {"sp": sp_val, "xy": geom.asPoint()}
                if src_idx >= 0:
                    row["_src"] = feature.attribute(src_idx)
                by_line_rows[line_num].append(row)

            # Endpoints: one vertex per SP (center source if tagged, else mean of same-SP group)
            n_skipped_single_sp = 0
            for line_num, rows in by_line_rows.items():
                rows.sort(key=lambda r: r["sp"])
                meta = self._centerline_geometry_meta_from_line_rows(rows, src_idx)
                if meta is None:
                    log.debug("Skipping Line %s: fewer than two SP groups after center/mean resolution", line_num)
                    n_skipped_single_sp += 1
                    continue
                line_endpoints[line_num] = (meta["line_start_xy"], meta["line_end_xy"])

        except UserCancelException as uce:
            log.info(f"{uce}")
            return False
        except Exception as e:
            log.exception(f"Error collecting line endpoints: {e}")
            if not silent:
                QMessageBox.critical(self, "Error", f"Error collecting line data:\n{e}")
            return False
        finally:
            if 'progress' in locals() and progress:
                progress.close()

        # --- 3. CALCULATE HEADINGS ---
        log.debug(f"Calculating headings for {len(line_endpoints)} lines")
        line_headings = {}
        calculation_failures = 0

        for line_num, endpoints in line_endpoints.items():
            first_point, last_point = endpoints

            # Calculate heading using atan2 for reliable angle calculation
            dx = last_point.x() - first_point.x()
            dy = last_point.y() - first_point.y()

            # Skip if start and end points are too close
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                log.warning(f"Line {line_num}: Start and end points are coincident, cannot calculate heading")
                calculation_failures += 1
                continue
            
            # Calculate heading and normalize to 0-360 range, round to 1 decimal place
            rad = math.atan2(dx, dy)
            calculated_heading = math.degrees(rad)
            calculated_heading = (calculated_heading + 360) % 360
            calculated_heading = round(calculated_heading, 1)  # Round to 1 decimal place
            line_headings[line_num] = calculated_heading

        # Exit if no headings could be calculated
        if not line_headings:
            log.warning("No valid headings could be calculated")
            parts = [
                "Could not calculate headings for any lines.",
                "",
                "Headings need at least two distinct SP stations per sail line. Triple-source: "
                "outer-row chord between min/max SP, shifted onto centerline (same as Generate Lines).",
                "",
                f"Features in layer: {total_features}",
                f"Lines with usable centerline endpoints: {len(line_endpoints)}",
                f"Lines skipped (one point or identical SP on line): {n_skipped_single_sp}",
                f"Features skipped (missing LineNum/SP): {n_skipped_null_attrs}",
                f"Features skipped (LineNum/SP not integer): {n_skipped_bad_numeric}",
                f"Lines skipped (invalid geometry): {n_skipped_bad_geom}",
            ]
            if calculation_failures:
                parts.append(f"Lines skipped (start point = end point): {calculation_failures}")
            parts.append("")
            parts.append("Check: attribute table has LineNum/SP; SPS import column positions match your file; "
                         "each line has multiple shots with different SP.")
            if not silent:
                QMessageBox.warning(self, "No Results", "\n".join(parts))
            return False

        # --- 4. UPDATE LAYER ATTRIBUTES ---
        log.info(f"Updating 'Heading' attribute for {len(line_headings)} lines")
        progress_update = None
        edit_started_here = False

        try:
            # Start editing session if needed
            if not source_layer.isEditable():
                if not source_layer.startEditing():
                    raise RuntimeError("Failed to start editing session on layer")
                edit_started_here = True

            # Set up progress dialog for the update operation
            progress_update = QProgressDialog("Updating heading attributes...", "Cancel", 0, 100, self)
            progress_update.setWindowModality(_QT_WINDOW_MODAL)
            progress_update.setMinimumDuration(0)
            progress_update.show()

            # --- 4a. Collect feature IDs by line ---
            log.debug("Collecting feature IDs by line number")
            progress_update.setLabelText("Collecting features to update...")
            QApplication.processEvents()

            feature_ids_by_line = {}
            batch_size = 100000  # Process in batches for large datasets
            processed = 0
            request_ids = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)
            total_features = source_layer.featureCount()

            for feature in source_layer.getFeatures(request_ids):
                processed += 1

                # Update progress periodically
                if processed % 50000 == 0 or processed == total_features:
                    progress_update.setValue(min(int(processed / total_features * 50), 50))
                    progress_update.setLabelText(f"Collecting features: {processed:,} of {total_features:,}")
                    QApplication.processEvents()

                # Check for user cancellation
                if progress_update.wasCanceled():
                    raise UserCancelException("Operation canceled by user")

                # Get line number and validate
                line_num = feature.attribute("LineNum")
                if line_num is None or line_num == NULL:
                    continue

                try:
                    line_num = int(line_num)
                except (ValueError, TypeError):
                    continue
                
                # Add feature ID to the collection if we have a heading for this line
                if line_num in line_headings:
                    if line_num not in feature_ids_by_line:
                        feature_ids_by_line[line_num] = []
                    feature_ids_by_line[line_num].append(feature.id())

            # --- 4b. Apply bulk updates ---
            log.debug("Performing bulk attribute updates")
            progress_update.setLabelText("Updating headings...")
            QApplication.processEvents()

            data_provider = source_layer.dataProvider()
            update_count = 0
            progress_counter = 0
            attr_map = {}
            total_lines_to_update = len(feature_ids_by_line)

            for line_num, feature_ids in feature_ids_by_line.items():
                # Check for user cancellation
                if progress_update.wasCanceled():
                    raise UserCancelException("Operation canceled by user")

                # Get heading for this line
                heading = line_headings[line_num]

                # Update progress periodically
                progress_counter += 1
                if progress_counter % 10 == 0 or progress_counter == total_lines_to_update:
                    progress_pct = 50 + int(progress_counter / total_lines_to_update * 50)
                    progress_update.setValue(min(progress_pct, 99))
                    progress_update.setLabelText(f"Updating {len(feature_ids)} points for line {line_num}")
                    QApplication.processEvents()

                # Add all features for this line to the attribute map
                for fid in feature_ids:
                    attr_map[fid] = {heading_idx: heading}
                    update_count += 1

                # Process in batches to avoid memory issues with large datasets
                if len(attr_map) >= batch_size or progress_counter == total_lines_to_update:
                    log.debug(f"Applying bulk update for {len(attr_map)} features")
                    if not data_provider.changeAttributeValues(attr_map):
                        errors = data_provider.lastError()
                        raise RuntimeError(f"Bulk update failed: {errors}")
                    attr_map = {}
                    QApplication.processEvents()

            # --- 4c. Commit changes ---
            log.debug("Committing changes to layer")
            progress_update.setValue(100)
            progress_update.setLabelText("Finalizing changes...")
            QApplication.processEvents()

            if source_layer.commitChanges():
                edit_started_here = False
                log.info(f"Successfully updated {update_count} features across {len(line_headings)} lines")

                # Close progress dialog and report success
                elapsed_time = time.time() - start_time
                progress_update.close()
                progress_update = None

                success_message = (
                    f"Default headings calculated and updated for {len(line_headings)} lines.\n"
                    f"Updated {update_count} points in {elapsed_time:.1f} seconds."
                )

                if calculation_failures:
                    success_message += f" ({calculation_failures} lines failed calculation)"

                heading_success = True
                if not silent:
                    QMessageBox.information(self, "Success", success_message)
            else:
                # Handle commit failure
                errors = source_layer.commitErrors()
                error_msg = "\n".join(errors) if errors else "Unknown error"
                raise RuntimeError(f"Failed to commit changes: {error_msg}")

        except UserCancelException as uce:
            log.info(f"{uce}")
        except Exception as e:
            log.exception(f"Error updating heading values: {e}")
            if not silent:
                QMessageBox.critical(self, "Error", f"Error updating heading values:\n{e}")
        finally:
            # Clean up resources
            if progress_update is not None:
                progress_update.close()

            # Rollback if we started editing and it's still in edit mode
            if edit_started_here and source_layer.isEditable():
                log.debug("Rolling back changes due to error or cancellation")
                source_layer.rollBack()

        # Force layer repaint to show the changes
        source_layer.triggerRepaint()
        log.info("Heading calculation completed")
        return heading_success

    # --- 3. Filtering Active Lines ---

    def _setup_min_max_line_tooltips(self):
        """Explain that bounds follow attribute LineNum in the selected point layer."""
        t_min = (
            "Lower limit for LineNum. When you pick the SPS layer above, this is set to the "
            "smallest LineNum in that layer (same field as in the attribute table)."
        )
        t_max = (
            "Upper limit for LineNum. When you pick the SPS layer above, this is set to the "
            "largest LineNum in that layer (same field as in the attribute table)."
        )
        t_row = (
            "LineNum range from the selected SPS layer: left spinbox = minimum, right = maximum "
            "(same field as in the attribute table)."
        )
        if hasattr(self, "label_2"):
            self.label_2.setToolTip(t_row)
        if hasattr(self, "startLineSpinBox"):
            self.startLineSpinBox.setToolTip(t_min)
        if hasattr(self, "endLineSpinBox"):
            self.endLineSpinBox.setToolTip(t_max)

    def _on_sps_layer_changed_line_num_bounds(self, layer):
        self._sync_min_max_line_spinboxes_from_sps_layer(layer)

    def _sync_min_max_line_spinboxes_from_sps_layer(self, layer=None):
        """
        Set Min Line / Max Line to the smallest and largest LineNum values in the layer.

        Uses LineNum (same case-insensitive resolution as SPS import). Tries provider
        min/max first; if those are missing (common for some OGR/GPKG states), scans features.
        If there is no layer, no LineNum field, or no numeric values, uses the full spin range.
        """
        if not hasattr(self, "startLineSpinBox") or not hasattr(self, "endLineSpinBox"):
            return
        lo = int(self.startLineSpinBox.minimum())
        hi = int(self.endLineSpinBox.maximum())

        def _apply_wide():
            self.startLineSpinBox.setValue(lo)
            self.endLineSpinBox.setValue(hi)

        if layer is None:
            layer = self.sps_layer_combo.currentLayer()
        if layer is None:
            _apply_wide()
            return
        try:
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                _apply_wide()
                return
        except RuntimeError:
            _apply_wide()
            return

        idx = self._sps_field_index(layer.fields(), "LineNum")
        if idx < 0:
            _apply_wide()
            return

        min_v = max_v = None
        try:
            min_v = layer.minimumValue(idx)
            max_v = layer.maximumValue(idx)
        except Exception as e:
            log.debug("min/max LineNum from layer provider stats failed: %s", e)
            min_v = max_v = None

        def _as_int(v):
            if v is None:
                return None
            try:
                if v == NULL:
                    return None
            except Exception:
                pass
            try:
                if isinstance(v, QVariant) and v.isNull():
                    return None
            except Exception:
                pass
            try:
                if hasattr(v, "isNull") and callable(getattr(v, "isNull", None)) and v.isNull():
                    return None
            except Exception:
                pass
            try:
                return int(v)
            except (TypeError, ValueError):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return None

        ln_min = _as_int(min_v)
        ln_max = _as_int(max_v)
        if ln_min is None or ln_max is None:
            scan_min = scan_max = None
            try:
                req = (
                    QgsFeatureRequest()
                    .setFlags(QgsFeatureRequest.NoGeometry)
                    .setSubsetOfAttributes(["LineNum"], layer.fields())
                )
                for feat in layer.getFeatures(req):
                    n = _as_int(feat.attribute(idx))
                    if n is None:
                        continue
                    scan_min = n if scan_min is None else min(scan_min, n)
                    scan_max = n if scan_max is None else max(scan_max, n)
            except Exception as e:
                log.debug("LineNum min/max feature scan failed: %s", e)
            if scan_min is not None and scan_max is not None:
                ln_min, ln_max = scan_min, scan_max
        if ln_min is None or ln_max is None:
            _apply_wide()
            return
        if ln_min > ln_max:
            ln_min, ln_max = ln_max, ln_min
        ln_min = max(lo, min(ln_min, hi))
        ln_max = max(lo, min(ln_max, hi))
        if ln_min > ln_max:
            ln_min, ln_max = ln_max, ln_min
        self.startLineSpinBox.setValue(ln_min)
        self.endLineSpinBox.setValue(ln_max)
        log.debug("Min/Max Line set from layer LineNum: %s … %s", ln_min, ln_max)

    def _format_line_list_item_text(self, line_id, base_ln, status, selection_order=None, sp_bounds=None):
        """Build left-side label text: '<line> [min-max] (Seq: n) (Part x)'."""
        part_suffix = ""
        try:
            if '_' in str(line_id):
                part_idx = int(str(line_id).split('_')[1])
                if part_idx > 0:
                    part_suffix = f" (Part {part_idx + 1})"
        except Exception as e:
            log.debug("Failed to parse part suffix for line_id=%r: %s", line_id, e)

        core = f"{base_ln}"

        if sp_bounds:
            core += f" [{sp_bounds[0]}-{sp_bounds[1]}]"

        if selection_order is not None:
            core += f" (Seq: {selection_order})"
            
        core += part_suffix
        return core

    def _refresh_line_list_item_labels(self):
        """Refresh all line labels based on status and current selection order."""
        if not hasattr(self, 'lineListWidget'):
            return

        start_seq = 1
        if hasattr(self, 'firstSeqComboBox'):
            try:
                start_seq = int(self.firstSeqComboBox.value())
            except (TypeError, ValueError):
                start_seq = 1

        order_map = {}
        seq_overrides = getattr(self, "_selection_sequence_numbers", {}) or {}
        for idx, ln in enumerate(self._selection_sequence):
            key = str(ln)
            if key in seq_overrides:
                order_map[key] = int(seq_overrides[key])
            else:
                order_map[key] = start_seq + idx
        max_seq_val = max(order_map.values()) if order_map else -1

        row_data = []
        for i in range(self.lineListWidget.count()):
            item = self.lineListWidget.item(i)
            line_id = item.data(_QT_USER_ROLE)
            base_ln = item.data(_QT_USER_ROLE + 2)
            status = item.data(_QT_USER_ROLE + 1)
            if line_id is None or base_ln is None:
                continue

            bounds = self.custom_line_sp_bounds.get(line_id) or self.default_line_sp_bounds.get(base_ln)
            seq_num = order_map.get(str(line_id))
            left_text = self._format_line_list_item_text(line_id, base_ln, status, seq_num, bounds)
            row_data.append((item, line_id, status, seq_num, left_text))

        for item, line_id, status, seq_num, left_text in row_data:
            status_label = ""
            if status not in (None, NULL) and str(status).strip():
                status_label = str(status).strip()
            item.setData(LINE_LIST_LEFT_TEXT_ROLE, left_text)
            item.setData(LINE_LIST_STATUS_TEXT_ROLE, status_label)
            # Keep plain text for search/accessibility; actual rendering is done by delegate.
            item.setText(f"{left_text} {status_label}".strip())

            status_str = str(status).strip().upper() if status else ""
            is_part = False
            try:
                if '_' in str(line_id) and int(str(line_id).split('_')[1]) > 0:
                    is_part = True
            except Exception as e:
                log.debug("Failed to detect split-part line_id=%r: %s", line_id, e)

            # Default font settings
            font = item.font()
            font.setBold(False)
            font.setItalic(False)

            # Maximum sequence = Bold Italic
            if seq_num is not None and seq_num == max_seq_val:
                font.setBold(True)
                font.setItalic(True)
                
            item.setFont(font)

            # Theme-aware fallback colors (for dark/light QGIS themes)
            palette = self.lineListWidget.palette()
            default_text = palette.text().color()
            base_bg = palette.base().color()
            alt_bg = palette.alternateBase().color()

            # Color coding
            if status_str == "ACQUIRED":
                item.setBackground(QColor("#006400"))  # Dark green background
                item.setForeground(QColor("#FFFFFF"))  # White text
            elif status_str == "TO BE ACQUIRED":
                item.setBackground(QColor("#FFA500"))  # Orange background
                item.setForeground(QColor("#000000"))  # Black text
            elif status_str == "PENDING":
                item.setBackground(QColor("#FF0000"))  # Red background
                item.setForeground(QColor("#FFFFFF"))  # White text
            elif is_part:
                # Keep "part" rows visually distinct without breaking dark themes.
                item.setBackground(alt_bg if alt_bg != base_bg else QColor("#2A2A2A"))
                item.setForeground(default_text)
            else:
                item.setData(_QT_BACKGROUND_ROLE, None)  # Remove background (transparent/default)
                item.setForeground(default_text)

    def _renumber_selection_sequence(self):
        """
        Rebuild Seq overrides as a dense contiguous range from start Seq.
        This keeps remaining queued lines visually updated after removals.
        """
        start_seq = 1
        if hasattr(self, "firstSeqComboBox"):
            try:
                start_seq = int(self.firstSeqComboBox.value())
            except (TypeError, ValueError):
                start_seq = 1
        cleaned = []
        seen = set()
        for lid in (getattr(self, "_selection_sequence", None) or []):
            s = str(lid)
            if s in seen:
                continue
            seen.add(s)
            cleaned.append(s)
        self._selection_sequence = cleaned
        self._selection_sequence_numbers = {
            lid: (start_seq + i) for i, lid in enumerate(cleaned)
        }
        self._sync_first_line_spinbox_from_shooting_queue()

    def _sync_first_line_spinbox_from_shooting_queue(self):
        """Keep First Line in sync with the first entry of the Right-Ctrl shooting queue."""
        seq = getattr(self, "_selection_sequence", None) or []
        if not seq or not hasattr(self, "firstLineSpinBox"):
            return
        try:
            base_ln = int(str(seq[0]).split("_", 1)[0])
            self.firstLineSpinBox.setValue(base_ln)
        except (ValueError, TypeError, IndexError):
            pass

    def _handle_line_list_selection_changed(self):
        """Track selection order so the list can show line priority numbers."""
        if not hasattr(self, 'lineListWidget'):
            return

        current_selected = []
        
        layer = None
        if hasattr(self, 'sps_layer_combo'):
            try:
                layer = self.sps_layer_combo.currentLayer()
            except RuntimeError:
                layer = None
            
        expr_parts = []
        
        for item in self.lineListWidget.selectedItems():
            line_id = item.data(_QT_USER_ROLE)
            base_ln = item.data(_QT_USER_ROLE + 2)
            if line_id is not None:
                current_selected.append(str(line_id))
                
            if layer and base_ln is not None:
                bounds = self.custom_line_sp_bounds.get(line_id) or self.default_line_sp_bounds.get(base_ln)
                if bounds:
                    expr_parts.append(f'("LineNum" = {base_ln} AND "SP" >= {bounds[0]} AND "SP" <= {bounds[1]})')
                else:
                    expr_parts.append(f'("LineNum" = {base_ln})')

        self._sync_first_line_spinbox_from_shooting_queue()

        # Highlight points on map
        if layer and layer.isValid():
            if expr_parts:
                full_expr = " OR ".join(expr_parts)
                try:
                    layer.selectByExpression(full_expr, QgsVectorLayer.SetSelection)
                except Exception as e:
                    log.warning(f"Map selection failed: {e}")
            else:
                layer.removeSelection()

        self._refresh_line_list_item_labels()

    def eventFilter(self, obj, event):
        """
        Sequence selection strictly via Right Ctrl+Click (on Windows),
        preventing normal clicks from clearing sequences.

        ExtendedSelection also selects a contiguous block when the user drags
        with the left button over rows (same effect as Shift+click). That is
        easy to trigger by accident while Ctrl-clicking across the list; block
        drag-range selection unless Shift is held — use Shift+click for ranges.
        """
        if hasattr(self, 'lineListWidget') and obj is self.lineListWidget.viewport():
            if event.type() == _QEVENT_MOUSE_MOVE:
                me = event
                if me.buttons() & _QT_LEFT_BUTTON:
                    if not (QApplication.keyboardModifiers() & _QT_SHIFT_MODIFIER):
                        return True
            if event.type() == _QEVENT_MOUSE_BUTTON_PRESS:
                item = self.lineListWidget.itemAt(event.pos())
                if item is not None:
                    # Strictly check for Right Ctrl (for Windows)
                    is_right_ctrl = False
                    if sys.platform == 'win32':
                        import ctypes
                        if (ctypes.windll.user32.GetAsyncKeyState(0xA3) & 0x8000) != 0:
                            is_right_ctrl = True
                    elif QApplication.keyboardModifiers() & _QT_CONTROL_MODIFIER:
                        is_right_ctrl = True  # fallback for other OS

                    if is_right_ctrl:
                        line_id = str(item.data(_QT_USER_ROLE))
                        if line_id in self._selection_sequence:
                            self._selection_sequence.remove(line_id)
                            if line_id in self._selection_sequence_numbers:
                                del self._selection_sequence_numbers[line_id]
                        else:
                            self._selection_sequence.append(line_id)
                            if line_id not in self._selection_sequence_numbers:
                                base = None
                                existing = list(getattr(self, "_selection_sequence_numbers", {}).values())
                                if existing:
                                    try:
                                        base = int(max(existing)) + 1
                                    except (TypeError, ValueError):
                                        base = None
                                if base is None:
                                    try:
                                        base = int(self.firstSeqComboBox.value())
                                    except Exception:
                                        base = 1
                                    base += max(0, len(self._selection_sequence) - 1)
                                self._selection_sequence_numbers[line_id] = int(base)
                        self._refresh_line_list_item_labels()
                        self._sync_first_line_spinbox_from_shooting_queue()
                        return True  # Block standard selection
        return super(LookaheadDockWidgetImpl, self).eventFilter(obj, event)

    def _edit_line_sp_range(self, item):
        """Opens a dialog to override the SP range for a specific line."""
        line_id = item.data(_QT_USER_ROLE)
        base_ln = item.data(_QT_USER_ROLE + 2)
        if line_id is None or base_ln is None:
            return

        default_bounds = self.default_line_sp_bounds.get(base_ln)
        bounds = self.custom_line_sp_bounds.get(line_id) or default_bounds
        if not bounds:
            QMessageBox.warning(self, "No Data", f"No SP data available for Line {base_ln}.")
            return

        part_suffix = ""
        try:
            if '_' in str(line_id):
                part_idx = int(str(line_id).split('_')[1])
                if part_idx > 0: part_suffix = f" (Part {part_idx + 1})"
        except Exception as e:
            log.debug("Failed to parse part suffix in SP editor for %r: %s", line_id, e)

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"Edit SP Range - Line {base_ln}{part_suffix}")
        layout = QtWidgets.QVBoxLayout(dlg)

        label = QtWidgets.QLabel(f"Set the first and last Shot Point (SP) for Line {base_ln}{part_suffix}.\nThe geometry will be trimmed to this range during generation.")
        layout.addWidget(label)

        form = QtWidgets.QFormLayout()
        min_spin = QtWidgets.QSpinBox()
        min_spin.setRange(-99999, 999999)
        min_spin.setValue(bounds[0])
        
        max_spin = QtWidgets.QSpinBox()
        max_spin.setRange(-99999, 999999)
        max_spin.setValue(bounds[1])
        
        form.addRow("Start SP:", min_spin)
        form.addRow("End SP:", max_spin)
        layout.addLayout(form)

        btn_layout = QtWidgets.QHBoxLayout()
        
        reset_btn = QtWidgets.QPushButton("Reset")
        def reset_to_default():
            if default_bounds:
                min_spin.setValue(default_bounds[0])
                max_spin.setValue(default_bounds[1])
        reset_btn.clicked.connect(reset_to_default)
        btn_layout.addWidget(reset_btn)

        btns = QtWidgets.QDialogButtonBox(_QDIALOGBUTTONBOX_OK | _QDIALOGBUTTONBOX_CANCEL)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        btn_layout.addWidget(btns)
        
        layout.addLayout(btn_layout)

        if dlg.exec() == _QDIALOG_ACCEPTED:
            v1, v2 = min_spin.value(), max_spin.value()
            self.custom_line_sp_bounds[line_id] = (min(v1, v2), max(v1, v2))
            self._refresh_line_list_item_labels()

    def handle_duplicate_line(self):
        """Duplicates the selected line in the list, allowing it to be shot in multiple parts."""
        if not hasattr(self, 'lineListWidget'):
            return
        selected_items = self.lineListWidget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a line to duplicate.")
            return
            
        for item in reversed(selected_items):
            line_id = item.data(_QT_USER_ROLE)
            status = item.data(_QT_USER_ROLE + 1)
            base_ln = item.data(_QT_USER_ROLE + 2)
            
            if line_id is None or base_ln is None: continue
                
            max_copy = -1
            for i in range(self.lineListWidget.count()):
                it = self.lineListWidget.item(i)
                if it.data(_QT_USER_ROLE + 2) == base_ln:
                    try:
                        if '_' in str(it.data(_QT_USER_ROLE)):
                            max_copy = max(max_copy, int(str(it.data(_QT_USER_ROLE)).split('_')[1]))
                        else:
                            max_copy = max(max_copy, 0)
                    except ValueError: pass
                        
            new_copy_idx = max(0, max_copy) + 1
            new_line_id = f"{base_ln}_{new_copy_idx}"
            
            old_bounds = self.custom_line_sp_bounds.get(line_id) or self.default_line_sp_bounds.get(base_ln)
            if old_bounds: self.custom_line_sp_bounds[new_line_id] = list(old_bounds)
                
            current_row = self.lineListWidget.row(item)
            bounds = self.custom_line_sp_bounds.get(new_line_id)
            new_item = QListWidgetItem(self._format_line_list_item_text(new_line_id, base_ln, status, sp_bounds=bounds))
            new_item.setData(_QT_USER_ROLE, new_line_id); new_item.setData(_QT_USER_ROLE + 1, status); new_item.setData(_QT_USER_ROLE + 2, base_ln)
            self.lineListWidget.insertItem(current_row + 1, new_item)
            
        self._refresh_line_list_item_labels()

    def handle_remove_line(self):
        """Removes the selected line(s) from the list."""
        if not hasattr(self, 'lineListWidget'):
            return
        selected_items = self.lineListWidget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select a line to remove.")
            return
            
        for item in selected_items:
            line_id = item.data(_QT_USER_ROLE)
            if line_id in self.custom_line_sp_bounds:
                del self.custom_line_sp_bounds[line_id]
            
            row = self.lineListWidget.row(item)
            self.lineListWidget.takeItem(row)
            
        self._handle_line_list_selection_changed()
        self._refresh_line_list_item_labels()

    def handle_apply_filter(self, refresh_line_list=True):
        """
        Reads filter UI, queries SPS layer, returns matching LineNums set.

        Args:
            refresh_line_list: If True (default), rebuilds the line list and clears selection
                sequence — use for «Refresh List». If False, only runs the query (e.g. before
                Generate Lines) so list order and shooting sequence numbers stay unchanged.
        """
        log.debug("Handle Refresh List (refresh_line_list=%s).", refresh_line_list)

        if not hasattr(self, "lineListWidget"):
            log.error("lineListWidget not found!")
            return None

        QApplication.setOverrideCursor(_QT_WAIT_CURSOR)
        try:
            if refresh_line_list:
                self.lineListWidget.clear()
                self._selection_sequence = []
                self._selection_sequence_numbers = {}

            # Get filter parameters
            layer = self._require_sail_layer("Refresh List")
            start_ln = self.startLineSpinBox.value()
            end_ln = self.endLineSpinBox.value()
            status = self.statusFilterComboBox.currentText()

            if not layer:
                return None
            if start_ln > end_ln:
                QMessageBox.warning(self, "Input Error", "Min Line is greater than Max Line.")
                return None

            # Build filter expression
            filter_parts = [f'"LineNum">={start_ln}', f'"LineNum"<={end_ln}']
            if status != "All":
                try:
                    status_lit = QgsExpression.quotedString(status)
                except AttributeError:
                    status_lit = "'" + str(status).replace("'", "''") + "'"
                filter_parts.append(f'"Status"={status_lit}')
            expr = " AND ".join(filter_parts)
            log.debug("Filter: %s", expr)

            fields = layer.fields()
            ln_idx = fields.lookupField("LineNum")
            st_idx = fields.lookupField("Status")
            sp_idx = fields.lookupField("SP")
            if ln_idx < 0 or st_idx < 0 or sp_idx < 0:
                QMessageBox.critical(self, "Field Error", "SPS layer must have LineNum, Status, and SP fields.")
                return None

            if status != "All":
                attr_subset = ["LineNum", "SP"]
                fixed_status_label = status
            else:
                attr_subset = ["LineNum", "Status", "SP"]
                fixed_status_label = None

            matching_nums = set()
            req = QgsFeatureRequest()
            req.setFilterExpression(expr)
            req.setFlags(QgsFeatureRequest.NoGeometry)
            req.setSubsetOfAttributes(attr_subset, fields)
            try:
                req.setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)
            except AttributeError:
                pass

            line_status_map = {}
            line_sp_bounds = {}
            
            # Optimization: cache attributes() and use inline comparisons 
            # instead of min()/max() functions, which speeds up the loop by 2-3 times
            for feat in layer.getFeatures(req):
                attrs = feat.attributes()
                ln_val = attrs[ln_idx]
                if ln_val is None or ln_val == NULL:
                    continue
                try:
                    line_num = int(ln_val)
                except (ValueError, TypeError):
                    continue
                matching_nums.add(line_num)
                if fixed_status_label is not None:
                    line_status_map[line_num] = fixed_status_label
                else:
                    status_val = attrs[st_idx]
                    line_status_map[line_num] = (
                        status_val if status_val not in (None, NULL) else ""
                    )
                
                sp_val = attrs[sp_idx]
                if sp_val is not None and sp_val != NULL:
                    try:
                        sp_int = int(sp_val)
                        bounds = line_sp_bounds.get(line_num)
                        if bounds is None:
                            line_sp_bounds[line_num] = [sp_int, sp_int]
                        else:
                            if sp_int < bounds[0]: bounds[0] = sp_int
                            elif sp_int > bounds[1]: bounds[1] = sp_int
                    except (ValueError, TypeError):
                        pass

            self.default_line_sp_bounds = line_sp_bounds

            if refresh_line_list:
                if matching_nums:
                    sorted_lines = sorted(list(matching_nums))
                    # Safely initialize dicts if QGIS hot-reloaded without calling __init__
                    if not hasattr(self, 'custom_line_sp_bounds'):
                        self.custom_line_sp_bounds = {}
                        self.default_line_sp_bounds = {}
                        
                    # Disable UI redraw for instant item addition
                    self.lineListWidget.setUpdatesEnabled(False)
                    try:
                        for ln in sorted_lines:
                            status_text = line_status_map.get(ln, "")
                            line_id = str(ln)
                            bounds = self.custom_line_sp_bounds.get(line_id) or line_sp_bounds.get(ln)
                            item = QListWidgetItem(self._format_line_list_item_text(line_id, ln, status_text, sp_bounds=bounds))
                            item.setData(_QT_USER_ROLE, line_id)
                            item.setData(_QT_USER_ROLE + 1, status_text)
                            item.setData(_QT_USER_ROLE + 2, ln)
                            
                            self.lineListWidget.addItem(item)
                    finally:
                        self.lineListWidget.setUpdatesEnabled(True)

                    try:
                        self.firstLineSpinBox.setValue(sorted_lines[0])
                    except AttributeError:
                        log.error("firstLineSpinBox not found!")
                    self._refresh_line_list_item_labels()
                    log.info(f"Populated list with {len(sorted_lines)} lines.")
                else:
                    log.info("No lines found matching filter.")
            else:
                if matching_nums:
                    log.debug("Filter query only: %s lines match (line list left unchanged).", len(matching_nums))
                else:
                    log.info("No lines found matching filter (line list not refreshed).")

            return matching_nums

        except Exception as e:
            log.exception(f"Filter error: {e}")
            QMessageBox.critical(self, "Filter Error", f"Error filtering:\n{e}")
            return None
        finally:
            self._pop_wait_cursor_if_busy()

    # --- 4. Line Markers (Status Updates) ---

    def handle_mark_acquired(self):
        """
        Handles the 'Acquired' status button.
        Updates the Status attribute of selected lines to 'Acquired'.
        """
        log.info("Handling Acquired status button click")
        self._update_selected_lines_status("Acquired")

    def handle_mark_tba(self):
        """
        Handles the 'To Be Acquired' status button.
        Updates the Status attribute of selected lines to 'To Be Acquired'.
        """
        log.info("Handling To Be Acquired status button click")
        self._update_selected_lines_status("To Be Acquired")

    def handle_mark_tba_to_acquired(self):
        """
        Convert all visible list rows with status 'To Be Acquired' to 'Acquired'.
        Useful for bulk close-out without selecting rows manually.
        """
        if not hasattr(self, "lineListWidget"):
            QMessageBox.warning(self, "Component Error", "Line list is not available.")
            return
        tba_lines = []
        for i in range(self.lineListWidget.count()):
            item = self.lineListWidget.item(i)
            if item is None or item.isHidden():
                continue
            status = str(item.data(_QT_USER_ROLE + 1) or "").strip().upper()
            if status != "TO BE ACQUIRED":
                continue
            base_ln = item.data(_QT_USER_ROLE + 2)
            try:
                tba_lines.append(int(base_ln))
            except (TypeError, ValueError):
                continue

        if not tba_lines:
            QMessageBox.information(self, "To Be Acq. to Acquired", "No visible 'To Be Acquired' lines found.")
            return

        unique_lines = sorted(set(tba_lines))
        try:
            updated_count = self._set_status_for_line_nums(unique_lines, "Acquired")
            self._sync_generated_survey_lines_status(unique_lines, "Acquired")
        except Exception as e:
            log.exception("Bulk TBA->Acquired failed: %s", e)
            QMessageBox.critical(self, "To Be Acq. to Acquired", f"Failed to update status:\n{e}")
            return

        affected = set(unique_lines)
        for i in range(self.lineListWidget.count()):
            item = self.lineListWidget.item(i)
            if item is None:
                continue
            try:
                base_ln = int(item.data(_QT_USER_ROLE + 2))
            except (TypeError, ValueError):
                continue
            if base_ln not in affected:
                continue
            item.setData(_QT_USER_ROLE + 1, "Acquired")
            line_id = str(item.data(_QT_USER_ROLE))
            if line_id in self._selection_sequence:
                self._selection_sequence.remove(line_id)
            if line_id in self._selection_sequence_numbers:
                del self._selection_sequence_numbers[line_id]

        self._refresh_line_list_item_labels()
        self._sync_first_line_spinbox_from_shooting_queue()

        if hasattr(self, "statusFilterComboBox"):
            current_filter_status = self.statusFilterComboBox.currentText()
            for i in range(self.lineListWidget.count()):
                item = self.lineListWidget.item(i)
                status_text = str(item.data(_QT_USER_ROLE + 1) or "")
                should_show = (
                    current_filter_status == "All" or
                    status_text.strip().lower() == current_filter_status.strip().lower()
                )
                if not should_show:
                    item.setHidden(True)
                    item.setSizeHint(QtCore.QSize(0, 0))
                else:
                    item.setHidden(False)
                    item.setSizeHint(QtCore.QSize())

        QMessageBox.information(
            self,
            "To Be Acq. to Acquired",
            f"Updated {updated_count:,} points across {len(unique_lines)} line(s) to 'Acquired'.",
        )

    def handle_mark_pending(self):
        """
        Handles the 'Pending' status button.
        Updates the Status attribute of selected lines to 'Pending'.
        """
        log.info("Handling Pending status button click")
        self._update_selected_lines_status("Pending")

    def _sync_generated_survey_lines_status(self, line_nums, new_status):
        """
        Mirror Status onto Generated_Survey_Lines for the given line numbers.

        Simulation reads Status from this layer, not from SPS points. Without this,
        lines generated before marking TBA would still look 'empty' to the simulator.
        """
        if not line_nums:
            return
        line_layer = None
        try:
            _gl_layer = getattr(self, "generated_lines_layer", None)
            if _gl_layer is not None and _gl_layer.isValid():
                line_layer = _gl_layer
        except RuntimeError:
            line_layer = None
        if line_layer is None:
            for lyr in QgsProject.instance().mapLayersByName("Generated_Survey_Lines"):
                try:
                    if lyr.type() == QgsMapLayer.VectorLayer and lyr.isValid():
                        line_layer = lyr
                        break
                except RuntimeError:
                    continue
        if line_layer is None:
            return
        ln_idx = line_layer.fields().lookupField("LineNum")
        st_idx = line_layer.fields().lookupField("Status")
        if ln_idx < 0 or st_idx < 0:
            return
        want = set(int(x) for x in line_nums)
        updates = {}
        for feat in line_layer.getFeatures(QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)):
            try:
                line_id_str = str(feat.attribute(ln_idx))
                base_ln = int(line_id_str.split('_')[0])
            except (ValueError, TypeError):
                continue
            if base_ln in want:
                updates[feat.id()] = {st_idx: new_status}
        if not updates:
            log.debug("_sync_generated_survey_lines_status: no matching features for line nums %s", want)
            return
        edit_here = False
        try:
            if not line_layer.isEditable():
                if not line_layer.startEditing():
                    log.warning("Could not start editing on Generated_Survey_Lines for status sync")
                    return
                edit_here = True
            if not line_layer.dataProvider().changeAttributeValues(updates):
                log.warning(
                    "Status sync to Generated_Survey_Lines failed: %s",
                    line_layer.dataProvider().lastError(),
                )
                if edit_here:
                    line_layer.rollBack()
                return
            if edit_here:
                if not line_layer.commitChanges():
                    log.warning("Status sync commit failed: %s", line_layer.commitErrors())
                    line_layer.rollBack()
                    return
        except Exception as e:
            log.exception("Status sync to Generated_Survey_Lines: %s", e)
            if edit_here and line_layer.isEditable():
                line_layer.rollBack()
            return
        self.generated_lines_layer = line_layer
        line_layer.triggerRepaint()
        log.info(
            "Synced Status on Generated_Survey_Lines for %d line(s) -> '%s'",
            len(updates),
            new_status,
        )

    def _line_list_items_for_actions(self):
        """
        List rows to apply status (and similar) actions to.

        If the user has a normal multi-selection, use that. Otherwise, if they set a
        shooting order with Right Ctrl+click (without keeping rows highlighted), use
        those lines in sequence order.
        """
        if not hasattr(self, "lineListWidget"):
            return []
        w = self.lineListWidget
        selected = w.selectedItems()
        if selected:
            return list(selected)
        seq = getattr(self, "_selection_sequence", None) or []
        if not seq:
            return []
        by_id = {}
        for i in range(w.count()):
            it = w.item(i)
            lid = it.data(_QT_USER_ROLE)
            if lid is not None:
                by_id[str(lid)] = it
        out = []
        seen = set()
        for lid in seq:
            s = str(lid)
            it = by_id.get(s)
            if it is not None and s not in seen:
                seen.add(s)
                out.append(it)
        return out

    def handle_remove_status(self):
        """Clear Status (NULL) on all SPS points for selected list lines. No-op if nothing selected."""
        if not hasattr(self, "lineListWidget"):
            return
        if not self._line_list_items_for_actions():
            return
        self._update_selected_lines_status(NULL, silent_if_empty=True, success_dialog=False)

    def handle_reset_sequences(self):
        """
        Clear the shooting-order queue built with Right Ctrl+click (Seq labels in the list).
        Does not change Status, list filter, or which rows are selected.
        """
        self._selection_sequence = []
        self._selection_sequence_numbers = {}
        self._refresh_line_list_item_labels()
        log.info("Shooting-order queue cleared (Reset Sequences)")

    def _update_selected_lines_status(self, new_status, *, silent_if_empty=False, success_dialog=True):
        """
        Updates the 'Status' attribute for all points belonging to selected lines.

        Uses efficient bulk updates to handle large datasets with progress reporting.
        Targets either multi-selected list rows or, if none selected, the shooting-order
        queue built with Right Ctrl+click (Seq numbers in the list).

        Args:
            new_status: New value (str) or NULL / empty QVariant to clear status.
            silent_if_empty: If True, return immediately when nothing is selected (no dialog).
            success_dialog: If False, skip the completion QMessageBox (e.g. Remove Status).
        """
        start_time = time.time()
        clearing = new_status == NULL or (
            isinstance(new_status, QVariant) and not new_status.isValid()
        )
        log.info("Starting status update (%s)", "clear / NULL" if clearing else repr(new_status))

        # --- 1. VALIDATE INPUTS ---
        if not hasattr(self, 'lineListWidget'):
            log.warning("Cannot update status: lineListWidget not found")
            QMessageBox.warning(self, "Component Error", "Line selection widget not available")
            return

        target_items = self._line_list_items_for_actions()
        if not target_items:
            if silent_if_empty:
                return
            log.info("No lines selected and no shooting-order queue for status update")
            QMessageBox.information(
                self,
                "No Selection",
                "Select one or more lines in the list, or set the shooting order with "
                "Right Ctrl+click (Seq numbers), then apply the status again.",
            )
            return

        # Get target layer
        target_layer = self._require_sail_layer("apply status")
        if not target_layer:
            log.warning("Cannot update status: no Sail layer selected")
            return

        # Verify Status field exists
        status_field_idx = target_layer.fields().lookupField("Status")
        if status_field_idx == -1:
            log.error(f"Cannot find 'Status' field in layer '{target_layer.name()}'")
            QMessageBox.critical(self, "Field Error", 
                                f"Cannot find the 'Status' field in layer '{target_layer.name()}'")
            return

        # --- 2. PREPARE SELECTED LINE NUMBERS ---
        log.debug("%s list row(s) targeted for status update", len(target_items))
        selected_base_line_nums = []

        for item in target_items:
            base_ln = item.data(_QT_USER_ROLE + 2)
            if base_ln is not None:
                selected_base_line_nums.append(int(base_ln))

        if not selected_base_line_nums:
            log.warning("Could not identify valid line numbers from selection")
            QMessageBox.warning(self, "Selection Error", 
                               "Could not identify valid line numbers from your selection")
            return

        unique_base_line_nums = list(set(selected_base_line_nums))
        log.debug(f"Line numbers selected for status update: {unique_base_line_nums}")

        # --- 3. BEGIN UPDATE OPERATION ---
        progress = None
        edit_started_here = False

        try:
            # Start editing if needed
            if not target_layer.isEditable():
                log.debug(f"Starting editing on layer '{target_layer.name()}'")
                if not target_layer.startEditing():
                    log.error(f"Could not start editing on layer '{target_layer.name()}'")
                    QMessageBox.critical(self, "Edit Error", 
                                        f"Could not start editing on layer '{target_layer.name()}'")
                    return
                edit_started_here = True

            # Set up filter expression based on number of lines
            if len(unique_base_line_nums) == 1:
                line_filter_expr = f'"LineNum" = {unique_base_line_nums[0]}'
            else:
                # Handle large lists properly by chunking if needed
                if len(unique_base_line_nums) > 1000:
                    log.debug("Large number of lines selected, using optimized query approach")
                    line_filter_expr = '"LineNum" IN (' + ','.join(str(n) for n in unique_base_line_nums) + ')'
                else:
                    line_filter_expr = f'"LineNum" IN {tuple(unique_base_line_nums)}'

            log.debug(f"Filter expression for update: {line_filter_expr}")

            # Setup progress dialog for user feedback
            prog_msg = "Clearing status..." if clearing else f"Updating status to '{new_status}'..."
            progress = QProgressDialog(prog_msg, "Cancel", 0, 100, self)
            progress.setWindowModality(_QT_WINDOW_MODAL)
            progress.setMinimumDuration(0)
            progress.show()
            QApplication.processEvents()

            # --- 4. COLLECT FEATURES TO UPDATE ---
            progress.setValue(10)
            progress.setLabelText("Collecting features to update...")
            QApplication.processEvents()

            # Get feature IDs matching the filter
            request = QgsFeatureRequest().setFilterExpression(line_filter_expr)
            request.setFlags(QgsFeatureRequest.NoGeometry)  # No need for geometries, speeds up query

            # Count total features first for better progress reporting
            total_features = sum(1 for _ in target_layer.getFeatures(request))
            log.debug(f"Found {total_features} features matching selected lines")

            if total_features == 0:
                log.warning(f"No features found for selected lines: {unique_base_line_nums}")
                progress.close()
                QMessageBox.information(self, "No Features", 
                                      f"No points found matching the selected lines.\nStatus not updated.")
                return

            # --- 5. PERFORM BULK UPDATE ---
            progress.setValue(30)
            progress.setLabelText(f"Updating {total_features} features...")
            QApplication.processEvents()

            # Create attribute map for bulk update
            feature_ids_to_update = {}
            batch_size = 100000  # Process in batches for large datasets
            processed = 0

            for feature in target_layer.getFeatures(request):
                # Check for user cancellation
                if progress.wasCanceled():
                    raise UserCancelException("Operation canceled by user")

                feature_ids_to_update[feature.id()] = {status_field_idx: new_status}
                processed += 1

                # Update progress periodically
                if processed % 5000 == 0 or processed == total_features:
                    progress_pct = 30 + int(processed / total_features * 60)
                    progress.setValue(min(progress_pct, 90))
                    progress.setLabelText(f"Processed {processed:,} of {total_features:,} features")
                    QApplication.processEvents()

                # Process in batches to avoid memory issues
                if len(feature_ids_to_update) >= batch_size:
                    if not target_layer.dataProvider().changeAttributeValues(feature_ids_to_update):
                        provider_error = target_layer.dataProvider().lastError()
                        raise RuntimeError(f"Bulk update failed: {provider_error}")
                    feature_ids_to_update = {}
                    QApplication.processEvents()

            # Process any remaining features
            if feature_ids_to_update:
                log.debug(f"Applying final batch update for {len(feature_ids_to_update)} features")
                if not target_layer.dataProvider().changeAttributeValues(feature_ids_to_update):
                    provider_error = target_layer.dataProvider().lastError()
                    raise RuntimeError(f"Bulk update failed: {provider_error}")

            # --- 6. COMMIT CHANGES ---
            progress.setValue(95)
            progress.setLabelText("Finalizing changes...")
            QApplication.processEvents()

            updated_feature_count = processed

            if edit_started_here:
                log.debug("Committing changes to layer")
                if not target_layer.commitChanges():
                    commit_errors = target_layer.commitErrors()
                    error_msg = "\n".join(commit_errors) if commit_errors else "Unknown error"
                    raise RuntimeError(f"Failed to commit changes: {error_msg}")
                edit_started_here = False
                log.info("Committed changes successfully")
            else:
                # Layer was already in edit mode, just trigger repaint
                target_layer.triggerRepaint()
                log.debug("Layer already in edit mode, triggered repaint only")

            # --- 7. REPORT SUCCESS AND REFRESH FILTERS ---
            progress.setValue(100)
            QApplication.processEvents()

            elapsed_time = time.time() - start_time
            log.info(
                "Successfully updated %s features (%s) in %.1fs",
                updated_feature_count,
                "cleared status" if clearing else repr(new_status),
                elapsed_time,
            )

            self._sync_generated_survey_lines_status(unique_base_line_nums, new_status)

            # Show success message
            if success_dialog:
                if clearing:
                    msg = (
                        f"Cleared status on {updated_feature_count:,} points "
                        f"across {len(unique_base_line_nums)} line(s) in {elapsed_time:.1f} s."
                    )
                else:
                    msg = (
                        f"Status updated to '{new_status}' for {updated_feature_count:,} points "
                        f"across {len(unique_base_line_nums)} lines in {elapsed_time:.1f} seconds"
                    )
                QMessageBox.information(self, "Success", msg)

            # Update list labels in-place to preserve current shooting sequence numbering.
            if hasattr(self, 'lineListWidget'):
                selected_set = set(selected_base_line_nums)
                list_status_val = "" if clearing else new_status

                # Remove the line from the sequence when its status changes (remaining sequences will shift)
                for item in target_items:
                    line_id = str(item.data(_QT_USER_ROLE))
                    if line_id in self._selection_sequence:
                        self._selection_sequence.remove(line_id)
                    if line_id in self._selection_sequence_numbers:
                        del self._selection_sequence_numbers[line_id]
                self._renumber_selection_sequence()

                for i in range(self.lineListWidget.count()):
                    item = self.lineListWidget.item(i)
                    base_ln = item.data(_QT_USER_ROLE + 2)
                    if base_ln in selected_set:
                        item.setData(_QT_USER_ROLE + 1, list_status_val)

                # Keep existing selection sequence/order and just redraw labels.
                self._refresh_line_list_item_labels()

                # If the current status filter excludes this new status, hide those rows
                # instead of rebuilding the list (which would reset sequence numbering).
                if hasattr(self, 'statusFilterComboBox'):
                    current_filter_status = self.statusFilterComboBox.currentText()
                    for i in range(self.lineListWidget.count()):
                        item = self.lineListWidget.item(i)
                        status_text = str(item.data(_QT_USER_ROLE + 1) or "")
                        should_show = (
                            current_filter_status == "All" or
                            status_text.strip().lower() == current_filter_status.strip().lower()
                        )
                        if not should_show:
                            item.setHidden(True)
                            item.setSizeHint(QtCore.QSize(0, 0))
                        else:
                            item.setHidden(False)
                            item.setSizeHint(QtCore.QSize())

        except UserCancelException as uce:
            log.info(f"{uce}")
            if edit_started_here:
                target_layer.rollBack()
                log.debug("Changes rolled back after user cancellation")
        except Exception as e:
            log.exception(f"Failed to update status: {e}")
            if edit_started_here:
                target_layer.rollBack()
                log.debug("Changes rolled back due to error")
            QMessageBox.critical(self, "Update Error", 
                                f"Failed to update status:\n{e}")
        finally:
            # Clean up resources
            if progress is not None:
                progress.close()

            # Ensure we clean up edit session if we started it
            if edit_started_here and target_layer.isEditable():
                target_layer.rollBack()
                log.debug("Rolled back changes in finally block")
            elif target_layer.isEditable():
                # If layer was already being edited, just refresh display
                target_layer.triggerRepaint()

    def _create_runins_layer(self):
        """
        Creates a memory layer for storing run-in line features.
        The layer includes fields for line number, length, position, direction,
        and start/end coordinates.
        Returns:
            QgsVectorLayer: The created memory layer, or None if creation failed
        """
        try:
            log.debug("Creating Generated Run-In Run-Out layer")
            # Get project CRS or use WGS84 fallback
            crs = QgsProject.instance().crs()
            if not crs.isValid():
                crs = QgsCoordinateReferenceSystem("EPSG:4326")
                log.warning("Using WGS84 fallback CRS for run-ins layer")
            # Create the layer
            layer = QgsVectorLayer(
                f"LineString?crs={crs.authid()}", 
                "Generated Run-In Run-Out", 
                "memory"
            )
            if not layer.isValid():
                log.error("Failed to create run-ins memory layer")
                return None
            # Get the data provider
            provider = layer.dataProvider()
            # Add fields
            provider.addAttributes([
            QgsField("LineNum", QVariant.String, len=50),
                QgsField("Length_m", QVariant.Double, "double", 10, 2),
                QgsField("Position", QVariant.String, "string", 10),
                QgsField("Direction", QVariant.String, "string", 20),
                QgsField("start_x", QVariant.Double),
                QgsField("start_y", QVariant.Double),
                QgsField("end_x", QVariant.Double),
                QgsField("end_y", QVariant.Double)
            ])
            # Update fields and return
            layer.updateFields()
            log.info("Successfully created run-ins layer")
            return layer
        except Exception as e:
            log.exception(f"Error creating run-ins layer: {e}")
            return None

    def _scale_runin_geometry(self, geom, target_length, position):
        """
        Scales a straight line geometry exactly to the target length based on the specified position.
        Assumes one end is the line anchor and the other end is the outer extreme point.
        """
        if not geom or geom.isEmpty() or target_length <= 0:
            return QgsGeometry()
        pts = geom.asPolyline()
        if len(pts) < 2: 
            return QgsGeometry(geom)
            
        if position.upper() == "START":
            # For Start, pts[-1] is the line anchor, pts[0] is the outer point
            anchor = pts[-1]
            outer = pts[0]
            dist = anchor.distance(outer)
            if dist < 1e-6: return geom
            ratio = target_length / dist
            new_outer = QgsPointXY(anchor.x() + (outer.x() - anchor.x()) * ratio, anchor.y() + (outer.y() - anchor.y()) * ratio)
            return QgsGeometry.fromPolylineXY([new_outer, anchor])
        else:
            # For End, pts[0] is the line anchor, pts[-1] is the outer point
            anchor = pts[0]
            outer = pts[-1]
            dist = anchor.distance(outer)
            if dist < 1e-6: return geom
            ratio = target_length / dist
            new_outer = QgsPointXY(anchor.x() + (outer.x() - anchor.x()) * ratio, anchor.y() + (outer.y() - anchor.y()) * ratio)
            return QgsGeometry.fromPolylineXY([anchor, new_outer])

    def _find_runin_geom(self, runin_layer, target_line_num, target_position, target_length=None):
        """
        Finds the geometry of a specific run-in feature based on line number and position.

        Args:
            runin_layer (QgsVectorLayer): Layer containing run-in features
            target_line_num (int): Line number to find run-in for
            target_position (str): Position to find ("Start" or "End")

        Returns:
            QgsGeometry: Run-in geometry if found, None otherwise
        """
        # Validate input parameters
        if not runin_layer:
            log.error("Invalid run-in layer provided")
            return None
        try:
            if not runin_layer.isValid():
                log.error("Invalid run-in layer provided")
                return None
        except RuntimeError:
            log.error("Run-in layer wrapper is no longer valid")
            return None

        if target_line_num is None:
            log.error(f"Invalid line number: {target_line_num}")
            return None

        if not target_position or not isinstance(target_position, str):
            log.error(f"Invalid position: {target_position}")
            return None

        if target_length is not None and target_length <= 0:
            return None

        try:
            # Match LineNum as string (field may be string or int). If ID is "1006_1", also try base "1006".
            pos_u = target_position.upper()
            lid = str(target_line_num).replace("'", "''")
            parts = str(target_line_num).split("_", 1)
            base = parts[0].replace("'", "''") if parts else lid
            if len(parts) > 1 and base != lid:
                line_match = (
                    f'(to_string("LineNum") = \'{lid}\' OR to_string("LineNum") = \'{base}\')'
                )
            else:
                line_match = f'to_string("LineNum") = \'{lid}\''
            expr_str = f'{line_match} AND upper("Position") = \'{pos_u}\''
            expr = QgsExpression(expr_str)

            # Create a feature request with the filter expression
            request = QgsFeatureRequest(expr)
            # No need to fetch attributes, only geometry
            request.setNoAttributes()
            
            # Try to set NoGeometrySimplify flag if available in this QGIS version
            try:
                # For newer QGIS versions
                request.setFlags(QgsFeatureRequest.NoGeometrySimplify)
            except AttributeError:
                # For older QGIS versions that don't have this flag
                log.debug("QgsFeatureRequest.NoGeometrySimplify flag not available, using default settings")
                # We don't set any flags, which is okay for geometry retrieval

            first_feat = None
            for feat in runin_layer.getFeatures(request):
                first_feat = feat
                break

            if first_feat is None:
                log.debug(f"No {target_position} run-in found for line {target_line_num}")
                return None

            # Extract and validate geometry
            geom = QgsGeometry(first_feat.geometry())  # Deep copy to prevent C++ crashes
            if not geom or geom.isEmpty():
                log.warning(f"Found {target_position} run-in for line {target_line_num}, but geometry is empty or invalid")
                return None

            if target_length is not None:
                geom = self._scale_runin_geometry(geom, target_length, target_position)

            if not geom or geom.isEmpty():
                return None

            log.debug(f"Found {target_position} run-in geometry for line {target_line_num} (length: {geom.length():.1f}m)")
            return geom

        except Exception as e:
            log.exception(f"Error finding run-in geometry for line {target_line_num}, position {target_position}: {e}")
            return None

    def _calculate_runin_time(self, runin_geom, sim_params, line_traversal_reciprocal=None):
        """
        Calculates the time to traverse a run-in segment based on geometry and speed.

        Args:
            runin_geom (QgsGeometry): Run-in geometry
            sim_params (dict): Simulation parameters including speed settings
            line_traversal_reciprocal: If set, True means the associated line is shot High→Low
                (reciprocal); used to pick directional turn / connector speed. If None, uses legacy
                ``avg_turn_speed_mps`` only.

        Returns:
            float: Time in seconds to traverse the run-in segment
        """
        # Validate input parameters
        if not runin_geom or runin_geom.isEmpty():
            return 0.0

        try:
            # Get length and ensure it's non-negative
            length = max(0.0, runin_geom.length())

            # Run-in / run-out use the same nominal speed as turns (directional when available).
            if line_traversal_reciprocal is None:
                speed = sim_params.get("avg_turn_speed_mps")
            else:
                speed = turn_speed_mps(sim_params, bool(line_traversal_reciprocal))
            if not speed or speed <= 0:
                log.warning(f"Invalid run-in speed: {speed}. Using default of 4.0 m/s")
                speed = 4.0  # Default speed in m/s

            # Calculate time
            time_seconds = length / speed

            log.debug(f"Run-in time: {time_seconds:.1f}s (length: {length:.1f}m @ {speed:.1f}m/s)")
            return time_seconds

        except Exception as e:
            log.exception(f"Error calculating run-in time: {e}")
            return 0.0

    def _calculate_geom_heading(self, geom):
        """
        Calculates heading (0-360, CW from N) for a straight line geometry.
        Args:
            geom (QgsGeometry): Line geometry to calculate heading for
        Returns:
            float or None: Heading in degrees (0=North, CW) or None on error
        """
        if not geom or geom.isEmpty():
            log.warning("Invalid geometry for heading calc.")
            return None
        try:
            if geom.type() != QgsWkbTypes.LineGeometry:
                # Convert point pair to line if needed
                if geom.type() == QgsWkbTypes.PointGeometry:
                    log.warning("Cannot calculate heading from single point.")
                    return None
            # Extract start and end points
            vertices = list(geom.vertices())
            if len(vertices) < 2:
                log.warning("Need at least 2 vertices for heading.")
                return None
            start_pt = vertices[0]
            end_pt = vertices[-1]
            # Calculate heading
            dx = end_pt.x() - start_pt.x()
            dy = end_pt.y() - start_pt.y()
            if abs(dx) < GEOMETRY_PRECISION and abs(dy) < GEOMETRY_PRECISION:
                log.warning("Start and end points are too close.")
                return None
            rad = math.atan2(dx, dy)  # atan2 handles division by zero
            heading = (math.degrees(rad) + 360) % 360
            return heading
        except Exception as e:
            log.error(f"Error calc geom heading: {e}")
            return None

    # --- 5. Straight Lines & Run-ins Generator ---

    def handle_generate_lines(self, checked=False, silent=False):
        """
        Generates straight lines and run-ins based on UI filters.

        Creates two memory layers:
        1. Generated_Survey_Lines - Contains line features created from SPS points
        2. Generated_RunIns - Contains run-in segments at start and end of lines

        Survey segment: axis through centroids of min-SP and max-SP groups; endpoints are
        projections of global along-axis extremes onto that axis (all shots on the line).
        Run-ins use Heading from the SPS layer.
        """
        log.info("Starting generation of survey lines and run-ins")
        start_time = time.time()

        # Constants
        LINE_LAYER_NAME = "Generated_Survey_Lines"
        RUNIN_LAYER_NAME = "Generated Run-In Run-Out"

        # Progress tracking
        progress = None
        QApplication.setOverrideCursor(_QT_WAIT_CURSOR)

        try:
            # --- 1. VALIDATE INPUTS ---
            log.debug("Step 1: Validating inputs and parameters")

            # Check for UI components
            if not hasattr(self, 'maxRunInDoubleSpinBox'):
                raise AttributeError("UI component 'maxRunInDoubleSpinBox' not found")

            # Get run-in length parameter
            max_run_in_length = self.maxRunInDoubleSpinBox.value()
            max_run_out_length = self.runOutDoubleSpinBox.value() if hasattr(self, 'runOutDoubleSpinBox') else 0.0
            if max_run_in_length < 0 or max_run_out_length < 0:
                raise ValueError("Run-in / Run-out Lengths cannot be negative")
            if not math.isfinite(max_run_in_length) or not math.isfinite(max_run_out_length):
                raise ValueError("Run-in / Run-out Lengths must be finite numbers")
            
            lines_to_process_info = []
            base_line_nums_set = set()
            for i in range(self.lineListWidget.count()):
                item = self.lineListWidget.item(i)
                line_id = item.data(_QT_USER_ROLE)
                base_ln = item.data(_QT_USER_ROLE + 2)
                status = item.data(_QT_USER_ROLE + 1)
                if str(status).strip().upper() == "TO BE ACQUIRED":
                    lines_to_process_info.append({'line_id': line_id, 'base_ln': base_ln})
                    base_line_nums_set.add(base_ln)
                    
            if not lines_to_process_info:
                raise ValueError("No lines with status 'To Be Acquired' found in the list.")

            # Get and validate source layer
            source_layer = self._require_sail_layer("Create Lookahead Lines", silent=silent)
            if not source_layer:
                return False

            # Validate required fields exist
            fields = source_layer.fields()
            required_fields = ['LineNum', 'SP', 'Heading', 'Status']
            missing_fields = []
            field_indices = {}

            for field_name in required_fields:
                field_idx = fields.lookupField(field_name)
                if field_idx == -1:
                    missing_fields.append(field_name)
                else:
                    field_indices[field_name] = field_idx

            if missing_fields:
                raise ValueError(f"Source layer missing required fields: {', '.join(missing_fields)}")

            # Validate CRS
            source_crs = source_layer.crs()
            if not source_crs.isValid():
                raise ValueError("Source layer has invalid coordinate reference system")

            # Lines matching filter; generation only for those with ≥1 point "To Be Acquired".
            candidate_lines = sorted(list(base_line_nums_set))
            log.debug("Found %s candidate lines from current filter.", len(candidate_lines))

            ln_idx = field_indices["LineNum"]
            sp_idx = field_indices["SP"]
            st_idx = field_indices["Status"]
            hd_idx = field_indices["Heading"]
            match_set = base_line_nums_set
            src_idx, src_role_field = self._sps_source_role_field_index(fields)
            if src_idx >= 0:
                log.info(
                    "Generate lines: using role field %r for triple-source center line "
                    "(center-tagged shots per SP; otherwise mean XY per SP).",
                    src_role_field,
                )

            by_line_points = defaultdict(list)
            tba_line_nums = set()

            def _line_num_chunks(seq, size):
                for i in range(0, len(seq), size):
                    yield seq[i : i + size]

            # One pass per chunk over candidate LineNums (not the whole layer twice + per-line scans).
            for chunk in _line_num_chunks(candidate_lines, 500):
                if len(chunk) == 1:
                    in_expr = f'"LineNum" = {chunk[0]}'
                else:
                    in_expr = '"LineNum" IN (' + ",".join(str(n) for n in chunk) + ")"
                req_collect = QgsFeatureRequest().setFilterExpression(in_expr)
                _attr_subset = ["LineNum", "SP", "Status", "Heading"]
                if src_idx >= 0:
                    _attr_subset.append(fields.at(src_idx).name())
                req_collect.setSubsetOfAttributes(_attr_subset, source_layer.fields())
                for feature in source_layer.getFeatures(req_collect):
                    geom = feature.geometry()
                    if not geom or geom.isNull() or geom.type() != QgsWkbTypes.PointGeometry:
                        continue
                    sp_value = feature.attribute(sp_idx)
                    if sp_value is None or sp_value == NULL:
                        continue
                    try:
                        sp_int = int(sp_value)
                    except (ValueError, TypeError):
                        continue
                        
                    ln_val = feature.attribute(ln_idx)
                    try:
                        ln = int(ln_val)
                    except (ValueError, TypeError):
                        continue
                    if ln not in base_line_nums_set:
                        continue
                    _row = {
                        "sp": sp_int,
                        "heading": feature.attribute(hd_idx),
                        "status": feature.attribute(st_idx),
                        "xy": geom.asPoint(),
                    }
                    if src_idx >= 0:
                        _row["_src"] = feature.attribute(src_idx)
                    by_line_points[ln].append(_row)

            log.debug("Processing %s 'To Be Acquired' line parts.", len(lines_to_process_info))

            # --- 2. PREPARE OUTPUT LAYERS ---
            log.debug("Step 2: Preparing output memory layers")

            # Remove any existing layers with the same names
            self.generated_lines_layer = None
            self.generated_runins_layer = None
            self._last_generation_signature = None
            project = QgsProject.instance()
            self._remove_layer_by_name(LINE_LAYER_NAME)
            self._remove_layer_by_name(RUNIN_LAYER_NAME)

            # Create line feature fields
            line_fields = QgsFields()
            line_fields.append(QgsField("LineNum", QVariant.String, len=50))
            line_fields.append(QgsField("Status", QVariant.String, len=20))
            line_fields.append(QgsField("Length_m", QVariant.Double, len=10, prec=2))
            line_fields.append(QgsField("Heading", QVariant.Double, len=10, prec=1))
            line_fields.append(QgsField("LowestSP", QVariant.Int))
            line_fields.append(QgsField("LowestSP_x", QVariant.Double, len=15, prec=3))
            line_fields.append(QgsField("LowestSP_y", QVariant.Double, len=15, prec=3))
            line_fields.append(QgsField("HighestSP", QVariant.Int))
            line_fields.append(QgsField("HighestSP_x", QVariant.Double, len=15, prec=3))
            line_fields.append(QgsField("HighestSP_y", QVariant.Double, len=15, prec=3))

            # Create run-in feature fields
            runin_fields = QgsFields()
            runin_fields.append(QgsField("LineNum", QVariant.String, len=50))
            runin_fields.append(QgsField("Length_m", QVariant.Double, len=10, prec=2))
            runin_fields.append(QgsField("Position", QVariant.String, len=10))
            runin_fields.append(QgsField("Direction", QVariant.String, len=20))
            runin_fields.append(QgsField("start_x", QVariant.Double, len=15, prec=3))
            runin_fields.append(QgsField("start_y", QVariant.Double, len=15, prec=3))
            runin_fields.append(QgsField("end_x", QVariant.Double, len=15, prec=3))
            runin_fields.append(QgsField("end_y", QVariant.Double, len=15, prec=3))

            # Create memory layers
            line_uri = f"LineString?crs={source_crs.authid()}&index=yes"
            runin_uri = f"LineString?crs={source_crs.authid()}&index=yes"

            self.generated_lines_layer = QgsVectorLayer(line_uri, LINE_LAYER_NAME, "memory")
            self.generated_runins_layer = QgsVectorLayer(runin_uri, RUNIN_LAYER_NAME, "memory")

            if not self.generated_lines_layer.isValid() or not self.generated_runins_layer.isValid():
                raise RuntimeError("Failed to create memory layers")

            # Add fields to layers
            line_provider = self.generated_lines_layer.dataProvider()
            line_provider.addAttributes(line_fields)
            self.generated_lines_layer.updateFields()

            runin_provider = self.generated_runins_layer.dataProvider()
            runin_provider.addAttributes(runin_fields)
            self.generated_runins_layer.updateFields()

            # Start editing sessions on the layers
            self.generated_lines_layer.startEditing()
            self.generated_runins_layer.startEditing()

            # --- 3. PROCESS LINES AND GENERATE FEATURES ---
            log.debug("Step 3: Processing lines and generating features")

            # Setup progress dialog (defer popup for small jobs — avoids flash + event overhead)
            total_lines = len(lines_to_process_info)
            progress = QProgressDialog("Generating Lines and Run-ins...", "Cancel", 0, total_lines, self)
            progress.setWindowModality(_QT_WINDOW_MODAL)
            progress.setMinimumDuration(2500 if total_lines <= 12 else 400)
            progress.show()

            # Prepare batch processing
            lines_generated = 0
            runins_generated = 0
            line_features = []
            runin_features = []
            batch_size = 1000  # Process features in batches for better performance

            for i, info in enumerate(lines_to_process_info):
                if progress.wasCanceled():
                    raise UserCancelException("Operation canceled by user")

                line_id = info['line_id']
                base_ln = info['base_ln']

                progress.setValue(i)
                progress.setLabelText(f"Processing line {line_id} ({i+1} of {total_lines})")
                if total_lines > 12 or (i % 4 == 0):
                    QApplication.processEvents()

                rows = by_line_points.get(base_ln) or []
                
                # Apply custom SP bounds per specific line part
                custom_bounds = self.custom_line_sp_bounds.get(line_id)
                if custom_bounds:
                    min_sp, max_sp = custom_bounds
                    rows = [r for r in rows if min_sp <= r["sp"] <= max_sp]
                
                rows.sort(key=lambda r: r["sp"])
                if len(rows) < 2:
                    log.warning(
                        "Skipping Line ID %s: Found only %s valid points (requires >= 2)",
                        line_id,
                        len(rows),
                    )
                    continue

                meta = self._centerline_geometry_meta_from_line_rows(rows, src_idx)
                if meta is None:
                    log.warning(
                        "Skipping Line ID %s: need at least two distinct SP groups after center/mean resolution",
                        line_id,
                    )
                    continue

                lowest_sp = meta["lowest_sp"]
                highest_sp = meta["highest_sp"]
                rep_low = meta["rep_low"]
                line_status = rep_low["status"]
                line_heading = rep_low["heading"]
                lowest_sp_point = meta["line_start_xy"]
                highest_sp_point = meta["line_end_xy"]
                points_xy_list = [lowest_sp_point, highest_sp_point]
                line_geometry = QgsGeometry.fromPolylineXY([lowest_sp_point, highest_sp_point])

                if line_geometry and not line_geometry.isNull():
                    line_feature = QgsFeature(line_fields)
                    line_feature.setGeometry(line_geometry)
                    line_feature.setAttributes([
                        line_id,
                        line_status if line_status is not None and line_status != NULL else NULL,
                        line_geometry.length(),
                        line_heading,
                        lowest_sp,
                        lowest_sp_point.x(),
                        lowest_sp_point.y(),
                        highest_sp,
                        highest_sp_point.x(),
                        highest_sp_point.y(),
                    ])

                    line_features.append(line_feature)
                    lines_generated += 1

                    heading_value = None
                    if line_heading is not None and line_heading != NULL:
                        try:
                            heading_value = float(line_heading)
                        except (ValueError, TypeError):
                            log.warning("Invalid heading value for Line ID %s: %s", line_id, line_heading)
                    if heading_value is not None and not math.isfinite(heading_value):
                        log.warning("Skipping run-ins for Line ID %s: Heading is not finite (%s)", line_id, line_heading)
                        heading_value = None

                    if heading_value is not None:
                        try:
                            rad = math.radians(heading_value)
                            vx = math.sin(rad)
                            vy = math.cos(rad)
                            if (not math.isfinite(vx)) or (not math.isfinite(vy)):
                                raise ValueError(f"Non-finite direction vector from heading {heading_value}")

                            start_point = points_xy_list[0]
                            if max_run_in_length > 0:
                                runin_start_x = start_point.x() - vx * max_run_in_length
                                runin_start_y = start_point.y() - vy * max_run_in_length
                                if (not math.isfinite(runin_start_x)) or (not math.isfinite(runin_start_y)):
                                    raise ValueError("Computed non-finite Start run-in coordinates")
                                runin_start_point = QgsPointXY(runin_start_x, runin_start_y)

                                start_runin_geom = QgsGeometry.fromPolylineXY([runin_start_point, start_point])
                                if start_runin_geom and not start_runin_geom.isEmpty():
                                    start_runin_feature = QgsFeature(runin_fields)
                                    start_runin_feature.setGeometry(start_runin_geom)
                                    start_runin_feature.setAttributes([
                                        line_id,
                                        start_runin_geom.length(),
                                        "Start",
                                        "Low to High SP",
                                        runin_start_point.x(),
                                        runin_start_point.y(),
                                        start_point.x(),
                                        start_point.y(),
                                    ])

                                    runin_features.append(start_runin_feature)
                                    runins_generated += 1

                            end_point = points_xy_list[-1]
                            # End connector: true run-out length when run-out > 0; when run-out is 0 it is still
                            # required for reciprocal (High→Low) run-in — same ray from line end, use run-in length.
                            end_extent_m = (
                                max_run_out_length if max_run_out_length > 0 else max_run_in_length
                            )
                            if end_extent_m > 0:
                                runin_end_x = end_point.x() + vx * end_extent_m
                                runin_end_y = end_point.y() + vy * end_extent_m
                                if (not math.isfinite(runin_end_x)) or (not math.isfinite(runin_end_y)):
                                    raise ValueError("Computed non-finite End run-out coordinates")
                                runin_end_point = QgsPointXY(runin_end_x, runin_end_y)

                                end_runin_geom = QgsGeometry.fromPolylineXY([end_point, runin_end_point])
                                if end_runin_geom and not end_runin_geom.isEmpty():
                                    end_runin_feature = QgsFeature(runin_fields)
                                    end_runin_feature.setGeometry(end_runin_geom)
                                    end_runin_feature.setAttributes([
                                        line_id,
                                        end_runin_geom.length(),
                                        "End",
                                        "High to Low SP",
                                        end_point.x(),
                                        end_point.y(),
                                        runin_end_point.x(),
                                        runin_end_point.y(),
                                    ])

                                    runin_features.append(end_runin_feature)
                                    runins_generated += 1
                        except Exception as runin_e:
                            log.warning("Error calculating run-ins for Line ID %s: %s", line_id, runin_e)
                    elif heading_value is None:
                        log.warning("Skipping run-ins for Line ID %s: Heading is NULL", line_id)
                else:
                    log.warning("Failed to create valid line geometry for Line ID %s", line_id)

                if len(line_features) >= batch_size:
                    if not line_provider.addFeatures(line_features):
                        log.warning("Failed to add batch of %s line features", len(line_features))
                    line_features = []

                if len(runin_features) >= batch_size:
                    if not runin_provider.addFeatures(runin_features):
                        log.warning("Failed to add batch of %s run-in features", len(runin_features))
                    runin_features = []

                if total_lines > 20 and i % 10 == 0:
                    QApplication.processEvents()

            # Add any remaining features
            if line_features:
                line_provider.addFeatures(line_features)
            if runin_features:
                runin_provider.addFeatures(runin_features)

            # Complete the progress
            progress.setValue(total_lines)
            QApplication.processEvents()

            # --- 4. COMMIT CHANGES AND ADD LAYERS TO PROJECT ---
            log.debug("Step 4: Committing changes and adding layers to project")

            # Commit changes to memory layers
            lines_commit_ok = self.generated_lines_layer.commitChanges()
            runins_commit_ok = self.generated_runins_layer.commitChanges()

            if not lines_commit_ok:
                commit_error = self.generated_lines_layer.commitErrors()
                log.error(f"Failed to commit generated lines: {commit_error}")
                raise RuntimeError(f"Failed to commit changes to lines layer: {commit_error}")

            if not runins_commit_ok:
                commit_error = self.generated_runins_layer.commitErrors()
                log.error(f"Failed to commit generated run-ins: {commit_error}")
                raise RuntimeError(f"Failed to commit changes to run-ins layer: {commit_error}")

            # Add layers to project and apply styling
            layers_added = 0

            if lines_generated > 0 and self.generated_lines_layer and self.generated_lines_layer.isValid():
                self.generated_lines_layer.updateExtents()
                self._apply_basic_style(self.generated_lines_layer, 'blue', width=0.6)
                self._add_layer_to_lookahead_group(self.generated_lines_layer)
                layers_added += 1

            if runins_generated > 0 and self.generated_runins_layer and self.generated_runins_layer.isValid():
                self.generated_runins_layer.updateExtents()
                self._apply_basic_style(self.generated_runins_layer, 'red', line_style='dash', width=0.6)
                self._add_layer_to_lookahead_group(self.generated_runins_layer)
                layers_added += 1

            # Show results message
            elapsed_time = time.time() - start_time

            if layers_added > 0:
                self._last_generation_signature = self._build_generation_signature()
                message = (f"Successfully generated {lines_generated} lines and {runins_generated} run-ins "
                          f"in {elapsed_time:.1f} seconds")
                log.info(message)
                self._pop_wait_cursor_if_busy()
                if not silent:
                    QMessageBox.information(self, "Success", message)
            else:
                self._remove_layer_by_name(LINE_LAYER_NAME)
                self._remove_layer_by_name(RUNIN_LAYER_NAME)
                self.generated_lines_layer = None
                self.generated_runins_layer = None
                log.warning("No valid lines or run-ins were generated")
                self._pop_wait_cursor_if_busy()
                if not silent:
                    QMessageBox.warning(self, "No Output", "No valid lines or run-ins could be generated for the selected criteria")

        except UserCancelException as uce:
            log.info(f"{uce}")
            self._pop_wait_cursor_if_busy()
            if not silent:
                QMessageBox.information(self, "Canceled", "Operation was canceled by user")
        except ValueError as ve:
            log.warning(f"Validation error: {ve}")
            self._pop_wait_cursor_if_busy()
            if not silent:
                QMessageBox.warning(self, "Input Error", str(ve))
        except Exception as e:
            log.exception(f"Error generating lines and run-ins: {e}")
            self._pop_wait_cursor_if_busy()
            if not silent:
                QMessageBox.critical(self, "Error", f"An error occurred during generation:\n{str(e)}")
        finally:
            # Clean up resources
            if progress is not None:
                progress.close()

            # Cancel edits if still active
            if hasattr(self, 'generated_lines_layer') and self.generated_lines_layer and self.generated_lines_layer.isEditable():
                self.generated_lines_layer.rollBack()

            if hasattr(self, 'generated_runins_layer') and self.generated_runins_layer and self.generated_runins_layer.isEditable():
                self.generated_runins_layer.rollBack()

            self._pop_wait_cursor_if_busy()

            log.debug("Line generation process completed")

    # --- 6. Deviation Calculation (RRT Based) ---
           
    def handle_calculate_deviations(self):
        """
        Handler for the Generate Deviation Lines button. Runs the deviation
        calculation process directly.
        """
        log.info("Starting deviation calculation...")
        if not self._require_sail_layer("Create Deviation Lines"):
            return False
        
        # --- AUTO-UPDATE BASE LINES ---
        # Silently regenerate straight lines to bend them from scratch each time
        try:
            self.handle_generate_lines(silent=True)
        except Exception as e:
            log.warning(f"Failed to auto-regenerate straight lines: {e}")
            
        QApplication.setOverrideCursor(_QT_WAIT_CURSOR) # Set busy cursor

        # --- Input Validation ---
        lines_layer = self.generated_lines_layer
        lines_valid = False
        try:
            if lines_layer is not None and lines_layer.isValid():
                lines_valid = True
        except RuntimeError:
            pass # Suppress "wrapped C/C++ object has been deleted" error
            
        if not lines_valid:
            self._pop_wait_cursor_if_busy()
            QMessageBox.warning(self, "Input Error", "Survey lines layer has been deleted or is unavailable. Please click 'Generate Lookahead Lines' first.")
            return False

        nogo_combo = getattr(self, "nogo_zone_combo", None)
        nogo_layer = nogo_combo.currentLayer() if nogo_combo is not None else None
        if not nogo_layer or not nogo_layer.isValid():
            self._pop_wait_cursor_if_busy()
            QMessageBox.warning(self, "Input Error", "Select a valid No-Go Zone layer.")
            return False

        # --- Parameter Setup ---
        clearance_m = 0.0
        turn_radius_m = 0.0
        try:
            # Use try-except for UI access
            clearance_m = self.deviationClearanceDoubleSpinBox.value()
            turn_radius_m = self.turnRadiusDoubleSpinBox.value()
        except AttributeError as ae:
             log.error(f"UI element missing for parameters: {ae}")
             self._pop_wait_cursor_if_busy()
             QMessageBox.critical(self, "UI Error", f"Could not find UI element for parameters: {ae}")
             return False

        # Validate parameter ranges
        if clearance_m <= 0:
            self._pop_wait_cursor_if_busy()
            QMessageBox.warning(self, "Parameter Error", "Clearance distance must be greater than zero.")
            return False

        if turn_radius_m <= 0:
            self._pop_wait_cursor_if_busy()
            QMessageBox.warning(self, "Parameter Error", "Turn radius must be greater than zero.")
            return False

        log.info(f"Starting direct deviation calculation with clearance={clearance_m}m, turn_radius={turn_radius_m}m")

        try:
            # --- Determine Debug Mode (Optional - can be hardcoded or read from a setting) ---
            # For now, let's default to False unless you have a specific debug checkbox
            debug_mode = False # Default to non-debug mode for direct calculation
            # Example: if hasattr(self, 'debugCheckBox') and self.debugCheckBox.isChecked():
            #     debug_mode = True
            #     log.info("Debug mode enabled for deviation calculation.")

            # --- Run Full Calculation Directly ---
            log.info("Proceeding directly to full deviation calculation...")
            success = self._calculate_and_apply_deviations_v2(
                lines_layer, nogo_layer, clearance_m, turn_radius_m, debug_mode
            )

            # --- Process Results ---
            if success:
                log.info("Deviation calculation completed successfully.")
                self._pop_wait_cursor_if_busy()
                QMessageBox.information(self, "Success",
                                       "Deviation calculation completed successfully.\n"
                                       "Check the results in the 'Generated_Survey_Lines' layer.")
                # Optional: Refresh relevant layers or zoom to extent
                lines_layer.triggerRepaint()
                self._refresh_map_canvas_safe()
                return True
            else:
                # Specific error messages should ideally be handled within _calculate_and_apply_deviations_v2
                log.error("Deviation calculation failed or was aborted.")
                self._pop_wait_cursor_if_busy()
                QMessageBox.critical(self, "Calculation Error",
                                   "Deviation calculation failed or was aborted.\n"
                                   "Please check the log file for details.")
                return False

        except Exception as e:
            log.exception(f"Unhandled error during deviation calculation: {e}")
            self._pop_wait_cursor_if_busy()
            QMessageBox.critical(
                self,
                "Processing Error",
                f"An unexpected error occurred during calculation:\n{str(e)}\n\nCheck the log for details."
            )
            # Attempt to rollback if editing was started within the called function
            if lines_layer and lines_layer.isEditable():
                 log.warning("Attempting to roll back changes on lines layer due to error.")
                 lines_layer.rollBack()
            return False
        finally:
             self._pop_wait_cursor_if_busy()


    def _calculate_intermediate_components(self, lines_layer, nogo_layer, clearance_m, turn_radius_m, debug_mode=False):
        """
        Calculate just the intermediate components (reference lines, peak points) 
        without attempting the full deviation path calculation.

        This is useful for debugging geometry issues before running the full calculation.

        Args:
            lines_layer (QgsVectorLayer): Layer containing the survey lines
            nogo_layer (QgsVectorLayer): Layer containing the NoGo zones
            clearance_m (float): Clearance distance in meters
            turn_radius_m (float): Minimum turning radius for the vessel in meters
            debug_mode (bool): If True, enables extensive debugging logs

        Returns:
            bool: True if calculation was successful, False otherwise
        """
        log.info("Calculating intermediate components for deviation...")

        project = QgsProject.instance()

        # Store calculation results for visualization
        self.all_reference_lines = {}
        self.all_peaks = {}

        # --- Phase 1: Preparation ---
        if not self._add_deviation_fields(lines_layer):
            QMessageBox.critical(self, "Setup Error", "Failed to add required deviation fields to the lines layer.")
            return False

        try:
            # Prepare avoidance geometry
            log.debug(f"Preparing avoidance geometry with clearance {clearance_m}m...")
            avoidance_geom = self._prepare_avoidance_geometry(nogo_layer, clearance_m)

            if not avoidance_geom:
                log.error("Failed to prepare avoidance geometry.")
                return False

            # Separate the geometry into distinct components
            log.debug("Separating avoidance geometry into distinct obstacles...")
            obstacle_geometries = self._separate_avoidance_geometry(avoidance_geom)

            if not obstacle_geometries:
                log.error("Failed to separate avoidance geometry into obstacles.")
                return False

            # --- Identify conflicts & group ---
            log.debug("Identifying conflicted lines...")
            conflicted_lines_info = []
            fld_linenum = lines_layer.fields().lookupField("LineNum")
            fld_heading = lines_layer.fields().lookupField("Heading")

            # Use spatial index to quickly find potential conflicts
            idx = QgsSpatialIndex()
            for feat in lines_layer.getFeatures():
                idx.insertFeature(feat)

            candidate_ids = idx.intersects(avoidance_geom.boundingBox())

            # Detailed intersection check for candidates
            conflicted_fids = {}
            for fid in candidate_ids:
                feat = lines_layer.getFeature(fid)
                geom = feat.geometry()

                if not geom or geom.isEmpty():
                    continue

                if geom.intersects(avoidance_geom):
                    conflicted_fids[fid] = True

                    if fld_linenum >= 0 and fld_heading >= 0:
                        line_num = feat[fld_linenum]
                        heading = feat[fld_heading]

                        if line_num is not None and heading is not None:
                            conflicted_lines_info.append((fid, geom, line_num, heading))

            if not conflicted_lines_info:
                log.info("No survey lines conflict with the avoidance zones.")
                return True

            log.info(f"Found {len(conflicted_lines_info)} conflicted lines.")

            # --- Grouping logic with multiple obstacle support ---
            obstacle_groups = {}

            # Sort conflicted lines by LineNum
            conflicted_lines_info.sort(key=lambda item: item[2])

            # Create a mapping of which lines intersect with which obstacles
            if len(obstacle_geometries) > 1:
                log.info(f"Processing {len(obstacle_geometries)} distinct obstacles - grouping lines by obstacle")

                # For each line, check which obstacles it intersects
                for line_idx, (fid, line_geom, line_num, heading) in enumerate(conflicted_lines_info):
                    line_obstacles = []

                    for obs_idx, obs_geom in enumerate(obstacle_geometries):
                        if line_geom.intersects(obs_geom):
                            if obs_idx not in obstacle_groups:
                                obstacle_groups[obs_idx] = []
                            obstacle_groups[obs_idx].append((fid, line_geom, line_num, heading, line_idx))
                            line_obstacles.append(obs_idx)

                    log.debug(f"Line {line_num} intersects obstacles: {line_obstacles}")
            else:
                # Just one obstacle - put all lines in the same group
                obstacle_groups[0] = [(fid, line_geom, line_num, heading, idx) 
                                     for idx, (fid, line_geom, line_num, heading) in enumerate(conflicted_lines_info)]
                log.info("Single obstacle detected - all lines in same group")

            # Store results for visualization
            self.conflicted_lines_info = conflicted_lines_info
            self.obstacle_groups = obstacle_groups
            self.obstacle_centers = {}

            # Calculate the middle line for each obstacle group
            log.debug("Identifying middle reference lines for each obstacle...")
            middle_lines = {}
            for obs_idx, group_lines in obstacle_groups.items():
                if not group_lines:
                    continue

                # Sort by LineNum (should already be sorted, but ensure it)
                group_lines.sort(key=lambda x: x[2])

                # Use median approach to find middle line
                median_idx = len(group_lines) // 2
                middle_fid, middle_geom, middle_num, middle_heading, orig_idx = group_lines[median_idx]

                # Store middle line info for this obstacle
                middle_lines[obs_idx] = {
                    'fid': middle_fid,
                    'geom': middle_geom,
                    'num': middle_num,
                    'heading': middle_heading,
                    'idx': orig_idx
                }

                # Store the obstacle geometry for visualization
                middle_lines[obs_idx]['obstacle_geom'] = obstacle_geometries[obs_idx]

                log.info(f"Obstacle {obs_idx}: Middle reference line identified: {middle_num}")

            if not middle_lines:
                log.error("Failed to identify any middle reference lines.")
                return False

            # Process each obstacle independently with its own middle reference line
            log.info(f"Processing {len(middle_lines)} obstacles with separate reference lines")

            # Store original values for future visualization
            for obs_idx, middle_line_info in middle_lines.items():
                middle_line_num = middle_line_info['num']
                middle_line_geom = middle_line_info['geom']
                middle_line_heading = middle_line_info['heading']
                obstacle_geom = middle_line_info.get('obstacle_geom')

                # Store reference information for this obstacle
                self.all_reference_lines[obs_idx] = {
                    'num': middle_line_num,
                    'geom': middle_line_geom,
                    'heading': middle_line_heading,
                    'group_lines': obstacle_groups[obs_idx],
                    'obstacle_geom': obstacle_geom
                }

                # Store the obstacle center
                if obstacle_geom:
                    self.obstacle_centers[obs_idx] = obstacle_geom.centroid().asPoint()

                log.info(f"Obstacle {obs_idx}: Using middle line {middle_line_num} as reference")

            # Calculate avoidance centroid for reference
            avoidance_centroid = avoidance_geom.centroid().asPoint()

            # Calculate Peak Points for each obstacle
            for obs_idx, ref_line in self.all_reference_lines.items():
                middle_line_geom = ref_line['geom']
                middle_line_heading = ref_line['heading']

                # Use the center of the obstacle 
                obstacle_geom = obstacle_geometries[obs_idx]
                obstacle_centroid = obstacle_geom.centroid()
                mid_pt = obstacle_centroid.asPoint()

                log.debug(f"Using obstacle center at ({mid_pt.x():.1f}, {mid_pt.y():.1f}) for perpendicular rays")
                middle_line_heading_rad = math.radians(middle_line_heading)
                perp_angle_rad_A = middle_line_heading_rad + math.pi / 2.0
                perp_angle_rad_B = middle_line_heading_rad - math.pi / 2.0

                # Extract obstacle boundary 
                try:
                    obstacle_boundary = self._extract_obstacle_boundary(obstacle_geom)
                except Exception as e:
                    log.warning(f"Could not extract boundary properly: {e}")
                    obstacle_boundary = obstacle_geom

                log.debug(f"Successfully extracted boundary for obstacle {obs_idx}")

                # Create rays for finding peaks
                mid_point_xy = QgsPointXY(mid_pt)
                ray_length = max(obstacle_geom.boundingBox().width() + obstacle_geom.boundingBox().height(), 5000)

                # Ray in direction A
                ray_A_end_x = mid_pt.x() + ray_length * math.sin(perp_angle_rad_A)
                ray_A_end_y = mid_pt.y() + ray_length * math.cos(perp_angle_rad_A)
                ray_A = QgsGeometry.fromPolylineXY([mid_point_xy, QgsPointXY(ray_A_end_x, ray_A_end_y)])

                # Ray in direction B
                ray_B_end_x = mid_pt.x() + ray_length * math.sin(perp_angle_rad_B)
                ray_B_end_y = mid_pt.y() + ray_length * math.cos(perp_angle_rad_B)
                ray_B = QgsGeometry.fromPolylineXY([mid_point_xy, QgsPointXY(ray_B_end_x, ray_B_end_y)])

                # Find intersection with obstacle boundary
                intersection_A = ray_A.intersection(obstacle_boundary)
                intersection_B = ray_B.intersection(obstacle_boundary)

                # Calculate peak positions
                offset_dist = clearance_m  # Strict clearance distance
                peak_a_x = mid_pt.x() + offset_dist * math.sin(perp_angle_rad_A)
                peak_a_y = mid_pt.y() + offset_dist * math.cos(perp_angle_rad_A)
                peak_b_x = mid_pt.x() + offset_dist * math.sin(perp_angle_rad_B)
                peak_b_y = mid_pt.y() + offset_dist * math.cos(perp_angle_rad_B)

                # If we found intersection with boundary, use that point instead
                if intersection_A and not intersection_A.isEmpty():
                    if intersection_A.type() == QgsWkbTypes.PointGeometry:
                        # Process point geometry intersections
                        if intersection_A.isMultipart():
                            points = intersection_A.asMultiPoint()
                            if points:
                                # Find closest point to midpoint
                                closest_dist = float('inf')
                                closest_point = None
                                for pt in points:
                                    dist = math.sqrt((pt.x() - mid_pt.x())**2 + (pt.y() - mid_pt.y())**2)
                                    if dist < closest_dist:
                                        closest_dist = dist
                                        closest_point = pt
                                if closest_point:
                                    peak_a_x = closest_point.x()
                                    peak_a_y = closest_point.y()
                        else:
                            point = intersection_A.asPoint()
                            peak_a_x = point.x()
                            peak_a_y = point.y()
                    else:
                        # For other geometry types, find closest point
                        closest_pt = intersection_A.nearestPoint(QgsGeometry.fromPointXY(mid_point_xy))
                        if not closest_pt.isEmpty():
                            peak_a_x = closest_pt.asPoint().x()
                            peak_a_y = closest_pt.asPoint().y()

                # Similar process for intersection B
                if intersection_B and not intersection_B.isEmpty():
                    if intersection_B.type() == QgsWkbTypes.PointGeometry:
                        if intersection_B.isMultipart():
                            points = intersection_B.asMultiPoint()
                            if points:
                                closest_dist = float('inf')
                                closest_point = None
                                for pt in points:
                                    dist = math.sqrt((pt.x() - mid_pt.x())**2 + (pt.y() - mid_pt.y())**2)
                                    if dist < closest_dist:
                                        closest_dist = dist
                                        closest_point = pt
                                if closest_point:
                                    peak_b_x = closest_point.x()
                                    peak_b_y = closest_point.y()
                        else:
                            point = intersection_B.asPoint()
                            peak_b_x = point.x()
                            peak_b_y = point.y()
                    else:
                        closest_pt = intersection_B.nearestPoint(QgsGeometry.fromPointXY(mid_point_xy))
                        if not closest_pt.isEmpty():
                            peak_b_x = closest_pt.asPoint().x()
                            peak_b_y = closest_pt.asPoint().y()

                # Store peaks for visualization
                peak_A = QgsPoint(peak_a_x, peak_a_y)
                peak_B = QgsPoint(peak_b_x, peak_b_y)
                self.all_peaks[obs_idx] = {'A': peak_A, 'B': peak_B}

                log.debug(f"Obstacle {obs_idx}: Peak A: {peak_A.x():.1f},{peak_A.y():.1f}, Peak B: {peak_B.x():.1f},{peak_B.y():.1f}")

                # Add entry/exit points for visualization
                # Calculate entry/exit points from obstacle center along middle line heading
                obstacle_center = self.obstacle_centers[obs_idx]
                if obstacle_center:
                    entry_point, exit_point = self._calculate_entry_exit_points(
                        obstacle_center, 
                        middle_line_heading,
                        1000.0  # Use 1000m distance as requested
                    )
                    
                    # Store for visualization
                    self.all_reference_lines[obs_idx]['entry_point'] = entry_point
                    self.all_reference_lines[obs_idx]['exit_point'] = exit_point
                    
                    # Create a simple deviation polygon for visualization
                    entry_pt_xy = entry_point  # Already QgsPointXY
                    exit_pt_xy = exit_point    # Already QgsPointXY
                    peak_a_xy = QgsPointXY(peak_A)
                    peak_b_xy = QgsPointXY(peak_B)
                    
                    # Create the polygon points (clockwise order)
                    polygon_points = [
                        entry_pt_xy,
                        peak_a_xy,
                        exit_pt_xy,
                        peak_b_xy,
                        entry_pt_xy  # Close the polygon
                    ]
                    
                    # Create polygon geometry
                    deviation_polygon = QgsGeometry.fromPolygonXY([polygon_points])
                    self.all_reference_lines[obs_idx]['deviation_polygon'] = deviation_polygon

                    # Store for visualization
                    self.all_reference_lines[obs_idx]['entry_point'] = entry_point
                    self.all_reference_lines[obs_idx]['exit_point'] = exit_point

                    # Create a simple deviation polygon for visualization
                    entry_pt_xy = QgsPointXY(entry_point)
                    exit_pt_xy = QgsPointXY(exit_point)
                    peak_a_xy = QgsPointXY(peak_A)
                    peak_b_xy = QgsPointXY(peak_B)

                    # Create the polygon points (clockwise order)
                    polygon_points = [
                        entry_pt_xy,
                        peak_a_xy,
                        exit_pt_xy,
                        peak_b_xy,
                        entry_pt_xy  # Close the polygon
                    ]

                    # Create polygon geometry
                    deviation_polygon = QgsGeometry.fromPolygonXY([polygon_points])
                    self.all_reference_lines[obs_idx]['deviation_polygon'] = deviation_polygon

            # All intermediate components calculated successfully
            log.info("Successfully calculated intermediate components for deviation!")
            return True

        except Exception as e:
            log.exception(f"Error calculating intermediate components: {e}")
            return False

    def _extract_obstacle_boundary(self, obstacle_geom):
        """
        Helper method to extract the boundary of an obstacle geometry.

        Args:
            obstacle_geom (QgsGeometry): The obstacle geometry

        Returns:
            QgsGeometry: The boundary geometry
        """
        if obstacle_geom.type() == QgsWkbTypes.PolygonGeometry:
            if obstacle_geom.isMultipart():
                # For multipolygon, use the part with largest area
                multi_polygon = obstacle_geom.asMultiPolygon()
                if multi_polygon:
                    # Find the largest polygon by area
                    largest_idx = 0
                    largest_area = 0
                    for i, polygon in enumerate(multi_polygon):
                        temp_geom = QgsGeometry.fromPolygonXY(polygon)
                        area = temp_geom.area()
                        if area > largest_area:
                            largest_area = area
                            largest_idx = i

                    # Get the exterior ring of the largest polygon
                    if multi_polygon[largest_idx]:
                        exterior_ring = multi_polygon[largest_idx][0]  # First ring is exterior
                        return QgsGeometry.fromPolylineXY(exterior_ring)
            else:
                # Single polygon
                polygon = obstacle_geom.asPolygon()
                if polygon and polygon[0]:  # Check if polygon has rings
                    exterior_ring = polygon[0]  # First ring is exterior
                    return QgsGeometry.fromPolylineXY(exterior_ring)
        elif obstacle_geom.type() == QgsWkbTypes.LineGeometry:
            # If it's already a line, use it directly
            return obstacle_geom

        # For other types, just use the original geometry
        return obstacle_geom

    def _prepare_nogo_geometry(self, nogo_layer, clearance_m):
        """
        Prepares a single, valid, buffered geometry representing all NoGo zones.
        Args:
            nogo_layer (QgsVectorLayer): Layer containing NoGo polygons
            clearance_m (float): Buffer distance in meters to apply
        Returns:
            QgsGeometry or None: Combined buffered geometry or None on error
        """
        log.debug(f"Preparing NoGo geometry with clearance {clearance_m}m")
        if nogo_layer is None or not nogo_layer.isValid():
            log.warning("No valid No-Go layer.")
            return None
        all_nogo_geoms = []
        processed_feats = 0
        invalid_feats = 0
        req = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoFlags)
        try:
            # Collect and buffer all geometries
            for feat in nogo_layer.getFeatures(req):
                processed_feats += 1
                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    invalid_feats += 1
                    continue
                # Apply buffer
                if clearance_m > 0:
                    buffered = geom.buffer(clearance_m, 10)  # 10 segments per quarter circle
                else:
                    buffered = QgsGeometry(geom)  # Create a copy
                # Validate geometry
                if not buffered or buffered.isEmpty():
                    invalid_feats += 1
                    continue
                if not buffered.isGeosValid():
                    log.warning(f"Feature {processed_feats}: Invalid buffered geom. Repairing...")
                    buffered = self._repair_geometry(buffered)
                    if not buffered:
                        invalid_feats += 1
                        continue
                all_nogo_geoms.append(buffered)
            # Combine all geometries
            if not all_nogo_geoms:
                log.warning("No valid NoGo geometries to process.")
                return None
            elif len(all_nogo_geoms) == 1:
                log.debug("Single NoGo feature, no union needed.")
                final_geom = all_nogo_geoms[0]
            else:
                log.debug(f"Unioning {len(all_nogo_geoms)} geoms...")
                final_geom = QgsGeometry.unaryUnion(all_nogo_geoms)
            # Final validation
            if not final_geom or final_geom.isEmpty():
                log.error("Unary union failed.")
                return None
            if not final_geom.isGeosValid():
                log.warning("Union invalid. Repairing...")
                final_geom = self._repair_geometry(final_geom)
            if not final_geom:
                log.error("Union repair failed.")
                return None
            log.info("Successfully prepared avoidance geometry.")
            return final_geom
        except Exception as e:
            log.exception(f"Error preparing NoGo geometry: {e}")
            return None

    def _repair_geometry(self, geometry):
        """
        Attempts to repair an invalid QgsGeometry using makeValid and buffer(0).

        Args:
            geometry (QgsGeometry): The potentially invalid geometry to repair

        Returns:
            QgsGeometry or None: Repaired geometry or None if repair failed
        """
        log.debug("Attempting geometry repair...")

        if not geometry or geometry.isEmpty():
            return None

        # Try makeValid first
        try:
            valid_geom = geometry.makeValid()
            if valid_geom and not valid_geom.isEmpty() and valid_geom.isGeosValid():
                log.debug("Repaired using makeValid().")
                return valid_geom
        except Exception as e_mv:
            log.debug(f"makeValid error: {e_mv}")

        # If that fails, try buffer(0)
        try:
            log.debug("makeValid failed. Trying buffer(0)...")
            valid_geom = geometry.buffer(0, 5)  # 5 segments per quarter circle
            if valid_geom and not valid_geom.isEmpty() and valid_geom.isGeosValid():
                log.debug("Repaired using buffer(0).")
                return valid_geom
        except Exception as e_buf:
            log.debug(f"buffer(0) error: {e_buf}")

        log.warning("Geometry repair failed.")
        return None

    def _find_intersection_points(self, line_geom, avoidance_geom):
        """
        Finds intersection points between a line and an avoidance geometry.
        Args:
            line_geom (QgsGeometry): Line geometry to check
            avoidance_geom (QgsGeometry): NoGo/avoidance geometry to check against
        Returns:
            list: List of intersection points (QgsPointXY) or empty list
        """
        if not line_geom or not avoidance_geom:
            return []
        try:
            # Get intersection
            intersection = line_geom.intersection(avoidance_geom)
            if not intersection or intersection.isEmpty():
                return []
            points = []
            # Extract points from potentially complex geometry
            if intersection.type() == QgsWkbTypes.PointGeometry:
                # Single point intersection
                if intersection.isMultipart():
                    for pt in intersection.asMultiPoint():
                        points.append(QgsPointXY(pt))
                else:
                    points.append(intersection.asPoint())
            elif intersection.type() == QgsWkbTypes.LineGeometry:
                # Line intersection - use endpoints
                if intersection.isMultipart():
                    for line in intersection.asMultiPolyline():
                        for pt in line:
                            points.append(QgsPointXY(pt))
                else:
                    for pt in intersection.asPolyline():
                        points.append(QgsPointXY(pt))
            return points
        except Exception as e:
            log.exception(f"Error finding intersections: {e}")
            return []

    def _calculate_point_distances(self, point_list, line_geom):
        """
        Calculates distance along a line for each point in a list.
        Args:
            point_list (list): List of QgsPointXY objects
            line_geom (QgsGeometry): Line geometry to calculate distances along
        Returns:
            list: Sorted list of tuples (distance, point)
        """
        if not point_list or not line_geom:
            return []
        try:
            # Calculate distance for each point
            point_distances = []
            for point in point_list:
                # Project point to closest position on line
                nearest_point = line_geom.nearestPoint(QgsGeometry.fromPointXY(point))
                if nearest_point and not nearest_point.isEmpty():
                    # Get distance along line
                    dist_along = line_geom.lineLocatePoint(QgsGeometry.fromPointXY(nearest_point.asPoint()))
                    point_distances.append((dist_along, point))
            # Sort by distance along line
            point_distances.sort(key=lambda x: x[0])
            return point_distances
        except Exception as e:
            log.exception(f"Error calculating point distances: {e}")
            return []

    def _get_heading_at_distance(self, geometry, distance):
        """
        Calculates heading (0-360, CW from N) at a distance along a line using interpolation.
        Args:
            geometry (QgsGeometry): Line geometry to calculate heading on
            distance (float): Distance along the line in meters
        Returns:
            float or None: Heading in degrees or None on error
        """
        log.debug(f"Calculating heading at distance {distance:.2f}m...")
        if not geometry or geometry.isEmpty() or not is_line_type(geometry.wkbType()):
            log.warning("Invalid geom for heading calc.")
            return None
        try:
            length = geometry.length()
            if length <= GEOMETRY_PRECISION:
                log.warning("Zero-length geom for heading calc.")
                return None
            # Clamp distance to valid range
            dist_clamped = max(0.0, min(length, distance))
            # Use a small sample distance for the direction calculation
            sample_dist = max(length * 0.01, 1.0)
            # Get points before and after the target distance
            dist_before = max(0.0, dist_clamped - sample_dist/2)
            dist_after = min(length, dist_clamped + sample_dist/2)
            p_before_g = geometry.interpolate(dist_before)
            p_after_g = geometry.interpolate(dist_after)
            if not p_before_g or not p_after_g:
                log.warning(f"Failed to interpolate points for heading at dist {distance:.2f}.")
                return None
            # Get coordinates and calculate heading
            p_before = p_before_g.asPoint()
            p_after = p_after_g.asPoint()
            dx = p_after.x() - p_before.x()
            dy = p_after.y() - p_before.y()
            if abs(dx) < GEOMETRY_PRECISION and abs(dy) < GEOMETRY_PRECISION:
                log.warning(f"Interpolated points coincident near dist {distance:.2f}.")
                return None
            rad = math.atan2(dx, dy)
            heading = (math.degrees(rad) + 360) % 360
            log.debug(f"Calculated heading at distance {distance:.2f}: {heading:.1f}°")
            return heading
        except Exception as e:
            log.error(f"Error calc heading at dist {distance:.2f}: {e}")
            return None
            
    def _calculate_and_apply_deviations(self, line_data, nogo_layer, clearance_m, turn_radius_m, vessel_turn_rate_dpm=180.0):
        """
        Calculates deviations for lines that intersect with nogo zones using RRT algorithm.

        This function:
        1. Prepares nogo geometry with appropriate clearance buffer
        2. Identifies lines that intersect with nogo zones
        3. Applies RRT-based path planning to create deviation paths
        4. Updates line_data with deviated geometries or marks lines as failed

        Args:
            line_data (dict): Dictionary of line data to process
            nogo_layer (QgsVectorLayer): Layer containing nogo zones
            clearance_m (float): Clearance distance in meters
            turn_radius_m (float): Vessel turn radius in meters
            vessel_turn_rate_dpm (float): Vessel turn rate in degrees per minute

        Returns:
            dict: Updated line_data dictionary with deviation information
        """
        log.info(f"Starting deviation calculation (Clearance: {clearance_m}m, Turn Radius: {turn_radius_m}m)...")

        # Check if RRT planner is available
        if rrt_planner is None:
            log.critical("RRT Planner module is not available. Skipping deviations.")
            return line_data

        # Prepare nogo geometry with clearance buffer
        avoidance_geom = self._prepare_nogo_geometry(nogo_layer, clearance_m)
        if not avoidance_geom:
            log.warning("No avoidance geometry available. Skipping deviations.")
            return line_data

        # Try to extract boundary for more efficient intersection tests
        boundary_avoid = None
        try:
            if avoidance_geom.isMultipart():
                boundaries = [p.exteriorRing() for p in avoidance_geom.parts() 
                             if p.type() == QgsWkbTypes.PolygonGeometry and p.exteriorRing()]
                boundary_avoid = QgsGeometry.collectGeometry(boundaries) if boundaries else None
            elif avoidance_geom.type() == QgsWkbTypes.PolygonGeometry:
                boundary_avoid = QgsGeometry.fromPolyline(avoidance_geom.exteriorRing())

            if not boundary_avoid or boundary_avoid.isEmpty():
                log.warning("Could not extract simple boundary. Will use full buffer for intersections.")
        except Exception as b_ex:
            log.warning(f"Error extracting boundary: {b_ex}. Will use full buffer for intersections.")

        # Initialize counters and progress dialog
        processed_count = 0
        deviated_count = 0
        failed_count = 0
        lines_to_process = list(line_data.keys())
        total_lines = len(lines_to_process)

        progress = QProgressDialog("Generating Deviation Lines...", "Cancel", 0, total_lines, self)
        progress.setWindowModality(_QT_WINDOW_MODAL)
        progress.setMinimumDuration(500)
        progress.show()

        # Process each line
        for i, line_num in enumerate(lines_to_process):
            progress.setValue(i)
            QApplication.processEvents()

            if progress.wasCanceled():
                log.info("Deviation calculation cancelled by user.")
                break
            
            # Get line data
            data = line_data[line_num]
            original_geom = data['line_geom']
            original_length = data['length']

            # Initialize deviation flags
            data['deviated'] = False
            data['deviation_failed'] = False
            processed_count += 1

            # Skip lines that don't intersect with nogo zones
            if not original_geom or original_geom.isEmpty() or not original_geom.intersects(avoidance_geom):
                continue
            
            log.info(f"Line {line_num}: Intersects with nogo zone. Attempting RRT deviation...")

            try:
                # Use boundary if available, otherwise use full buffer
                intersect_target = boundary_avoid if boundary_avoid else avoidance_geom

                # Find intersection points between line and nogo zone
                intersection_points = self._find_intersection_points(original_geom, intersect_target)
                if not intersection_points:
                    log.warning(f"Line {line_num}: No intersection points found.")
                    data['deviation_failed'] = True
                    failed_count += 1
                    continue
                
                # Calculate distances along line for each intersection point
                point_distances = self._calculate_point_distances(intersection_points, original_geom)
                if len(point_distances) < 1:
                    log.warning(f"Line {line_num}: Failed to locate intersection points along line.")
                    data['deviation_failed'] = True
                    failed_count += 1
                    continue
                
                # Get entry and exit points for the nogo zone
                entry_dist = point_distances[0][0]
                exit_dist = point_distances[-1][0]
                log.debug(f"  Intersection span: {entry_dist:.1f}m to {exit_dist:.1f}m.")

                # Calculate start and end poses for RRT planning
                # Add offset based on turn radius for smoother transitions
                offset = 1.0 * turn_radius_m
                start_pose_dist = max(0.0, entry_dist - offset)
                end_pose_dist = min(original_length, exit_dist + offset)

                # Handle edge cases where start and end are too close
                if start_pose_dist >= end_pose_dist - GEOMETRY_PRECISION:
                    log.warning(f"Line {line_num}: Invalid RRT pose order. Using minimal separation.")
                    start_pose_dist = max(0.0, entry_dist - GEOMETRY_PRECISION)
                    end_pose_dist = min(original_length, exit_dist + GEOMETRY_PRECISION)

                if start_pose_dist >= end_pose_dist:
                    log.error(f"Line {line_num}: Cannot define RRT poses with valid separation.")
                    data['deviation_failed'] = True
                    failed_count += 1
                    continue
                
                # Interpolate start and end points along the line
                start_p_g = original_geom.interpolate(start_pose_dist)
                end_p_g = original_geom.interpolate(end_pose_dist)

                if start_p_g.isEmpty() or end_p_g.isEmpty():
                    log.error(f"Line {line_num}: Failed to interpolate RRT points.")
                    data['deviation_failed'] = True
                    failed_count += 1
                    continue
                
                # Convert geometries to points
                start_p = start_p_g.asPoint()
                end_p = end_p_g.asPoint()

                # Calculate headings at start and end points
                start_h_qgis = self._get_heading_at_distance(original_geom, start_pose_dist)
                end_h_qgis = self._get_heading_at_distance(original_geom, end_pose_dist)

                if start_h_qgis is None or end_h_qgis is None:
                    log.error(f"Line {line_num}: Failed to calculate RRT headings.")
                    data['deviation_failed'] = True
                    failed_count += 1
                    continue
                
                # Convert QGIS headings to RRT format (radians, different reference frame)
                start_h_rrt = math.radians((90.0 - start_h_qgis + 360.0) % 360.0)
                end_h_rrt = math.radians((90.0 - end_h_qgis + 360.0) % 360.0)

                # Create pose tuples for RRT
                start_pose = (start_p.x(), start_p.y(), start_h_rrt)
                end_pose = (end_p.x(), end_p.y(), end_h_rrt)

                log.debug(f"  RRT Start: ({start_pose[0]:.1f}, {start_pose[1]:.1f}) "
                         f"Heading: {math.degrees(start_pose[2]):.1f}° | "
                         f"End: ({end_pose[0]:.1f}, {end_pose[1]:.1f}) "
                         f"Heading: {math.degrees(end_pose[2]):.1f}°")

                # Prepare RRT parameters
                rrt_params = {}

                # Add any RRT-specific parameters from sim_params if available
                for param_name in ['step_size', 'max_iterations', 'goal_bias']:
                    param_key = f'rrt_{param_name}'
                    if param_key in line_data.get('sim_params', {}):
                        rrt_params[param_name] = line_data['sim_params'][param_key]

                # Call RRT planner to generate deviation path
                deviation_segment = rrt_planner.find_rrt_path(
                    start_pose, end_pose, [avoidance_geom], turn_radius_m, **rrt_params)

                # Process RRT result
                if deviation_segment and not deviation_segment.isEmpty() and deviation_segment.isGeosValid():
                    log.info(f"Line {line_num}: RRT Success (Length: {deviation_segment.length():.1f}m). Assembling final path...")

                    try:
                        # Extract geometry before and after the deviation using our custom method
                        geom_before = self._extract_line_segment(original_geom, 0, start_pose_dist)
                        geom_after = self._extract_line_segment(original_geom, end_pose_dist, original_length)

                        # Combine geometries to create the final path
                        combined = [g for g in [geom_before, deviation_segment, geom_after] 
                                   if g and not g.isEmpty()]
                        final_geom = QgsGeometryUtils.mergeLines(combined)

                        # Validate final geometry
                        if not final_geom or final_geom.isEmpty() or not is_line_type(final_geom.wkbType()):
                            log.error(f"Line {line_num}: Failed to merge geometries.")
                            data['deviation_failed'] = True
                            failed_count += 1
                            continue
                        
                        # Verify that final path doesn't intersect nogo zones
                        if final_geom.intersects(avoidance_geom):
                            log.warning(f"Line {line_num}: Final path still intersects nogo zones!")
                            data['deviation_failed'] = True
                            failed_count += 1
                            continue
                        
                        # Update line data with deviated path
                        new_length = final_geom.length()
                        data['line_geom'] = final_geom
                        data['length'] = max(0.0, new_length)

                        # Update start and end points
                        if hasattr(final_geom, 'asPolyline'):
                            new_vertices = final_geom.asPolyline()
                            data['start_point_geom'] = QgsPoint(new_vertices[0])
                            data['end_point_geom'] = QgsPoint(new_vertices[-1])
                        else:
                            log.warning(f"Line {line_num}: Could not extract vertices from deviated path.")

                        # Mark as successfully deviated
                        data['deviated'] = True
                        deviated_count += 1
                        log.info(f"Line {line_num}: Deviation applied (New Length: {data['length']:.1f}m).")

                    except Exception as e:
                        log.exception(f"Line {line_num}: Error during geometry assembly: {e}")
                        data['deviation_failed'] = True
                        failed_count += 1
                        data['line_geom'] = original_geom  # Restore original geometry on error
                else:
                    log.warning(f"Line {line_num}: RRT planner failed to find a valid path.")
                    data['deviation_failed'] = True
                    failed_count += 1

            except Exception as dev_err:
                log.exception(f"Line {line_num}: Error during RRT deviation: {dev_err}")
                data['deviation_failed'] = True
                failed_count += 1
                data['line_geom'] = original_geom  # Restore original geometry on error

        # Cleanup and final reporting
        progress.setValue(total_lines)
        progress.deleteLater()

        log.info(f"Deviation calculation complete. Processed: {processed_count}, "
                f"Deviated: {deviated_count}, Failed: {failed_count}")

        if failed_count > 0:
            QMessageBox.warning(self, "Deviation Failures", 
                              f"{failed_count} line(s) failed deviation and will be excluded from simulation.")

        return line_data

    def _prepare_avoidance_geometry(self, nogo_layer, clearance_m, preserve_individual=False):
        """
        Prepares buffered geometry representing NoGo zones.
        Args:
            nogo_layer: The layer containing NoGo zones
            clearance_m: Buffer distance in meters
            preserve_individual: If True, returns a list of individual obstacle geometries;
                               If False, returns a single combined geometry (default behavior)
        Returns:
            If preserve_individual=False: QgsGeometry or None
            If preserve_individual=True: List of QgsGeometry objects or None
        """
        log.debug(f"Preparing NoGo geometry with clearance {clearance_m}m")
        if not nogo_layer or not nogo_layer.isValid():
            log.warning("No valid No-Go layer provided.")
            return None

        all_buffered_geoms = []
        processed_feats = 0
        invalid_input_feats = 0
        buffer_failures = 0
        feature_request = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoFlags) # Need geometry

        # Progress for potentially long buffering
        progress = QProgressDialog("Buffering NoGo Zones...", "Cancel", 0, nogo_layer.featureCount(), self)
        progress.setWindowModality(_QT_WINDOW_MODAL)
        progress.setMinimumDuration(500)

        try:
            for i, feat in enumerate(nogo_layer.getFeatures(feature_request)):
                if progress.wasCanceled():
                    raise UserCancelException("Buffering cancelled.")
                progress.setValue(i)

                geom = feat.geometry()
                if not geom or geom.isEmpty():
                    invalid_input_feats += 1
                    continue

                # Repair input geometry if necessary
                if not geom.isGeosValid():
                    log.debug(f"Repairing invalid input geometry for feature {feat.id()}")
                    geom = self._repair_geometry(geom)
                    if not geom:
                        invalid_input_feats += 1
                        continue # Repair failed

                # Apply buffer
                buffered_geom = geom.buffer(clearance_m, 10) # 10 segments per quarter circle

                if not buffered_geom or buffered_geom.isEmpty():
                    log.warning(f"Buffering failed for feature {feat.id()}")
                    buffer_failures += 1
                    continue

                # Repair buffered geometry if necessary
                if not buffered_geom.isGeosValid():
                    log.debug(f"Repairing invalid buffered geometry for feature {feat.id()}")
                    buffered_geom = self._repair_geometry(buffered_geom)
                    if not buffered_geom:
                        buffer_failures += 1
                        continue # Repair failed

                all_buffered_geoms.append(buffered_geom)
                processed_feats += 1

            progress.setValue(nogo_layer.featureCount())

            if invalid_input_feats > 0:
                log.warning(f"Skipped {invalid_input_feats} invalid input NoGo features.")
            if buffer_failures > 0:
                log.warning(f"Encountered {buffer_failures} buffer/repair failures.")

            if not all_buffered_geoms:
                log.warning("No valid buffered NoGo geometries generated.")
                QMessageBox.warning(self,"NoGo Preparation", "No valid NoGo zones found or buffering failed.")
                return None

            # Return individual geometries or combined geometry based on the preserve_individual flag
            if preserve_individual:
                # Return the list of individual buffered geometries
                if not all_buffered_geoms:
                    return None
                
                log.info(f"Successfully prepared {len(all_buffered_geoms)} individual avoidance geometries from {processed_feats} features.")
                return all_buffered_geoms
            else:
                # Combine all buffered geometries using unaryUnion (original behavior)
                log.debug(f"Combining {len(all_buffered_geoms)} buffered geometries...")
                progress.setLabelText("Combining buffered zones...")
                QApplication.processEvents() # Update UI

                final_avoidance_geom = QgsGeometry.unaryUnion(all_buffered_geoms)

                if not final_avoidance_geom or final_avoidance_geom.isEmpty():
                    log.error("Failed to combine buffered NoGo zones.")
                    QMessageBox.critical(self, "Error", "Failed to combine buffered NoGo zones.")
                    return None

                # Final validation and repair
                if not final_avoidance_geom.isGeosValid():
                    log.warning("Combined avoidance geometry is invalid, attempting repair...")
                    final_avoidance_geom = self._repair_geometry(final_avoidance_geom)
                    if not final_avoidance_geom:
                        log.error("Repair of combined avoidance geometry failed.")
                        QMessageBox.critical(self,"Error", "Repair of combined avoidance geometry failed.")
                        return None

                log.info(f"Successfully prepared combined avoidance geometry from {processed_feats} features.")
                return final_avoidance_geom
                
        except Exception as e:
            log.exception(f"Error preparing NoGo avoidance geometry: {e}")
            QMessageBox.critical(self, "Error", f"Failed to prepare NoGo zones for analysis:\n{e}")
            return None
        finally:
            # Close progress dialog
            if progress:
                progress.setValue(nogo_layer.featureCount())

    def _separate_avoidance_geometry(self, geometry, max_distance=500):
        """
        Breaks a single MultiPolygon geometry into separate obstacle geometries based on spatial proximity.
        
        Args:
            geometry: The input geometry (usually a MultiPolygon)
            max_distance: Maximum distance (in map units) to consider geometries as part of the same obstacle cluster
            
        Returns:
            List of QgsGeometry objects, each representing a distinct obstacle
        """
        if not geometry:
            return []
        
        log.debug(f"Separating avoidance geometry of type {geometry.wkbType()} into distinct obstacles")
        
        # If it's already a single polygon, return it as a list with one item
        if geometry.wkbType() == QgsWkbTypes.Polygon:
            return [geometry]
            
        # For MultiPolygon, extract individual polygons
        individual_geometries = []
        
        if geometry.wkbType() == QgsWkbTypes.MultiPolygon:
            # Get geometry parts using QGIS API methods
            multi_geom = geometry.constGet()
            for i in range(multi_geom.numGeometries()):
                single_geom = QgsGeometry(multi_geom.geometryN(i).clone())
                if single_geom and not single_geom.isEmpty():
                    individual_geometries.append(single_geom)
        else:
            # If it's not a MultiPolygon but still a valid geometry, treat it as a single obstacle
            individual_geometries = [geometry]
            
        log.debug(f"Extracted {len(individual_geometries)} individual polygons from input geometry")
        
        # If we only have 0 or 1 geometry, no need for clustering
        if len(individual_geometries) <= 1:
            return individual_geometries
            
        # Perform spatial clustering based on distance
        clusters = []
        remaining = individual_geometries.copy()
        
        while remaining:
            # Start a new cluster with the first geometry
            current_cluster = [remaining.pop(0)]
            cluster_changed = True
            
            # Keep expanding the cluster while we can add geometries to it
            while cluster_changed:
                cluster_changed = False
                current_union = QgsGeometry.unaryUnion(current_cluster)
                
                # Check each remaining geometry
                i = 0
                while i < len(remaining):
                    # If this geometry is within max_distance of our cluster, add it
                    if current_union.distance(remaining[i]) <= max_distance:
                        current_cluster.append(remaining.pop(i))
                        cluster_changed = True
                    else:
                        i += 1
            
            # Add the completed cluster to our list and continue with remaining geometries
            if current_cluster:
                clusters.append(QgsGeometry.unaryUnion(current_cluster))
                
        log.info(f"Spatial clustering identified {len(clusters)} distinct obstacle groups")
        return clusters

    def _split_geometry_at_distances(self, line_geom, dist1, dist2):
        """
        Splits a line geometry into three parts at two specified distances using interpolate_vl.
        Returns (geom_before, geom_middle, geom_after) or (None, None, None).
        Ensures dist1 < dist2.
        """
        if not line_geom or line_geom.isEmpty() or not is_line_type(line_geom.wkbType()):
            log.error("Invalid input geometry for splitting.")
            return None, None, None

        line_length = line_geom.length()
        if line_length < 1e-6: # Avoid issues with zero-length lines
             log.warning("Cannot split zero-length geometry.")
             return None, None, None


        # Clamp distances and ensure order
        d1 = max(0.0, min(dist1, line_length))
        d2 = max(0.0, min(dist2, line_length))

        if d1 >= d2 - 1e-9: # Use tolerance for float comparison
            log.warning(f"Split distances are too close or invalid (d1={d1}, d2={d2}). Returning original geometry as 'before'.")
            # Return the original geometry as the 'before' part, and None for the others
            return QgsGeometry(line_geom), None, None


        try:
            # Use interpolate_vl which returns a list of points along the line
            # We need to create LineString geometries from these points
            
            # Extract all vertices to a list first to avoid QgsVertexIterator len() error
            vertex_list = []
            vertices_iter = line_geom.vertices()
            while vertices_iter.hasNext():
                vertex_list.append(vertices_iter.next())
            
            if len(vertex_list) < 2:
                log.warning("Not enough vertices in line geometry for splitting.")
                return None, None, None

            # Part 1: from start to dist1
            points_before = []
            current_dist = 0.0
            for i in range(len(vertex_list) - 1):
                p1 = vertex_list[i]
                p2 = vertex_list[i + 1]
                segment_len = math.sqrt(p1.sqrDist(p2))
                if current_dist <= d1:
                    points_before.append(QgsPointXY(p1)) # Always add the start point of the segment
                    if current_dist + segment_len > d1:
                        # This segment contains d1, interpolate
                        fraction = (d1 - current_dist) / segment_len
                        interp_x = p1.x() + fraction * (p2.x() - p1.x())
                        interp_y = p1.y() + fraction * (p2.y() - p1.y())
                        points_before.append(QgsPointXY(interp_x, interp_y))
                        break # We have reached d1
                else:
                    break # We are past d1
                current_dist += segment_len
            geom_before = QgsGeometry.fromPolylineXY(points_before) if len(points_before) >= 2 else QgsGeometry()

            # Part 2: from dist1 to dist2
            points_middle = []
            current_dist = 0.0
            started_middle = False
            for i in range(len(vertex_list) - 1):
                p1 = vertex_list[i]
                p2 = vertex_list[i + 1]
                segment_len = math.sqrt(p1.sqrDist(p2))
                segment_end_dist = current_dist + segment_len

                # If the start distance is within this segment
                if not started_middle and current_dist <= d1 < segment_end_dist:
                    fraction_start = (d1 - current_dist) / segment_len
                    start_x = p1.x() + fraction_start * (p2.x() - p1.x())
                    start_y = p1.y() + fraction_start * (p2.y() - p1.y())
                    points_middle.append(QgsPointXY(start_x, start_y))
                    started_middle = True

                # If the end distance is within this segment
                if started_middle and current_dist <= d2 < segment_end_dist:
                    fraction_end = (d2 - current_dist) / segment_len
                    end_x = p1.x() + fraction_end * (p2.x() - p1.x())
                    end_y = p1.y() + fraction_end * (p2.y() - p1.y())
                    points_middle.append(QgsPointXY(end_x, end_y))
                    break # Finished the middle part

                # If the entire segment is within the middle range
                if started_middle and segment_end_dist <= d2:
                     # Ensure we don't add duplicate points if start_dist was exactly at a vertex
                     if not points_middle or points_middle[-1].compare(QgsPointXY(p2), 0.0001) != 0:
                        points_middle.append(QgsPointXY(p2))

                current_dist += segment_len

            geom_middle = QgsGeometry.fromPolylineXY(points_middle) if len(points_middle) >= 2 else QgsGeometry()

            # Part 3: from dist2 to end
            points_after = []
            current_dist = 0.0
            started_after = False
            for i in range(len(vertex_list) - 1):
                p1 = vertex_list[i]
                p2 = vertex_list[i + 1]
                segment_len = math.sqrt(p1.sqrDist(p2))
                segment_end_dist = current_dist + segment_len

                # Find the start of the 'after' segment
                if not started_after and current_dist <= d2 < segment_end_dist:
                    fraction_start = (d2 - current_dist) / segment_len
                    start_x = p1.x() + fraction_start * (p2.x() - p1.x())
                    start_y = p1.y() + fraction_start * (p2.y() - p1.y())
                    points_after.append(QgsPointXY(start_x, start_y))
                    started_after = True

                # Add the rest of the vertices
                if started_after and i < len(vertex_list) - 1:
                    if not points_after or points_after[-1].compare(QgsPointXY(p2), 0.0001) != 0:
                        points_after.append(QgsPointXY(p2))

                current_dist += segment_len

            # Add the last vertex if we haven't already
            if started_after and vertex_list and len(points_after) > 0:
                last_vertex = vertex_list[-1]
                if not points_after[-1].compare(QgsPointXY(last_vertex), 0.0001) == 0:
                    points_after.append(QgsPointXY(last_vertex))

            geom_after = QgsGeometry.fromPolylineXY(points_after) if len(points_after) >= 2 else QgsGeometry()

            return geom_before, geom_middle, geom_after
        except Exception as e:
            log.exception(f"Error splitting geometry at distances: {e}")
            return None, None, None
            
    def _merge_geometries(self, geom_list):
        """
        Merges a list of line geometries into a single line geometry.
        
        Args:
            geom_list (list): List of QgsGeometry objects to merge
            
        Returns:
            QgsGeometry: Merged line geometry or None if merge fails
        """
        if not geom_list:
            return None
            
        # Filter out empty geometries
        valid_geoms = [g for g in geom_list if g and not g.isEmpty() and is_line_type(g.wkbType())]
        
        if not valid_geoms:
            return None
            
        if len(valid_geoms) == 1:
            return QgsGeometry(valid_geoms[0])
            
        try:
            # Create a list of points from all geometries
            all_points = []
            for geom in valid_geoms:
                points = []
                vertices = geom.vertices()
                while vertices.hasNext():
                    point = vertices.next()
                    points.append(QgsPointXY(point))
                    
                if points:
                    if not all_points:
                        # First geometry - add all points
                        all_points.extend(points)
                    else:
                        # Check if the first point of this geometry is close to the last point of our accumulated points
                        if points[0].compare(all_points[-1], 0.0001) == 0:
                            # Skip first point to avoid duplicates, add the rest
                            all_points.extend(points[1:])
                        else:
                            # Geometries don't connect, add a warning but still try to merge
                            log.warning("Merging discontinuous geometries - result may have jumps.")
                            all_points.extend(points)
                        
            # Create a new geometry from the combined points
            if len(all_points) >= 2:
                return QgsGeometry.fromPolylineXY(all_points)
            else:
                log.warning("Not enough points to create a valid line geometry after merging.")
                return None
                
        except Exception as e:
            log.exception(f"Error merging geometries: {e}")
            return None

    def _add_deviation_fields(self, lines_layer):
        """
        Add the required fields for deviation tracking to the lines layer.

        Args:
            lines_layer (QgsVectorLayer): The layer to add fields to

        Returns:
            bool: True if successful, False otherwise
        """
        if not lines_layer or not lines_layer.isValid():
            log.error("Invalid layer provided to _add_deviation_fields")
            return False

        log.debug(f"Adding deviation tracking fields to layer '{lines_layer.name()}'")

        provider = lines_layer.dataProvider()
        fields_to_add = []

        # Check which fields are already present
        existing_fields = [field.name() for field in lines_layer.fields()]

        if "is_conflicted" not in existing_fields:
            fields_to_add.append(QgsField("is_conflicted", QVariant.Bool))

        if "is_deviation_created" not in existing_fields:
            fields_to_add.append(QgsField("is_deviation_created", QVariant.Bool))

        if "is_line_merged" not in existing_fields:
            fields_to_add.append(QgsField("is_line_merged", QVariant.Bool))

        if "Length_m" not in existing_fields:
            fields_to_add.append(QgsField("Length_m", QVariant.Double, "double", 10, 2))

        # Add fields if any need to be added
        if fields_to_add:
            if not provider.addAttributes(fields_to_add):
                log.error(f"Failed to add fields: {provider.lastError()}")
                return False

            # Update layer fields
            lines_layer.updateFields()

            # Initialize all instances of new boolean fields to False
            features = lines_layer.getFeatures()
            fld_conflicted_idx = lines_layer.dataProvider().fieldNameIndex("is_conflicted")
            fld_created_idx = lines_layer.dataProvider().fieldNameIndex("is_deviation_created")
            fld_merged_idx = lines_layer.dataProvider().fieldNameIndex("is_line_merged")

            attr_map = {}
            for feature in features:
                attrs = {}
                if fld_conflicted_idx >= 0:
                    attrs[fld_conflicted_idx] = False
                if fld_created_idx >= 0:
                    attrs[fld_created_idx] = False
                if fld_merged_idx >= 0:
                    attrs[fld_merged_idx] = False

                if attrs:
                    attr_map[feature.id()] = attrs

            if attr_map:
                if not provider.changeAttributeValues(attr_map):
                    log.warning("Failed to initialize boolean field values to False")

            log.info(f"Added {len(fields_to_add)} deviation tracking fields to layer.")
            return True
        else:
            log.info("All required deviation fields already exist.")
            return True

    def _calculate_and_apply_deviations_v2(self, lines_layer, nogo_layer, clearance_m, turn_radius_m, debug_mode=False):
        """
        Core logic for calculating and applying deviations using the Peak/Tangent approach.

        Args:
            lines_layer (QgsVectorLayer): Layer containing the survey lines
            nogo_layer (QgsVectorLayer): Layer containing the NoGo zones
            clearance_m (float): Clearance distance in meters
            turn_radius_m (float): Minimum turning radius for the vessel in meters
            debug_mode (bool): If True, enables extensive debugging logs

        Returns:
            bool: True if calculation was successful, False otherwise
        """
        success_flag = True # Assume success unless something fails critically
        project = QgsProject.instance()

        # Store calculation results for visualization
        self.all_reference_lines = {}
        self.all_peaks = {}

        # Initialize progress variable at the beginning to avoid UnboundLocalError
        progress = None

        # --- Phase 1: Preparation ---
        if not self._add_deviation_fields(lines_layer):
            QMessageBox.critical(self, "Setup Error", "Failed to add required deviation fields to the lines layer.")
            return False

        # Start editing the lines layer if not already in editing mode
        edit_started_here = False
        if not lines_layer.isEditable():
            if not lines_layer.startEditing():
                 return False
            edit_started_here = True
            log.debug(f"Started editing layer: {lines_layer.name()}")

        try:
            # --- PREPARE FIELDS ---
            # Get full field details for better error diagnosis
            if debug_mode:
                field_names = [field.name() for field in lines_layer.fields()]
                log.debug(f"Available fields in layer: {', '.join(field_names)}")

            log.debug("Initializing deviation fields...")
            fld_conflicted_idx = lines_layer.dataProvider().fieldNameIndex("is_conflicted")
            fld_created_idx = lines_layer.dataProvider().fieldNameIndex("is_deviation_created")
            fld_merged_idx = lines_layer.dataProvider().fieldNameIndex("is_line_merged")
            fld_length_idx = lines_layer.dataProvider().fieldNameIndex("Length_m")

            # Detailed logging of field indices
            if debug_mode:
                log.debug(f"Field indices: is_conflicted={fld_conflicted_idx}, " +
                          f"is_deviation_created={fld_created_idx}, " +
                          f"is_line_merged={fld_merged_idx}, " +
                          f"Length_m={fld_length_idx}")

            # Double-check that fields are present
            if -1 in [fld_conflicted_idx, fld_created_idx, fld_merged_idx, fld_length_idx]:
                still_missing = [name for name, idx in zip(
                    ["is_conflicted", "is_deviation_created", "is_line_merged", "Length_m"],
                    [fld_conflicted_idx, fld_created_idx, fld_merged_idx, fld_length_idx]
                ) if idx == -1]
                raise ValueError(f"Required fields still missing after adding: {', '.join(still_missing)}")

            # Initialize values for tracking fields
            log.debug("Resetting deviation fields to initial values...")
            init_attrs = {}

            features = lines_layer.getFeatures()
            attr_map = {}
            provider = lines_layer.dataProvider()

            for feature in features:
                attrs = {}
                if fld_conflicted_idx >= 0:
                    attrs[fld_conflicted_idx] = False
                if fld_created_idx >= 0:
                    attrs[fld_created_idx] = False
                if fld_merged_idx >= 0:
                    attrs[fld_merged_idx] = False

                if attrs:
                    attr_map[feature.id()] = attrs

            if attr_map:
                for fid, attrs in attr_map.items():
                    for field_idx, value in attrs.items():
                        lines_layer.changeAttributeValue(fid, field_idx, value)

            log.debug("Deviation fields initialized.")

            # --- PREPARE AVOIDANCE GEOMETRY ---
            log.debug(f"Preparing avoidance geometry with clearance {clearance_m}m...")
            avoidance_geom = self._prepare_avoidance_geometry(nogo_layer, clearance_m)

            if not avoidance_geom:
                log.error("Failed to prepare avoidance geometry. Aborting deviation calculation.")
                raise ValueError("Failed to prepare avoidance geometry.") # Raise exception to trigger rollback

            if debug_mode:
                log.debug(f"Avoidance geometry type: {avoidance_geom.type()}, " +
                          f"Geometry is valid: {avoidance_geom.isGeosValid()}, " +
                          f"Is multipart: {avoidance_geom.isMultipart()}")

            # Separate the geometry into distinct components by using spatial clustering
            log.debug("Separating avoidance geometry into distinct obstacles...")
            obstacle_geometries = self._separate_avoidance_geometry(avoidance_geom)

            if not obstacle_geometries:
                log.error("Failed to separate avoidance geometry into obstacles. Aborting.")
                raise ValueError("Failed to separate avoidance geometry into obstacles.")

            if debug_mode:
                log.debug(f"Identified {len(obstacle_geometries)} distinct obstacle geometries")
                for i, geom in enumerate(obstacle_geometries):
                    log.debug(f"Obstacle {i}: Valid: {geom.isGeosValid()}, " +
                             f"Type: {geom.type()}, Area: {geom.area():.2f}")

            # --- IDENTIFY CONFLICTS & GROUP ---
            log.debug("Identifying conflicted lines...")
            conflicted_lines_info = [] # List of (fid, line_geom, line_num, heading)
            fld_linenum = lines_layer.fields().lookupField("LineNum")
            fld_heading = lines_layer.fields().lookupField("Heading")

            # Use a spatial request to quickly find candidates
            log.debug("Building spatial index for conflict detection...")
            # FIX: Do not use NoGeometry, as the spatial index needs real geometry
            request_geom = QgsFeatureRequest().setSubsetOfAttributes(
                ["LineNum", "Heading"], lines_layer.fields()
            )

            log.debug("Creating spatial index from line features...")
            all_features = {}
            idx = QgsSpatialIndex()
            for feat in lines_layer.getFeatures(request_geom):
                if feat.hasGeometry() and not feat.geometry().isNull():
                    all_features[feat.id()] = feat
                    idx.insertFeature(feat)

            # Use spatial index to quickly find potential conflicts
            log.debug("Using spatial index to find potential conflicts...")
            candidate_ids = idx.intersects(avoidance_geom.boundingBox())
            log.debug(f"Found {len(candidate_ids)} potential candidates using spatial index")

            # Detailed intersection check for candidates
            conflicted_fids = {}
            for fid in candidate_ids:
                feat = all_features.get(fid)
                if not feat: continue
                geom = feat.geometry()

                if not geom or geom.isEmpty():
                    continue

                if geom.intersects(avoidance_geom):
                    conflicted_fids[fid] = True

                    # Get LineNum and Heading for this feature if available
                    if fld_linenum >= 0 and fld_heading >= 0:
                        # FIX: Use str() to avoid crashes on duplicates (e.g., "1001_1")
                        line_num_val = feat.attribute(fld_linenum)
                        line_num = str(line_num_val) if line_num_val is not None and line_num_val != NULL else str(fid)
                        heading_val = feat.attribute(fld_heading)
                        
                        heading_float = None
                        if heading_val is not None and heading_val != NULL:
                            try:
                                heading_float = float(heading_val)
                            except (ValueError, TypeError):
                                pass
                                
                        if heading_float is None:
                            heading_float = self._calculate_geom_heading(geom)
                            if heading_float is None:
                                heading_float = 0.0

                        conflicted_lines_info.append((fid, QgsGeometry(geom), line_num, heading_float))
                    else:
                        log.warning(f"Missing LineNum or Heading for FID {fid}. Skipping.")

            if not conflicted_lines_info:
                log.info("No survey lines conflict with the avoidance zones.")
                if edit_started_here: lines_layer.commitChanges()
                return True

            log.info(f"Found {len(conflicted_lines_info)} conflicted lines.")

            # Mark conflicted lines via attribute update
            if conflicted_fids:
                log.debug("Marking conflicted lines in attribute table...")
                for fid in conflicted_fids.keys():
                    lines_layer.changeAttributeValue(fid, fld_conflicted_idx, True)

            # --- GROUPING LOGIC WITH MULTIPLE OBSTACLE SUPPORT ---
            # Group conflicted lines by which obstacle they intersect
            log.debug("Grouping conflicted lines by obstacle...")
            obstacle_groups = {}  # Dictionary of obstacle_idx -> list of conflicted lines for that obstacle

            # First, sort conflicted lines by LineNum for each group
            conflicted_lines_info.sort(key=lambda item: item[2])

            # Create a mapping of which lines intersect with which obstacles
            if len(obstacle_geometries) > 1:
                log.info(f"Processing {len(obstacle_geometries)} distinct obstacles - grouping lines by obstacle")

                # For each line, check which obstacles it intersects
                for line_idx, (fid, line_geom, line_num, heading) in enumerate(conflicted_lines_info):
                    # Track which obstacles this line intersects
                    line_obstacles = []

                    for obs_idx, obs_geom in enumerate(obstacle_geometries):
                        if line_geom.intersects(obs_geom):
                            if obs_idx not in obstacle_groups:
                                obstacle_groups[obs_idx] = []
                            obstacle_groups[obs_idx].append((fid, line_geom, line_num, heading, line_idx))
                            line_obstacles.append(obs_idx)

                    log.debug(f"Line {line_num} intersects obstacles: {line_obstacles}")
            else:
                # Just one obstacle - put all lines in the same group
                obstacle_groups[0] = [(fid, line_geom, line_num, heading, idx) 
                                     for idx, (fid, line_geom, line_num, heading) in enumerate(conflicted_lines_info)]
                log.info("Single obstacle detected - all lines in same group")

            # Store the results for later visualization
            # This allows the handle_calculate_deviations method to access these
            # for visualization without recomputing
            self.conflicted_lines_info = conflicted_lines_info
            self.obstacle_groups = obstacle_groups
            self.obstacle_centers = {}

            # STEP 1: Calculate the middle line for each obstacle group
            log.debug("Identifying middle reference lines for each obstacle...")
            middle_lines = {}
            for obs_idx, group_lines in obstacle_groups.items():
                if not group_lines:
                    continue

                # Sort by LineNum (should already be sorted, but ensure it)
                group_lines.sort(key=lambda x: x[2])

                # Use median approach to find middle line
                median_idx = len(group_lines) // 2
                middle_fid, middle_geom, middle_num, middle_heading, orig_idx = group_lines[median_idx]

                # Store middle line info for this obstacle
                middle_lines[obs_idx] = {
                    'fid': middle_fid,
                    'geom': middle_geom,
                    'num': middle_num,
                    'heading': middle_heading,
                    'idx': orig_idx
                }

                # Store the obstacle geometry for visualization
                middle_lines[obs_idx]['obstacle_geom'] = obstacle_geometries[obs_idx]

                log.info(f"Obstacle {obs_idx}: Middle reference line identified: {middle_num} at index {orig_idx}")

            # If no obstacles had valid lines, this is an error
            if not middle_lines:
                log.error("Failed to identify any middle reference lines across all obstacles.")
                raise RuntimeError("No valid middle reference lines could be identified.")

            # Process each obstacle independently with its own middle reference line
            log.info(f"Processing {len(middle_lines)} obstacles with separate reference lines")

            # Store original values for future enhancements and visualization
            for obs_idx, middle_line_info in middle_lines.items():
                middle_line_num = middle_line_info['num']
                middle_line_geom = middle_line_info['geom']
                middle_line_heading = middle_line_info['heading']
                middle_line_index = middle_line_info['idx']
                obstacle_geom = middle_line_info.get('obstacle_geom')

                # Store reference information for this obstacle
                self.all_reference_lines[obs_idx] = {
                    'num': middle_line_num,
                    'geom': middle_line_geom,
                    'heading': middle_line_heading,
                    'group_lines': obstacle_groups[obs_idx],
                    'obstacle_geom': obstacle_geom
                }

                # STEP 2: Store the obstacle center (Find Obstacle Center Point)
                if obstacle_geom:
                    self.obstacle_centers[obs_idx] = obstacle_geom.centroid().asPoint()

                log.info(f"Obstacle {obs_idx}: Using middle line {middle_line_num} as reference")

            # For centroid calculation (used in various places later)
            avoidance_centroid_geom = avoidance_geom.centroid()
            if not avoidance_centroid_geom or avoidance_centroid_geom.isEmpty():
                log.error("Cannot calculate avoidance zone centroid.")
                raise RuntimeError("Cannot calculate avoidance zone centroid.") # Raise exception for rollback
            avoidance_centroid_point = avoidance_centroid_geom.asPoint() # QgsPoint

            # Log midpoint distances for debugging (kept for backward compatibility)
            log.debug("Calculating midpoint distances to centroid for conflicted lines:")
            for idx, (fid, geom, num, head) in enumerate(conflicted_lines_info):
                midpoint_geom = geom.interpolate(geom.length() / 2.0)
                if not midpoint_geom or not midpoint_geom.isEmpty():
                    midpoint_point = midpoint_geom.asPoint() # QgsPoint
                    dist_sq = midpoint_point.sqrDist(avoidance_centroid_point)
                    log.debug(f"  Line {num}: Midpoint ({midpoint_point.x():.1f}, {midpoint_point.y():.1f}), DistSq = {dist_sq:.2f}")

            # STEPS 3-4: Calculate Peak Points A and B for each obstacle using perpendicular rays
            for obs_idx, ref_line in self.all_reference_lines.items():
                middle_line_geom = ref_line['geom']
                middle_line_heading = ref_line['heading']

                # Calculate the peaks for this obstacle
                # Use the center of the obstacle instead of midpoint of the line
                obstacle_geom = obstacle_geometries[obs_idx]
                obstacle_centroid = obstacle_geom.centroid()
                mid_pt = obstacle_centroid.asPoint() # Get the center point of the obstacle
                mid_point_xy = QgsPointXY(mid_pt) # Convert to QgsPointXY for distance calculation

                log.debug(f"Using obstacle center at ({mid_pt.x():.1f}, {mid_pt.y():.1f}) for perpendicular rays")
                middle_line_heading_rad = math.radians(middle_line_heading)
                perp_angle_rad_A = middle_line_heading_rad + math.pi / 2.0
                perp_angle_rad_B = middle_line_heading_rad - math.pi / 2.0

                # Use the obstacle boundary to find intersections with perpendicular rays
                try:
                    # For polygon, the boundary would be the exterior ring - we can convert to a line
                    obstacle_boundary = None
                    if obstacle_geom.type() == QgsWkbTypes.PolygonGeometry:
                        if obstacle_geom.isMultipart():
                            # For multipolygon, use the part with largest area
                            multi_polygon = obstacle_geom.asMultiPolygon()
                            if multi_polygon:
                                # Find the largest polygon by area
                                largest_idx = 0
                                largest_area = 0
                                for i, polygon in enumerate(multi_polygon):
                                    temp_geom = QgsGeometry.fromPolygonXY(polygon)
                                    area = temp_geom.area()
                                    if area > largest_area:
                                        largest_area = area
                                        largest_idx = i

                                # Get the exterior ring of the largest polygon
                                if multi_polygon[largest_idx]:
                                    exterior_ring = multi_polygon[largest_idx][0]  # First ring is exterior
                                    obstacle_boundary = QgsGeometry.fromPolylineXY(exterior_ring)
                        else:
                            # Single polygon
                            polygon = obstacle_geom.asPolygon()
                            if polygon and polygon[0]:  # Check if polygon has rings
                                exterior_ring = polygon[0]  # First ring is exterior
                                obstacle_boundary = QgsGeometry.fromPolylineXY(exterior_ring)
                    elif obstacle_geom.type() == QgsWkbTypes.LineGeometry:
                        # If it's already a line, use it directly
                        obstacle_boundary = obstacle_geom
                    else:
                        # For other types, just use the original geometry
                        obstacle_boundary = obstacle_geom

                except (ValueError, IndexError, AttributeError) as e:
                    log.warning(f"Could not extract boundary properly: {e}")
                    # Fallback to using the original geometry
                    obstacle_boundary = obstacle_geom

                log.debug(f"Successfully extracted boundary for obstacle {obs_idx}")

                # Create a ray extending from midpoint in perpendicular directions (longer than needed to ensure intersection)
                search_distance = obstacle_geom.boundingBox().width() + obstacle_geom.boundingBox().height()
                ray_length = max(search_distance, 5000)  # Use a larger value to ensure we intersect the boundary

                # Ray in direction A
                ray_A_end_x = mid_pt.x() + ray_length * math.sin(perp_angle_rad_A)
                ray_A_end_y = mid_pt.y() + ray_length * math.cos(perp_angle_rad_A)
                ray_A = QgsGeometry.fromPolylineXY([mid_point_xy, QgsPointXY(ray_A_end_x, ray_A_end_y)])

                # Ray in direction B
                ray_B_end_x = mid_pt.x() + ray_length * math.sin(perp_angle_rad_B)
                ray_B_end_y = mid_pt.y() + ray_length * math.cos(perp_angle_rad_B)
                ray_B = QgsGeometry.fromPolylineXY([mid_point_xy, QgsPointXY(ray_B_end_x, ray_B_end_y)])

                # Find intersection with obstacle boundary
                intersection_A = ray_A.intersection(obstacle_boundary)
                intersection_B = ray_B.intersection(obstacle_boundary)

                # Use fallback in case of no intersection
                offset_dist = max(clearance_m * 1.1, 300.0)  # Reasonable fallback
                peak_a_x = mid_pt.x() + offset_dist * math.sin(perp_angle_rad_A)
                peak_a_y = mid_pt.y() + offset_dist * math.cos(perp_angle_rad_A)
                peak_b_x = mid_pt.x() + offset_dist * math.sin(perp_angle_rad_B)
                peak_b_y = mid_pt.y() + offset_dist * math.cos(perp_angle_rad_B)

                # If we found intersection with boundary, use that point instead
                if intersection_A and not intersection_A.isEmpty():
                    # Get the closest intersection point to the midpoint
                    if intersection_A.type() == QgsWkbTypes.PointGeometry:
                        if intersection_A.isMultipart():
                            # Multiple intersection points, find closest one
                            points = intersection_A.asMultiPoint()
                            if points:
                                closest_dist = float('inf')
                                closest_point = None
                                for pt in points:
                                    dist = math.sqrt((pt.x() - mid_pt.x())**2 + (pt.y() - mid_pt.y())**2)
                                    if dist < closest_dist:
                                        closest_dist = dist
                                        closest_point = pt
                                if closest_point:
                                    peak_a_x = closest_point.x()
                                    peak_a_y = closest_point.y()
                        else:
                            # Single intersection point
                            point = intersection_A.asPoint()
                            peak_a_x = point.x()
                            peak_a_y = point.y()
                    else:
                        # For more complex geometries, try to find the closest point
                        closest_pt = intersection_A.nearestPoint(QgsGeometry.fromPointXY(mid_point_xy))
                        if not closest_pt.isEmpty():
                            peak_a_x = closest_pt.asPoint().x()
                            peak_a_y = closest_pt.asPoint().y()

                if intersection_B and not intersection_B.isEmpty():
                    # Get the closest intersection point to the midpoint
                    if intersection_B.type() == QgsWkbTypes.PointGeometry:
                        if intersection_B.isMultipart():
                            # Multiple intersection points, find closest one
                            points = intersection_B.asMultiPoint()
                            if points:
                                closest_dist = float('inf')
                                closest_point = None
                                for pt in points:
                                    dist = math.sqrt((pt.x() - mid_pt.x())**2 + (pt.y() - mid_pt.y())**2)
                                    if dist < closest_dist:
                                        closest_dist = dist
                                        closest_point = pt
                                if closest_point:
                                    peak_b_x = closest_point.x()
                                    peak_b_y = closest_point.y()
                        else:
                            # Single intersection point
                            point = intersection_B.asPoint()
                            peak_b_x = point.x()
                            peak_b_y = point.y()
                    else:
                        # For more complex geometries, try to find the closest point
                        closest_pt = intersection_B.nearestPoint(QgsGeometry.fromPointXY(mid_point_xy))
                        if not closest_pt.isEmpty():
                            peak_b_x = closest_pt.asPoint().x()
                            peak_b_y = closest_pt.asPoint().y()

                # Create Peaks for this obstacle
                peak_A = QgsPoint(peak_a_x, peak_a_y)
                peak_B = QgsPoint(peak_b_x, peak_b_y)

                # Store peaks for this obstacle
                self.all_peaks[obs_idx] = {'A': peak_A, 'B': peak_B}

                log.debug(f"Obstacle {obs_idx}: Peak A: {peak_A.x():.1f},{peak_A.y():.1f}, Peak B: {peak_B.x():.1f},{peak_B.y():.1f}")

            # STEPS 5-10: Complete the deviation calculation (handled in _complete_deviation_calculation)
            # This calls the method that implements the remaining steps
            return self._complete_deviation_calculation(lines_layer, obstacle_geometries, clearance_m, turn_radius_m)

        except Exception as e:
            log.exception(f"Error in deviation calculation: {e}")
            if edit_started_here and lines_layer.isEditable():
                lines_layer.rollBack()
                log.info("Changes rolled back due to error")
            return False


    # <<< Helper Function Start: _extract_line_segment (Attempting Explicit LineString access) >>>
    def _extract_line_segment(self, line_geom, start_dist, end_dist):
        """
        Extracts a segment of a line geometry between two distances along the line.
        Attempts to use native curveSubstring via explicit LineString access.
        Falls back to manual iteration if needed.

        Args:
            line_geom (QgsGeometry): The input line geometry
            start_dist (float): Start distance along the line
            end_dist (float): End distance along the line

        Returns:
            QgsGeometry: The extracted line segment, or None on error or if segment is invalid.
        """
        if not line_geom or not line_geom.isGeosValid():
            log.warning(f"_extract_line_segment: Invalid input geometry")
            return None

        # Check if it's a line type BEFORE trying to access specific methods
        if not is_line_type(line_geom.wkbType()):
             log.warning(f"_extract_line_segment: Input geometry is not a line type (Type: {line_geom.wkbType()})")
             return None

        line_length = line_geom.length()
        start_dist = max(0.0, min(start_dist, line_length))
        end_dist = max(0.0, min(end_dist, line_length))

        if abs(start_dist - end_dist) < 1e-9:
            log.debug(f"_extract_line_segment: Zero or negative length requested.")
            return None

        try:
            # --- Attempt 1: Native curveSubstring ---
            # Check if the method exists directly (might work in some contexts/future versions)
            if hasattr(line_geom, 'curveSubstring'):
                segment_geom = line_geom.curveSubstring(start_dist, end_dist)
                if segment_geom and not segment_geom.isEmpty() and is_line_type(segment_geom.wkbType()):
                    # log.debug("Used direct line_geom.curveSubstring")
                    return segment_geom
                else:
                    log.warning("Direct line_geom.curveSubstring failed or returned invalid geometry.")
            else:
                 log.debug("line_geom object does not directly have curveSubstring method.")

            # --- Attempt 2: Access as LineString ---
            # If it's specifically a LineString, try accessing it directly
            if line_geom.wkbType() == QgsWkbTypes.LineString:
                 line_string_part = line_geom.constGet() # Get pointer to implementation
                 if hasattr(line_string_part, 'curveSubstring'):
                     # QgsLineString::curveSubstring returns a new QgsLineString pointer,
                     # we need to wrap it back into a QgsGeometry
                     new_line_part = line_string_part.curveSubstring(start_dist, end_dist)
                     if new_line_part:
                         segment_geom = QgsGeometry(new_line_part) # Wrap in QgsGeometry
                         if segment_geom and not segment_geom.isEmpty() and is_line_type(segment_geom.wkbType()):
                              # log.debug("Used line_string_part.curveSubstring")
                              return segment_geom
                         else:
                              log.warning("line_string_part.curveSubstring failed or returned invalid geometry.")
                     else:
                          log.warning("line_string_part.curveSubstring returned None")
                 else:
                      log.debug("line_string_part does not have curveSubstring method (unexpected for LineString).")


            # --- Fallback: Manual Extraction (If curveSubstring failed) ---
            log.warning("curveSubstring approaches failed. Falling back to manual extraction.")
            return self._extract_line_segment_manual(line_geom, start_dist, end_dist)


        except Exception as e:
             log.exception(f"Error in _extract_line_segment (native/explicit attempts): {e}")
             log.warning("Error during native extraction, falling back to manual.")
             # Fallback to manual extraction on any error during native attempt
             return self._extract_line_segment_manual(line_geom, start_dist, end_dist)
    # <<< Helper Function End: _extract_line_segment >>>


    # <<< Helper Function Start: _extract_line_segment_manual (FIXED AttributeError) >>>
    def _extract_line_segment_manual(self, line_geom, start_dist, end_dist):
        """Extracts segment using interpolation and vertex iteration. (Fixed sqrDist Error)"""
        log.debug(f"Executing manual segment extraction for {start_dist:.2f}-{end_dist:.2f}")
        # Re-check basic validity
        if not line_geom or not line_geom.isGeosValid() or not is_line_type(line_geom.wkbType()):
            log.warning(f"_extract_line_segment_manual: Invalid input geometry")
            return None
        line_length = line_geom.length()
        start_dist = max(0.0, min(start_dist, line_length))
        end_dist = max(0.0, min(end_dist, line_length))
        if abs(start_dist - end_dist) < 1e-6: return None

        try:
            points_xy = []
            # Add start point
            start_geom_interpolated = line_geom.interpolate(start_dist)
            if not start_geom_interpolated or start_geom_interpolated.isEmpty():
                log.warning(f"_extract_line_segment_manual: Failed to interpolate start point at {start_dist:.2f}")
                return None
            points_xy.append(QgsPointXY(start_geom_interpolated.asPoint()))

            # Add intermediate vertices
            vertices_iter = line_geom.vertices()
            current_dist = 0.0
            first_vertex = line_geom.vertexAt(0)
            if first_vertex is None: log.error("_extract_line_segment_manual: Cannot get first vertex."); return None
            last_point = first_vertex # QgsPoint

            vertex_index = 0
            while vertices_iter.hasNext():
                 current_point = vertices_iter.next() # QgsPoint
                 segment_len = last_point.distance(current_point) # Uses QgsPoint.distance()

                 segment_start_dist = current_dist
                 segment_end_dist = current_dist + segment_len

                 # Add vertex if it falls strictly between start and end distances
                 if segment_end_dist > start_dist + 1e-6 and segment_end_dist < end_dist - 1e-6:
                      points_xy.append(QgsPointXY(current_point))

                 current_dist = segment_end_dist
                 last_point = current_point
                 vertex_index += 1
                 if current_dist > end_dist + 1e-6: break

            # Add end point
            end_geom_interpolated = line_geom.interpolate(end_dist)
            if not end_geom_interpolated or end_geom_interpolated.isEmpty():
                log.warning(f"_extract_line_segment_manual: Failed to interpolate end point at {end_dist:.2f}")
                last_v = line_geom.vertexAt(-1)
                if last_v: points_xy.append(QgsPointXY(last_v)); log.debug("_extract_line_segment_manual: Used last vertex as fallback.")
                else: return None
            else:
                 points_xy.append(QgsPointXY(end_geom_interpolated.asPoint()))

            # Remove duplicates
            final_points = []
            if points_xy:
                final_points.append(points_xy[0])
                for i in range(1, len(points_xy)):
                    if points_xy[i].compare(final_points[-1], 0.001) != 0: final_points.append(points_xy[i])

            if len(final_points) >= 2:
                log.debug(f"_extract_line_segment_manual: Extracted segment with {len(final_points)} points.")
                return QgsGeometry.fromPolylineXY(final_points)
            else:
                log.warning(f"_extract_line_segment_manual: Failed, only {len(final_points)} unique points found.")
                return None
        except Exception as e:
             log.exception(f"Error in _extract_line_segment_manual: {e}")
             return None
    # <<< Helper Function End: _extract_line_segment_manual >>>


    # <<< Helper Function Start: _calculate_segment_heading (FIXED _is_line_type call) >>>
    def _calculate_segment_heading(self, segment_geom, start=True):
        """Calculate heading (0-360 CW from N) for a line segment. (Fixed _is_line_type call)"""
        # --- FIX: Call global function ---
        if not segment_geom or segment_geom.isEmpty() or not is_line_type(segment_geom.wkbType()):
            log.warning("_calculate_segment_heading: Invalid geometry")
            return None
        # --- END FIX ---
        try:
            points = segment_geom.asPolyline()
            if len(points) < 2: log.warning("_calculate_segment_heading: Not enough points"); return None
            if start: p1 = points[0]; p2 = points[1]
            else: p1 = points[-2]; p2 = points[-1]
            dx = p2.x() - p1.x(); dy = p2.y() - p1.y()
            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                 log.warning("_calculate_segment_heading: Start/End points coincident.")
                 if start and len(points) > 2: p2 = points[2]; dx = p2.x() - p1.x(); dy = p2.y() - p1.y()
                 elif not start and len(points) > 2: p1 = points[-3]; dx = p2.x() - p1.x(); dy = p2.y() - p1.y()
                 else: return None
            if abs(dx) < 1e-9 and abs(dy) < 1e-9: return None
            angle_rad = math.atan2(dx, dy); heading_deg = math.degrees(angle_rad)
            qgis_heading = (90.0 - heading_deg + 360.0) % 360.0
            return qgis_heading
        except Exception as e: log.exception(f"Error in _calculate_segment_heading: {e}"); return None
    # <<< Helper Function End: _calculate_segment_heading >>>

    # <<< Function Start: _process_conflicted_lines (Phase 1 Headings Added) >>>
    def _process_conflicted_lines(self, lines_layer, obstacle_geometries, clearance_m, turn_radius_m, debug_mode=False):
        """
        Process conflicted lines: Correctly identify split points, calculate peaks relative
        to the gap, create TRUNCATED 'Outside' segments, calculate headings at truncation points,
        store data for Dubins turn.
        (Refined V5 + Phase 1 Headings Added)
        """
        log.info("Starting direct processing of conflicted lines (Refined V5 + Phase 1 Headings)...")

        # Setup (Unchanged)
        path_options = {}; chosen_paths = {}; segments_to_add_outside = []; segments_to_delete = []
        process_stats = {'lines_processed': 0, 'obstacles_processed': 0, 'paths_recorded': 0, 'segments_created': 0, 'lines_with_options': set(), 'errors': []}
        conflicted_lines = []; fld_conflicted_idx = lines_layer.dataProvider().fieldNameIndex("is_conflicted")
        log.info(f"[DIRECT-DEBUG] Querying conflicted lines (bypassing provider filter to read edit buffer)")
        if fld_conflicted_idx >= 0:
            # FIX: expression filters ignore unsaved edit buffer.
            # Query directly by FID, which we already determined earlier.
            known_fids = [item[0] for item in getattr(self, 'conflicted_lines_info', [])]
            conflicted_request = QgsFeatureRequest()
            if known_fids:
                conflicted_request.setFilterFids(known_fids)
            
            conflicted_request.setFlags(QgsFeatureRequest.NoFlags)
            for feature in lines_layer.getFeatures(conflicted_request):
                val = feature.attribute(fld_conflicted_idx)
                if val == True or feature.id() in known_fids:
                    fid = feature.id(); line_geom = feature.geometry(); line_num_attr = feature.attribute("LineNum")
                    line_num = str(line_num_attr) if line_num_attr is not None and line_num_attr != NULL else str(fid)
                    if line_geom.isEmpty() or not line_geom.isGeosValid(): log.warning(f"L{line_num}(FID={fid}) invalid geom"); continue
                    conflicted_lines.append((fid, line_num, line_geom, feature))
            log.info(f"[DIRECT-DEBUG] Found {len(conflicted_lines)} conflicted lines.")
        else:
            log.error("Required field 'is_conflicted' not found.");
            return {'path_options': {}, 'chosen_paths': {}, 'segments_to_add': [], 'segments_to_delete': [], 'process_stats': process_stats}

        processed_line_fids = set(); total_lines_processed = 0

        # Get Field Indices (Unchanged, but ensure target_fields is derived from a valid feature)
        if conflicted_lines:
             target_fields = conflicted_lines[0][3].fields(); # Use fields from the first feature
             fld_lsx = target_fields.lookupField("LowestSP_x"); fld_lsy = target_fields.lookupField("LowestSP_y")
             fld_hsx = target_fields.lookupField("HighestSP_x"); fld_hsy = target_fields.lookupField("HighestSP_y")
             coord_indices_valid = all(idx != -1 for idx in [fld_lsx, fld_lsy, fld_hsx, fld_hsy])
             if not coord_indices_valid: log.error("SP coordinate fields missing. Cannot update coords.")
        else:
            log.warning("No conflicted lines found, cannot determine target fields.")
            coord_indices_valid = False
            target_fields = QgsFields() # Create empty fields object to avoid errors later

        # <<< Main Loop >>>
        for fid, line_num, line_geom, feature in conflicted_lines:
            if fid in processed_line_fids: continue
            total_lines_processed += 1; log.info(f"Processing line {line_num} (FID={fid})")
            process_stats['lines_processed'] += 1
            QApplication.processEvents()

            # Line Setup (Unchanged)
            line_pts_xy = []
            vertices_iter = line_geom.vertices()
            while vertices_iter.hasNext():
                line_pts_xy.append(QgsPointXY(vertices_iter.next()))
            if len(line_pts_xy) < 2: log.warning(f"L{line_num}: Insufficient points."); continue
            line_start = line_pts_xy[0]; line_end = line_pts_xy[-1]; dx_orig = line_end.x() - line_start.x(); dy_orig = line_end.y() - line_start.y()
            heading_orig = 0.0 # Initialize
            if abs(dx_orig) > 1e-6 or abs(dy_orig) > 1e-6:
                heading_rad_math = math.atan2(dy_orig, dx_orig) # Math angle (0=E, CCW)
                qgis_heading_orig = (90.0 - math.degrees(heading_rad_math) + 360.0) % 360.0 # QGIS angle (0=N, CW)
            else:
                h_attr = feature.attribute("Heading") # Fallback to attribute table heading
                try:
                    qgis_heading_orig = float(h_attr) if h_attr is not None and h_attr != NULL else 0.0
                except (ValueError, TypeError):
                    qgis_heading_orig = 0.0


            current_outside_segments = [QgsGeometry(line_geom)]; line_was_split = False

            # <<< Obstacle Loop >>>
            obstacle_interacted_with_line = False
            for obs_idx, obstacle_geom in enumerate(obstacle_geometries):
                QApplication.processEvents()
                # FIX: obstacle_geom is already expanded by clearance_m in _prepare_avoidance_geometry!
                # FIX: obstacle_geom is ALREADY expanded by clearance_m in _prepare_avoidance_geometry!
                # Remove the double buffer, which gave 200m instead of 100m.
                obstacle_buffer = obstacle_geom 
                if not obstacle_buffer or obstacle_buffer.isEmpty() or not obstacle_buffer.isGeosValid():
                    log.warning(f"Invalid obstacle geometry Obs{obs_idx}. Skipping.")
                    continue

                next_iteration_segments = []; processed_segment_in_obstacle = False
                segments_intersecting_this_obstacle = []; segments_not_intersecting = []

                # Process each current segment against this obstacle
                for segment in current_outside_segments:
                     if segment and not segment.isEmpty() and segment.intersects(obstacle_buffer):
                         segments_intersecting_this_obstacle.append(segment)
                     elif segment and not segment.isEmpty():
                         segments_not_intersecting.append(segment)

                # If no segments intersect this obstacle, carry over non-intersecting ones and continue
                if not segments_intersecting_this_obstacle:
                    next_iteration_segments.extend(segments_not_intersecting)
                    continue

                log.info(f"  Processing Line {line_num}, Interacting Segment(s) vs Obstacle {obs_idx}")
                obstacle_interacted_with_line = True
                process_stats['obstacles_processed'] += 1
                new_outside_parts_for_this_obstacle = [] # Collect new segments created by interacting with THIS obstacle

                for segment_geom in segments_intersecting_this_obstacle:
                    actual_entry_point = None; actual_exit_point = None
                    segment_was_split_this_time = False
                    geom_part1_original = None; geom_part2_original = None # Store original split parts
                    
                    this_seg_products = [] # Keep track of products from this segment safely

                    try:
                        # --- STEP 7 (Splitting) ---
                        # Use difference, not a temp polygon, for more robust splitting
                        outside_geom = segment_geom.difference(obstacle_buffer)
                        self._log_debug_geom("Difference Result", outside_geom, "debug") # Log result

                        if outside_geom.isEmpty():
                            log.warning(f"Segment L{line_num} entirely within buffer {obs_idx}.")
                        elif outside_geom.wkbType() == QgsWkbTypes.LineString:
                            log.debug(f"Segment L{line_num} partially inside buffer {obs_idx}, one outside part remains.")
                            this_seg_products.append(outside_geom)
                        elif outside_geom.wkbType() == QgsWkbTypes.MultiLineString:
                            parts = []
                            try:
                                parts_geom = outside_geom.asMultiPolyline()
                                if parts_geom: parts = parts_geom # Ensure it's not None
                            except Exception as e:
                                log.error(f"Error converting MultiLineString parts L{line_num}: {e}")

                            log.debug(f"  Split into {len(parts)} parts.")
                            valid_parts_geoms = [QgsGeometry.fromPolylineXY(p) for p in parts if len(p) >= 2]

                            if len(valid_parts_geoms) >= 2:
                                segment_was_split_this_time = True
                                # Sort parts based on distance from the original segment's start point
                                segment_start_pt = QgsPointXY(segment_geom.vertexAt(0))
                                valid_parts_geoms.sort(key=lambda g: g.distance(QgsGeometry.fromPointXY(segment_start_pt)))

                                geom_part1_original = valid_parts_geoms[0]; geom_part2_original = valid_parts_geoms[-1]
                                points1 = geom_part1_original.asPolyline(); points2 = geom_part2_original.asPolyline()
                                actual_entry_point = QgsPointXY(points1[-1]); actual_exit_point = QgsPointXY(points2[0])
                                log.debug(f"  [P1-Split] L{line_num} Obs{obs_idx}: Split points: Entry({actual_entry_point.x():.1f},{actual_entry_point.y():.1f}), Exit({actual_exit_point.x():.1f},{actual_exit_point.y():.1f})")
                            elif len(valid_parts_geoms) == 1:
                                log.debug(f" Split resulted in 1 valid part L{line_num}, Obs{obs_idx}.")
                                this_seg_products.extend(valid_parts_geoms)
                            else:
                                log.warning(f" Split resulted < 1 valid parts L{line_num}, Obs{obs_idx}.")
                        else:
                            log.warning(f" Unexpected geom type {outside_geom.wkbType()} after difference L{line_num}, Obs{obs_idx}.")
                            this_seg_products.append(segment_geom) # Keep original if difference fails unexpectedly
                        # --- STEP 7 END ---

                        # Proceed only if the segment was actually split into two parts
                        if segment_was_split_this_time:
                            line_was_split = True # Mark that the original line geometry was modified
                            
                            # --- GLOBAL PEAK ASSIGNMENT (Strict Boundary Convergence) ---
                            # Use obstacle centroid so ALL parallel lines, 
                            # avoiding it, converge strictly at one maximum point (peak).
                            obs_centroid = obstacle_buffer.centroid().asPoint()
                            if obs_centroid.isEmpty():
                                cx, cy = (actual_entry_point.x() + actual_exit_point.x()) / 2.0, (actual_entry_point.y() + actual_exit_point.y()) / 2.0
                            else:
                                cx, cy = obs_centroid.x(), obs_centroid.y()
                            mid_point_xy = QgsPointXY(cx, cy)
                            
                            dx_gap = actual_exit_point.x() - actual_entry_point.x()
                            dy_gap = actual_exit_point.y() - actual_entry_point.y()
                            gap_len = math.hypot(dx_gap, dy_gap)
                            
                            if gap_len > 1e-8:
                                dx_norm_gap, dy_norm_gap = dx_gap / gap_len, dy_gap / gap_len
                            else:
                                heading_rad_math = math.radians(qgis_heading_orig)
                                dx_norm_gap, dy_norm_gap = math.sin(heading_rad_math), math.cos(heading_rad_math)
                                
                            perp_dx1, perp_dy1 = -dy_norm_gap, dx_norm_gap
                            perp_dx2, perp_dy2 = dy_norm_gap, -dx_norm_gap
                            
                            # Extract boundary of obstacle_buffer safely
                            obs_boundary = None
                            try:
                                if obstacle_buffer.type() == QgsWkbTypes.PolygonGeometry:
                                    if obstacle_buffer.isMultipart():
                                        polys = obstacle_buffer.asMultiPolygon()
                                        if polys and polys[0]: obs_boundary = QgsGeometry.fromPolylineXY(polys[0][0])
                                    else:
                                        poly = obstacle_buffer.asPolygon()
                                        if poly: obs_boundary = QgsGeometry.fromPolylineXY(poly[0])
                            except Exception as e:
                                log.debug("Obstacle boundary extraction fallback for line %r: %s", line_num, e)
                            if not obs_boundary or obs_boundary.isEmpty(): obs_boundary = obstacle_buffer
                                
                            ray_len = max(5000.0, gap_len * 2)
                            ray_a = QgsGeometry.fromPolylineXY([mid_point_xy, QgsPointXY(cx + perp_dx1 * ray_len, cy + perp_dy1 * ray_len)])
                            ray_b = QgsGeometry.fromPolylineXY([mid_point_xy, QgsPointXY(cx + perp_dx2 * ray_len, cy + perp_dy2 * ray_len)])
                            
                            def get_closest_intersection(ray):
                                inter = ray.intersection(obs_boundary)
                                if inter and not inter.isEmpty():
                                    if inter.type() == QgsWkbTypes.PointGeometry:
                                        if inter.isMultipart():
                                            pts = inter.asMultiPoint()
                                            if pts: return min(pts, key=lambda p: (p.x()-cx)**2 + (p.y()-cy)**2)
                                        else: return inter.asPoint()
                                    else:
                                        nearest = inter.nearestPoint(QgsGeometry.fromPointXY(mid_point_xy))
                                        if not nearest.isEmpty(): return nearest.asPoint()
                                return None
                            
                            pt_a = get_closest_intersection(ray_a)
                            pt_b = get_closest_intersection(ray_b)
                            
                            if pt_a: peak_a_point = QgsPointXY(pt_a)
                            else: peak_a_point = QgsPointXY(cx + perp_dx1 * clearance_m, cy + perp_dy1 * clearance_m)
                            
                            if pt_b: peak_b_point = QgsPointXY(pt_b)
                            else: peak_b_point = QgsPointXY(cx + perp_dx2 * clearance_m, cy + perp_dy2 * clearance_m)


                            # --- Path evaluation and choice ---
                            path_a_length = self._calculate_path_length(actual_entry_point, peak_a_point, actual_exit_point); path_b_length = self._calculate_path_length(actual_entry_point, peak_b_point, actual_exit_point)
                            log.debug(f"  Path Lengths (Revised Peaks): A={path_a_length:.1f}, B={path_b_length:.1f}")
                            if line_num not in path_options: path_options[line_num] = []
                            self._record_path_option(path_options, line_num, "A", path_a_length, actual_entry_point, peak_a_point, actual_exit_point, obs_idx)
                            self._record_path_option(path_options, line_num, "B", path_b_length, actual_entry_point, peak_b_point, actual_exit_point, obs_idx)
                            process_stats['paths_recorded'] += 2; process_stats['lines_with_options'].add(line_num)
                            if path_a_length <= path_b_length: chosen_peak = peak_a_point; peak_label = "A"; log.info(f"  L{line_num}, Obs{obs_idx}: Peak A chosen (Revised).")
                            else: chosen_peak = peak_b_point; peak_label = "B"; log.info(f"  L{line_num}, Obs{obs_idx}: Peak B chosen (Revised).")


                            # --- Calculate Far Points and Truncated Segments ---
                            # --- Dynamic Tangent Offset Calculation for S-Curve ---
                            wx = chosen_peak.x() - actual_entry_point.x()
                            wy = chosen_peak.y() - actual_entry_point.y()
                            D_offset = abs(dx_norm_gap * wy - dy_norm_gap * wx)
                            if D_offset < 1.0: D_offset = 1.0
                            
                            L_req = math.pi * math.sqrt((D_offset * turn_radius_m) / 2.0) * 1.05
                            tangent_offset_dist = max(5.0, L_req - (gap_len / 2.0))
                            log.debug(f"  [Cosine Prep] D_offset={D_offset:.1f}m, L_req={L_req:.1f}m, Gap={gap_len:.1f}m -> Tangent Offset: {tangent_offset_dist:.1f}m")
                            
                            far_entry_point = None; far_exit_point = None;
                            new_truncated_geom1 = None; new_truncated_geom2 = None
                            # --- PHASE 1: Calculate Headings ---
                            entry_heading_qgis = None; exit_heading_qgis = None
                            # --- END PHASE 1 ---
                            truncation_failed = False

                            # Process first outside part (before the gap)
                            if geom_part1_original:
                                len1 = geom_part1_original.length()
                                target_dist1 = max(0.0, len1 - tangent_offset_dist) # Distance from START of geom_part1
                                interp_geom1 = geom_part1_original.interpolate(target_dist1)
                                if interp_geom1 and not interp_geom1.isEmpty():
                                    far_entry_point = QgsPointXY(interp_geom1.asPoint())
                                    # Truncate geom_part1_original from its start (0) to target_dist1
                                    new_truncated_geom1 = self._extract_line_segment(geom_part1_original, 0, target_dist1)
                                    if new_truncated_geom1:
                                        log.debug(f"  [Dubins Prep] Far Entry Point: ({far_entry_point.x():.1f},{far_entry_point.y():.1f}) on Seg1 (Len:{new_truncated_geom1.length():.1f})")
                                        # --- PHASE 1: Calculate Entry Heading ---
                                        entry_heading_qgis = self._calculate_segment_heading(new_truncated_geom1, start=False)
                                        log.debug(f"  [Dubins Prep] Calculated Entry Heading: {entry_heading_qgis}")
                                        # --- END PHASE 1 ---
                                    else: log.warning(f"  [Dubins Prep] Failed to truncate Seg1 L{line_num}."); truncation_failed = True
                                else: log.warning(f"  [Dubins Prep] Failed interpolate Far Entry L{line_num}."); truncation_failed = True
                            else:
                                log.warning(f"  [Dubins Prep] Original Segment 1 missing L{line_num}."); truncation_failed = True

                            # Process second outside part (after the gap)
                            if geom_part2_original and not truncation_failed:
                                len2 = geom_part2_original.length()
                                target_dist2 = min(len2, tangent_offset_dist) # Distance from START of geom_part2
                                interp_geom2 = geom_part2_original.interpolate(target_dist2)
                                if interp_geom2 and not interp_geom2.isEmpty():
                                    far_exit_point = QgsPointXY(interp_geom2.asPoint())
                                    # Truncate geom_part2_original from target_dist2 to its end (len2)
                                    new_truncated_geom2 = self._extract_line_segment(geom_part2_original, target_dist2, len2)
                                    if new_truncated_geom2:
                                        log.debug(f"  [Dubins Prep] Far Exit Point: ({far_exit_point.x():.1f},{far_exit_point.y():.1f}) on Seg2 (Len:{new_truncated_geom2.length():.1f})")
                                        # --- PHASE 1: Calculate Exit Heading ---
                                        exit_heading_qgis = self._calculate_segment_heading(new_truncated_geom2, start=True)
                                        log.debug(f"  [Dubins Prep] Calculated Exit Heading: {exit_heading_qgis}")
                                        # --- END PHASE 1 ---
                                    else: log.warning(f"  [Dubins Prep] Failed to truncate Seg2 L{line_num}."); truncation_failed = True
                                else: log.warning(f"  [Dubins Prep] Failed interpolate Far Exit L{line_num}."); truncation_failed = True
                            else:
                                # Don't set truncation_failed=True here if it already failed on segment 1
                                if not truncation_failed:
                                    log.warning(f"  [Dubins Prep] Original Segment 2 missing L{line_num}.")
                                    truncation_failed = True


                            # --- Store Data for Connector ---
                            if line_num not in chosen_paths: chosen_paths[line_num] = [] # Initialize if first interaction for this line
                            choice_exists_for_obstacle = any(c.get('obstacle_id') == obs_idx for c in chosen_paths[line_num])

                            if not choice_exists_for_obstacle:
                                if not truncation_failed:
                                    log.debug(f"  Storing choice with FAR points and TRUNCATED geoms L{line_num}, Obs{obs_idx}")
                                    chosen_paths[line_num].append({
                                        'obstacle_id': obs_idx,
                                        'peak': peak_label,
                                        'entry_point': far_entry_point,
                                        'peak_point': chosen_peak,
                                        'exit_point': far_exit_point,
                                        'original_fid': fid,
                                        'geom_outside1': new_truncated_geom1,
                                        'geom_outside2': new_truncated_geom2,
                                        # --- PHASE 1: Store Headings ---
                                        'entry_heading_qgis': entry_heading_qgis,
                                        'exit_heading_qgis': exit_heading_qgis,
                                        # --- END PHASE 1 ---
                                    })
                                    # Add TRUNCATED parts
                                    if new_truncated_geom1: this_seg_products.append(new_truncated_geom1)
                                    if new_truncated_geom2: this_seg_products.append(new_truncated_geom2)
                                else:
                                    log.warning(f"  Truncation failed L{line_num}, Obs{obs_idx}. Storing choice with ORIGINAL split points/geoms and NO headings.")
                                    chosen_paths[line_num].append({
                                        'obstacle_id': obs_idx,
                                        'peak': peak_label,
                                        'entry_point': actual_entry_point, # Use original split points
                                        'peak_point': chosen_peak,
                                        'exit_point': actual_exit_point, # Use original split points
                                        'original_fid': fid,
                                        'geom_outside1': geom_part1_original, # Keep original geometries
                                        'geom_outside2': geom_part2_original,
                                        # --- PHASE 1: Store None for Headings ---
                                        'entry_heading_qgis': None,
                                        'exit_heading_qgis': None,
                                        # --- END PHASE 1 ---
                                    })
                                    # Add ORIGINAL parts
                                    if geom_part1_original: this_seg_products.append(geom_part1_original)
                                    if geom_part2_original: this_seg_products.append(geom_part2_original)
                            else:
                                log.debug(f"  Choice for L{line_num}, Obs{obs_idx} already exists, skipping storage.")
                                # Fallback if choice exists
                                if geom_part1_original: this_seg_products.append(geom_part1_original)
                                if geom_part2_original: this_seg_products.append(geom_part2_original)
                                
                        # Add all valid segment products to the main list
                        new_outside_parts_for_this_obstacle.extend(this_seg_products)

                    except Exception as e:
                        log.exception(f"Error processing segment L{line_num}, Obs{obs_idx}: {e}")
                        process_stats['errors'].append(f"L{line_num}, Obs{obs_idx}, Segment: {str(e)}")
                        new_outside_parts_for_this_obstacle.append(segment_geom) # Keep original line if an error occurred midway

                # Update current_outside_segments for the next obstacle check
                # Combine the parts that didn't intersect this obstacle with the new parts created by this obstacle
                current_outside_segments = segments_not_intersecting + new_outside_parts_for_this_obstacle
            # <<< End Obstacle Loop >>>

            # --- Final Feature Creation & Deletion Marking ---
            if line_was_split:
                processed_line_fids.add(fid) # Mark the original FID as processed
                if fid not in segments_to_delete: segments_to_delete.append(fid) # Mark original line for deletion
                log.info(f"Creating {len(current_outside_segments)} final outside features for line {line_num}")
                for final_segment_geom in current_outside_segments:
                     if final_segment_geom and not final_segment_geom.isEmpty() and final_segment_geom.isGeosValid():
                          feat_final_outside = QgsFeature(target_fields) # Use fields from original feature
                          feat_final_outside.setGeometry(final_segment_geom)
                          feat_final_outside.setAttributes(feature.attributes()) # Copy attributes from original
                          feat_final_outside["Length_m"] = final_segment_geom.length()
                          feat_final_outside["is_line_merged"] = True # Mark as part of a modified line
                          feat_final_outside["is_deviation_created"] = True # Indicate deviation process applied
                          # Update coordinates if possible
                          if coord_indices_valid:
                              try:
                                  if final_segment_geom.wkbType() == QgsWkbTypes.LineString:
                                      points = final_segment_geom.asPolyline()
                                      if len(points) >= 2:
                                          start_v_xy = points[0]; end_v_xy = points[-1]
                                          feat_final_outside.setAttribute(fld_lsx, start_v_xy.x()); feat_final_outside.setAttribute(fld_lsy, start_v_xy.y())
                                          feat_final_outside.setAttribute(fld_hsx, end_v_xy.x()); feat_final_outside.setAttribute(fld_hsy, end_v_xy.y())
                                      else: log.warning(f"Cannot update coords for outside segment L{line_num}: < 2 points.")
                                  else: log.warning(f"Cannot update coords for outside segment L{line_num}: Not LineString.")
                              except Exception as update_ex: log.warning(f"Error updating coords for outside segment L{line_num}: {update_ex}")
                          segments_to_add_outside.append(feat_final_outside)
                          process_stats['segments_created'] += 1
                     else:
                         log.warning(f"Skipping invalid final outside segment L{line_num}")
            else:
                 # Line conflicted but didn't require splitting (e.g., fully contained or only touched)
                 log.info(f"Line {line_num} conflicted but no splitting occurred.")
                 # If it was marked for deletion previously by another obstacle interaction, keep it marked
                 # Otherwise, if it wasn't split, ensure it's NOT marked for deletion
                 if fid in segments_to_delete and not any(c.get('original_fid') == fid for choices in chosen_paths.values() for c in choices):
                     log.debug(f"Line {line_num} (FID={fid}) was marked for deletion but wasn't split, removing deletion flag.")
                     segments_to_delete.remove(fid)

        # <<< End Main Loop >>>

        # Final log summary & Return (Unchanged)
        log.info(f"Processed {process_stats['lines_processed']} lines vs {process_stats['obstacles_processed']} obstacles.")
        log.info(f"Recorded options for {len(process_stats['lines_with_options'])} lines.")
        log.info(f"Created {len(segments_to_add_outside)} 'Outside' features.")
        log.info(f"Marked {len(segments_to_delete)} original lines for deletion.")
        if process_stats['errors']: log.warning(f"Encountered {len(process_stats['errors'])} errors.")
        log.info(f"[DIRECT-DEBUG] Processed {total_lines_processed} lines total.")

        return_dict = {'path_options': path_options, 'chosen_paths': chosen_paths, 'segments_to_add': segments_to_add_outside, 'segments_to_delete': segments_to_delete, 'process_stats': process_stats}
        self.path_options = path_options # Assign to self for potential later use/debugging
        log.info(f"[DIRECT-ASSIGN] Assigned self.path_options. Keys: {list(self.path_options.keys())}")
        log.info(f"[RETURN-CHECK] Returning dict. Path options keys: {list(return_dict.get('path_options', {}).keys())}")
        return return_dict

    # <<< Function Start: _complete_deviation_calculation (Merging Version - Final) >>>
    def _complete_deviation_calculation(self, lines_layer, obstacle_geometries, clearance_m, turn_radius_m, debug_mode=False):
        """
        Completes deviation: Creates SMOOTHED connectors, merges segments, finalizes layer updates.
        (Refined V4 + QGIS Native Smoothing + Merging)
        """
        log.info("Completing deviation calculation and finalizing paths (QGIS Smooth + Merging)...")
        project = QgsProject.instance()

        # --- Layers Setup ---
        deviation_connectors_layer_name = "Deviation_Connectors_Final"
        self._remove_layer_by_name(deviation_connectors_layer_name)
        deviation_connectors_layer = None # Initialize
        deviation_provider = None
        try:
            # Ensure CRS is valid before creating the layer
            layer_crs = lines_layer.crs()
            if not layer_crs.isValid():
                log.warning("Source layer CRS is invalid. Falling back to project CRS or EPSG:4326 for debug layer.")
                layer_crs = QgsProject.instance().crs()
                if not layer_crs.isValid():
                    layer_crs = QgsCoordinateReferenceSystem("EPSG:4326") # Last resort

            deviation_connectors_layer = QgsVectorLayer(f"LineString?crs={layer_crs.authid()}", deviation_connectors_layer_name, "memory")
            if not deviation_connectors_layer.isValid(): raise ValueError(f"Failed to create debug connector layer with CRS {layer_crs.authid()}")

            deviation_provider = deviation_connectors_layer.dataProvider()
            provider_fields = [ QgsField("LineNum", QVariant.Int), QgsField("OriginalFID", QVariant.Int), QgsField("ObstacleID", QVariant.Int), QgsField("ChosenPeak", QVariant.String), QgsField("Status", QVariant.String) ]
            if not deviation_provider.addAttributes(provider_fields):
                 raise ValueError(f"Failed to add attributes to debug connector layer: {deviation_provider.lastError()}")
            deviation_connectors_layer.updateFields()
            deviation_connectors_layer.startEditing()
        except Exception as layer_err:
            log.error(f"Failed to initialize debug connector layer: {layer_err}")
            deviation_connectors_layer = None # Ensure it's None if creation fails
            deviation_provider = None

        # --- Smoothing Parameters ---
        densify_factor = 5.0
        smooth_iterations = 3
        smooth_offset = 0.25
        endpoint_tolerance = 0.5
        # --- End Smoothing Parameters ---

        # --- Main Processing Block ---
        edit_started_here = False
        lines_layer_provider = lines_layer.dataProvider()
        if not lines_layer.isEditable():
            if not lines_layer.startEditing():
                 log.error(f"Failed to start editing on main lines layer: {lines_layer.dataProvider().lastError()}")
                 if deviation_connectors_layer and deviation_connectors_layer.isEditable(): deviation_connectors_layer.rollBack()
                 return False # Cannot proceed without editing capability
            edit_started_here = True
            log.debug(f"Started editing layer: {lines_layer.name()}")

        try:
            log.info("Processing pre-calculated conflicted lines and path options...")
            results = self._process_conflicted_lines(lines_layer, obstacle_geometries, clearance_m, turn_radius_m, debug_mode)
            if not results:
                 log.error("Failed to process conflicted lines. Aborting deviation completion.")
                 raise ValueError("Failed to process conflicted lines.")

            log.info(f"[COMPLETE] Received results. Path options keys: {list(results.get('path_options', {}).keys())}")
            path_options = results['path_options']; chosen_paths = results['chosen_paths']
            segments_to_add_outside = results['segments_to_add'] # List of QgsFeatures
            segments_to_delete_fids = results['segments_to_delete'] # List of FIDs
            process_stats = results['process_stats']
            self.path_options = path_options; self.chosen_paths = chosen_paths
            log.info(f"[COMPLETE] Assigned self.path_options ({len(self.path_options)} lines), self.chosen_paths ({len(self.chosen_paths)} lines)")

            # --- Cache Original Attributes ---
            log.debug("Caching attributes of original lines before deletion...")
            original_feature_attributes = {}
            target_fields = lines_layer.fields()
            if segments_to_delete_fids:
                request = QgsFeatureRequest().setFilterFids(segments_to_delete_fids)
                request.setFlags(QgsFeatureRequest.NoGeometry | QgsFeatureRequest.SubsetOfAttributes)
                all_field_names = [target_fields.at(i).name() for i in range(target_fields.count())]
                request.setSubsetOfAttributes(all_field_names, target_fields)

                if target_fields.lookupField("LineNum") == -1:
                    log.warning("Essential 'LineNum' field missing, ensuring geometry is fetched for attribute caching.")
                    request.setFlags(QgsFeatureRequest.NoFlags)

                for feat in lines_layer.getFeatures(request):
                     attrs = feat.attributes()
                     if not attrs and target_fields.lookupField("LineNum") != -1:
                         log.warning(f"Failed to fetch attributes for FID {feat.id()} despite fields existing? Check request flags.")
                         attrs = [NULL] * len(target_fields)
                     original_feature_attributes[feat.id()] = attrs

                log.debug(f"Cached attributes for {len(original_feature_attributes)} original features.")
            else: log.debug("No original lines marked for deletion.")

            # --- Generate Connector Segments (In Memory) ---
            log.info(f"Generating connector paths for {len(chosen_paths)} lines (in memory)...")
            segments_to_add_connectors = []; connectors_added_debug = 0
            fld_lsx_conn = target_fields.lookupField("LowestSP_x"); fld_lsy_conn = target_fields.lookupField("LowestSP_y")
            fld_hsx_conn = target_fields.lookupField("HighestSP_x"); fld_hsy_conn = target_fields.lookupField("HighestSP_y")
            coord_indices_valid_conn = all(idx != -1 for idx in [fld_lsx_conn, fld_lsy_conn, fld_hsx_conn, fld_hsy_conn])

            for line_num, choices in chosen_paths.items():
                QApplication.processEvents()
                for choice in choices:
                    original_fid = choice.get('original_fid')
                    if original_fid in original_feature_attributes:
                        original_attributes = original_feature_attributes[original_fid]
                    else:
                        log.warning(f"No cached attributes for FID {original_fid} (L{line_num}). Using NULLs.");
                        original_attributes = [NULL] * len(target_fields)

                    connector_geom = None
                    smoothing_status = "Not Attempted"

                    try:
                        obs_idx = choice['obstacle_id']; peak_label = choice['peak']
                        entry_point = choice['entry_point']; peak_point = choice['peak_point']; exit_point = choice['exit_point']
                        geom_outside1 = choice.get('geom_outside1'); geom_outside2 = choice.get('geom_outside2')

                        if not all([entry_point, peak_point, exit_point]):
                            log.warning(f"Skip connector L{line_num}, Obs{obs_idx}: Missing point data."); continue
                        if not all(isinstance(p, QgsPointXY) for p in [entry_point, peak_point, exit_point]):
                             log.warning(f"Skip connector L{line_num}, Obs{obs_idx}: Invalid point types."); continue

                        log.debug(f"  [Curve Prep] L{line_num} Obs{obs_idx}: Points: Entry({entry_point.x():.1f},{entry_point.y():.1f}), Peak({peak_point.x():.1f},{peak_point.y():.1f}), Exit({exit_point.x():.1f},{exit_point.y():.1f})")

                        # --- Mathematical Cosine S-Curve Generation ---
                        # Generate an ideal S-curve ("Hat") that passes exactly through the maximum distance point
                        # and strictly observes the specified vessel turn radius (turn_radius_m).
                        dx_total = exit_point.x() - entry_point.x()
                        dy_total = exit_point.y() - entry_point.y()
                        L_total = math.hypot(dx_total, dy_total)
                        
                        if L_total > 1e-6:
                            ux = dx_total / L_total
                            uy = dy_total / L_total
                            
                            px = peak_point.x() - entry_point.x()
                            py = peak_point.y() - entry_point.y()
                            cross = ux * py - uy * px
                            
                            nx = -uy if cross > 0 else uy
                            ny = ux if cross > 0 else -ux
                            
                            D_peak = abs(cross)
                            
                            num_points = max(32, int(L_total / 15.0))
                            curve_points = []
                            
                            for pt_idx in range(num_points + 1):
                                t = pt_idx / float(num_points)
                                curr_x = entry_point.x() + t * dx_total
                                curr_y = entry_point.y() + t * dy_total
                                
                                offset = D_peak * 0.5 * (1.0 - math.cos(2.0 * math.pi * t))
                                pt_x = curr_x + nx * offset
                                pt_y = curr_y + ny * offset
                                curve_points.append(QgsPointXY(pt_x, pt_y))
                                
                            connector_geom = QgsGeometry.fromPolylineXY(curve_points)
                            
                            if connector_geom.isEmpty():
                                connector_geom = QgsGeometry.fromPolylineXY([entry_point, peak_point, exit_point])
                                smoothing_status = "Cosine Failed (Empty)"
                            else:
                                smoothing_status = "Cosine S-Curve (Success)"
                                log.info(f"  [Curve Success] L{line_num}, Obs{obs_idx}: S-Curve generated with {len(curve_points)} points. Peak offset: {D_peak:.1f}m")
                        else:
                            connector_geom = QgsGeometry.fromPolylineXY([entry_point, peak_point, exit_point])
                            smoothing_status = "Sharp Fallback (Zero Length)"

                        if connector_geom and not connector_geom.isEmpty():
                            connector_heading = None
                            try:
                                if len(list(connector_geom.vertices())) >= 2:
                                     connector_heading = self._calculate_segment_heading(connector_geom, start=True)
                            except: pass

                            connector_feat_mem = QgsFeature(target_fields)
                            connector_feat_mem.setGeometry(connector_geom)
                            connector_feat_mem.setAttributes(original_attributes)
                            connector_feat_mem["Length_m"] = connector_geom.length()
                            connector_feat_mem["is_line_merged"] = True
                            connector_feat_mem["is_deviation_created"] = True
                            connector_feat_mem["Heading"] = connector_heading if connector_heading is not None else NULL
                            fld_seg_type_idx = target_fields.lookupField("SegmentType")
                            fld_linenum_idx_conn = target_fields.lookupField("LineNum")
                            if fld_seg_type_idx != -1: connector_feat_mem[fld_seg_type_idx] = "Connector"
                            if fld_linenum_idx_conn != -1: connector_feat_mem[fld_linenum_idx_conn] = line_num

                            if coord_indices_valid_conn:
                                try:
                                    points = connector_geom.asPolyline()
                                    if len(points) >= 2:
                                        start_v_xy = points[0]; end_v_xy = points[-1]
                                        connector_feat_mem.setAttribute(fld_lsx_conn, start_v_xy.x()); connector_feat_mem.setAttribute(fld_lsy_conn, start_v_xy.y())
                                        connector_feat_mem.setAttribute(fld_hsx_conn, end_v_xy.x()); connector_feat_mem.setAttribute(fld_hsy_conn, end_v_xy.y())
                                except Exception as update_ex: log.warning(f"Error updating coords Connector L{line_num}: {update_ex}")

                            segments_to_add_connectors.append(connector_feat_mem)

                            if deviation_provider:
                                 debug_connector_feat = QgsFeature(deviation_connectors_layer.fields())
                                 debug_connector_feat.setGeometry(connector_geom)
                                 debug_connector_feat.setAttributes([line_num, original_fid, obs_idx, peak_label, smoothing_status])
                                 deviation_provider.addFeature(debug_connector_feat)
                                 connectors_added_debug += 1
                        else:
                             log.warning(f"  [Smooth Skip] L{line_num}, Obs{obs_idx}: Final connector geometry invalid or empty. No connector generated.")

                    except Exception as conn_err:
                        log.error(f"Error creating connector L{line_num}, Obs{obs_idx}: {conn_err}")
                        if deviation_provider:
                            debug_connector_feat = QgsFeature(deviation_connectors_layer.fields())
                            debug_connector_feat.setGeometry(QgsGeometry())
                            debug_connector_feat.setAttributes([line_num, original_fid, obs_idx, peak_label, f"Error: {conn_err}"])
                            deviation_provider.addFeature(debug_connector_feat)

            log.info(f"Generated {len(segments_to_add_connectors)} connector features (in memory).")
            if deviation_connectors_layer: log.info(f"Generated {connectors_added_debug} connector features for debug layer.")

            # --- Collect All Generated Segments By LineNum ---
            segments_by_line = defaultdict(list)
            all_new_segments = segments_to_add_outside + segments_to_add_connectors

            fld_linenum_idx_collect = target_fields.lookupField("LineNum")
            if fld_linenum_idx_collect == -1:
                log.error("Cannot collect segments: LineNum field index not found.")
                raise ValueError("LineNum field missing, cannot proceed with merging.")

            for segment_feat in all_new_segments:
                try:
                    line_num_val = segment_feat.attribute(fld_linenum_idx_collect)
                    if line_num_val is not None and line_num_val != NULL:
                        segments_by_line[str(line_num_val)].append(segment_feat)
                    else:
                        log.warning(f"Segment feature lacks valid LineNum attribute, cannot group for merging.")
                except Exception as e:
                     log.warning(f"Error getting LineNum for segment grouping: {e}. Skipping segment.")

            # --- Merge Collected Segments ---
            merged_features = self._merge_line_segments(
                segments_by_line,
                target_fields,
                original_feature_attributes,
                turn_radius_m
            )

            merged_line_nums = set()
            for mf in merged_features:
                ln_val = mf.attribute(fld_linenum_idx_collect)
                if ln_val is not None and ln_val != NULL:
                    merged_line_nums.add(str(ln_val))

            # --- Finalize Layer Updates ---
            # 1. Delete original conflicted lines ONLY IF successfully merged
            if segments_to_delete_fids:
                fids_to_actually_delete = []
                for fid in segments_to_delete_fids:
                    if fid in original_feature_attributes:
                        orig_ln = str(original_feature_attributes[fid][fld_linenum_idx_collect])
                        if orig_ln in merged_line_nums:
                            fids_to_actually_delete.append(fid)
                        else:
                            log.warning(f"Merge failed for line {orig_ln}, keeping original geometry.")
                
                if fids_to_actually_delete:
                    unique_fids_to_delete = list(set(fids_to_actually_delete))
                    log.info(f"Deleting {len(unique_fids_to_delete)} original lines from '{lines_layer.name()}'.")
                    
                    # FIX: Use layer method instead of provider to respect edit buffer
                    delete_ok = lines_layer.deleteFeatures(unique_fids_to_delete)
                    if not delete_ok:
                        log.error("Failed delete original features.")
                    else:
                        log.debug("Success delete original features.")
                else:
                    log.debug("No valid merged lines, so no original features deleted.")
            else:
                 log.debug("No original conflicted lines to delete.")

            # 2. Add the NEW MERGED features
            if merged_features:
                log.info(f"Adding {len(merged_features)} merged features to '{lines_layer.name()}'.")
                
                # FIX: Use layer method instead of provider to respect edit buffer
                success = lines_layer.addFeatures(merged_features)
                if not success:
                    log.error("Failed add merged features to layer.")
                    raise RuntimeError("Failed to add merged features.")
                else:
                    log.debug(f"Success add {len(merged_features)} merged features.")
            else:
                 log.warning("No merged features were generated to add.")

            # Commit the main lines layer
            if lines_layer.isEditable(): # Check again in case of prior rollback attempts
                 if not lines_layer.commitChanges():
                      commit_errors = lines_layer.commitErrors()
                      log.error(f"CRITICAL: Failed commit lines layer changes: {commit_errors}");
                      QMessageBox.critical(self, "Commit Error", f"Failed save final lines layer changes:\n{commit_errors}")
                      raise RuntimeError("Failed to commit changes to lines layer.")
                 else:
                      log.info("Successfully committed changes to lines layer.")
                      edit_started_here = False # Mark commit as successful

            # --- Create Generated_Deviation_Lines Layer ---
            dev_layer_name = "Generated_Deviation_Lines"
            self._remove_layer_by_name(dev_layer_name)
            try:
                dev_layer = QgsVectorLayer(f"LineString?crs={layer_crs.authid()}", dev_layer_name, "memory")
                dev_provider = dev_layer.dataProvider()
                dev_provider.addAttributes([
                    QgsField("SL", QVariant.String, len=50),
                    QgsField("Length_m", QVariant.Double, len=10, prec=2)
                ])
                dev_layer.updateFields()
                
                dev_features = []
                for conn_feat in segments_to_add_connectors:
                    if not conn_feat.geometry().isEmpty():
                        new_f = QgsFeature(dev_layer.fields())
                        new_f.setGeometry(conn_feat.geometry())
                        ln_val = conn_feat.attribute(fld_linenum_idx_collect)
                        # Extract clean base line name (strictly 4 digits), dropping 5th digit and suffixes
                        base_ln = str(ln_val).split('_')[0][:4] if ln_val else "Unknown"
                        new_f.setAttribute("SL", base_ln)
                        new_f.setAttribute("Length_m", conn_feat.geometry().length())
                        dev_features.append(new_f)
                        
                if dev_features:
                    dev_provider.addFeatures(dev_features)
                    # Apply a distinctive style
                    self._apply_basic_style(dev_layer, '#006400', line_style='solid', width=0.6)
                    self._add_layer_to_lookahead_group(dev_layer)
                    log.info(f"Created {dev_layer_name} with {len(dev_features)} features.")
            except Exception as dev_err:
                log.warning(f"Could not create {dev_layer_name} layer: {dev_err}")
            # --- End Create Generated_Deviation_Lines Layer ---

            # # --- Finalize Debug Layer ---
            # if deviation_connectors_layer and deviation_provider:
            #     if not deviation_connectors_layer.commitChanges():
            #          log.error(f"Failed commit debug connectors: {deviation_connectors_layer.commitErrors()}")
            #     if deviation_connectors_layer.featureCount() > 0:
            #          project.addMapLayer(deviation_connectors_layer)
            #          try:
            #             # Style the debug layer based on Smoothing Status
            #             categories = []
            #             symbols = { # Define symbols for each status
            #                 "Success": QgsLineSymbol.createSimple({'color': '#00DD00', 'width': '0.7'}), # Green
            #                 "Success (Obstacle Check Skipped)": QgsLineSymbol.createSimple({'color': '#90EE90', 'width': '0.7', 'line_style': 'dash'}),
            #                 "Validation Failed": QgsLineSymbol.createSimple({'color': '#FFA500', 'width': '0.7', 'line_style': 'dash'}),
            #                 "Sharp Geom Invalid": QgsLineSymbol.createSimple({'color': '#FF0000', 'width': '0.7', 'line_style': 'dot'}),
            #                 "Densify Failed": QgsLineSymbol.createSimple({'color': '#FF00FF', 'width': '0.7', 'line_style': 'dash'}),
            #                 "Smooth Failed (Empty)": QgsLineSymbol.createSimple({'color': '#FF00FF', 'width': '0.7', 'line_style': 'dot'}),
            #                 "Not Attempted": QgsLineSymbol.createSimple({'color': '#888888', 'width': '0.5'}),
            #                 "Error": QgsLineSymbol.createSimple({'color': '#AA0000', 'width': '1.0', 'line_style': 'dashdot'}), # Dark Red for Errors
            #             }
            #             default_symbol = QgsLineSymbol.createSimple({'color': '#555555', 'width': '0.5', 'line_style': 'dot'}) # Default Grey Dotted

            #             status_values = set()
            #             for f in deviation_connectors_layer.getFeatures():
            #                 status_val = f['Status']
            #                 if status_val and isinstance(status_val, str):
            #                    if status_val.startswith("Error:"): status_values.add("Error") # Group all errors
            #                    else: status_values.add(status_val)
            #                 elif status_val is None or status_val == NULL:
            #                      status_values.add("Unknown/NULL")

            #             # Create categories only for statuses that actually occurred
            #             for status in status_values:
            #                 sym = symbols.get(status, default_symbol) # Use specific symbol or fallback
            #                 cat_value = status if status != "Unknown/NULL" else NULL
            #                 categories.append(QgsRendererCategory(cat_value, sym, status))

            #             # renderer = QgsCategorizedSymbolRenderer("Status", categories)
            #             # deviation_connectors_layer.setRenderer(renderer)
            #             # deviation_connectors_layer.triggerRepaint()

            #          except Exception as style_ex: log.warning(f"Could not style debug connector layer: {style_ex}")
            #     else: log.warning("No deviation connector paths generated for debug layer.")

            # --- Display Path Options Table ---
            if hasattr(self, 'path_options') and self.path_options:
                 log.info(f"[DISPLAY] Calling display table. self.path_options keys: {list(self.path_options.keys())}")
                 if not hasattr(self, 'chosen_paths'): self.chosen_paths = chosen_paths
                 self._display_path_options_table()
            else: log.warning("No path options recorded.")

            return True # Indicate overall success

        except Exception as e:
             log.exception(f"Error during complete deviation calculation (Merging Version): {e}")
             if edit_started_here and lines_layer.isEditable():
                 log.info("Rolling back lines layer due to error.")
                 lines_layer.rollBack()
             if deviation_connectors_layer and deviation_connectors_layer.isEditable():
                 log.info("Rolling back debug connector layer.")
                 deviation_connectors_layer.rollBack()
             return False # Indicate failure
    # <<< Function End: _complete_deviation_calculation >>>

    # <<< Function Start: _merge_line_segments (Use Original Heading) >>>
    def _merge_line_segments(self, segments_by_line, target_fields, original_feature_attributes, turn_radius_m):
        """
        Merges collected line segments (outside, connector) for each line number
        into a single feature, using the original line's heading. Includes manual
        ordering fallback if QgsGeometryUtils.mergeLines is unavailable/fails.

        Args:
            segments_by_line (dict): {line_num: [list_of_QgsFeature_segments]}
            target_fields (QgsFields): Fields definition for the output layer.
            original_feature_attributes (dict): {original_fid: [attributes]}
            turn_radius_m (float): Turn radius for potential re-smoothing params.

        Returns:
            list: A list of new QgsFeature objects, one for each merged line.
        """
        log.info(f"Starting merge process for {len(segments_by_line)} lines (Manual Fallback - Use Original Heading)...")
        merged_features = []
        # --- Field Index Lookups ---
        fld_linenum_idx = target_fields.lookupField("LineNum")
        fld_status_idx = target_fields.lookupField("Status")
        fld_length_idx = target_fields.lookupField("Length_m")
        fld_heading_idx = target_fields.lookupField("Heading") # Index for Heading field
        fld_lsp_idx = target_fields.lookupField("LowestSP")
        fld_hsp_idx = target_fields.lookupField("HighestSP")
        fld_lsx_idx = target_fields.lookupField("LowestSP_x")
        fld_lsy_idx = target_fields.lookupField("LowestSP_y")
        fld_hsx_idx = target_fields.lookupField("HighestSP_x")
        fld_hsy_idx = target_fields.lookupField("HighestSP_y")
        fld_is_conflicted_idx = target_fields.lookupField("is_conflicted")
        fld_is_dev_created_idx = target_fields.lookupField("is_deviation_created")
        fld_is_merged_idx = target_fields.lookupField("is_line_merged")
        fld_seg_type_idx = target_fields.lookupField("SegmentType")
        # --- End Field Index Lookups ---

        # --- Re-smoothing & Connection Params ---
        densify_factor_merge = 8.0
        smooth_iterations_merge = 8
        smooth_offset_merge = 0.4
        connect_tolerance = 0.1
        # --- End Params ---

        for line_num, segment_features in segments_by_line.items():
            QApplication.processEvents()
            log.debug(f"  Merging {len(segment_features)} segments for Line {line_num}")
            if not segment_features:
                log.warning(f"  Skipping Line {line_num}: No segments provided.")
                continue

            valid_segment_geometries = []
            valid_segments_with_info = []
            log.debug(f"  Filtering {len(segment_features)} input segments for Line {line_num}...")
            for idx, feat in enumerate(segment_features):
                 # ... (Filtering logic as in the previous working version - using is_line_type, isValid, etc.) ...
                 geom = feat.geometry()
                 segment_valid = False
                 if geom and not geom.isEmpty():
                      is_line = is_line_type(geom.wkbType())
                      is_valid = geom.isGeosValid()
                      if is_line and is_valid:
                           try:
                                start_pt = QgsPointXY(geom.vertexAt(0))
                                vertices = list(geom.vertices())
                                if len(vertices) > 0:
                                     end_pt = QgsPointXY(vertices[-1])
                                     if start_pt and end_pt:
                                          valid_segment_geometries.append(geom)
                                          valid_segments_with_info.append({'idx': idx, 'geom': geom, 'start_pt': start_pt, 'end_pt': end_pt, 'feature': feat})
                                          segment_valid = True
                                     else: log.warning(f"    L{line_num} Seg {idx}: Could not get valid start/end points despite being line type.")
                                else: log.warning(f"    L{line_num} Seg {idx}: Geometry is a line but has no vertices.")
                           except Exception as e: log.warning(f"    L{line_num} Seg {idx}: Error getting points: {e}. Skipping for manual merge.")
                      else: log.warning(f"    L{line_num} Seg {idx}: Skipped - IsLine={is_line}, IsValid={is_valid}")
                 else: log.warning(f"    L{line_num} Seg {idx}: Skipped - Geometry is None or Empty.")

                 if not segment_valid:
                     geom_type_str = QgsWkbTypes.displayString(geom.wkbType()) if geom else 'None'
                     log.warning(f"  -> Skipped segment {idx} for Line {line_num}. Reason: Invalid/Empty/Non-Line. Type: {geom_type_str}, IsValid: {geom.isGeosValid() if geom else 'N/A'}")


            log.debug(f"  Line {line_num}: Found {len(valid_segments_with_info)} valid segments for merging.")
            if len(valid_segments_with_info) < 1:
                 log.warning(f"  Skipping Line {line_num}: No valid geometries remain after filtering for manual merge.")
                 continue

            merged_geom = None

            # --- Attempt Merge using QGIS Utils (if available) ---
            # ... (Same try/except block for mergeLines using valid_segment_geometries) ...
            try:
                if hasattr(QgsGeometryUtils, 'mergeLines') and len(valid_segment_geometries) > 0:
                    merged_geom = QgsGeometryUtils.mergeLines(valid_segment_geometries)
                    log.debug(f"  Line {line_num}: Attempted mergeLines.")
                    if merged_geom and not merged_geom.isEmpty() and is_line_type(merged_geom.wkbType()):
                        if merged_geom.isMultipart():
                            log.debug(f"  Line {line_num}: mergeLines produced MultiLine. Falling back to manual merge for guaranteed ordering.")
                            merged_geom = None

                        if merged_geom:
                            log.debug(f"  Line {line_num}: mergeLines successful.")
                        else:
                            log.warning(f"  Line {line_num}: Failed to force Single part.")
                    else:
                        wkb_type_str = QgsWkbTypes.displayString(merged_geom.wkbType()) if merged_geom else 'None'
                        log.warning(f"  Line {line_num}: mergeLines failed or produced Invalid (Type: {wkb_type_str}). Falling back to manual merge.")
                        merged_geom = None
                else:
                     log.info("  QgsGeometryUtils.mergeLines not available or no valid geometries for it. Proceeding with manual merge.")
                     merged_geom = None
            except Exception as merge_util_err:
                 log.warning(f"  Error during mergeLines for Line {line_num}: {merge_util_err}. Falling back to manual merge.")
                 merged_geom = None


            # --- Manual Merge Fallback (Using valid_segments_with_info) ---
            if merged_geom is None:
                # ... (Manual merge logic - SAME AS PREVIOUS WORKING VERSION) ...
                log.debug(f"  Attempting manual merge for Line {line_num} using {len(valid_segments_with_info)} valid segments...")
                if not valid_segments_with_info:
                     log.error(f"  Cannot manually merge Line {line_num}: No valid segments available for manual merge.")
                     continue

                try:
                    # 1. Find the starting segment
                    original_fid_for_line = None
                    original_lsx = None; original_lsy = None
                    for fid, attrs in original_feature_attributes.items():
                         try:
                                  if fld_linenum_idx != -1 and len(attrs) > fld_linenum_idx and str(attrs[fld_linenum_idx]) == str(line_num):
                                   original_fid_for_line = fid
                                   if fld_lsx_idx != -1 and fld_lsy_idx != -1:
                                        original_lsx = attrs[fld_lsx_idx]
                                        original_lsy = attrs[fld_lsy_idx]
                                   break
                         except (TypeError, IndexError): continue

                    if original_lsx is None or original_lsy is None:
                        log.warning(f"  Cannot manually merge Line {line_num}: Missing original LowestSP coordinates in cache.")
                        continue

                    original_start_point = QgsPointXY(original_lsx, original_lsy)
                    start_segment_info = None
                    min_start_dist_sq = float('inf')

                    for seg_info in valid_segments_with_info:
                        dist_sq = original_start_point.sqrDist(seg_info['start_pt'])
                        if dist_sq < min_start_dist_sq:
                            min_start_dist_sq = dist_sq
                            start_segment_info = seg_info

                    if start_segment_info is None or min_start_dist_sq > (connect_tolerance * 5)**2:
                        log.warning(f"  Cannot manually merge Line {line_num}: Could not identify a valid start segment close enough to original start (MinDistSq: {min_start_dist_sq}).")
                        continue

                    # 2. Order segments
                    ordered_segments_info = []
                    remaining_segments_info = valid_segments_with_info[:]
                    current_segment_info = None

                    for i in range(len(remaining_segments_info)):
                         if remaining_segments_info[i]['idx'] == start_segment_info['idx']:
                              current_segment_info = remaining_segments_info.pop(i)
                              break

                    if not current_segment_info:
                        log.error(f"  Internal error: Start segment info not found in valid list for Line {line_num}.")
                        continue

                    ordered_segments_info.append(current_segment_info)
                    final_vertices = list(current_segment_info['geom'].vertices())

                    while remaining_segments_info:
                        found_next = False
                        current_end_pt = QgsPointXY(final_vertices[-1])
                        best_match_idx = -1
                        min_connect_dist_sq = (connect_tolerance * 50)**2  # Increased connection tolerance (~5 meters)
                        reverse_next = False

                        for i in range(len(remaining_segments_info)):
                            next_seg_info = remaining_segments_info[i]
                            
                            dist_to_start_sq = current_end_pt.sqrDist(next_seg_info['start_pt'])
                            if dist_to_start_sq < min_connect_dist_sq:
                                min_connect_dist_sq = dist_to_start_sq
                                best_match_idx = i
                                reverse_next = False
                                found_next = True
                            
                            dist_to_end_sq = current_end_pt.sqrDist(next_seg_info['end_pt'])
                            if dist_to_end_sq < min_connect_dist_sq:
                                min_connect_dist_sq = dist_to_end_sq
                                best_match_idx = i
                                reverse_next = True
                                found_next = True

                        if found_next:
                             current_segment_info = remaining_segments_info.pop(best_match_idx)
                             ordered_segments_info.append(current_segment_info)
                             next_vertices = list(current_segment_info['geom'].vertices())
                             if reverse_next:
                                 next_vertices.reverse()
                             if len(next_vertices) > 1:
                                 final_vertices.extend(next_vertices[1:])
                        else:
                             log.warning(f"  Manual merge stopped for Line {line_num}: Could not find connecting segment after segment {len(ordered_segments_info)} ending at ({current_end_pt.x():.1f}, {current_end_pt.y():.1f}). Segments remaining: {len(remaining_segments_info)}")
                             final_vertices = None
                             break

                    # 3. Create Merged Geometry
                    if final_vertices and len(final_vertices) >= 2:
                         final_vertices_xy = [QgsPointXY(pt) for pt in final_vertices]
                         merged_geom = QgsGeometry.fromPolylineXY(final_vertices_xy)
                         if merged_geom.isEmpty() or not merged_geom.isGeosValid():
                              log.error(f"  Manual merge for Line {line_num} produced invalid geometry.")
                              merged_geom = None
                         else:
                              log.info(f"  Manual merge successful for Line {line_num}.")
                    else:
                         log.error(f"  Manual merge failed for Line {line_num}: Not enough vertices or connection failed.")
                         merged_geom = None

                except Exception as manual_err:
                    log.exception(f"  Exception during manual merge for Line {line_num}: {manual_err}")
                    merged_geom = None
            # --- End Manual Merge Fallback ---

            if merged_geom is None:
                log.error(f"  Failed to create a valid merged geometry for Line {line_num}. Skipping feature creation.")
                continue

            # --- Optional: Re-Smooth ---
            # ... (Re-smoothing logic - SAME AS PREVIOUS VERSION) ...
            final_geom = merged_geom
            try:
                log.debug(f"  Attempting re-smoothing for merged Line {line_num}...")
                densify_dist_merge = max(1.0, turn_radius_m / densify_factor_merge)
                densified_merge = merged_geom.densifyByDistance(densify_dist_merge)
                if not densified_merge.isEmpty():
                    smoothed_merge = densified_merge.smooth(smooth_iterations_merge, smooth_offset_merge)
                    if not smoothed_merge.isEmpty() and smoothed_merge.isGeosValid():
                         orig_start_re = QgsPointXY(merged_geom.vertexAt(0))
                         mg_vertices = list(merged_geom.vertices())
                         orig_end_re = QgsPointXY(mg_vertices[-1]) if mg_vertices else None
                         smooth_start_re = QgsPointXY(smoothed_merge.vertexAt(0))
                         sm_vertices = list(smoothed_merge.vertices())
                         smooth_end_re = QgsPointXY(sm_vertices[-1]) if sm_vertices else None

                         if orig_end_re and smooth_end_re and \
                            orig_start_re.distance(smooth_start_re) < 1.0 and \
                            orig_end_re.distance(smooth_end_re) < 1.0:
                              log.info(f"  Re-smoothing successful for Line {line_num}. Final length: {smoothed_merge.length():.1f}m")
                              final_geom = smoothed_merge
                         else:
                              log.warning(f"  Re-smoothing endpoint shift too large or failed for Line {line_num}. Using un-smoothed merged geometry.")
                    else:
                         log.warning(f"  Re-smoothing failed (empty/invalid) for Line {line_num}. Using un-smoothed merged geometry.")
                else:
                     log.warning(f"  Densification for re-smoothing failed for Line {line_num}. Using un-smoothed merged geometry.")
            except Exception as smooth_err:
                log.warning(f"  Error during re-smoothing for Line {line_num}: {smooth_err}. Using un-smoothed merged geometry.")
            # --- End Re-Smoothing ---

            # --- Create Final Feature ---
            merged_feature = QgsFeature(target_fields)
            merged_feature.setGeometry(final_geom)

            # --- Populate Attributes ---
            original_attrs = None; original_fid = None
            for fid, attrs in original_feature_attributes.items():
                 try:
                          if fld_linenum_idx != -1 and len(attrs) > fld_linenum_idx and str(attrs[fld_linenum_idx]) == str(line_num):
                           original_attrs = attrs; original_fid = fid; break
                 except (TypeError, IndexError): continue

            if original_attrs is None:
                log.warning(f"  Could not find original attributes for Line {line_num} to copy from. Using defaults.")
                original_attrs = [NULL] * target_fields.count()
                if fld_linenum_idx != -1: original_attrs[fld_linenum_idx] = line_num
                if fld_status_idx != -1: original_attrs[fld_status_idx] = "To Be Acquired"

            attributes = list(original_attrs)
            if fld_length_idx != -1: attributes[fld_length_idx] = final_geom.length()
            if fld_is_conflicted_idx != -1: attributes[fld_is_conflicted_idx] = True
            if fld_is_dev_created_idx != -1: attributes[fld_is_dev_created_idx] = True
            if fld_is_merged_idx != -1: attributes[fld_is_merged_idx] = True
            if fld_seg_type_idx != -1: attributes[fld_seg_type_idx] = NULL

            # --- Use ORIGINAL Heading ---
            original_heading = NULL
            if original_attrs and fld_heading_idx != -1 and len(original_attrs) > fld_heading_idx:
                original_heading = original_attrs[fld_heading_idx]
                if original_heading is None or original_heading == NULL:
                     log.warning(f"  Original heading for Line {line_num} was NULL in cache.")

            if fld_heading_idx != -1:
                 attributes[fld_heading_idx] = original_heading # Assign original heading
                 log.debug(f"  Assigned original heading {original_heading} to merged Line {line_num}")
            else:
                 log.warning(f"  Heading field index invalid, cannot assign original heading to Line {line_num}")
            # --- End Original Heading ---

            # --- Update start/end points based on FINAL geometry ---
            try:
                final_vertices = list(final_geom.vertices())
                if len(final_vertices) >= 2:
                    start_pt = final_vertices[0]; end_pt = final_vertices[-1]
                    if fld_lsx_idx != -1: attributes[fld_lsx_idx] = start_pt.x()
                    if fld_lsy_idx != -1: attributes[fld_lsy_idx] = start_pt.y()
                    if fld_hsx_idx != -1: attributes[fld_hsx_idx] = end_pt.x()
                    if fld_hsy_idx != -1: attributes[fld_hsy_idx] = end_pt.y()
                    log.debug(f"  Updated start/end coordinates for merged Line {line_num}")
                else:
                    log.warning(f"  Merged geom for Line {line_num} has < 2 vertices. Cannot update coords.")
                    # Clear coordinate attributes if vertices are insufficient
                    if fld_lsx_idx != -1: attributes[fld_lsx_idx] = NULL
                    if fld_lsy_idx != -1: attributes[fld_lsy_idx] = NULL
                    if fld_hsx_idx != -1: attributes[fld_hsx_idx] = NULL
                    if fld_hsy_idx != -1: attributes[fld_hsy_idx] = NULL
            except Exception as attr_err:
                 log.warning(f"  Error updating coordinates for merged Line {line_num}: {attr_err}")
                 # Clear coordinate attributes on error
                 if fld_lsx_idx != -1: attributes[fld_lsx_idx] = NULL
                 if fld_lsy_idx != -1: attributes[fld_lsy_idx] = NULL
                 if fld_hsx_idx != -1: attributes[fld_hsx_idx] = NULL
                 if fld_hsy_idx != -1: attributes[fld_hsy_idx] = NULL
            # --- End Update start/end points ---

            merged_feature.setAttributes(attributes)
            merged_features.append(merged_feature)
            log.info(f"  Prepared merged feature for Line {line_num}.")

        # --- End Line Loop ---

        log.info(f"Finished merging. Generated {len(merged_features)} final merged features.")
        return merged_features
    # <<< Function End: _merge_line_segments >>>


    # Add the helper function if it's not already present or reliable
    def _create_temp_deviation_polygon(self, segment_geom, obstacle_buffer, clearance, turn_radius, fallback_heading):
        """Helper to create a temporary deviation polygon for splitting a specific segment."""
        try:
            # Use obstacle centroid as reference, similar to original peak calc
            obstacle_center_geom = obstacle_buffer.centroid()
            if not obstacle_center_geom or obstacle_center_geom.isEmpty(): return None
            obstacle_center_xy = QgsPointXY(obstacle_center_geom.asPoint())

            # Get segment heading or use fallback
            qgis_heading = self._calculate_geom_heading(segment_geom)
            if qgis_heading is None: qgis_heading = fallback_heading

            # Simple projection for temporary polygon - size based on clearance/radius
            entry_exit_distance = max(500.0, turn_radius * 0.5) # Smaller distance than original helpers
            qgis_angle_rad = math.radians(qgis_heading)
            helper_entry = QgsPointXY(obstacle_center_xy.x()-entry_exit_distance*math.sin(qgis_angle_rad), obstacle_center_xy.y()-entry_exit_distance*math.cos(qgis_angle_rad))
            helper_exit = QgsPointXY(obstacle_center_xy.x()+entry_exit_distance*math.sin(qgis_angle_rad), obstacle_center_xy.y()+entry_exit_distance*math.cos(qgis_angle_rad))

            mid_x = (helper_entry.x() + helper_exit.x()) / 2
            mid_y = (helper_entry.y() + helper_exit.y()) / 2
            dx = helper_exit.x() - helper_entry.x()
            dy = helper_exit.y() - helper_entry.y()
            length = math.sqrt(dx**2 + dy**2)
            if length > 1e-8: dx_norm, dy_norm = dx/length, dy/length
            else: heading_rad_math = math.radians((90.0-qgis_heading+360)%360); dx_norm, dy_norm = math.cos(heading_rad_math), math.sin(heading_rad_math)

            perp_dx1, perp_dy1 = -dy_norm, dx_norm
            perp_dx2, perp_dy2 = dy_norm, -dx_norm
            peak_dist = clearance # Strict clearance distance

            peak_a_point = QgsPointXY(mid_x + perp_dx1 * peak_dist, mid_y + perp_dy1 * peak_dist)
            peak_b_point = QgsPointXY(mid_x + perp_dx2 * peak_dist, mid_y + perp_dy2 * peak_dist)

            poly_points = [helper_entry, peak_a_point, helper_exit, peak_b_point, helper_entry]
            deviation_poly = QgsGeometry.fromPolygonXY([poly_points])
            if not deviation_poly.isGeosValid(): deviation_poly = deviation_poly.makeValid()
            if not deviation_poly.isGeosValid(): return None
            return deviation_poly
        except Exception as e:
            log.warning(f"Failed to create temp deviation polygon: {e}")
            return None

    def _record_path_option(self, path_options, line_num, peak_label, path_length, entry_point, peak_point, exit_point, obstacle_id):
        """
        Record a path option in the options table for later analysis.
        Corresponds to storing results of Step 9 evaluation.

        Args:
            path_options (dict): Dictionary to store path options.
            line_num (int): Line number.
            peak_label (str): Label for peak (A or B).
            path_length (float): Calculated path length.
            entry_point (QgsPointXY): Entry point (result of Step 5).
            peak_point (QgsPointXY): Peak point (result of Step 4).
            exit_point (QgsPointXY): Exit point (result of Step 5).
            obstacle_id (int): ID of the obstacle.

        Returns:
            None: Updates path_options dictionary in place.
        """
        source = "Direct" # Source identifier

        log.info(f"[RECORD-{source}] Recording path option for Line {line_num}, Peak {peak_label}, Obstacle {obstacle_id}")
        log.info(f"[RECORD-{source}] Type of path_options: {type(path_options)}, contains: {list(path_options.keys()) if isinstance(path_options, dict) else 'NOT A DICT'}")

        # Ensure points are QgsPointXY
        entry_point_xy = QgsPointXY(entry_point) if not isinstance(entry_point, QgsPointXY) else entry_point
        peak_point_xy = QgsPointXY(peak_point) if not isinstance(peak_point, QgsPointXY) else peak_point
        exit_point_xy = QgsPointXY(exit_point) if not isinstance(exit_point, QgsPointXY) else exit_point

        # Initialize entry for this line if it doesn't exist
        if line_num not in path_options:
            path_options[line_num] = []

        # Record this path option
        path_options[line_num].append({
            'peak': peak_label,
            'length': path_length,
            'entry': entry_point_xy,       # Store QgsPointXY
            'peak_point': peak_point_xy,   # Store QgsPointXY
            'exit': exit_point_xy,         # Store QgsPointXY
            'obstacle_id': obstacle_id
        })

    # Helper function needed by _process_conflicted_lines
    def _calculate_path_length(self, point1, point2, point3):
        """ Calculate the total length of a three-point path. """
        length1 = math.sqrt((point2.x() - point1.x())**2 + (point2.y() - point1.y())**2)
        length2 = math.sqrt((point3.x() - point2.x())**2 + (point3.y() - point2.y())**2)
        return length1 + length2

    # Helper function needed by _process_conflicted_lines
    def _find_closest_point_on_line(self, line_points, target_point):
        """ Find the closest point on a line (list of QgsPointXY) to a target point. """
        if not line_points or len(line_points) < 2: return None
        min_dist_sq = float('inf'); closest_idx = -1; closest_proj = None

        for i in range(len(line_points) - 1):
            p1 = line_points[i]; p2 = line_points[i+1]
            len_sq = p1.sqrDist(p2)
            if len_sq < 1e-12: continue # Avoid division by zero for coincident points

            # Project target point onto the line segment defined by p1, p2
            # Vector v = p2 - p1; Vector w = target - p1
            vx = p2.x() - p1.x(); vy = p2.y() - p1.y()
            wx = target_point.x() - p1.x(); wy = target_point.y() - p1.y()

            dot_vw = wx * vx + wy * vy
            t = dot_vw / len_sq # Parameter along the segment (0=p1, 1=p2)
            t = max(0.0, min(1.0, t)) # Clamp t to be within the segment [0, 1]

            # Calculate projected point coordinates
            proj_x = p1.x() + t * vx
            proj_y = p1.y() + t * vy
            proj_pt = QgsPointXY(proj_x, proj_y)

            # Calculate distance squared from target to projected point
            dist_sq = target_point.sqrDist(proj_pt)

            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                closest_idx = i
                closest_proj = proj_pt # This is the projection ON the segment

        if closest_proj is None: return None

        return (closest_idx, closest_proj, math.sqrt(min_dist_sq))


    def _point_near_segment(self, point, segment_start, segment_end, tolerance=1.0):
        """
        Check if a point is near a line segment within tolerance.

        Args:
            point (QgsPointXY): Point to check
            segment_start (QgsPointXY): Start point of segment
            segment_end (QgsPointXY): End point of segment
            tolerance (float): Distance tolerance

        Returns:
            bool: True if point is near segment, False otherwise
        """
        # Create geometries
        pt_geom = QgsGeometry.fromPointXY(point)
        line_geom = QgsGeometry.fromPolylineXY([segment_start, segment_end])

        # Check distance
        return pt_geom.distance(line_geom) <= tolerance

    def _debug_line_splitting(self, stage, line_num, fid, line_geom, deviation_poly, split_result=None):
        """
        Comprehensive debugging for line splitting operations.

        Args:
            stage (str): Current processing stage name
            line_num (int): Line number being processed
            fid (int): Feature ID being processed
            line_geom (QgsGeometry): Line geometry being processed
            deviation_poly (QgsGeometry): Deviation polygon geometry
            split_result (QgsGeometry, optional): Result of a splitting operation
        """
        log.info(f"===== DEBUG: {stage} for Line {line_num} (FID={fid}) =====")

        # Log line geometry properties
        if line_geom is None:
            log.info("  LINE GEOMETRY: None")
        elif line_geom.isEmpty():
            log.info("  LINE GEOMETRY: Empty")
        else:
            line_type = "Unknown"
            if line_geom.type() == QgsWkbTypes.LineGeometry:
                if line_geom.isMultipart():
                    parts = line_geom.asMultiPolyline()
                    total_vertices = sum(len(part) for part in parts)
                    line_type = f"MultiLine with {len(parts)} parts, {total_vertices} total vertices"
                else:
                    points = line_geom.asPolyline()
                    line_type = f"Line with {len(points)} vertices"
                    if len(points) >= 2:
                        log.info(f"  LINE START: ({points[0].x():.2f}, {points[0].y():.2f})")
                        log.info(f"  LINE END: ({points[-1].x():.2f}, {points[-1].y():.2f})")

            log.info(f"  LINE TYPE: {line_type}")
            log.info(f"  LINE LENGTH: {line_geom.length():.2f}")
            log.info(f"  LINE VALID: {line_geom.isGeosValid()}")

        # Log polygon properties
        if deviation_poly is None:
            log.info("  POLYGON: None")
        elif deviation_poly.isEmpty():
            log.info("  POLYGON: Empty")
        else:
            log.info(f"  POLYGON TYPE: {'Multipart' if deviation_poly.isMultipart() else 'Single part'}")
            log.info(f"  POLYGON AREA: {deviation_poly.area():.2f}")
            log.info(f"  POLYGON VALID: {deviation_poly.isGeosValid()}")

        # Log spatial relationships
        if line_geom and not line_geom.isEmpty() and deviation_poly and not deviation_poly.isEmpty():
            log.info(f"  INTERSECTS: {line_geom.intersects(deviation_poly)}")
            log.info(f"  TOUCHES: {line_geom.touches(deviation_poly)}")
            log.info(f"  WITHIN: {line_geom.within(deviation_poly)}")
            log.info(f"  DISTANCE: {line_geom.distance(deviation_poly):.2f}")

            # Check result of intersection
            intersection = line_geom.intersection(deviation_poly)
            if intersection.isEmpty():
                log.info("  INTERSECTION RESULT: Empty")
            else:
                int_type = "Unknown"
                if intersection.type() == QgsWkbTypes.PointGeometry:
                    if intersection.isMultipart():
                        int_type = f"MultiPoint with {len(intersection.asMultiPoint())} points"
                    else:
                        point = intersection.asPoint()
                        int_type = f"Point at ({point.x():.2f}, {point.y():.2f})"
                elif intersection.type() == QgsWkbTypes.LineGeometry:
                    if intersection.isMultipart():
                        parts = intersection.asMultiPolyline()
                        int_type = f"MultiLine with {len(parts)} parts"
                    else:
                        points = intersection.asPolyline()
                        int_type = f"Line with {len(points)} vertices, length {intersection.length():.2f}"

                log.info(f"  INTERSECTION RESULT: {int_type}")

            # Check result of difference
            difference = line_geom.difference(deviation_poly)
            if difference.isEmpty():
                log.info("  DIFFERENCE RESULT: Empty")
            else:
                diff_type = "Unknown"
                if difference.type() == QgsWkbTypes.LineGeometry:
                    if difference.isMultipart():
                        parts = difference.asMultiPolyline()
                        diff_type = f"MultiLine with {len(parts)} parts"
                    else:
                        points = difference.asPolyline()
                        diff_type = f"Line with {len(points)} vertices, length {difference.length():.2f}"

                log.info(f"  DIFFERENCE RESULT: {diff_type}")

        # Log split result
        if split_result is not None:
            if split_result.isEmpty():
                log.info("  SPLIT RESULT: Empty")
            else:
                split_type = "Unknown"
                if split_result.type() == QgsWkbTypes.LineGeometry:
                    if split_result.isMultipart():
                        parts = split_result.asMultiPolyline()
                        split_type = f"MultiLine with {len(parts)} parts"

                        # Log details of each part
                        for i, part in enumerate(parts):
                            log.info(f"  SPLIT PART {i+1}: {len(part)} vertices, length ≈ {QgsGeometry.fromPolylineXY(part).length():.2f}")
                    else:
                        points = split_result.asPolyline()
                        split_type = f"Line with {len(points)} vertices, length {split_result.length():.2f}"

                log.info(f"  SPLIT RESULT: {split_type}")

        log.info("=" * 50)

    def _display_path_options_table(self):
        """
        Display a summary table of all path options analyzed during deviation calculation.
        This provides a comprehensive view of all options considered and which ones were chosen.
        """
        if not hasattr(self, 'path_options') or not self.path_options:
            log.warning("No path options to display")
            return

        # Start the table output
        log.info("========== PATH OPTIONS SUMMARY ==========")
        log.info("Line | Obstacle | Via Peak | Length (m) | Status")
        log.info("------|----------|----------|------------|--------")

        # Sort by line number for consistent output
        sorted_lines = sorted(self.path_options.keys())

        # Track lines with no chosen paths for diagnostics
        lines_without_choices = []
        total_options = 0
        total_chosen = 0

        for line_num in sorted_lines:
            options = self.path_options[line_num]
            total_options += len(options)

            # Get chosen paths for this line
            chosen_paths = self.chosen_paths.get(line_num, [])
            if not chosen_paths:
                lines_without_choices.append(line_num)

            # Organize by obstacle ID
            options_by_obstacle = {}
            for opt in options:
                obs_id = opt.get('obstacle_id', -1)
                if obs_id not in options_by_obstacle:
                    options_by_obstacle[obs_id] = []
                options_by_obstacle[obs_id].append(opt)

            # Process each obstacle's options for this line
            for obs_id, obs_options in sorted(options_by_obstacle.items()):
                first_row = True

                # Find chosen path for this obstacle
                chosen_peak = None
                for chosen in chosen_paths:
                    if chosen.get('obstacle_id') == obs_id:
                        chosen_peak = chosen.get('peak')
                        total_chosen += 1
                        break
                    
                # Display options for this obstacle
                for opt in sorted(obs_options, key=lambda x: x['peak']):
                    peak = opt['peak']
                    length = opt['length']

                    # First row shows line number, subsequent rows don't
                    line_display = str(line_num) if first_row else " " * len(str(line_num))
                    first_row = False

                    # Status column
                    status = "CHOSEN" if peak == chosen_peak else ""

                    # Format and output the row
                    log.info(f"{line_display:5} | {obs_id:8} | {peak:8} | {length:10.2f} | {status}")

        # Display summary statistics
        log.info("==========================================")
        log.info(f"Total lines processed: {len(sorted_lines)}")
        log.info(f"Total path options: {total_options}")
        log.info(f"Total chosen paths: {total_chosen}")

        # Diagnostic information if some lines don't have chosen paths
        if lines_without_choices:
            log.warning(f"Lines without chosen paths: {', '.join(map(str, lines_without_choices))}")


    def _create_line_segment_from_point(self, line_points, target_point, from_target_to_end=True):
        """
        Create a line segment from the target point to either the start or end of the line.
        
        Args:
            line_points (list): List of QgsPointXY objects comprising the original line
            target_point (QgsPointXY): The target point to create segment from/to
            from_target_to_end (bool): If True, create segment from target point to line end
                                      If False, create segment from line start to target point
        
        Returns:
            QgsGeometry: The created line segment, or None if invalid
        """
        if not line_points or len(line_points) < 2:
            return None
        
        # Find the position on the line closest to the target point
        min_dist = float('inf')
        closest_idx = 0
        closest_proj = None
        
        # Iterate through line segments to find closest point
        for i in range(len(line_points) - 1):
            p1 = line_points[i]
            p2 = line_points[i+1]
            
            # Calculate projection onto line segment
            segment_length = math.sqrt((p2.x() - p1.x())**2 + (p2.y() - p1.y())**2)
            if segment_length < 1e-8:  # Near zero length
                continue
                
            # Vector from p1 to target
            v1x = target_point.x() - p1.x()
            v1y = target_point.y() - p1.y()
            
            # Unit vector along segment
            vx = (p2.x() - p1.x()) / segment_length
            vy = (p2.y() - p1.y()) / segment_length
            
            # Projection length
            proj = v1x * vx + v1y * vy
            
            # Clamp to segment
            proj = max(0, min(segment_length, proj))
            
            # Calculate distance to projection
            proj_x = p1.x() + proj * vx
            proj_y = p1.y() + proj * vy
            dist = math.sqrt((target_point.x() - proj_x)**2 + (target_point.y() - proj_y)**2)
            
            if dist < min_dist:
                min_dist = dist
                closest_idx = i
                closest_proj = QgsPointXY(proj_x, proj_y)
        
        # If no valid projection found, return None
        if closest_proj is None:
            return None
        
        # Create new point array for the segment
        segment_points = []
        
        if from_target_to_end:
            # Start with the target point
            segment_points.append(QgsPointXY(target_point))
            
            # Add rest of the points from the closest segment to the end
            segment_points.append(closest_proj)
            segment_points.extend(line_points[closest_idx+1:])
        else:
            # Start with line start up to the closest segment
            segment_points.extend(line_points[:closest_idx+1])
            segment_points.append(closest_proj)
            
            # End with the target point
            segment_points.append(QgsPointXY(target_point))
        
        # Create geometry from points
        if len(segment_points) >= 2:
            return QgsGeometry.fromPolylineXY(segment_points)
        
        return None
    
    def _create_line_segment_between_points(self, line_points, start_point, end_point):
        """
        Create a line segment between two points on an existing line.
        
        Args:
            line_points (list): List of QgsPointXY objects comprising the original line
            start_point (QgsPointXY): The start point to create segment from
            end_point (QgsPointXY): The end point to create segment to
        
        Returns:
            QgsGeometry: The created line segment, or None if invalid
        """
        if not line_points or len(line_points) < 2:
            return None
        
        # Find the positions on the line closest to the start and end points
        start_info = self._find_closest_point_on_line(line_points, start_point)
        end_info = self._find_closest_point_on_line(line_points, end_point)
        
        if not start_info or not end_info:
            return None
        
        start_idx, start_proj, _ = start_info
        end_idx, end_proj, _ = end_info
        
        # Ensure start comes before end on the line
        if start_idx > end_idx or (start_idx == end_idx and start_proj > end_proj):
            start_idx, end_idx = end_idx, start_idx
            start_proj, end_proj = end_proj, start_proj
        
        # Create new point array for the segment
        segment_points = []
        
        # Start with the first projection point
        segment_points.append(QgsPointXY(start_proj))
        
        # Add intermediate points if any
        if start_idx < end_idx:
            segment_points.extend(line_points[start_idx+1:end_idx+1])
        
        # End with the second projection point
        segment_points.append(QgsPointXY(end_proj))
        
        # Create geometry from points
        if len(segment_points) >= 2:
            return QgsGeometry.fromPolylineXY(segment_points)
        
        return None

    def _log_debug_geom(self, stage, geom, log_level="debug"):
        """Detailed geometry debugging logger with extensive information."""
        if geom is None:
            log_msg = f"[{stage}] GEOMETRY IS NONE"
            if log_level == "debug":
                log.debug(log_msg)
            elif log_level == "info":
                log.info(log_msg)
            elif log_level == "warning":
                log.warning(log_msg)
            elif log_level == "error":
                log.error(log_msg)
            return

        if geom.isEmpty():
            log_msg = f"[{stage}] GEOMETRY IS EMPTY"
        else:
            geom_type = "Unknown"
            if geom.type() == QgsWkbTypes.PointGeometry:
                geom_type = "Point"
                if geom.isMultipart():
                    count = len(geom.asMultiPoint())
                    geom_type = f"MultiPoint ({count} points)"
                else:
                    pt = geom.asPoint()
                    geom_type = f"Point ({pt.x():.4f}, {pt.y():.4f})"
            elif geom.type() == QgsWkbTypes.LineGeometry:
                geom_type = "Line"
                if geom.isMultipart():
                    count = len(geom.asMultiPolyline())
                    geom_type = f"MultiLine ({count} segments)"
                else:
                    points = geom.asPolyline()
                    geom_type = f"Line ({len(points)} vertices)"
            elif geom.type() == QgsWkbTypes.PolygonGeometry:
                geom_type = "Polygon"
                if geom.isMultipart():
                    count = len(geom.asMultiPolygon())
                    geom_type = f"MultiPolygon ({count} polygons)"
                else:
                    rings = geom.asPolygon()
                    if rings:
                        geom_type = f"Polygon ({len(rings)} rings, {len(rings[0])} vertices in outer ring)"

            log_msg = f"[{stage}] TYPE: {geom_type}, VALID: {geom.isGeosValid()}"

        if log_level == "debug":
            log.debug(log_msg)
        elif log_level == "info":
            log.info(log_msg)
        elif log_level == "warning":
            log.warning(log_msg)
        elif log_level == "error":
            log.error(log_msg)

    # def _calculate_segment_heading(self, segment_geom, from_point=None, start=True):
    #     """
    #     Calculate heading (in degrees) for a line segment.

    #     Args:
    #         segment_geom (QgsGeometry): Line segment geometry
    #         from_point (QgsPointXY, optional): Specific point to calculate heading from
    #         start (bool): Whether to calculate from start (True) or end (False) of segment
    #                      Only used if from_point is None

    #     Returns:
    #         float: Heading in degrees (0-360)
    #     """
    #     if segment_geom.isEmpty() or segment_geom.type() != QgsWkbTypes.LineGeometry:
    #         return 0

    #     segment_points = segment_geom.asPolyline()
    #     if len(segment_points) < 2:
    #         return 0

    #     # If from_point specified, find closest point and calculate heading from there
    #     if from_point is not None:
    #         # Convert to QgsPointXY if needed
    #         if not isinstance(from_point, QgsPointXY):
    #             from_point = QgsPointXY(from_point)

    #         # Find closest segment
    #         closest_info = self._find_closest_point_on_line(segment_points, from_point)
    #         if not closest_info:
    #             return 0

    #         segment_idx, _, _ = closest_info

    #         # Use this segment for heading calculation
    #         if segment_idx < len(segment_points) - 1:
    #             p1 = segment_points[segment_idx]
    #             p2 = segment_points[segment_idx + 1]
    #         else:
    #             # Use previous segment if at end
    #             p1 = segment_points[segment_idx - 1]
    #             p2 = segment_points[segment_idx]
    #     else:
    #         # Otherwise use start or end of segment
    #         if start:
    #             p1 = segment_points[0]
    #             p2 = segment_points[1]
    #         else:
    #             p1 = segment_points[-2]
    #             p2 = segment_points[-1]

    #     # Calculate heading (in degrees, clockwise from North)
    #     dx = p2.x() - p1.x()
    #     dy = p2.y() - p1.y()

    #     # Use atan2 to avoid division by zero
    #     angle_rad = math.atan2(dx, dy)  # Note: x,y order for consistent bearing

    #     # Convert to degrees and normalize to 0-360
    #     angle_deg = math.degrees(angle_rad)
    #     if angle_deg < 0:
    #         angle_deg += 360

    #     return angle_deg

    def _visualize_deviation_steps(self):
        """
        Creates temporary visualization layers to show the steps in the deviation calculation process.
        Visualizes:
        - Middle Reference Lines 
        - Obstacle Center Points
        - Perpendicular Lines from Center to Peaks
        - Peak Points A and B
        - Entry and Exit Points
        - Deviation Polygons

        This is intended for debugging and understanding the deviation calculation process.
        """
        log.info("Creating visualization layers for deviation calculation steps...")

        # Check if we have calculated data to visualize
        if not hasattr(self, 'all_reference_lines') or not self.all_reference_lines:
            log.warning("No deviation calculation data available for visualization.")
            QMessageBox.warning(self, "Visualization Error", 
                                "No deviation calculation data is available to visualize.\n"
                                "Please run the calculation first.")
            return False

        project = QgsProject.instance()

        # Create layers for each component
        reference_lines_layer = QgsVectorLayer("LineString?crs=EPSG:31984", "Debug_Reference_Lines", "memory")
        center_points_layer = QgsVectorLayer("Point?crs=EPSG:31984", "Debug_Obstacle_Centers", "memory")
        perpendicular_lines_layer = QgsVectorLayer("LineString?crs=EPSG:31984", "Debug_Perpendicular_Lines", "memory")
        peak_points_layer = QgsVectorLayer("Point?crs=EPSG:31984", "Debug_Peak_Points", "memory")
        entry_exit_points_layer = QgsVectorLayer("Point?crs=EPSG:31984", "Debug_Entry_Exit_Points", "memory")
        deviation_polygons_layer = QgsVectorLayer("Polygon?crs=EPSG:31984", "Debug_Deviation_Polygons", "memory")

        # Set up fields for the layers
        for layer in [reference_lines_layer, center_points_layer, perpendicular_lines_layer, 
                      peak_points_layer, entry_exit_points_layer, deviation_polygons_layer]:
            provider = layer.dataProvider()
            provider.addAttributes([
                QgsField("ObstacleID", QVariant.Int),
                QgsField("Description", QVariant.String)
            ])
            layer.updateFields()

        # Style the layers for better visualization
        # Reference Lines - Blue thick lines
        ref_symbol = QgsLineSymbol.createSimple({
            'line_color': '#0000FF',  # Blue
            'line_width': '0.6',
            'line_style': 'solid'
        })
        reference_lines_layer.renderer().setSymbol(ref_symbol)

        # Obstacle Centers - Red large points
        center_symbol = QgsMarkerSymbol.createSimple({
            'name': 'circle',
            'color': '#FF0000',  # Red
            'size': '4',
            'outline_style': 'solid',
            'outline_color': '#000000',
            'outline_width': '0.6'
        })
        center_points_layer.renderer().setSymbol(center_symbol)

        # Perpendicular Lines - Green dashed lines
        perp_symbol = QgsLineSymbol.createSimple({
            'line_color': '#00FF00',  # Green
            'line_width': '0.6',
            'line_style': 'dash'
        })
        perpendicular_lines_layer.renderer().setSymbol(perp_symbol)

        # Peak Points - Orange large points
        peak_symbol = QgsMarkerSymbol.createSimple({
            'name': 'circle',
            'color': '#FFA500',  # Orange
            'size': '5',
            'outline_style': 'solid',
            'outline_color': '#000000',
            'outline_width': '0.6'
        })
        peak_points_layer.renderer().setSymbol(peak_symbol)

        # Entry/Exit Points - Purple diamonds
        entry_exit_symbol = QgsMarkerSymbol.createSimple({
            'name': 'diamond',
            'color': '#800080',  # Purple
            'size': '5',
            'outline_style': 'solid',
            'outline_color': '#000000',
            'outline_width': '0.6'
        })
        entry_exit_points_layer.renderer().setSymbol(entry_exit_symbol)

        # Deviation Polygons - Yellow semi-transparent
        polygon_symbol = QgsFillSymbol.createSimple({
            'color': '#FFFF0060',  # Yellow with alpha
            'outline_color': '#FF9500',  # Orange outline
            'outline_width': '0.6',
            'outline_style': 'solid'
        })
        deviation_polygons_layer.renderer().setSymbol(polygon_symbol)

        # Populate the layers
        for obs_idx, ref_line_info in self.all_reference_lines.items():
            # Add Reference Line
            if 'geom' in ref_line_info:
                ref_feat = QgsFeature()
                ref_feat.setGeometry(ref_line_info['geom'])
                ref_feat.setAttributes([
                    obs_idx,
                    f"Middle Reference Line {ref_line_info.get('num', 'Unknown')}"
                ])
                reference_lines_layer.dataProvider().addFeature(ref_feat)

            # Add Obstacle Center Point
            if obs_idx in self.obstacle_centers:
                center_point = self.obstacle_centers[obs_idx]
                center_feat = QgsFeature()
                center_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(center_point)))
                center_feat.setAttributes([
                    obs_idx,
                    f"Obstacle Center {obs_idx}"
                ])
                center_points_layer.dataProvider().addFeature(center_feat)

            # Add Peak Points
            if obs_idx in self.all_peaks:
                peaks = self.all_peaks[obs_idx]

                # Peak A
                if 'A' in peaks:
                    peak_a_feat = QgsFeature()
                    peak_a_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(peaks['A'])))
                    peak_a_feat.setAttributes([
                        obs_idx,
                        f"Peak A for Obstacle {obs_idx}"
                    ])
                    peak_points_layer.dataProvider().addFeature(peak_a_feat)

                # Peak B
                if 'B' in peaks:
                    peak_b_feat = QgsFeature()
                    peak_b_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(peaks['B'])))
                    peak_b_feat.setAttributes([
                        obs_idx,
                        f"Peak B for Obstacle {obs_idx}"
                    ])
                    peak_points_layer.dataProvider().addFeature(peak_b_feat)

                # Perpendicular Lines from Center to Peaks
                if obs_idx in self.obstacle_centers:
                    center_point = self.obstacle_centers[obs_idx]
                    center_xy = QgsPointXY(center_point)

                    # Line to Peak A
                    if 'A' in peaks:
                        perp_a_feat = QgsFeature()
                        perp_a_feat.setGeometry(QgsGeometry.fromPolylineXY([
                            center_xy, 
                            QgsPointXY(peaks['A'])
                        ]))
                        perp_a_feat.setAttributes([
                            obs_idx,
                            f"Center to Peak A {obs_idx}"
                        ])
                        perpendicular_lines_layer.dataProvider().addFeature(perp_a_feat)

                    # Line to Peak B
                    if 'B' in peaks:
                        perp_b_feat = QgsFeature()
                        perp_b_feat.setGeometry(QgsGeometry.fromPolylineXY([
                            center_xy, 
                            QgsPointXY(peaks['B'])
                        ]))
                        perp_b_feat.setAttributes([
                            obs_idx,
                            f"Center to Peak B {obs_idx}"
                        ])
                        perpendicular_lines_layer.dataProvider().addFeature(perp_b_feat)

            # Add Entry/Exit Points
            if 'entry_point' in ref_line_info:
                entry_feat = QgsFeature()
                entry_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(ref_line_info['entry_point'])))
                entry_feat.setAttributes([
                    obs_idx,
                    f"Entry Point {obs_idx}"
                ])
                entry_exit_points_layer.dataProvider().addFeature(entry_feat)

            if 'exit_point' in ref_line_info:
                exit_feat = QgsFeature()
                exit_feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(ref_line_info['exit_point'])))
                exit_feat.setAttributes([
                    obs_idx,
                    f"Exit Point {obs_idx}"
                ])
                entry_exit_points_layer.dataProvider().addFeature(exit_feat)

            # Add Deviation Polygon
            if 'deviation_polygon' in ref_line_info:
                poly_feat = QgsFeature()
                poly_feat.setGeometry(ref_line_info['deviation_polygon'])
                poly_feat.setAttributes([
                    obs_idx,
                    f"Deviation Polygon {obs_idx}"
                ])
                deviation_polygons_layer.dataProvider().addFeature(poly_feat)

        # Update and add the layers to the project
        for layer in [deviation_polygons_layer, reference_lines_layer, perpendicular_lines_layer, 
                      entry_exit_points_layer, peak_points_layer, center_points_layer]:
            layer.updateExtents()
            if layer.featureCount() > 0:
                self._add_layer_to_lookahead_group(layer)

        # Refresh the canvas
        self._refresh_map_canvas_safe()

        log.info(f"Created {peak_points_layer.featureCount()} peak points, " +
                 f"{center_points_layer.featureCount()} center points, " +
                 f"{entry_exit_points_layer.featureCount()} entry/exit points, " +
                 f"{deviation_polygons_layer.featureCount()} deviation polygons")

        return True

    def _add_debug_layers(self, avoidance_geom, obstacle_geometries, clearance_m):
        """
        Creates temporary visualization layers for debugging the avoidance geometry
        and individual obstacle geometries.

        Args:
            avoidance_geom (QgsGeometry): The combined avoidance geometry (buffered NoGo zones)
            obstacle_geometries (list): List of individual obstacle geometries
            clearance_m (float): Clearance distance in meters

        Returns:
            QgsLayerTreeGroup: The group containing the debug layers
        """
        log.info("Creating debug visualization layers...")

        project = QgsProject.instance()
        root = project.layerTreeRoot()

        # Create a group for the debug layers
        group_name = f"Debug_NoGo_Analysis_{datetime.now().strftime('%H%M%S')}"
        lookahead_group = self._get_or_create_group("Lookahead")
        debug_group = lookahead_group.insertGroup(0, group_name)

        # Create a layer for the avoidance geometry
        avoidance_layer = QgsVectorLayer("Polygon?crs=EPSG:31984", f"NoGo_Buffer_{clearance_m}m", "memory")
        avoidance_provider = avoidance_layer.dataProvider()

        # Add fields
        avoidance_provider.addAttributes([
            QgsField("Buffer_m", QVariant.Double),
            QgsField("Description", QVariant.String)
        ])
        avoidance_layer.updateFields()

        # Add the avoidance geometry
        avoidance_feat = QgsFeature()
        avoidance_feat.setGeometry(avoidance_geom)
        avoidance_feat.setAttributes([
            clearance_m,
            f"NoGo zones with {clearance_m}m buffer"
        ])
        avoidance_provider.addFeature(avoidance_feat)

        # Style the avoidance layer
        avoidance_symbol = QgsFillSymbol.createSimple({
            'color': '#FF000040',  # Red with 25% opacity
            'outline_color': '#FF0000',  # Red outline
            'outline_width': '0.6',
            'outline_style': 'solid'
        })
        avoidance_layer.renderer().setSymbol(avoidance_symbol)

        # Create a layer for the individual obstacles
        obstacles_layer = QgsVectorLayer("Polygon?crs=EPSG:31984", "Individual_Obstacles", "memory")
        obstacles_provider = obstacles_layer.dataProvider()

        # Add fields for obstacles
        obstacles_provider.addAttributes([
            QgsField("ObstacleID", QVariant.Int),
            QgsField("Area_m2", QVariant.Double)
        ])
        obstacles_layer.updateFields()

        # Add obstacle geometries
        for i, obstacle_geom in enumerate(obstacle_geometries):
            obstacle_feat = QgsFeature()
            obstacle_feat.setGeometry(obstacle_geom)
            obstacle_feat.setAttributes([
                i,
                obstacle_geom.area()
            ])
            obstacles_provider.addFeature(obstacle_feat)

        # Style the obstacles layer with categorized renderer
        # Using different colors for different obstacles
        categories = []
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        # Create a category for each obstacle, cycling through colors
        for i in range(len(obstacle_geometries)):
            color_idx = i % len(colors)
            color = colors[color_idx]

            symbol = QgsFillSymbol.createSimple({
                'color': f'{color}80',  # Add 50% transparency
                'outline_color': color,
                'outline_width': '0.6',
                'outline_style': 'solid'
            })

            category = QgsRendererCategory(i, symbol, f"Obstacle {i}")
            categories.append(category)

        # Create the categorized renderer
        renderer = QgsCategorizedSymbolRenderer("ObstacleID", categories)
        obstacles_layer.setRenderer(renderer)

        # Add the layers to the project through the debug group
        avoidance_layer.updateExtents()
        obstacles_layer.updateExtents()

        project.addMapLayer(avoidance_layer, False)
        project.addMapLayer(obstacles_layer, False)

        debug_group.addLayer(avoidance_layer)
        debug_group.addLayer(obstacles_layer)

        # Refresh the canvas
        self._refresh_map_canvas_safe()

        log.info(f"Created debug visualization with {len(obstacle_geometries)} obstacles")
        return debug_group

    def _calculate_entry_exit_points(self, obstacle_center, middle_line_heading, distance=1000.0):
        """
        Calculate entry and exit points by projecting along the middle line heading
        from the obstacle center.

        Args:
            obstacle_center (QgsPointXY): The center point of the obstacle
            middle_line_heading (float): The heading of the middle reference line in degrees
            distance (float): The distance to project along the heading in meters

        Returns:
            tuple: (entry_point, exit_point) as QgsPointXY objects
        """
        # Calculate forward and reverse angles in radians
        forward_angle_rad = math.radians(middle_line_heading)
        reverse_angle_rad = math.radians((middle_line_heading + 180.0) % 360.0)

        # Calculate offsets for the forward direction (entry point)
        dx_entry = distance * math.sin(forward_angle_rad)
        dy_entry = distance * math.cos(forward_angle_rad)

        # Calculate offsets for the reverse direction (exit point)
        dx_exit = distance * math.sin(reverse_angle_rad)
        dy_exit = distance * math.cos(reverse_angle_rad)

        # Create entry and exit points
        entry_point = QgsPointXY(
            obstacle_center.x() + dx_entry,
            obstacle_center.y() + dy_entry
        )

        exit_point = QgsPointXY(
            obstacle_center.x() + dx_exit,
            obstacle_center.y() + dy_exit
        )

        return entry_point, exit_point

    def _visualize_split_lines(self, split_lines_layer, fid_map=None):
        """
        Enhance the visualization of split lines to clearly show which lines have been split
        and how they relate to the deviation polygons.

        Args:
            split_lines_layer (QgsVectorLayer): The layer containing split line segments
            fid_map (dict, optional): Mapping of original FIDs to line numbers for reference

        Returns:
            bool: True if successful, False otherwise
        """
        if not split_lines_layer or not split_lines_layer.isValid():
            log.error("Invalid split lines layer for visualization")
            return False

        # Get the layer provider
        provider = split_lines_layer.dataProvider()
        if provider.featureCount() == 0:
            log.warning("No features in split lines layer to visualize")
            return False

        # Log feature details for debugging
        log.info(f"Visualizing {provider.featureCount()} split line features")
        for feature in split_lines_layer.getFeatures():
            log.debug(f"Split line feature: LineNum={feature['LineNum']}, Type={feature['SegmentType']}")

        # Setup labeling for the split lines layer
        label_settings = QgsPalLayerSettings()
        text_format = QgsTextFormat()
        text_format.setSize(9)
        text_format.setColor(QColor("black"))

        # Add white buffer around text for better visibility
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(1.0)
        buffer.setColor(QColor("white"))
        text_format.setBuffer(buffer)

        # Configure the label settings
        label_settings.setFormat(text_format)
        label_settings.fieldName = "LineNum"
        label_settings.enabled = True
        LookaheadDockWidgetImpl._path_label_pin_to_segment_centroid(label_settings)

        # Apply label settings
        labeling = QgsVectorLayerSimpleLabeling(label_settings)
        split_lines_layer.setLabelsEnabled(True)
        split_lines_layer.setLabeling(labeling)

        # Create a categorized renderer for inside/outside segments with more distinct styles
        categories = []

        # Inside segments (to be removed) - shown in red with dash pattern
        inside_symbol = QgsLineSymbol.createSimple({
            'line_color': '#FF0000',  # Red
            'line_width': '0.6',
            'line_style': 'dot',
            'use_custom_dash': '1',
            'customdash': '3;2'
        })
        categories.append(QgsRendererCategory("Inside", inside_symbol, "Inside Deviation Polygon (Removed)"))

        # Outside segments (to be kept) - shown in blue with solid line
        outside_symbol = QgsLineSymbol.createSimple({
            'line_color': '#0000FF',  # Blue
            'line_width': '0.6',
            'line_style': 'solid'
        })
        categories.append(QgsRendererCategory("Outside", outside_symbol, "Outside Deviation Polygon (Kept)"))

        # Apply the categorized renderer
        renderer = QgsCategorizedSymbolRenderer("SegmentType", categories)
        split_lines_layer.setRenderer(renderer)

        # Add the layer to the group if it's not already there
        project = QgsProject.instance()
        debug_group = None

        # Look for existing debug group or create one
        lookahead_group = self._get_or_create_group("Lookahead")
        for child in lookahead_group.children():
            if child.nodeType() == 0 and "Debug" in child.name():
                debug_group = child
                break

        if not debug_group:
            debug_group = lookahead_group.insertGroup(0, "Debug Visualizations")

        # Add to project through the group
        # Note: The layer should already be added to the project before this method is called
        if split_lines_layer not in project.mapLayers().values():
            project.addMapLayer(split_lines_layer, False)

        debug_group.addLayer(split_lines_layer)

        log.info(f"Added split lines visualization with {provider.featureCount()} segments")

        # Force layer update and refresh
        split_lines_layer.triggerRepaint()
        split_lines_layer.updateExtents()

        # If there's a map canvas available, refresh it
        self._refresh_map_canvas_safe()

        return True
    
    # --- 7. Simulation and Sequencing ---
    def _gather_simulation_parameters(self):
        """
        Reads and validates simulation parameters from the UI.

        This function collects all parameters needed for simulation including:
        - Acquisition mode (Teardrop or Racetrack)
        - Deviation parameters (clearance, nogo zones)
        - Line sequencing parameters (first line, heading)
        - Vessel parameters (speeds, turn radius, turn rate)
        - Timing parameters (start datetime)

        Returns:
            dict: Dictionary of validated parameters or None if validation fails
        """
        log.debug("Gathering simulation parameters from UI...")
        params = {}

        try:
            # --- Acquisition Mode ---
            if hasattr(self, 'acquisitionModeComboBox'):
                c = self.acquisitionModeComboBox
                raw_data = c.currentData()
                mode_key = _normalize_acquisition_combo_userdata(raw_data)
                if mode_key is None:
                    t = (c.currentText() or "").strip().casefold()
                    if t == "teardrop":
                        mode_key = "teardrop"
                    elif t == "racetrack" or t.startswith("racetrack"):
                        mode_key = "racetrack"
                if mode_key not in ("teardrop", "racetrack"):
                    # Final fallback: known combo order
                    mode_key = "teardrop" if c.currentIndex() == 1 else "racetrack"
                params["acquisition_mode_key"] = mode_key
                params["acquisition_mode"] = "Teardrop" if mode_key == "teardrop" else "Racetrack"
                log.debug(
                    "Acquisition mode from UI: idx=%s text=%r data=%r -> key=%s display=%s",
                    c.currentIndex(),
                    c.currentText(),
                    raw_data,
                    mode_key,
                    params["acquisition_mode"],
                )
            else:
                log.warning("Acquisition Mode ComboBox not found, defaulting to Racetrack")
                params['acquisition_mode'] = "Racetrack"
                params["acquisition_mode_key"] = "racetrack"

            # --- Deviation Parameters ---
            nogo_combo = getattr(self, "nogo_zone_combo", None)
            params['nogo_layer'] = nogo_combo.currentLayer() if nogo_combo is not None else None

            if hasattr(self, 'deviationClearanceDoubleSpinBox'):
                params['deviation_clearance_m'] = self.deviationClearanceDoubleSpinBox.value()
            else:
                log.warning("Deviation Clearance SpinBox not found, defaulting to 80.0m")
                params['deviation_clearance_m'] = 80.0

            # --- RRT-Specific Parameters ---
            # Include these for future RRT integration
            for rrt_param in ['step_size', 'max_iterations', 'goal_bias']:
                param_name = f'rrt_{rrt_param}'
                if hasattr(self, f'{param_name}SpinBox'):
                    params[param_name] = getattr(self, f'{param_name}SpinBox').value()

            # --- Sequence Parameters ---
            params['first_line_num'] = self.firstLineSpinBox.value()
            params['first_heading_option'] = self.firstHeadingComboBox.currentText()
            params['start_sequence_number'] = self.firstSeqComboBox.value()

            # --- Vessel Speed Parameters (per sail-line direction) ---
            if hasattr(self, 'avgShootingSpeedDoubleSpinBox'):
                l2h_shoot_kn = float(self.avgShootingSpeedDoubleSpinBox.value())
            elif hasattr(self, 'acqSpeedPrimaryDoubleSpinBox'):
                l2h_shoot_kn = float(self.acqSpeedPrimaryDoubleSpinBox.value())
                log.info("Using 'acqSpeedPrimaryDoubleSpinBox' for Low→High shooting speed.")
            else:
                raise AttributeError("Suitable acquisition speed input widget(s) not found.")

            h2l_shoot_kn = (
                float(self.acqSpeedHighToLowDoubleSpinBox.value())
                if getattr(self, "acqSpeedHighToLowDoubleSpinBox", None) is not None
                else l2h_shoot_kn
            )

            l2h_turn_kn = float(self.turnSpeedDoubleSpinBox.value())
            h2l_turn_kn = (
                float(self.turnSpeedHighToLowDoubleSpinBox.value())
                if getattr(self, "turnSpeedHighToLowDoubleSpinBox", None) is not None
                else l2h_turn_kn
            )

            params['avg_shooting_speed_low_to_high_knots'] = l2h_shoot_kn
            params['avg_shooting_speed_high_to_low_knots'] = h2l_shoot_kn
            params['avg_shooting_speed_low_to_high_mps'] = l2h_shoot_kn * KNOTS_TO_MPS
            params['avg_shooting_speed_high_to_low_mps'] = h2l_shoot_kn * KNOTS_TO_MPS

            params['avg_turn_speed_low_to_high_knots'] = l2h_turn_kn
            params['avg_turn_speed_high_to_low_knots'] = h2l_turn_kn
            params['avg_turn_speed_low_to_high_mps'] = l2h_turn_kn * KNOTS_TO_MPS
            params['avg_turn_speed_high_to_low_mps'] = h2l_turn_kn * KNOTS_TO_MPS

            # Legacy single-value keys (Low→High); used where direction is not applied.
            params['avg_shooting_speed_knots'] = l2h_shoot_kn
            params['avg_shooting_speed_mps'] = params['avg_shooting_speed_low_to_high_mps']
            params['avg_turn_speed_knots'] = l2h_turn_kn
            params['avg_turn_speed_mps'] = params['avg_turn_speed_low_to_high_mps']

            params['turn_radius_meters'] = self.turnRadiusDoubleSpinBox.value()

            # Vessel turn rate
            if hasattr(self, 'vesselTurnRateDoubleSpinBox'):
                params['vessel_turn_rate_dps'] = self.vesselTurnRateDoubleSpinBox.value()
            else:
                params['vessel_turn_rate_dps'] = 3.0
                log.warning(f"Vessel turn rate UI not found. Using default: {params['vessel_turn_rate_dps']} deg/sec")

            # Other parameters
            if hasattr(self, "maxRunInDoubleSpinBox"):
                params["run_in_length_meters"] = self.maxRunInDoubleSpinBox.value()
            else:
                log.warning("Max Run-In spinbox not found, defaulting to 500.0 m")
                params["run_in_length_meters"] = 500.0
            params['run_out_length_meters'] = self.runOutDoubleSpinBox.value() if hasattr(self, 'runOutDoubleSpinBox') else 0.0
            start_dt = self.startDateTimeEdit.dateTime().toPyDateTime()
            params['start_datetime'] = start_dt.replace(second=0, microsecond=0)

            # --- Validate Critical Parameters ---
            for _k in (
                "avg_shooting_speed_low_to_high_mps",
                "avg_shooting_speed_high_to_low_mps",
                "avg_turn_speed_low_to_high_mps",
                "avg_turn_speed_high_to_low_mps",
            ):
                if params.get(_k, 0) <= 0:
                    raise ValueError("All shooting and turn speeds (both directions) must be positive.")
            if params['turn_radius_meters'] <= 0:
                raise ValueError("Turn Radius must be positive.")
            if params['vessel_turn_rate_dps'] <= 0:
                raise ValueError("Turn Rate must be positive.")

            params["stability"] = self._get_stability_settings()

            tr = params['turn_radius_meters']
            circ = 2.0 * math.pi * tr
            min_clearance_allowed = -circ
            cl = params.get('deviation_clearance_m', 0.0)
            if cl < min_clearance_allowed - 1e-6:
                raise ValueError(
                    f"Deviation Clearance ({cl} m) cannot be less than -turn circumference "
                    f"(-{circ:.1f} m) for the current turn radius ({tr} m)."
                )

            log.debug(f"Parameters gathered: {params}")
            return params

        except AttributeError as ae:
            log.error(f"UI element not found: {ae}")
            QMessageBox.critical(self, "UI Error", f"Could not find UI element: {ae}")
            return None
        except ValueError as ve:
            log.error(f"Invalid parameter: {ve}")
            QMessageBox.critical(self, "Input Error", f"Invalid parameter value: {ve}")
            return None
        except Exception as e:
            log.exception(f"Error gathering parameters: {e}")
            QMessageBox.critical(self, "Error", f"Error reading parameters: {e}")
            return None

    def _prepare_line_data(self, sim_params):
        """
        Prepares line data from layers for simulation.

        This function:
        1. Verifies required layers exist and are valid
        2. Checks for required fields in the layers
        3. Processes line features to extract geometries and attributes
        4. Processes run-in features and connects them to lines
        5. Validates data completeness and returns final line data dictionary

        Args:
            sim_params (dict): Dictionary of simulation parameters

        Returns:
            tuple: (line_data, required_layers) where:
                   - line_data is a dictionary of line data indexed by line number
                   - required_layers is a dictionary of required layers
                   - or (None, None) if preparation fails
        """
        log.debug("Preparing line data from temporary layers...")
        self._prepare_line_data_user_informed = False

        # --- Locate Required Layers ---
        project = QgsProject.instance()
        line_layer_name = "Generated_Survey_Lines"
        runin_layer_name = "Generated Run-In Run-Out"

        def _is_valid_vector_layer(layer):
            """Safely validate wrapped QGIS layer objects that may have been deleted."""
            if layer is None:
                return False
            try:
                return layer.type() == QgsMapLayer.VectorLayer and layer.isValid()
            except RuntimeError:
                return False

        # Try to get layers from instance variables first
        lines_layer = self.generated_lines_layer if hasattr(self, 'generated_lines_layer') else None
        runins_layer = self.generated_runins_layer if hasattr(self, 'generated_runins_layer') else None

        # If instance variables are None, try to find layers by name
        if not _is_valid_vector_layer(lines_layer):
            lines_layer = None
            for layer in project.mapLayersByName(line_layer_name):
                if _is_valid_vector_layer(layer):
                    lines_layer = layer
                    break

        if not _is_valid_vector_layer(runins_layer):
            runins_layer = None
            for layer in project.mapLayersByName(runin_layer_name):
                if _is_valid_vector_layer(layer):
                    runins_layer = layer
                    break
                
        # Validate layers
        if not _is_valid_vector_layer(lines_layer):
            err_msg = f"Failed to find valid layer for '{line_layer_name}'."
            log.error(err_msg)
            QMessageBox.critical(self, "Layer Error", err_msg)
            self._prepare_line_data_user_informed = True
            return None, None

        if not _is_valid_vector_layer(runins_layer):
            err_msg = f"Failed to find valid layer for '{runin_layer_name}'."
            log.error(err_msg)
            QMessageBox.critical(self, "Layer Error", err_msg)
            self._prepare_line_data_user_informed = True
            return None, None

        # Refresh cached references to avoid reusing deleted wrappers next run.
        self.generated_lines_layer = lines_layer
        self.generated_runins_layer = runins_layer
        required_layers = {'lines': lines_layer, 'runins': runins_layer}

        # --- Verify Required Fields ---
        line_fields = lines_layer.fields()

        # Field indices for survey lines
        field_indices = {
            'line_num': line_fields.lookupField("LineNum"),
            'base_heading': line_fields.lookupField("Heading"),
            'status': line_fields.lookupField("Status"),
            'length': line_fields.lookupField("Length_m"),
            'lowest_sp': line_fields.lookupField("LowestSP"),
            'highest_sp': line_fields.lookupField("HighestSP"),
            'is_dev': line_fields.lookupField("is_deviation_created"),
            'is_fail': line_fields.lookupField("is_conflicted")
        }

        # Check for missing fields
        missing_fields = [name for name, idx in field_indices.items() if idx == -1 and name not in ('is_dev', 'is_fail')]
        if missing_fields:
            field_names = [name.replace('_', ' ').title() for name in missing_fields]
            err_msg = f"Lines layer '{lines_layer.name()}' missing fields: {', '.join(field_names)}"
            log.error(err_msg)
            QMessageBox.critical(self, "Field Error", err_msg)
            self._prepare_line_data_user_informed = True
            return None, None

        # Field indices for run-ins
        runin_fields = runins_layer.fields()
        runin_indices = {
            'line_num': runin_fields.lookupField("LineNum"),
            'position': runin_fields.lookupField("Position"),
            'start_x': runin_fields.lookupField("start_x"),
            'start_y': runin_fields.lookupField("start_y"),
            'end_x': runin_fields.lookupField("end_x"),
            'end_y': runin_fields.lookupField("end_y")
        }

        # Check if run-in layer has coordinate fields
        has_runin_coords = all(idx != -1 for name, idx in runin_indices.items() 
                              if name in ['start_x', 'start_y', 'end_x', 'end_y'])
        if not has_runin_coords:
            log.warning(f"Run-ins layer lacks coordinate fields. Falling back to geometry extraction.")

        # --- Process Survey Lines ---
        line_data = {}
        log.debug("Processing survey lines layer...")

        # Create feature request
        request = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoFlags)  # Need geometry

        # Process features
        processed_lines = 0
        skipped_status = 0
        skipped_geom = 0
        skipped_attr = 0

        for feature in lines_layer.getFeatures(request):
            # Validate geometry
            line_geom = QgsGeometry(feature.geometry())  # Deep copy to prevent C++ crashes
            if not line_geom or line_geom.isEmpty() or line_geom.type() != QgsWkbTypes.LineGeometry:
                skipped_geom += 1
                continue

            # Extract attributes
            line_num_val = feature.attribute(field_indices['line_num'])
            base_heading_val = feature.attribute(field_indices['base_heading'])
            status_val = feature.attribute(field_indices['status'])
            length_val = feature.attribute(field_indices['length'])
            lowest_sp_val = feature.attribute(field_indices['lowest_sp'])
            highest_sp_val = feature.attribute(field_indices['highest_sp'])

            # Check line status
            status_str = str(status_val).strip().upper() if status_val is not None and status_val != NULL else ""
            if status_str != "TO BE ACQUIRED":
                skipped_status += 1
                continue

            # Convert and validate attributes
            try:
                line_num = str(line_num_val)
                base_heading = float(base_heading_val)
                length = float(length_val)
                lowest_sp = int(lowest_sp_val) if lowest_sp_val is not None and lowest_sp_val != NULL else None
                highest_sp = int(highest_sp_val) if highest_sp_val is not None and highest_sp_val != NULL else None
            except (ValueError, TypeError) as e:
                log.warning(f"Skipping LineNum {line_num_val} due to attribute conversion error: {e}. "
                           f"Attrs: Head={base_heading_val}, Len={length_val}")
                skipped_attr += 1
                continue

            # Read deviation flags if they exist
            is_deviated = False
            if field_indices['is_dev'] != -1:
                val = feature.attribute(field_indices['is_dev'])
                is_deviated = bool(val) if val else False
            is_failed = False
            if field_indices['is_fail'] != -1 and not is_deviated:
                val = feature.attribute(field_indices['is_fail'])
                is_failed = bool(val) if val else False

            if base_heading is None or length is None or length < 0:
                log.warning(f"Skipping LineNum {line_num}: Invalid base heading ({base_heading}) or length ({length}).")
                skipped_attr += 1
                continue

            # Get line vertices
            vertices = list(line_geom.vertices())
            if len(vertices) < 2:
                skipped_geom += 1
                continue

            start_pt = vertices[0]  # QgsPoint
            end_pt = vertices[-1]   # QgsPoint

            # Store line data
            line_data[line_num] = {
                'line_geom': line_geom,
                'base_heading': base_heading,
                'length': length,
                'lowest_sp': lowest_sp,
                'highest_sp': highest_sp,
                'start_point_geom': start_pt,
                'end_point_geom': end_pt,
                'start_runin_point': None,  # Will be populated later
                'end_runin_point': None,     # Will be populated later
                'deviated': is_deviated,
                'deviation_failed': is_failed
            }
            processed_lines += 1

        log.info(f"Processed {processed_lines} 'To Be Acquired' lines from '{lines_layer.name()}'.")
        log.debug(f"  Skipped {skipped_status} (Status), {skipped_geom} (Geometry), {skipped_attr} (Attributes).")

        if processed_lines == 0:
            QMessageBox.warning(
                self,
                "Simulation needs ready survey lines",
                "The simulator could not use any rows from the layer 'Generated_Survey_Lines'.\n\n"
                "Do this in order:\n\n"
                "1) On your SPS point layer: use Import SPS (headings fill automatically) or click Calculate Headings if you edited points.\n"
                "2) Set status to To Be Acquired for the lines you want, then click Generate Lookahead Lines.\n"
                "3) Run Simulation again.\n\n"
                "(Simulation reads Status and Heading on the generated line layer. If you only changed "
                "points after generating, click Generate Lookahead Lines again or use To Be Acquired "
                "so the line layer is updated.)",
            )
            self._prepare_line_data_user_informed = True
            return None, None

        # --- Process Run-ins ---
        log.debug("Processing run-ins layer to find run-in endpoints...")

        runins_processed = 0
        runins_matched = 0
        runins_skipped_geom = 0
        runins_skipped_attr = 0

        # Only process run-ins if the layer has features
        if runins_layer.featureCount() > 0:
            request_runin = QgsFeatureRequest()

            st = self._get_stability_settings()
            tol_m = float(st.get("runin_connect_tolerance_m", 10.0))
            tol_m = max(0.01, tol_m)
            connect_tolerance_sq = tol_m * tol_m

            for feature in runins_layer.getFeatures(request_runin):
                runins_processed += 1

                # Get line number and position attributes
                try:
                    line_num = feature.attribute(runin_indices['line_num'])
                    position = feature.attribute(runin_indices['position'])

                    if line_num is None or line_num == NULL:
                        raise ValueError("NULL LineNum")
                    if position is None or position == NULL:
                        raise ValueError("NULL Position")

                    line_num = str(line_num)
                    position = str(position).strip().capitalize()

                    if position not in ["Start", "End"]:
                        raise ValueError(f"Invalid Position '{position}'")
                except (ValueError, TypeError) as e:
                    log.warning(f"Skipping run-in FID {feature.id()} invalid LineNum/Position: {e}")
                    runins_skipped_attr += 1
                    continue

                # Skip if line wasn't processed or is not 'To Be Acquired'
                if line_num not in line_data:
                    continue

                # Try to get coordinates from attributes first
                runin_start_pt_xy = None
                runin_end_pt_xy = None

                if has_runin_coords:
                    try:
                        sx = feature.attribute(runin_indices['start_x'])
                        sy = feature.attribute(runin_indices['start_y'])
                        ex = feature.attribute(runin_indices['end_x'])
                        ey = feature.attribute(runin_indices['end_y'])

                        if (sx is None or sx == NULL or sy is None or sy == NULL or 
                            ex is None or ex == NULL or ey is None or ey == NULL):
                            raise ValueError("NULL coordinate value")

                        runin_start_pt_xy = QgsPointXY(float(sx), float(sy))
                        runin_end_pt_xy = QgsPointXY(float(ex), float(ey))
                    except (ValueError, TypeError, AttributeError):
                        runin_start_pt_xy = None
                        runin_end_pt_xy = None

                # Fallback to geometry if attributes are not available
                if runin_start_pt_xy is None or runin_end_pt_xy is None:
                    runin_geom = QgsGeometry(feature.geometry())  # Deep copy

                    if not runin_geom or runin_geom.isEmpty() or runin_geom.type() != QgsWkbTypes.LineGeometry:
                        log.warning(f"Skipping run-in FID {feature.id()} ({line_num}, {position}) invalid geometry.")
                        runins_skipped_geom += 1
                        continue

                    vertices = list(runin_geom.vertices())
                    if len(vertices) >= 2:
                        runin_start_pt_xy = QgsPointXY(vertices[0].x(), vertices[0].y())
                        runin_end_pt_xy = QgsPointXY(vertices[-1].x(), vertices[-1].y())
                    else:
                        log.warning(f"Skipping run-in FID {feature.id()} ({line_num}, {position}) geom < 2 vertices.")
                        runins_skipped_geom += 1
                        continue
                    
                # Get the line endpoint to connect to (start or end of the line)
                line_info = line_data[line_num]
                expected_connection_point = None

                if position == "Start":
                    expected_connection_point = line_info['start_point_geom']
                elif position == "End":
                    expected_connection_point = line_info['end_point_geom']

                if expected_connection_point:
                    # Calculate distances between run-in points and expected connection point
                    dist_runin_start_to_expected_sq = runin_start_pt_xy.sqrDist(
                        expected_connection_point.x(), expected_connection_point.y())
                    dist_runin_end_to_expected_sq = runin_end_pt_xy.sqrDist(
                        expected_connection_point.x(), expected_connection_point.y())

                    # Determine which run-in point connects to the line
                    runin_outer_pt = None
                    is_connected = False

                    if dist_runin_end_to_expected_sq < dist_runin_start_to_expected_sq:
                        # Run-in END vertex connects to the line
                        if dist_runin_end_to_expected_sq < connect_tolerance_sq:
                            runin_outer_pt = runin_start_pt_xy
                            is_connected = True
                        else:
                            log.warning(f"Run-in FID {feature.id()} ({line_num}, {position}) end vertex not close to "
                                       f"line {position} point (DistSq: {dist_runin_end_to_expected_sq:.2f}).")
                    else:
                        # Run-in START vertex connects to the line
                        if dist_runin_start_to_expected_sq < connect_tolerance_sq:
                            runin_outer_pt = runin_end_pt_xy
                            is_connected = True
                        else:
                            log.warning(f"Run-in FID {feature.id()} ({line_num}, {position}) start vertex not close to "
                                       f"line {position} point (DistSq: {dist_runin_start_to_expected_sq:.2f}).")

                    # Store the outer point if connection is valid
                    if is_connected and runin_outer_pt:
                        if position == "Start":
                            line_data[line_num]['start_runin_point'] = runin_outer_pt
                        elif position == "End":
                            line_data[line_num]['end_runin_point'] = runin_outer_pt
                        runins_matched += 1
                    elif is_connected:
                        log.error(f"Internal error: Run-in FID {feature.id()} connected but failed to identify outer point.")

            log.info(f"Processed {runins_processed} features from '{runins_layer.name()}'. "
                   f"Matched {runins_matched} run-in points.")
            log.debug(f"  Run-in skips: Geom={runins_skipped_geom}, Attr={runins_skipped_attr}.")
        else:
            log.warning(f"Skipping run-in processing loop as '{runins_layer.name()}' is empty.")

        # --- Validate Final Line Data ---
        final_line_data = {}
        missing_runin_lines = []
        run_in_length = sim_params.get('run_in_length_meters', 0.0) if sim_params else 0.0
        run_out_length = sim_params.get('run_out_length_meters', 0.0) if sim_params else 0.0

        for line_num, data in line_data.items():
            if data.get('start_runin_point') is None and run_in_length <= 0.0:
                data['start_runin_point'] = data.get('start_point_geom')
            if data.get('end_runin_point') is None and run_out_length <= 0.0:
                data['end_runin_point'] = data.get('end_point_geom')

            if data.get('start_runin_point') is None or data.get('end_runin_point') is None:
                missing_runin_lines.append(line_num)
            else:
                final_line_data[line_num] = data

        if missing_runin_lines:
            log.warning(f"Excluding {len(missing_runin_lines)} lines missing run-in points: {sorted(missing_runin_lines)}")
            QMessageBox.warning(self, "Missing Run-in Data", 
                              f"Excluding {len(missing_runin_lines)} lines missing run-in points. Check connections.")

        final_line_nums = sorted(list(final_line_data.keys()))
        log.info(f"Prepared final data for {len(final_line_nums)} lines: {final_line_nums}")

        if not final_line_data:
            QMessageBox.warning(self, "No Data", "No valid lines with run-in points found.")
            self._prepare_line_data_user_informed = True
            return None, None

        return final_line_data, required_layers

    def _get_line_order_for_simulation(self, allowed_line_nums):
        """
        Simulation uses only the shooting queue (Right Ctrl+click → Seq in the dock list).

        Lines may stay To Be Acquired for mapping / generation but intentionally off the queue;
        they must not enter the run plan or receive turns. If the queue is empty, nothing runs
        until the user adds at least one line to the queue.
        """
        allowed = set(str(x) for x in allowed_line_nums)
        if not allowed:
            return []

        raw_seq = getattr(self, "_selection_sequence", None) or []
        seq = [str(ln) for ln in raw_seq]
        if not seq:
            log.info("Shooting queue empty — simulation needs Right Ctrl+click order (Seq).")
            return []

        ordered_queue = []
        seen_q = set()
        for ln in seq:
            if ln in allowed and ln not in seen_q:
                ordered_queue.append(ln)
                seen_q.add(ln)

        if not ordered_queue:
            log.warning(
                "Shooting queue has no line that matches current TBA survey data "
                "(regenerate lines or refresh the list, then rebuild the queue)."
            )
            return []

        skipped = len(allowed) - len(seen_q)
        if skipped:
            log.info(
                "Plan: %d queued line(s); %d TBA line(s) without Seq stay out of the simulation.",
                len(ordered_queue),
                skipped,
            )
        else:
            log.info(
                "Plan: %d queued line(s) (every TBA line in the prepared set is in the queue).",
                len(ordered_queue),
            )
        return ordered_queue

    @staticmethod
    def _rotate_sequence_to_first_line(sequence, first_line_num):
        """Rotate sequence so it starts at first_line_num while preserving cyclic order."""
        seq = list(sequence)
        if not seq:
            return seq, first_line_num
        key = str(first_line_num).strip() if first_line_num is not None else ""
        if key not in seq:
            log.warning(
                "First line %s not in sequence %s; starting with line %s",
                first_line_num,
                seq,
                seq[0],
            )
            return seq, seq[0]
        idx = seq.index(key)
        rot = seq[idx:] + seq[:idx]
        return rot, key

    def handle_run_simulation(self):
        """
        Main handler: Runs selected algorithm, including deviation calculation,
        visualizes result, enables editing. Filters out lines that failed deviation.
        """
        log.info("Run Simulation button clicked.")
        if self._needs_regeneration_before_simulation():
            answer = QMessageBox.question(
                self,
                "Regenerate Lookahead Lines",
                "Settings affecting generated lines have changed (or generated layers are missing).\n\n"
                "Please regenerate lookahead lines before simulation.\n\n"
                "Generate now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return
            self.handle_generate_lines(silent=True)
            if self._needs_regeneration_before_simulation():
                QMessageBox.warning(
                    self,
                    "Generation Required",
                    "Could not refresh generated lookahead layers. Please click 'Generate Lookahead Lines' and try again.",
                )
                return

        # Keep both generated layers available, but hide them while simulation results are shown.
        generated_layer_names = ["Generated_Survey_Lines", "Generated Run-In Run-Out"]
        generated_layer_refs = [
            getattr(self, "generated_lines_layer", None),
            getattr(self, "generated_runins_layer", None),
        ]

        def _apply_generated_layers_visibility(visible):
            self._set_layer_visibility_by_names(generated_layer_names, visible=visible)
            project = QgsProject.instance()
            root = project.layerTreeRoot()
            for lyr in generated_layer_refs:
                try:
                    if lyr is None or not lyr.isValid():
                        continue
                    node = root.findLayer(lyr.id())
                    if node is not None:
                        node.setItemVisibilityChecked(bool(visible))
                except Exception as e:
                    log.debug("Direct generated-layer visibility toggle skipped: %s", e)

        _apply_generated_layers_visibility(False)
        # Some QGIS UI refresh paths can re-check nodes; enforce hide once more.
        QtCore.QTimer.singleShot(0, lambda: _apply_generated_layers_visibility(False))
        QtCore.QTimer.singleShot(80, lambda: _apply_generated_layers_visibility(False))
        QApplication.setOverrideCursor(_QT_WAIT_CURSOR)
        progress = None
        self.last_simulation_result = None; self.last_sim_params = None
        self.last_line_data = None; self.last_required_layers = None
        self.last_turn_cache = {}
        # Always replace previous simulation visuals so only last run is displayed.
        self._remove_layer_by_name("Optimized_Path")
        self._remove_layer_by_name("Optimized_Path_Racetrack")
        self._remove_layer_by_name("Optimized_Path_Teardrop")
        self._remove_layer_by_name("Turn_Racetrack")
        self._remove_layer_by_name("Turn_Teardrop")
        if hasattr(self, 'editFinalizeButton'): self.editFinalizeButton.setEnabled(False)

        try:
            start_prep_time = time.time()
            log.debug("Running Step 1: Data Gathering & Preparation...")
            sim_params = self._gather_simulation_parameters()
            if not sim_params:
                return  # Error notification already shown in _gather_simulation_parameters
            # Re-read from UI at run time to avoid stale/restored key drift.
            if hasattr(self, 'acquisitionModeComboBox'):
                mk = _normalize_acquisition_combo_userdata(self.acquisitionModeComboBox.currentData())
                if mk not in ("teardrop", "racetrack"):
                    t = (self.acquisitionModeComboBox.currentText() or "").strip().casefold()
                    mk = "teardrop" if t == "teardrop" else "racetrack"
                sim_params["acquisition_mode_key"] = mk
                sim_params["acquisition_mode"] = "Teardrop" if mk == "teardrop" else "Racetrack"
            self.last_sim_params = sim_params

            line_data, required_layers = self._prepare_line_data(sim_params)

            # --- <<< ELEGANT HANDLING for NO VALID LINES >>> ---
            if not line_data: # Checks for None OR empty dictionary
                log.error("Preparation resulted in no valid 'To Be Acquired' lines for simulation based on current filters and generated layers.")
                if not getattr(self, "_prepare_line_data_user_informed", False):
                    self._pop_wait_cursor_if_busy()
                    QMessageBox.warning(self, "No Lines Found for Simulation",
                                        "No survey lines marked 'To Be Acquired' were found in the 'Generated_Survey_Lines' layer that match the current filter settings.\n\n"
                                        "Please check the following:\n"
                                        "1. **Source Layer Status:** Ensure the lines you want to simulate have their 'Status' set to 'To Be Acquired' in the original SPS point layer.\n"
                                        "2. **Filter Settings:** Verify the 'Min Line', 'Max Line', and 'Status' filter settings in the UI are correct.\n"
                                        "3. **Refresh List:** Click 'Refresh List' to update the line list.\n"
                                        "4. **Regenerate Lines:** Click 'Generate Lines' again *after* confirming the status and filters are correct.\n\n"
                                        "Simulation cannot proceed without valid lines.")
                return
            # --- <<< END ELEGANT HANDLING >>> ---

            if not line_data: raise ValueError("Failed to prepare line data")
            self.last_required_layers = required_layers
            log.info(f"Initial line data preparation complete ({time.time() - start_prep_time:.2f}s). Found {len(line_data)} lines.")

            # --- <<< START Deviation Calculation >>> ---
            # start_dev_time = time.time()
            # log.debug("Running Step 2: Calculating Deviations...")
            # nogo_layer = sim_params.get('nogo_layer')
            # clearance = sim_params.get('deviation_clearance_m', 80.0)
            # turn_radius = sim_params.get('turn_radius_meters', 500.0)

            # # line_data is modified IN PLACE
            # # Convert vessel turn rate from degrees per second to degrees per minute
            # vessel_turn_rate_dps = sim_params.get('vessel_turn_rate_dps', 3.0)
            # vessel_turn_rate_dpm = vessel_turn_rate_dps * 60.0

            # line_data = self._calculate_and_apply_deviations(
            #     line_data, nogo_layer, clearance, turn_radius, vessel_turn_rate_dpm
            # )
            # # Store the potentially modified line_data for the editor/visualizer
            # self.last_line_data = line_data
            # log.info(f"Deviation calculation complete ({time.time() - start_dev_time:.2f}s).")
            # --- <<< END Deviation Calculation >>> ---

            # Store the unmodified line_data since we're not calculating deviations
            self.last_line_data = line_data

            selected_mode = sim_params.get('acquisition_mode', 'Racetrack')
            mode_key = sim_params.get("acquisition_mode_key")
            if mode_key not in ("teardrop", "racetrack"):
                mode_norm = str(selected_mode).strip().casefold()
                mode_key = "teardrop" if mode_norm == "teardrop" else "racetrack"
            log.info(
                "Selected Acquisition Mode: %r (key=%r)",
                selected_mode,
                mode_key,
            )

            # --- FOOLPROOF PROTECTION FOR TEARDROP ---
            if mode_key == "teardrop":
                line_interval = self._calculate_most_common_interval_from_lines(required_layers['lines'])
                
                # If layer calculation returned None, calculate average distance directly from line_data
                if line_interval is None and line_data and len(line_data) >= 2:
                    try:
                        sorted_keys = sorted(list(line_data.keys()))
                        intervals = []
                        for i in range(len(sorted_keys)-1):
                            k1, k2 = sorted_keys[i], sorted_keys[i+1]
                            g1 = line_data[k1].get('line_geom')
                            g2 = line_data[k2].get('line_geom')
                            if g1 and g2 and not g1.isEmpty() and not g2.isEmpty():
                                dist = g1.distance(g2)
                                if dist > 1.0:
                                    intervals.append(dist)
                        if intervals:
                            intervals.sort()
                            line_interval = intervals[len(intervals) // 2]
                    except Exception as e:
                        log.debug(f"Fallback interval calculation failed: {e}")

                turn_radius = sim_params.get('turn_radius_meters', 0)
                if line_interval and turn_radius > 0:
                    safe_diameter = turn_radius * 2.0
                    if safe_diameter <= line_interval:
                        log.warning(f"Teardrop foolproof protection triggered: turn diameter ({safe_diameter}m) <= line_interval ({line_interval:.1f}m)")
                        self._pop_wait_cursor_if_busy()
                        
                        min_radius = (line_interval / 2.0) + 1.0
                        QMessageBox.warning(
                            self,
                            "Teardrop Not Suitable",
                            f"The vessel's turning diameter (2 × {turn_radius}m = {safe_diameter}m) is less than or equal to the distance to the next line (≈{line_interval:.1f} m).\n\n"
                            f"In these conditions, a Teardrop loop is not required as the vessel has ample space for a direct U-turn.\n\n"
                            f"Please select Racetrack mode.\n"
                            f"(Or, if you specifically need a Teardrop loop, increase the turn radius to at least {min_radius:.1f} m)."
                        )
                        return
            # --- END FOOLPROOF PROTECTION ---

            log.debug("Running Step 3: Sequencing Algorithm...")
            start_sim_time = time.time()
            best_final_sequence_info = None

            # Line order: multi-select order first, then dock list top-to-bottom, then numeric tail
            allowed = set(line_data.keys())
            active_line_nums = self._get_line_order_for_simulation(allowed)

            if not active_line_nums:
                log.error("No lines in shooting queue for simulation (or queue does not match TBA lines).")
                self._pop_wait_cursor_if_busy()
                raw_sq = getattr(self, "_selection_sequence", None) or []
                if not raw_sq:
                    QMessageBox.warning(
                        self,
                        "Set Sequences",
                        "Please set sequences first.\n\n"
                        "Simulation only uses lines in the shooting queue (Right Ctrl+click on list "
                        "rows — they show Seq numbers).\n\n"
                        "Other lines may stay To Be Acquired on the map and in the list for context, "
                        "but they are not part of the run until you add them to the queue.\n\n"
                        "Queue every line you want in this plan, then run simulation again.",
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Set Sequences",
                        "Please set sequences again.\n\n"
                        "Your shooting queue does not match any of the current survey lines "
                        "(e.g. after Refresh List or Regenerate).\n\n"
                        "Rebuild the queue with Right Ctrl+click, then run simulation again.",
                    )
                raise ValueError("No queued lines for sequencing.")
            log.info(f"Proceeding with {len(active_line_nums)} lines; base order: {active_line_nums}")

            # firstLineSpinBox is int; shooting queue & line_data keys are str — compare as str.
            first_line_raw = sim_params["first_line_num"]
            first_line_key = str(first_line_raw).strip() if first_line_raw is not None else ""

            if first_line_key not in active_line_nums:
                queued_first = active_line_nums[0]
                log.warning(
                    "First Line spinbox (%r) is not in the shooting queue (Right Ctrl+click order). "
                    "First queued line is %s — using that as start. (Update the spinbox if you want a "
                    "different start line that appears in the queue.)",
                    first_line_raw,
                    queued_first,
                )
                first_line_num = queued_first
                # Avoid repeating this warning on every run: align spinbox with the queue.
                if hasattr(self, "firstLineSpinBox"):
                    try:
                        spin_val = int(str(queued_first).split("_", 1)[0])
                        self.firstLineSpinBox.setValue(spin_val)
                        sim_params["first_line_num"] = spin_val
                    except (ValueError, TypeError):
                        log.debug("Could not sync firstLineSpinBox from %r", queued_first)
            else:
                first_line_num = first_line_key

            active_line_nums, first_line_num = self._rotate_sequence_to_first_line(
                active_line_nums, first_line_num
            )
            log.info(f"Sequence after applying First Line {first_line_num}: {active_line_nums}")

            # ================================================
            # --- EVALUATE EXACT SEQUENCE FROM LIST ---
            # ================================================
            # Adhere strictly to the line sequence as specified 
            # in the UI list (active_line_nums).
            # The difference between Teardrop and Racetrack is now only in the Dubins turn type
            # (LSR/RSL vs LSL/RSR), which is passed via mode_key to the turn calculator.
            
            log.info(f"Evaluating exact sequence from list using {selected_mode} turns: {active_line_nums}")
            
            user_prefers_reciprocal = (sim_params['first_heading_option'] == "High to Low SP (Reciprocal)")
            
            # Evaluate sequence, starting with normal direction
            cost_normal, directions_normal = self._calculate_sequence_time(
                active_line_nums, False, sim_params, 
                line_data, required_layers, self.last_turn_cache
            )
            
            # Evaluate sequence, starting with reciprocal direction
            cost_recip, directions_recip = self._calculate_sequence_time(
                active_line_nums, True, sim_params, 
                line_data, required_layers, self.last_turn_cache
            )
            
            normal_ok = cost_normal is not None
            recip_ok = cost_recip is not None
            
            if not normal_ok and not recip_ok:
                raise ValueError(f"Sequence timing calculations failed for {selected_mode}.")
                
            best_final_sequence_info = None
            if user_prefers_reciprocal:
                if recip_ok:
                    log.info("Selecting Reciprocal start (User Preference).")
                    best_final_sequence_info = {'seq': active_line_nums, 'cost': cost_recip, 'state': {'line_directions': directions_recip}}
                elif normal_ok:
                    log.warning("User preference Reciprocal failed. Falling back to Normal.")
                    best_final_sequence_info = {'seq': active_line_nums, 'cost': cost_normal, 'state': {'line_directions': directions_normal}}
            else:
                if normal_ok:
                    log.info("Selecting Normal start (User Preference).")
                    best_final_sequence_info = {'seq': active_line_nums, 'cost': cost_normal, 'state': {'line_directions': directions_normal}}
                elif recip_ok:
                    log.warning("User preference Normal failed. Falling back to Reciprocal.")
                    best_final_sequence_info = {'seq': active_line_nums, 'cost': cost_recip, 'state': {'line_directions': directions_recip}}
            
            if not best_final_sequence_info:
                raise ValueError(f"{selected_mode} sequence calculation failed.")
            # ================================================
            # --- END OF EXACT SEQUENCE EVALUATION ---
            # ================================================

            # --- Post-Simulation Processing ---
            if best_final_sequence_info:
                log.info("--- Starting Post-Simulation Processing ---")
                self.last_simulation_result = best_final_sequence_info # Store result for editing
                final_sequence = best_final_sequence_info.get('seq', [])
                final_cost_seconds = best_final_sequence_info.get('cost')
                final_state = best_final_sequence_info.get('state', {})
                final_directions = final_state.get('line_directions', {})

                if not final_sequence: raise ValueError("Final sequence missing from result.")
                if final_cost_seconds is None: raise ValueError("Final cost missing from result.")
                if not final_directions: raise ValueError("Final directions map missing from result.")

                final_cost_hours = final_cost_seconds / 3600.0

                log.info("Visualizing final result...")
                start_datetime = sim_params.get('start_datetime', datetime.now())
                source_crs = required_layers.get('lines', QgsProject.instance()).crs()
                if not source_crs or not source_crs.isValid():
                    log.warning("Source/Project CRS invalid, using fallback WGS84 for visualization.")
                    source_crs = QgsCoordinateReferenceSystem("EPSG:4326")

                log.debug("Calling _reconstruct_path...")
                path_segments_reconstructed = self._reconstruct_path(
                    best_final_sequence_info, line_data, required_layers,
                    sim_params, self.last_turn_cache
                )
                log.debug(f"_reconstruct_path returned {len(path_segments_reconstructed) if path_segments_reconstructed is not None else 'None'} segments.")

                if not path_segments_reconstructed:
                    log.error("Path reconstruction failed. Cannot visualize.")
                    self._pop_wait_cursor_if_busy()
                    QMessageBox.warning(self, "Visualization Skipped", "Path reconstruction failed, skipping visualization.")
                else:
                    log.debug("Calling _visualize_optimized_path...")
                    # Pass line_data for the flags
                    self._visualize_optimized_path(
                        final_sequence, path_segments_reconstructed, start_datetime, source_crs, line_data
                    )
                    log.info("Final visualization complete.")

                if hasattr(self, 'editFinalizeButton'):
                    log.debug("Enabling Edit/Finalize button.")
                    self.editFinalizeButton.setEnabled(True)
                else: log.warning("Edit/Finalize button not found, cannot enable.")

                log.info(f"Algorithm {selected_mode} finished.")
                log.info(f"Final Sequence: {final_sequence}")
                log.info(f"Estimated Cost: {final_cost_hours:.2f} hours ({final_cost_seconds:.0f} seconds)")

            else: # Simulation algorithm itself failed to produce a result
                log.error(f"{selected_mode} simulation failed to produce a valid result (best_final_sequence_info is None).")
                self._pop_wait_cursor_if_busy()
                QMessageBox.critical(self, "Simulation Failed", f"{selected_mode} simulation did not complete successfully. Check logs.")

        except Exception as e:
            log.exception("Error during Run Simulation process (in main try block).")
            self._pop_wait_cursor_if_busy()
            QMessageBox.critical(self, "Simulation Error", f"An unexpected error occurred:\n{e}\n\nTraceback:\n{traceback.format_exc()}")
        finally:
            if 'progress' in locals() and progress and isinstance(progress, QProgressDialog):
                if not progress.wasCanceled(): progress.setValue(progress.maximum())
                progress.deleteLater()
            self._pop_wait_cursor_if_busy()
            # Restore generated layer visibility after simulation completes or fails.
            _apply_generated_layers_visibility(True)
            log.info("--- handle_run_simulation finished ---")

    def _run_teardrop_algorithm(self, first_line_num, active_line_nums, all_remaining_lines, 
                                line_data, required_layers, sim_params, turn_cache):
        """
        Runs the Teardrop simulation algorithm to generate an optimized sequence.
        Fixed to pass explicit turn mode to turn calculations.
        """
        log.info("Starting Teardrop Simulation...")

        # Initialize progress dialog
        progress = None
        if len(all_remaining_lines) > 1:
            progress = QtWidgets.QProgressDialog(f"Running Teardrop Simulation...", "Cancel", 
                                               0, len(all_remaining_lines), self)
            progress.setWindowModality(_QT_WINDOW_MODAL)
            progress.setMinimumDuration(500)

        try:
            # Determine starting direction
            start_reciprocal = (sim_params.get('first_heading_option') == "High to Low SP (Reciprocal)")
            log.info(f"Teardrop starting direction: {'Reciprocal' if start_reciprocal else 'Normal'}")

            # Get turn mode from UI or params
            # Important: This forces the turn calculator to use LSR/RSL instead of LSL/RSR
            current_turn_mode = "teardrop" 
            if hasattr(self, 'turnTypeComboBox'):
                current_turn_mode = self.turnTypeComboBox.currentText().lower()

            # Initialize sequence with first line
            current_seq = [first_line_num]
            first_line_info = line_data.get(first_line_num)
            if not first_line_info:
                raise ValueError(f"Line data missing for first line {first_line_num}")

            # Initial cost calculation
            initial_cost = 0.0
            shooting_speed = shooting_speed_mps(sim_params, bool(start_reciprocal))

            # Line time
            line_time = first_line_info['length'] / shooting_speed

            # Run-in time
            runin_time = 0.0
            runin_geom = self._find_runin_geom(
                required_layers["runins"],
                first_line_num,
                "End" if start_reciprocal else "Start",
                sim_params.get("run_in_length_meters", 500),
            )
            if runin_geom:
                runin_time = self._calculate_runin_time(
                    runin_geom, sim_params, line_traversal_reciprocal=start_reciprocal
                )
            
            initial_cost += runin_time + line_time

            # Get exit state after first line
            current_exit_pt, current_exit_hdg = self._get_next_exit_state(
                first_line_num, start_reciprocal, line_data, sim_params
            )
            
            if current_exit_pt is None or current_exit_hdg is None:
                raise ValueError("Exit state error after first line")

            # Initialize state
            initial_remaining = set(all_remaining_lines) - {first_line_num}
            initial_direction_str = 'high_to_low' if start_reciprocal else 'low_to_high'
            
            current_state = {
                'last_line_num': first_line_num, 
                'exit_pt': current_exit_pt, 
                'exit_hdg': current_exit_hdg,
                'is_reciprocal': start_reciprocal, 
                'remaining_lines': initial_remaining,
                'line_directions': {first_line_num: initial_direction_str}
            }
            current_cost = initial_cost

            # Process each remaining line
            seq_step = 1
            while current_state['remaining_lines']:
                if progress:
                    if progress.wasCanceled():
                        raise Exception("Simulation cancelled by user.")
                    progress.setValue(seq_step)
                    QtWidgets.QApplication.processEvents()

                last_line_num = current_state['last_line_num']
                exit_pt = current_state['exit_pt']
                exit_hdg = current_state['exit_hdg']
                remaining = current_state['remaining_lines']

                # Find nearest/next line
                next_line_num = self._determine_next_line(last_line_num, remaining, line_data)
                if next_line_num is None:
                    break

                # Teardrop logic: Alternate direction every line
                next_is_reciprocal = not current_state['is_reciprocal']
                next_line_info = line_data.get(next_line_num)
                
                if not next_line_info:
                    current_state['remaining_lines'].remove(next_line_num)
                    continue

                # Entry state for next line
                p_entry, h_entry = self._get_entry_details(next_line_info, next_is_reciprocal, sim_params)
                
                if not p_entry or h_entry is None:
                    log.error(f"Cannot find entry for line {next_line_num}")
                    current_state['remaining_lines'].remove(next_line_num)
                    continue

                # --- Turn Calculation WITH Turn Mode ---
                # This ensures the simulation cost reflects actual Teardrop length
                turn_geom, turn_length, turn_time = self._get_cached_turn(
                    last_line_num,
                    next_line_num,
                    current_state["is_reciprocal"],
                    next_is_reciprocal,
                    exit_pt,
                    exit_hdg,
                    p_entry,
                    h_entry,
                    sim_params,
                    turn_cache,
                    turn_mode=current_turn_mode  # PASS TURN MODE HERE
                )

                if turn_time is None:
                    log.error(f"Turn calculation failed {last_line_num}->{next_line_num}")
                    current_state['remaining_lines'].remove(next_line_num)
                    continue

                # Simulate adding line segments
                new_exit_pt, new_exit_hdg, r_time, l_time = self._simulate_add_line(
                    next_line_num, next_is_reciprocal, line_data, required_layers, sim_params
                )

                if new_exit_pt is None:
                    current_state['remaining_lines'].remove(next_line_num)
                    continue

                # Update sequence info
                current_cost += turn_time + r_time + l_time
                current_seq.append(next_line_num)
                
                # Update current state for next iteration
                current_state['line_directions'][next_line_num] = 'high_to_low' if next_is_reciprocal else 'low_to_high'
                current_state.update({
                    'last_line_num': next_line_num,
                    'exit_pt': new_exit_pt,
                    'exit_hdg': new_exit_hdg,
                    'is_reciprocal': next_is_reciprocal,
                    'remaining_lines': remaining - {next_line_num}
                })

                seq_step += 1

            if progress:
                progress.setValue(len(all_remaining_lines))

            return {
                'seq': current_seq, 
                'cost': current_cost, 
                'state': current_state
            }

        except Exception as e:
            log.exception(f"Error in Teardrop algorithm: {e}")
            return None
        finally:
            if progress:
                progress.deleteLater()

    def _run_racetrack_algorithm(self, first_line_num, active_line_nums, line_data, 
                                required_layers, sim_params, turn_cache):
        """
        Runs the Racetrack simulation algorithm to generate an optimized interleaved sequence.

        This algorithm:
        1. Calculates the optimal jump interval based on turn radius and line spacing
        2. Generates an interleaved sequence that minimizes turns
        3. Evaluates both normal and reciprocal directions
        4. Selects the optimal direction based on cost and user preference

        Args:
            first_line_num (int): Line number to start the sequence
            active_line_nums (list): List of available non-failed line numbers
            line_data (dict): Dictionary containing line information
            required_layers (dict): Dictionary of required QGIS layers
            sim_params (dict): Simulation parameters
            turn_cache (dict): Cache for turn calculations

        Returns:
            dict: Final sequence information or None if simulation fails
                  Format: {'seq': list, 'cost': float, 'state': dict}
        """
        log.info("Starting True Interleaved Racetrack Algorithm...")

        try:
            if not active_line_nums:
                raise ValueError("No active lines found.")

            # Calculate ideal jump count based on turn radius and line interval
            turn_radius = sim_params.get('turn_radius_meters', 900.0)
            line_interval = self._calculate_most_common_interval_from_lines(required_layers['lines'])
            ideal_jump_count = 1

            if line_interval and line_interval > 1.0:
                try:
                    ideal_jump_count = max(1, int(round((turn_radius * 2.0) / line_interval)))
                except Exception as e:
                    log.error(f"Error calculating ideal jump: {e}. Falling back to jump=1.")
            else:
                log.warning("Could not determine valid line interval. Falling back to jump=1.")

            log.info(f"Calculated Ideal Racetrack Jump = {ideal_jump_count} lines")

            # Generate the interleaved racetrack sequence
            generated_racetrack_sequence = self._generate_interleaved_racetrack_sequence(
                active_line_nums, first_line_num, ideal_jump_count
            )

            if not generated_racetrack_sequence:
                raise ValueError("Failed to generate interleaved racetrack sequence.")

            log.debug(f"Generated Interleaved Racetrack Sequence: {generated_racetrack_sequence}")

            # Evaluate both normal and reciprocal directions
            log.debug("Evaluating Interleaved Sequence - Start Normal (Low->High)")
            cost_normal, directions_normal = self._calculate_sequence_time(
                generated_racetrack_sequence, False, sim_params, 
                line_data, required_layers, turn_cache
            )

            log.debug("Evaluating Interleaved Sequence - Start Reciprocal (High->Low)")
            cost_recip, directions_recip = self._calculate_sequence_time(
                generated_racetrack_sequence, True, sim_params, 
                line_data, required_layers, turn_cache
            )

            # Determine which direction is valid
            normal_ok = cost_normal is not None
            recip_ok = cost_recip is not None

            if not normal_ok and not recip_ok:
                raise ValueError("Both Racetrack sequence timing calculations failed.")

            # Select final sequence based on user preference and available results
            user_prefers_reciprocal = (sim_params['first_heading_option'] == "High to Low SP (Reciprocal)")
            final_sequence = generated_racetrack_sequence
            final_cost_seconds = 0
            final_directions = {}

            if user_prefers_reciprocal:
                if recip_ok:
                    log.info("Selecting Reciprocal start (User Preference).")
                    final_cost_seconds = cost_recip
                    final_directions = directions_recip
                elif normal_ok:
                    log.warning("User preference Reciprocal failed. Falling back to Normal.")
                    final_cost_seconds = cost_normal
                    final_directions = directions_normal
                else:
                    raise ValueError("Calculation failed for preferred and alternative directions.")
            else:  # User prefers Normal
                if normal_ok:
                    log.info("Selecting Normal start (User Preference).")
                    final_cost_seconds = cost_normal
                    final_directions = directions_normal
                elif recip_ok:
                    log.warning("User preference Normal failed. Falling back to Reciprocal.")
                    final_cost_seconds = cost_recip
                    final_directions = directions_recip
                else:
                    raise ValueError("Calculation failed for preferred and alternative directions.")

            # Return final sequence information
            return {
                'seq': final_sequence, 
                'cost': final_cost_seconds, 
                'state': {'line_directions': final_directions}
            }

        except Exception as e:
            log.exception(f"Error in Racetrack algorithm: {e}")
            return None

    def _calculate_sequence_time(self, sequence_list, start_reciprocal, sim_params, 
                                line_data, required_layers, turn_cache):
        """
        Calculates the total time required to execute a given sequence.

        This function:
        1. Processes each line in the sequence
        2. Determines the direction (normal/reciprocal) for each line
        3. Calculates turn times between consecutive lines
        4. Sums up acquisition time for each line and transition time between lines

        Args:
            sequence_list (list): Ordered list of line numbers to process
            start_reciprocal (bool): Whether to start in reciprocal direction
            sim_params (dict): Simulation parameters
            line_data (dict): Dictionary containing line information
            required_layers (dict): Required QGIS layers
            turn_cache (dict): Cache for turn calculations

        Returns:
            tuple: (total_time, direction_map) where:
                   - total_time is the estimated time in seconds
                   - direction_map is a dict mapping line numbers to directions
                   - or (None, None) if calculation fails
        """
        if not sequence_list:
            log.warning("Empty sequence provided to time calculation")
            return 0.0, {}

        log.debug(f"Calculating time for sequence of {len(sequence_list)} lines "
                 f"starting {'reciprocal' if start_reciprocal else 'normal'}")

        total_cost_seconds = 0.0
        line_directions = {}  # Maps line numbers to 'low_to_high' or 'high_to_low'

        try:
            # Process first line
            first_line_num = sequence_list[0]
            first_line_info = line_data.get(first_line_num)

            if not first_line_info:
                raise ValueError(f"Missing line data for first line {first_line_num}")

            # Set direction for first line
            current_is_reciprocal = start_reciprocal
            first_direction = 'high_to_low' if current_is_reciprocal else 'low_to_high'
            line_directions[first_line_num] = first_direction

            # Calculate time for first line
            shooting_speed = shooting_speed_mps(sim_params, bool(current_is_reciprocal))

            line_time = first_line_info['length'] / shooting_speed

            # Add run-in time if available
            runin_time = 0.0
            runin_geom = self._find_runin_geom(
                required_layers['runins'],
                first_line_num,
                "End" if current_is_reciprocal else "Start",
                sim_params.get("run_in_length_meters", 500),
            )

            if runin_geom:
                runin_time = self._calculate_runin_time(
                    runin_geom, sim_params, line_traversal_reciprocal=current_is_reciprocal
                )

            total_cost_seconds += runin_time + line_time

            # Get exit point and heading after first line
            exit_pt, exit_hdg = self._get_next_exit_state(
                first_line_num, current_is_reciprocal, line_data, sim_params
            )

            if exit_pt is None or exit_hdg is None:
                raise ValueError(f"Failed to get exit state for line {first_line_num}")

            # Initialize current state for iteration
            current_state = {
                'last_line_num': first_line_num,
                'exit_pt': exit_pt,
                'exit_hdg': exit_hdg,
                'is_reciprocal': current_is_reciprocal
            }

            # Process remaining lines in the sequence
            for i in range(len(sequence_list) - 1):
                from_line = sequence_list[i]
                to_line = sequence_list[i + 1]

                # Alternate direction for each consecutive line
                next_is_reciprocal = not current_state['is_reciprocal']
                next_direction = 'high_to_low' if next_is_reciprocal else 'low_to_high'
                line_directions[to_line] = next_direction

                # Get line data for next line
                to_line_info = line_data.get(to_line)
                if not to_line_info:
                    raise ValueError(f"Missing line data for line {to_line}")

                # Get entry details for next line
                p_entry, h_entry = self._get_entry_details(to_line_info, next_is_reciprocal, sim_params)
                exit_pt = current_state['exit_pt']
                exit_hdg = current_state['exit_hdg']

                if not p_entry or h_entry is None or not exit_pt or exit_hdg is None:
                    raise ValueError(f"Missing entry/exit details for turn {from_line}->{to_line}")

                # Calculate turn between lines
                turn_geom, turn_length, turn_time = self._get_cached_turn(
                    from_line,
                    to_line,
                    current_state["is_reciprocal"],
                    next_is_reciprocal,
                    exit_pt,
                    exit_hdg,
                    p_entry,
                    h_entry,
                    sim_params,
                    turn_cache,
                )

                if turn_geom is None or turn_time is None:
                    raise ValueError(f"Turn calculation failed for {from_line}->{to_line}")

                total_cost_seconds += turn_time

                # Simulate line acquisition
                next_exit_pt, next_exit_hdg, runin_time, line_time = self._simulate_add_line(
                    to_line, next_is_reciprocal, line_data, required_layers, sim_params
                )

                if next_exit_pt is None or next_exit_hdg is None:
                    raise ValueError(f"Exit state error after line {to_line}")

                total_cost_seconds += runin_time + line_time

                # Update state for next iteration
                current_state = {
                    'last_line_num': to_line,
                    'exit_pt': next_exit_pt,
                    'exit_hdg': next_exit_hdg,
                    'is_reciprocal': next_is_reciprocal
                }

            log.info(f"Sequence time calculation complete. Total time: {total_cost_seconds:.1f} seconds")
            # --- ADD DEBUG LOG ---
            log.debug(f"[_calculate_sequence_time] Returning directions: {line_directions}")
            # --- END DEBUG LOG ---
            return total_cost_seconds, line_directions

        except Exception as e:
            log.exception(f"Error calculating sequence time: {e}")
            return None, None

    # --- 8. Sequence Editing & Finalization ---

# --- Inside OBNPlannerDockWidget class in obn_planner_dockwidget.py ---

    def show_edit_sequence_dialog(self):
        """
        Shows the sequence editor dialog, passing context including deviated line data.

        This function creates and displays a dialog for editing the acquisition sequence,
        visualizes the updated path after edits, and prepares for potential future RRT integration.
        """
        log.debug("Edit Sequence button clicked")

        if self._needs_regeneration_before_simulation():
            answer = QMessageBox.question(
                self,
                "Regenerate Required Before Finalize",
                "Generation-related settings changed since the last successful Generate Lookahead Lines.\n\n"
                "Finalize/Edit would use outdated timing and geometry.\n\n"
                "Regenerate lookahead lines now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                self.handle_generate_lines(silent=True)
                if self._needs_regeneration_before_simulation():
                    QMessageBox.warning(
                        self,
                        "Generation Required",
                        "Could not refresh generated lookahead layers.\n"
                        "Please click 'Generate Lookahead Lines' and then run simulation again.",
                    )
                else:
                    QMessageBox.information(
                        self,
                        "Simulation Update Needed",
                        "Lookahead lines were regenerated.\n\n"
                        "Please run simulation again to refresh timing before Finalize/Edit.",
                    )
            return

        # Verify simulation results exist
        if not self.last_simulation_result:
            QMessageBox.warning(self, "No Sequence", "Run simulation first to generate a sequence")
            return

        # Verify dialog component is available
        if not SequenceEditDialog:
            log.error("SequenceEditDialog component not found")
            QMessageBox.critical(self, "Missing Component", "Sequence Edit Dialog component failed to load")
            return

        # Validate required context data
        required_context = [
            ('simulation parameters', self.last_sim_params),
            ('line data', self.last_line_data),
            ('required layers', self.last_required_layers),
            ('turn cache', self.last_turn_cache)
        ]

        missing_context = [name for name, value in required_context if not value]

        if missing_context:
            log.error(f"Missing context for editing: {', '.join(missing_context)}")
            QMessageBox.critical(self, "Missing Data",
                               f"Missing required data: {', '.join(missing_context)}. Please re-run simulation.")
            return

        # Prepare context with helper functions and data
        context = {
            "sim_params": self.last_sim_params,
            "line_data": self.last_line_data, # Pass potentially deviated line data
            "required_layers": self.last_required_layers,
            "turn_cache": self.last_turn_cache,
            # Pass necessary helper methods from the main widget
            "_get_cached_turn": self._get_cached_turn,
            "_find_runin_geom": self._find_runin_geom,
            "_calculate_runin_time": self._calculate_runin_time,
            "_get_next_exit_state": self._get_next_exit_state,
            "_get_entry_details": self._get_entry_details,
            "redraw_callback": self._redraw_map_from_dialog
        }

        # --- Initial Simulation Result Logging (for debugging) ---
        sim_result_to_pass = self.last_simulation_result
        log.debug(f"[show_edit_sequence_dialog - Before Dialog] Passing initial simulation result:")
        log.debug(f"  Sequence: {sim_result_to_pass.get('seq')}")
        log.debug(f"  Cost: {sim_result_to_pass.get('cost')}")
        log.debug(f"  State (raw): {sim_result_to_pass.get('state')}")
        log.debug(f"  Directions from state: {sim_result_to_pass.get('state', {}).get('line_directions')}")
        # --- End Initial Logging ---

        # Create and show dialog
        try:
            # Pass the current simulation result and context to the dialog
            dialog = SequenceEditDialog(
                self.last_simulation_result,
                context,
                self.recalculate_edited_sequence, # Callback for recalculation within dialog
                parent=self
            )

            result = dialog.exec() # Show the dialog modally

            if result == _QDIALOG_ACCEPTED:
                log.info("Sequence Edit Dialog accepted")
                # Get the final, potentially edited, sequence information from the dialog
                final_info = dialog.get_final_sequence_info()

                if not final_info:
                    log.error("Dialog returned invalid or missing final sequence information")
                    QMessageBox.warning(self, "Edit Error", "The edit dialog did not return valid sequence information.")
                    return

                # --- ADD DEBUG LOG for final directions received ---
                final_directions_map = final_info.get('state', {}).get('line_directions', {})
                log.debug(f"[show_edit_sequence_dialog - After Dialog] Final directions map received from dialog: {final_directions_map}")
                log.debug(f"[show_edit_sequence_dialog - After Dialog] Final sequence received: {final_info.get('seq')}")
                log.debug(f"[show_edit_sequence_dialog - After Dialog] Final cost received: {final_info.get('cost')}")
                # --- END DEBUG LOG ---

                # Update the stored results with the edited sequence/cost/state
                self.last_simulation_result = final_info

                # Visualize the final path based on the edited information
                QApplication.setOverrideCursor(_QT_WAIT_CURSOR)
                visualization_successful = False
                try:
                    # --- >>> CLEAR THE CACHE BEFORE RECONSTRUCTION <<< ---
                    log.debug("Clearing turn cache before final path reconstruction.")
                    if self.last_turn_cache is not None:
                        self.last_turn_cache.clear()
                    else:
                        log.warning("Turn cache object was None, cannot clear.")
                        self.last_turn_cache = {} # Re-initialize just in case
                    # --- >>> END CACHE CLEAR <<< --

                    # Reconstruct path geometry using the FINAL edited sequence info
                    log.debug("Reconstructing final path based on edited sequence...")
                    path_segments = self._reconstruct_path(
                        final_info, # Pass the final edited info
                        self.last_line_data, # Use potentially deviated line data
                        self.last_required_layers,
                        self.last_sim_params,
                        self.last_turn_cache
                    )

                    if not path_segments:
                         log.error("Path reconstruction failed after edit. Cannot visualize.")
                         self._pop_wait_cursor_if_busy()
                         QMessageBox.warning(self, "Visualization Skipped", "Path reconstruction failed after edits, skipping visualization.")
                    else:
                        # Visualize the reconstructed path
                        log.debug("Visualizing the final optimized path...")
                        source_crs = self.last_required_layers.get('lines', QgsProject.instance()).crs()
                        if not source_crs or not source_crs.isValid():
                            log.warning("Source/Project CRS invalid for visualization. Using fallback.")
                            source_crs = QgsCoordinateReferenceSystem("EPSG:4326")

                        self._visualize_optimized_path(
                            final_info['seq'], # Use final sequence
                            path_segments,
                            self.last_sim_params.get('start_datetime', datetime.now()),
                            source_crs,
                            self.last_line_data # Pass line data for deviation flags
                        )

                        # Show completion message with final timing estimate
                        hours = final_info.get('cost', 0) / 3600.0
                        log.info(f"Final plan visualized. Estimated time: {hours:.2f} hours")
                        visualization_successful = True

                except Exception as e:
                    log.exception(f"Error during final visualization or lookahead generation: {e}")
                    self._pop_wait_cursor_if_busy()
                    QMessageBox.critical(self, "Finalization Error",
                                       f"Error visualizing or finalizing the plan: {str(e)}")
                finally:
                    self._pop_wait_cursor_if_busy()

            else: # Dialog was cancelled
                log.info("Sequence Edit Dialog cancelled by user")

        except Exception as dialog_error:
            log.exception(f"Error creating or showing sequence edit dialog: {dialog_error}")
            QMessageBox.critical(self, "Dialog Error",
                               f"Error opening sequence editor: {str(dialog_error)}")

    def _redraw_map_from_dialog(self, sequence_info):
        """Callback to dynamically redraw the map while interacting with Sequence Edit Dialog."""
        if not sequence_info: return
        try:
            # Fresh redraw: avoid unbounded turn_cache growth during long edit sessions
            # (each nudge/mode tweak used to add new keys; paths are recomputed anyway).
            if self.last_turn_cache is not None:
                self.last_turn_cache.clear()

            path_segments = self._reconstruct_path(
                sequence_info,
                self.last_line_data,
                self.last_required_layers,
                self.last_sim_params,
                self.last_turn_cache
            )
            if path_segments:
                source_crs = self.last_required_layers.get('lines', QgsProject.instance()).crs()
                self._visualize_optimized_path(
                    sequence_info['seq'],
                    path_segments,
                    self.last_sim_params.get('start_datetime', datetime.now()),
                    source_crs,
                    self.last_line_data
                )
        except Exception as e:
            log.warning(f"Dynamic redraw failed: {e}")

# --- End of show_edit_sequence_dialog method ---

    def recalculate_edited_sequence(self, edited_sequence, edited_directions, custom_turns=None):
        """
        Recalculates total time for an edited sequence/directions using stored context.

        Uses the same ``_get_cached_turn`` overrides as path reconstruction: per-leg
        ``custom_turns`` may include radius, mode, flip, and path nudge (nudge_dx/dy).

        Note: The sequence editor dialog uses ``_calculate_segment_times`` for the table
        (including doubled run-in policy). Call this for a consistent **total cost** with
        those turn parameters when seq/dirs/custom_turns are known.

        Args:
            edited_sequence (list): List of line numbers in edited sequence
            edited_directions (dict): Dictionary mapping line numbers to directions
            custom_turns (dict, optional): Same structure as ``sequence_info['custom_turns']``

        Returns:
            dict: Updated sequence information with cost and state, or None on failure
        """
        log.debug(f"Recalculating time for edited sequence (length: {len(edited_sequence) if edited_sequence else 0})")

        # Validate input sequence
        if not edited_sequence:
            log.warning("Cannot recalculate: Empty sequence provided")
            return None

        # Get context from previous simulation
        sim_params = self.last_sim_params
        line_data = self.last_line_data
        req_layers = self.last_required_layers
        turn_cache = self.last_turn_cache

        # Verify all context data is available
        if not all([sim_params, line_data, req_layers, turn_cache is not None]):
            log.error("Cannot recalculate: Missing simulation context")
            return None

        # Initialize calculation state
        total_cost = 0.0
        current_state = {}
        custom_turns = custom_turns if custom_turns is not None else {}
        mode_key_global = sim_params.get("acquisition_mode_key", "teardrop")

        try:
            # Process first line in sequence
            first_line_num = edited_sequence[0]
            first_dir = edited_directions.get(first_line_num, 'low_to_high')
            first_is_recip = (first_dir == 'high_to_low')

            # Get exit state information for first line
            exit_pt, exit_hdg, runin_time, line_time = self._simulate_add_line(
                first_line_num, first_is_recip, line_data, req_layers, sim_params
            )

            if exit_pt is None:
                raise ValueError(f"Failed to calculate initial state for line {first_line_num}")

            # Add initial times to total
            total_cost += runin_time + line_time

            # Initialize current state after first line
            current_state = {
                'last_line_num': first_line_num,
                'exit_pt': exit_pt,
                'exit_hdg': exit_hdg,
                'is_reciprocal': first_is_recip,
                'line_directions': edited_directions  # Store full direction map
            }

            # Process remaining lines in sequence
            for i in range(len(edited_sequence) - 1):
                from_line = edited_sequence[i]
                to_line = edited_sequence[i + 1]
                to_dir = edited_directions.get(to_line, 'low_to_high')
                to_is_recip = (to_dir == 'high_to_low')

                # Get entry details for destination line
                to_info = line_data[to_line]
                entry_pt, entry_hdg = self._get_entry_details(to_info, to_is_recip, sim_params)

                # Get current exit state
                exit_pt = current_state['exit_pt']
                exit_hdg = current_state['exit_hdg']

                # Validate turn parameters
                if not all([entry_pt, entry_hdg is not None, exit_pt, exit_hdg is not None]):
                    raise ValueError(f"Missing turn data for {from_line} → {to_line}")

                from_is_recip = edited_directions.get(from_line, "low_to_high") == "high_to_low"

                turn_key = f"{from_line}_{to_line}"
                turn_override = custom_turns.get(turn_key, {})
                custom_radius = turn_override.get("radius")
                custom_flip = turn_override.get("flip", False)
                nudge_dx = float(turn_override.get("nudge_dx", 0) or 0)
                nudge_dy = float(turn_override.get("nudge_dy", 0) or 0)
                mid_loop_count = int(turn_override.get("mid_loop_count", 0) or 0)
                mid_loop_side = int(turn_override.get("mid_loop_side", 1) or 1)
                mid_loop_dx = float(turn_override.get("mid_loop_dx", 0) or 0)
                mid_loop_dy = float(turn_override.get("mid_loop_dy", 0) or 0)
                custom_mode_text = turn_override.get("mode")
                turn_mode_override = mode_key_global
                if custom_mode_text == "Teardrop":
                    turn_mode_override = "teardrop"
                elif custom_mode_text == "Racetrack":
                    turn_mode_override = "racetrack"

                turn_geom, turn_length, turn_time = self._get_cached_turn(
                    from_line,
                    to_line,
                    from_is_recip,
                    to_is_recip,
                    exit_pt,
                    exit_hdg,
                    entry_pt,
                    entry_hdg,
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

                if turn_geom is None or turn_time is None:
                    raise ValueError(f"Turn calculation failed for {from_line} → {to_line}")

                # Add turn time to total
                total_cost += turn_time

                # Calculate next line state
                next_exit_pt, next_exit_hdg, next_runin_time, next_line_time = self._simulate_add_line(
                    to_line, to_is_recip, line_data, req_layers, sim_params
                )

                if next_exit_pt is None:
                    raise ValueError(f"Failed to calculate state after line {to_line}")

                # Add line time to total
                total_cost += next_runin_time + next_line_time

                # Update current state for next iteration
                current_state['last_line_num'] = to_line
                current_state['exit_pt'] = next_exit_pt
                current_state['exit_hdg'] = next_exit_hdg
                current_state['is_reciprocal'] = to_is_recip

            # Return updated sequence information
            result = {
                'seq': edited_sequence,
                'cost': total_cost,
                'state': current_state,
                'custom_turns': dict(custom_turns),
            }

            log.debug(f"Recalculation complete. Total cost: {total_cost:.1f}s ({total_cost/3600:.2f}h)")
            return result

        except Exception as e:
            log.exception(f"Error during sequence recalculation: {e}")
            return None

    def _calculate_dubins_turn(self, p_exit, h_exit, p_entry, h_entry, radius, turn_speed_mps, turn_rate_dps=None, mode_key=None, turn_mode=None, custom_flip=False):
        """
        Calculates the Dubins path between two poses using the local dubins_path module.
        """
        # If turn_mode is not explicitly passed, try to take it from mode_key (for compatibility)
        if turn_mode is None:
            turn_mode = mode_key

        log.debug(f"Calculating Dubins turn (Mode: {turn_mode})...")
        
        try:
            # 1. Validation
            if not all([p_exit, p_entry, h_exit is not None, h_entry is not None]):
                log.error("Missing required points or headings for turn calculation")
                return None, None, None

            if radius <= 0:
                log.error(f"Invalid radius: {radius}m. Must be positive.")
                return None, None, None

            # 2. Check for coincident points AND matching headings
            heading_diff = abs((h_exit - h_entry + 180) % 360 - 180)
            if p_exit.sqrDist(p_entry) < 1e-6 and heading_diff < 1.0:
                # FIX: Do not create 0-length line segment (causes QGIS rendering crash)
                return QgsGeometry(), 0.0, 0.0

            # 3. Heading conversion (QGIS 0=N, CW -> Math 0=E, CCW)
            # IMPORTANT: dubins_path.get_curve expects radians internally, but we double-check conversion
            start_heading_math = (90.0 - h_exit + 360.0) % 360.0
            end_heading_math = (90.0 - h_entry + 360.0) % 360.0

            densification_dist = max(1.0, radius / 9.0)

            # 4. Core calculation
            projection_points = dubins_calc.get_curve(
                s_x=p_exit.x(), s_y=p_exit.y(), s_head=start_heading_math,
                e_x=p_entry.x(), e_y=p_entry.y(), e_head=end_heading_math,
                radius=radius,
                max_line_distance=densification_dist,
                turn_mode=turn_mode, # Use unified turn_mode
                flip_sense=custom_flip
            )

            # 5. Teardrop Extension Logic (if points are too close for a loop)
            if turn_mode == "teardrop" and not projection_points:
                log.debug("Teardrop failed (insufficient space). Extending entry backward.")
                
                # Backward vector along entry course
                rad_entry_rev = math.radians((h_entry + 180.0) % 360.0)
                vx, vy = math.sin(rad_entry_rev), math.cos(rad_entry_rev)
                
                extended_dist = 0.0
                # Step was too large (25% of radius = 425m for R=1700). 
                # Reduce it to 20 meters to extend the loop smoothly without visual jumps.
                step = 20.0
                max_ext = radius * 15.0
                
                while extended_dist < max_ext and not projection_points:
                    extended_dist += step
                    new_x = p_entry.x() + vx * extended_dist
                    new_y = p_entry.y() + vy * extended_dist
                    
                    projection_points = dubins_calc.get_curve(
                        s_x=p_exit.x(), s_y=p_exit.y(), s_head=start_heading_math,
                        e_x=new_x, e_y=new_y, e_head=end_heading_math,
                        radius=radius,
                        max_line_distance=densification_dist,
                        turn_mode=turn_mode,
                        flip_sense=custom_flip
                    )

            if not projection_points:
                log.error("Dubins path calculation returned no points")
                return None, None, None

            # 6. Convert to QGIS format, filtering out invalid points (NaN/Inf)
            raw_qgs_points = []
            for pt in projection_points:
                if not (math.isnan(pt[0]) or math.isnan(pt[1]) or math.isinf(pt[0]) or math.isinf(pt[1])):
                    raw_qgs_points.append(QgsPointXY(pt[0], pt[1]))

            if not raw_qgs_points:
                return QgsGeometry(), 0.0, 0.0

            # Always start exactly at p_exit
            qgs_points = [QgsPointXY(p_exit.x(), p_exit.y())]

            # Add points that are sufficiently far from the previous point (1 meter threshold to survive float32 rendering precision)
            for pt in raw_qgs_points:
                if qgs_points[-1].sqrDist(pt) > 1.0:
                    qgs_points.append(pt)

            # Force the final point to be p_entry
            target_entry = QgsPointXY(p_entry.x(), p_entry.y())
            
            # SAFE ENDPOINT MERGE: Remove ANY points at the end of the list that are too close to p_entry.
            # This completely eliminates the risk of 0-length segments at the end of the line.
            while len(qgs_points) > 1 and qgs_points[-1].sqrDist(target_entry) <= 1.0:
                qgs_points.pop()
                
            # If the only point left is p_exit and it's too close to target_entry, we don't need a turn geometry
            if len(qgs_points) == 1 and qgs_points[0].sqrDist(target_entry) <= 1.0:
                return QgsGeometry(), 0.0, 0.0
                
            qgs_points.append(target_entry)

            if len(qgs_points) < 2:
                return QgsGeometry(), 0.0, 0.0

            turn_geom = QgsGeometry.fromPolylineXY(qgs_points)
            if turn_geom.isEmpty():
                return None, None, None

            # 7. Length and Time
            turn_length = max(0.0, turn_geom.length())

            if turn_mode == "teardrop":
                st = self._get_stability_settings()
                min_chord = float(st.get("teardrop_loop_min_chord_m", 5.0))
                chord_fac = float(st.get("teardrop_loop_chord_factor", 3.5))
                circ_fac = float(st.get("teardrop_loop_circumference_factor", 1.05))
                chord_sq = p_exit.sqrDist(p_entry)
                chord = math.sqrt(chord_sq) if chord_sq > 0 else 0.0
                full_loop = 2.0 * math.pi * radius
                if chord > min_chord and (
                    turn_length > full_loop * circ_fac
                    or (
                        turn_length > chord * chord_fac
                        and turn_length > chord + radius * 2.0
                    )
                ):
                    log.warning(
                        "Teardrop turn looks like an excessive loop (chord=%.1f m, path=%.1f m, R=%.1f). "
                        "When line spacing is close to the turn diameter, try Racetrack or the Turn Editor.",
                        chord,
                        turn_length,
                        radius,
                    )

            if turn_speed_mps > 0:
                dist_time = turn_length / turn_speed_mps
                if turn_rate_dps and turn_rate_dps > 0:
                    h_diff = abs((h_entry - h_exit + 180) % 360 - 180)
                    rate_time = h_diff / turn_rate_dps
                    turn_time = max(dist_time, rate_time)
                else:
                    turn_time = dist_time
            else:
                turn_time = 0.0

            log.debug(f"Turn calculated: {turn_mode}, Length: {turn_length:.1f}m, Time: {turn_time:.1f}s")
            return turn_geom, turn_length, turn_time

        except Exception as e:
            log.exception(f"Unexpected error in _calculate_dubins_turn: {e}")
            return None, None, None

    def _get_entry_details(self, line_info, is_reciprocal, sim_params=None):
        """
        Gets the entry point and heading for a survey line dynamically based on run-in length.
        """
        line_num = line_info.get('line_num', 'unknown')
        base_heading = line_info.get('base_heading')
        if base_heading is None:
            log.error(f"Missing base heading for line {line_num}")
            return None, None

        run_in_length = sim_params.get('run_in_length_meters', 500.0) if sim_params else 500.0

        if is_reciprocal:  # Reciprocal direction (High->Low)
            line_pt = line_info.get('end_point_geom')
            heading = (base_heading + 180.0) % 360.0
        else:  # Normal direction (Low->High)
            line_pt = line_info.get('start_point_geom')
            heading = base_heading

        if not line_pt:
            log.error(f"Missing entry point geometry for line {line_num}")
            return None, None

        heading_rad = math.radians(heading)
        vx = math.sin(heading_rad)
        vy = math.cos(heading_rad)
        
        entry_pt = QgsPointXY(line_pt.x() - vx * run_in_length, line_pt.y() - vy * run_in_length)

        log.debug(f"Entry details for line {line_num}: "
                 f"point=({entry_pt.x():.1f}, {entry_pt.y():.1f}), heading={heading:.1f}°")

        return entry_pt, heading

    def _get_next_exit_state(self, line_num, direction_is_reciprocal, line_data, sim_params=None):
        """
        Determines the exit point and heading dynamically based on run-out length.
        """
        line_info = line_data.get(line_num)
        if not line_info:
            log.error(f"Missing data for line {line_num}")
            return None, None

        base_heading = line_info.get('base_heading')
        if base_heading is None:
            log.error(f"Missing base heading for line {line_num}")
            return None, None

        run_out_length = sim_params.get('run_out_length_meters', 0.0) if sim_params else 0.0

        if not direction_is_reciprocal:  # Normal direction (Low->High)
            line_pt = line_info.get('end_point_geom')
            exit_hdg = base_heading
        else:  # Reciprocal direction (High->Low)
            line_pt = line_info.get('start_point_geom')
            exit_hdg = (base_heading + 180.0) % 360.0

        if not line_pt:
            log.error(f"Missing exit point geometry for line {line_num}")
            return None, None

        heading_rad = math.radians(exit_hdg)
        vx = math.sin(heading_rad)
        vy = math.cos(heading_rad)
        
        exit_pt = QgsPointXY(line_pt.x() + vx * run_out_length, line_pt.y() + vy * run_out_length)

        log.debug(f"Exit state for line {line_num}: "
                 f"point=({exit_pt.x():.1f}, {exit_pt.y():.1f}), heading={exit_hdg:.1f}°")

        return exit_pt, exit_hdg

    def _simulate_add_line(self, line_num, direction_is_reciprocal, line_data, required_layers, sim_params):
        """
        Calculates run-in and line acquisition time for a potential line without modifying path segments.

        This function is used to estimate the time cost of adding a line to a sequence
        without actually adding it to the path segments.

        Args:
            line_num (int): Line number to simulate
            direction_is_reciprocal (bool): Whether the line is traversed in reciprocal direction
            line_data (dict): Dictionary containing line information
            required_layers (dict): Dictionary of required QGIS layers
            sim_params (dict): Simulation parameters

        Returns:
            tuple: (exit_point, exit_heading, runin_time, line_time) or (None, None, 0, 0) on failure
        """
        # Initialize timing variables
        runin_time = 0.0
        line_time = 0.0

        # Get line data with validation
        line_info = line_data.get(line_num)
        if not line_info:
            log.error(f"Missing data for line {line_num}")
            return None, None, 0.0, 0.0

        # Get line length and validate shooting speed (directional Low→High vs High→Low)
        line_length = line_info.get('length', 0.0)
        shooting_speed = shooting_speed_mps(sim_params, bool(direction_is_reciprocal))

        # Calculate line acquisition time
        if line_length > 0:
            line_time = line_length / shooting_speed
            log.debug(f"Line {line_num} acquisition time: {line_time:.1f}s ({line_length:.1f}m @ {shooting_speed:.2f}m/s)")
        else:
            log.warning(f"Line {line_num} has invalid length: {line_length}")

        # Find appropriate run-in geometry based on direction
        runin_location = "End" if direction_is_reciprocal else "Start"
        runin_geom = self._find_runin_geom(
            required_layers.get('runins'),
            line_num,
            runin_location,
            sim_params.get('run_in_length_meters', 500)
        )

        # Calculate run-in time if run-in geometry exists
        if runin_geom and not runin_geom.isEmpty():
            runin_time = self._calculate_runin_time(
                runin_geom, sim_params, line_traversal_reciprocal=direction_is_reciprocal
            )
            log.debug(f"Run-in time for line {line_num} ({runin_location}): {runin_time:.1f}s")

        # --- Calculate run-out time (only when run-out length > 0; End geometry may exist for reciprocal run-in) ---
        runout_time = 0.0
        run_out_len = float(sim_params.get("run_out_length_meters", 0) or 0.0)
        if run_out_len > 0:
            runout_location = "Start" if direction_is_reciprocal else "End"
            runout_geom = self._find_runin_geom(
                required_layers.get("runins"),
                line_num,
                runout_location,
                run_out_len,
            )
            if runout_geom and not runout_geom.isEmpty():
                runout_time = self._calculate_runin_time(
                    runout_geom, sim_params, line_traversal_reciprocal=direction_is_reciprocal
                )
                log.debug(f"Run-out time for line {line_num} ({runout_location}): {runout_time:.1f}s")

        line_time += runout_time

        # Get exit state after line acquisition
        exit_pt, exit_hdg = self._get_next_exit_state(line_num, direction_is_reciprocal, line_data, sim_params)

        # Check for valid exit state
        if exit_pt is None or exit_hdg is None:
            log.warning(f"Failed to determine exit state for line {line_num}")

        return exit_pt, exit_hdg, runin_time, line_time

    def _apply_turn_polyline_nudge(self, turn_geom, exit_pt, entry_pt, dx, dy):
        """
        Shift interior vertices of the sampled Dubins polyline by (dx,dy) in map units.
        Endpoints are pinned to exit_pt / entry_pt so the connector still meets run-out and run-in.
        (Not a tangency-preserving Dubins solve — a practical path edit from the Turn Editor.)
        """
        if not turn_geom or turn_geom.isEmpty() or turn_geom.type() != QgsWkbTypes.LineGeometry:
            return None
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            return QgsGeometry(turn_geom)
        pts = list(turn_geom.vertices())
        if len(pts) < 2:
            return QgsGeometry(turn_geom)
        new_xy = []
        for i, v in enumerate(pts):
            if i == 0:
                new_xy.append(QgsPointXY(exit_pt.x(), exit_pt.y()))
            elif i == len(pts) - 1:
                new_xy.append(QgsPointXY(entry_pt.x(), entry_pt.y()))
            else:
                new_xy.append(QgsPointXY(v.x() + dx, v.y() + dy))
        return QgsGeometry.fromPolylineXY(new_xy)

    def _apply_turn_mid_loop(self, turn_geom, loop_count=0, loop_side=1, loop_radius=0.0, loop_dx=0.0, loop_dy=0.0):
        """
        Inject one or more detour loops into a turn polyline.
        The loop is anchored near the end of the turn, so the vessel can
        "go away and come back" before entering the next line.
        """
        count = int(loop_count or 0)
        if count <= 0 or not turn_geom or turn_geom.isEmpty():
            return turn_geom
        if turn_geom.type() != QgsWkbTypes.LineGeometry:
            return turn_geom

        src = list(turn_geom.vertices())
        if len(src) < 3:
            return turn_geom

        # Put detour close to line entry so arrival is intentionally delayed.
        anchor_i = int((len(src) - 1) * 0.82)
        anchor_i = max(1, min(anchor_i, len(src) - 2))
        p_prev = src[anchor_i - 1]
        p_mid = src[anchor_i]
        p_next = src[anchor_i + 1]

        tx = p_next.x() - p_prev.x()
        ty = p_next.y() - p_prev.y()
        tlen = math.hypot(tx, ty)
        if tlen < 1e-9:
            return turn_geom
        tx /= tlen
        ty /= tlen
        nx, ny = -ty, tx
        sign = -1.0 if float(loop_side or 1) < 0 else 1.0

        r = float(loop_radius or 0.0)
        if r <= 0.0:
            chord = math.hypot(p_next.x() - p_prev.x(), p_next.y() - p_prev.y())
            r = max(40.0, chord * 1.10)

        cx = p_mid.x() + sign * nx * r + float(loop_dx or 0.0)
        cy = p_mid.y() + sign * ny * r + float(loop_dy or 0.0)
        start_ang = math.atan2(p_mid.y() - cy, p_mid.x() - cx)
        ccw = sign > 0
        step_sign = 1.0 if ccw else -1.0
        samples_per_loop = 28

        loop_pts = []
        for _ in range(count):
            for k in range(1, samples_per_loop + 1):
                a = start_ang + step_sign * (2.0 * math.pi * k / samples_per_loop)
                loop_pts.append(QgsPointXY(cx + r * math.cos(a), cy + r * math.sin(a)))

        out = [QgsPointXY(v.x(), v.y()) for v in src[: anchor_i + 1]]
        out.extend(loop_pts)
        out.extend(QgsPointXY(v.x(), v.y()) for v in src[anchor_i + 1 :])
        return QgsGeometry.fromPolylineXY(out)

    def _get_cached_turn(self, from_line, to_line, from_is_reciprocal, to_is_reciprocal, exit_pt, exit_hdg,
                        entry_pt, entry_hdg, sim_params, turn_cache, turn_mode=None, custom_radius=None, custom_flip=False,
                        nudge_dx=0.0, nudge_dy=0.0, mid_loop_count=0, mid_loop_side=1, mid_loop_dx=0.0, mid_loop_dy=0.0):
        """
        Retrieves a cached turn or calculates and caches a new turn between two lines.
        Modified to support specific turn modes (teardrop/racetrack).
        """
        # --- FIX: Avoid teardrop S-turns when connecting parts of the same line ---
        try:
            base_from = str(from_line).split('_')[0]
            base_to = str(to_line).split('_')[0]
            if base_from == base_to and from_is_reciprocal == to_is_reciprocal:
                turn_mode = "racetrack"  # Racetrack allows LSL/RSR, which perfectly form a straight line
        except Exception:
            pass
        # --- END FIX ---

        # Key: acquisition mode + turn parameters + directions + turn_mode.
        # IMPORTANT: turn_mode is added to cache_key so Teardrop and Racetrack don't mix in memory
        mode_key = sim_params.get("acquisition_mode_key") or str(
            sim_params.get("acquisition_mode", "")
        ).strip().casefold()
        
        effective_radius = custom_radius if custom_radius is not None else sim_params.get('turn_radius_meters')
        tr = effective_radius
        # Connector turn is timed for the line being entered (``to_is_reciprocal``).
        turn_speed_for_cache = turn_speed_mps(sim_params, bool(to_is_reciprocal))
        tt = sim_params.get('vessel_turn_rate_dps')

        turn_sig = (
            round(float(tr or 0.0), 3),
            round(float(turn_speed_for_cache or 0.0), 3),
            round(float(tt or 0.0), 3),
        )
        nd = (round(float(nudge_dx or 0.0), 3), round(float(nudge_dy or 0.0), 3))
        ml = (int(mid_loop_count or 0), -1 if float(mid_loop_side or 1) < 0 else 1)
        mld = (round(float(mid_loop_dx or 0.0), 3), round(float(mid_loop_dy or 0.0), 3))

        # Key is now unique for each turn mode and path nudge (Turn Editor drag)
        cache_key = (
            mode_key,
            turn_sig,
            from_line,
            to_line,
            from_is_reciprocal,
            to_is_reciprocal,
            turn_mode,
            custom_radius,
            custom_flip,
            nd,
            ml,
            mld,
        )

        # Return cached result if available
        if cache_key in turn_cache:
            log.debug(
                "Using cached turn [%s] %s->%s (mode=%s)",
                mode_key, from_line, to_line, turn_mode
            )
            return turn_cache[cache_key]

        # Extract required parameters from sim_params with validation
        turn_speed = turn_speed_for_cache
        turn_rate = sim_params.get('vessel_turn_rate_dps')

        if effective_radius is None or effective_radius <= 0:
            effective_radius = 250.0  # Fallback

        if turn_speed is None or turn_speed <= 0:
            turn_speed = 4.0  # Fallback

        # Calculate the turn
        log.debug(
            "Calculating new turn [%s] %s->%s (mode=%s)",
            mode_key, from_line, to_line, turn_mode
        )

        # PASS turn_mode to _calculate_dubins_turn function
        # Ensure _calculate_dubins_turn method also accepts this argument!
        turn_geom, turn_length, turn_time = self._calculate_dubins_turn(
            exit_pt, exit_hdg, entry_pt, entry_hdg,
            effective_radius, turn_speed, turn_rate, mode_key,
            turn_mode=turn_mode, custom_flip=custom_flip
        )

        # Apply minimum turn time if calculation succeeded
        if turn_geom is not None and turn_time is not None:
            turn_time = self._ensure_turn_time(
                turn_geom, turn_length, turn_time, sim_params, turn_speed_mps=turn_speed
            )
        else:
            log.warning(f"Turn calculation failed for {from_line}->{to_line}")

        if turn_geom is not None and not turn_geom.isEmpty() and (abs(nudge_dx) > 1e-9 or abs(nudge_dy) > 1e-9):
            nudged = self._apply_turn_polyline_nudge(turn_geom, exit_pt, entry_pt, nudge_dx, nudge_dy)
            if nudged is not None and not nudged.isEmpty():
                turn_geom = nudged
                turn_length = max(0.0, turn_geom.length())
                turn_time = self._ensure_turn_time(
                    turn_geom, turn_length, None, sim_params, turn_speed_mps=turn_speed
                )

        if turn_geom is not None and not turn_geom.isEmpty() and int(mid_loop_count or 0) > 0:
            looped = self._apply_turn_mid_loop(
                turn_geom,
                loop_count=mid_loop_count,
                loop_side=mid_loop_side,
                loop_radius=(float(effective_radius or 0.0) * 0.75),
                loop_dx=mid_loop_dx,
                loop_dy=mid_loop_dy,
            )
            if looped is not None and not looped.isEmpty():
                turn_geom = looped
                turn_length = max(0.0, turn_geom.length())
                turn_time = self._ensure_turn_time(
                    turn_geom, turn_length, None, sim_params, turn_speed_mps=turn_speed
                )

        # Cache the result
        turn_cache[cache_key] = (turn_geom, turn_length, turn_time)
        return turn_geom, turn_length, turn_time

    def _ensure_turn_time(self, turn_geom, turn_length, turn_time, sim_params, turn_speed_mps=None):
        """
        Ensures a valid turn time exists, calculating it if needed based on geometry and speed.

        This function handles cases where turn_time might be missing or invalid, calculating
        it based on geometry length and configured speeds/rates.

        Args:
            turn_geom (QgsGeometry): Turn geometry
            turn_length (float): Turn length in meters, or None to calculate from geometry
            turn_time (float): Pre-calculated turn time, or None to calculate
            sim_params (dict): Simulation parameters with speed and turn rate settings
            turn_speed_mps: Optional effective turn speed (m/s) for this connector; if omitted,
                uses legacy ``avg_turn_speed_mps``.

        Returns:
            float: Valid turn time in seconds
        """
        # Return existing time if valid
        if turn_time is not None and turn_time > 0:
            return turn_time

        # Handle missing or invalid geometry
        if not turn_geom or turn_geom.isEmpty():
            log.warning("Cannot calculate turn time: Missing geometry")
            return 0.0

        try:
            # Calculate or validate length
            if turn_length is None or turn_length < 0:
                turn_length = max(0.0, turn_geom.length())

            # Get turn speed with validation
            turn_speed = (
                turn_speed_mps
                if turn_speed_mps is not None and turn_speed_mps > 0
                else sim_params.get("avg_turn_speed_mps")
            )
            if not turn_speed or turn_speed <= 0:
                log.warning(f"Invalid turn speed: {turn_speed}. Using default of 3.0 m/s")
                turn_speed = 3.0  # Default speed in m/s

            # Calculate basic time based on distance/speed
            time_seconds = turn_length / turn_speed

            # Apply turning rate constraints if available
            turn_rate_dps = sim_params.get('vessel_turn_rate_dps')
            if turn_rate_dps and turn_rate_dps > 0:
                # Estimate heading change from geometry
                try:
                    # For RRT compatibility: try to extract start/end angles from geometry
                    start_point = None
                    end_point = None
                    heading_change = 0

                    # Get first and last segments for angle estimation
                    if turn_geom.type() == QgsWkbTypes.LineGeometry:
                        vertices = list(turn_geom.vertices())
                        if len(vertices) >= 3:
                            # Estimate heading change from first and last segments
                            # This is a simplification but works for many cases
                            first_segment_angle = math.degrees(math.atan2(
                                vertices[1].y() - vertices[0].y(),
                                vertices[1].x() - vertices[0].x()
                            ))
                            last_segment_angle = math.degrees(math.atan2(
                                vertices[-1].y() - vertices[-2].y(),
                                vertices[-1].x() - vertices[-2].x()
                            ))

                            # Calculate smallest angle between headings
                            heading_change = abs((last_segment_angle - first_segment_angle + 180) % 360 - 180)

                            # Calculate time based on turn rate
                            rate_time = heading_change / turn_rate_dps * 60  # Convert degrees per minute to seconds

                            # Use the longer of the two times (rate-limited or distance-limited)
                            if rate_time > time_seconds:
                                log.debug(f"Turn is rate-limited: {rate_time:.1f}s > {time_seconds:.1f}s (heading change: {heading_change:.1f}°)")
                                time_seconds = rate_time
                except Exception as angle_err:
                    log.debug(f"Could not estimate heading change from turn geometry: {angle_err}")

            # Ensure reasonable minimum time
            min_time = 5.0  # Minimum 5 seconds for any turn
            return max(time_seconds, min_time)

        except Exception as e:
            log.exception(f"Error ensuring turn time: {e}")
            return 0.0

    def _log_turn_connection(self, from_line, to_line, to_is_reciprocal, exit_pt, exit_hdg, entry_pt, entry_hdg):
        """
        Logs detailed information about a turn connection between survey lines.

        This function provides diagnostics for troubleshooting turn calculations
        and visualizing the path planning process.

        Args:
            from_line (int): Line number transitioning from
            to_line (int): Line number transitioning to
            to_is_reciprocal (bool): Whether destination line is acquired in reciprocal direction
            exit_pt (QgsPointXY): Exit point from start line
            exit_hdg (float): Exit heading in degrees
            entry_pt (QgsPointXY): Entry point to destination line
            entry_hdg (float): Entry heading in degrees
        """
        try:
            # Format coordinates safely
            exit_pt_str = "None" if exit_pt is None else f"({exit_pt.x():.1f}, {exit_pt.y():.1f})"
            entry_pt_str = "None" if entry_pt is None else f"({entry_pt.x():.1f}, {entry_pt.y():.1f})"

            # Format headings safely
            exit_hdg_str = "None" if exit_hdg is None else f"{exit_hdg:.1f}°"
            entry_hdg_str = "None" if entry_hdg is None else f"{entry_hdg:.1f}°"

            # Calculate distance and heading change if points are valid
            distance_str = "N/A"
            hdg_change_str = "N/A"

            if exit_pt is not None and entry_pt is not None:
                distance = exit_pt.distance(entry_pt)
                distance_str = f"{distance:.1f}m"

            if exit_hdg is not None and entry_hdg is not None:
                # Calculate smallest angle between headings
                hdg_change = abs((entry_hdg - exit_hdg + 180) % 360 - 180)
                hdg_change_str = f"{hdg_change:.1f}°"

            # Log full connection details
            direction = "reciprocal" if to_is_reciprocal else "normal"
            log.debug(f"Turn connection: Line {from_line} → Line {to_line} ({direction})")
            log.debug(f"  Exit: {exit_pt_str} @ {exit_hdg_str}")
            log.debug(f"  Entry: {entry_pt_str} @ {entry_hdg_str}")
            log.debug(f"  Distance: {distance_str}, Heading change: {hdg_change_str}")

        except Exception as e:
            log.warning(f"Error logging turn connection details: {e}")

    def _calculate_most_common_interval_from_lines(self, lines_layer):
        """
        Calculates the most common interval between adjacent survey lines.

        This function identifies the dominant spacing pattern between lines,
        which is useful for optimizing line acquisition sequences.

        Args:
            lines_layer (QgsVectorLayer): Layer containing survey lines

        Returns:
            float: Most common interval in meters, or None if calculation fails
        """
        log.info(f"Calculating most common line interval from layer: {lines_layer.name()}")

        # Validate input layer
        if not lines_layer or not lines_layer.isValid():
            log.error("Invalid lines layer provided for interval calculation")
            return None

        # Verify required fields exist
        line_num_idx = lines_layer.fields().lookupField("LineNum")
        if line_num_idx == -1:
            log.error("Lines layer missing required 'LineNum' field")
            return None

        # Check for Status field to filter lines
        status_idx = lines_layer.fields().lookupField("Status")
        use_status_filter = status_idx != -1

        # Dictionary to store line geometries
        line_geoms = {}

        # Create feature request - we need geometry
        request = QgsFeatureRequest()


        try:
            # Step 1: Calculate midpoints for each line
            for feature in lines_layer.getFeatures(request):
                # Apply status filter in Python to avoid case-sensitive SQL matching issues
                if use_status_filter:
                    stat_val = feature.attribute(status_idx)
                    if not stat_val or str(stat_val).strip().upper() != "TO BE ACQUIRED":
                        continue

                try:
                    # Get line number with validation
                    line_num_attr = feature.attribute(line_num_idx)
                    if line_num_attr is None:
                        continue

                    try:
                        line_id_str = str(line_num_attr)
                        base_ln = int(line_id_str.split('_')[0])
                    except (ValueError, TypeError):
                        log.warning(f"Skipping line with invalid number: {line_num_attr}")
                        continue
                    
                    # Get and validate geometry
                    geom = feature.geometry()
                    if not geom or geom.isEmpty():
                        continue
                    
                    # Handle multipart geometries
                    if geom.isMultipart():
                        # Try to get first part
                        geom_parts = geom.asGeometryCollection()
                        if not geom_parts:
                            continue
                        geom = geom_parts[0]

                    # Verify we have a line
                    if geom.type() != QgsWkbTypes.LineGeometry or geom.length() <= 0:
                        continue
                    
                    # Store geometry instead of midpoint
                    if base_ln not in line_geoms:
                        line_geoms[base_ln] = QgsGeometry(geom)

                except Exception as feat_err:
                    log.warning(f"Error processing line {feature.id()}: {feat_err}")
                    continue
                
            # Need enough lines to calculate intervals
            if len(line_geoms) < 2:
                log.warning(f"Not enough valid lines to calculate intervals (found {len(line_geoms)})")
                return None

            log.debug(f"Collected geometries for {len(line_geoms)} lines")

            # Step 2: Calculate distances between consecutive line numbers
            sorted_line_nums = sorted(line_geoms.keys())
            intervals = []

            # Calculate all intervals with reasonable threshold
            min_spacing = 1.0  # Minimum meaningful spacing in meters

            for i in range(len(sorted_line_nums) - 1):
                line1 = sorted_line_nums[i]
                line2 = sorted_line_nums[i+1]

                # Skip lines with unusual numbering patterns
                if line2 - line1 > 10000:  # Arbitrary large gap threshold
                    log.debug(f"Skipping large line number gap: {line1} to {line2}")
                    continue

                # Get geometries and calculate exact cross-track distance
                g1 = line_geoms[line1]
                g2 = line_geoms[line2]
                
                mid1 = g1.interpolate(g1.length() / 2.0)
                if mid1 and not mid1.isEmpty():
                    distance = g2.distance(mid1)
                    # Only consider meaningful intervals
                    if distance >= min_spacing:
                        intervals.append(distance)

            if not intervals:
                log.warning("No valid intervals calculated between lines")
                return None

            # Step 3: Group similar intervals to find the dominant pattern
            tolerance = max(5.0, min(intervals) * 0.1)  # Dynamic tolerance based on data
            interval_groups = defaultdict(list)

            for interval in intervals:
                # Find existing group or create new one
                grouped = False
                for group_key in list(interval_groups.keys()):
                    if abs(interval - group_key) <= tolerance:
                        interval_groups[group_key].append(interval)
                        grouped = True
                        break

                if not grouped:
                    interval_groups[interval] = [interval]

            # Step 4: Find most common group and calculate average
            if not interval_groups:
                log.warning("Failed to group intervals")
                return None

            # Get the group with most intervals
            most_common_group = max(interval_groups.items(), key=lambda x: len(x[1]))
            group_key, group_intervals = most_common_group

            # Calculate average of the group
            common_interval = sum(group_intervals) / len(group_intervals)

            log.info(f"Most common line interval: {common_interval:.2f}m "
                    f"(from {len(group_intervals)} out of {len(intervals)} intervals)")

            # Validate result for reasonableness
            if common_interval < 10.0:
                log.warning(f"Calculated interval ({common_interval:.2f}m) seems unusually small")

            return common_interval

        except Exception as e:
            log.exception(f"Error calculating line intervals: {e}")
            return None

    def _generate_interleaved_racetrack_sequence(self, sorted_active_lines, first_line_num, ideal_jump_count):
        """
        Generates an optimized interleaved racetrack sequence for survey line acquisition.

        This function creates a pattern where lines are visited in an interleaved pattern
        to minimize vessel turns. The pattern follows a structure like:
        1022 -> 1118 (1022 + 16*6)
        1028 (1022+6) -> 1124 (1028 + 16*6)
        1034 (1028+6) -> 1130 (1034 + 16*6)

        Args:
            sorted_active_lines (list): List of active line numbers, sorted numerically
            first_line_num (int): The user-specified starting line number
            ideal_jump_count (int): The number of line intervals to jump for the racetrack turn

        Returns:
            list: Line numbers in the calculated sequence, or None if generation fails
        """
        # Validate inputs
        if not sorted_active_lines:
            log.error("Cannot generate sequence: No active lines provided.")
            return None

        if ideal_jump_count < 1:
            log.warning(f"Ideal jump count ({ideal_jump_count}) is less than 1. Using default of 1.")
            ideal_jump_count = 1

        n_lines = len(sorted_active_lines)

        # Create a lookup for faster index retrieval
        line_to_index = {line: idx for idx, line in enumerate(sorted_active_lines)}

        # Verify first line is in active lines, fallback if not (str keys vs int from spinbox)
        first_key = str(first_line_num).strip() if first_line_num is not None else ""
        try:
            start_index = line_to_index[first_key]
            first_line_num = first_key
        except KeyError:
            log.warning(f"Start line {first_line_num} not in active line list. Using first available line.")
            start_index = 0
            first_line_num = sorted_active_lines[0]  # Ensure first line is valid

        log.info(f"Generating Interleaved Sequence: Start={first_line_num} (idx={start_index}), "
                 f"Jump Count={ideal_jump_count}, Total Lines={n_lines}")

        def _get_base_ln(line_id):
            try: return int(str(line_id).split('_')[0])
            except ValueError: return int(line_id)

        # Estimate the typical step between consecutive lines
        line_step = self._calculate_most_common_step(sorted_active_lines)
        if line_step <= 0:
            line_step = 6  # Default step if detection fails
            log.warning(f"Could not detect valid line step. Using default: {line_step}")
        else:
            log.debug(f"Detected common line number step: {line_step}")

        # Generate the sequence using paired structure
        sequence = []
        visited_indices = set()

        # Calculate the target jump line based on ideal_jump_count and detected step
        current_line_base = _get_base_ln(first_line_num)
        current_idx = start_index
        target_jump_line = current_line_base + ideal_jump_count * line_step

        # Find the closest available line to the target jump line
        target_jump_idx = self._find_closest_line_index(
            sorted_active_lines, target_jump_line, current_idx, ideal_jump_count
        )

        if target_jump_idx == -1:
            # Fallback if search failed
            target_jump_idx = min(current_idx + ideal_jump_count, n_lines - 1)
            log.warning(f"Could not find suitable jump line. Using index {target_jump_idx} as fallback.")

        # Setup for interleaved pattern generation
        outward_idx = current_idx
        return_idx = target_jump_idx

        log.debug(f"Starting pair generation: Line1={current_line_base}(idx={current_idx}), "
                  f"TargetJumpLine={target_jump_line}, JumpIdx={target_jump_idx}")

        # Generate the interleaved sequence
        while len(visited_indices) < n_lines:
            # Add outward line if valid and not visited
            if 0 <= outward_idx < n_lines and outward_idx not in visited_indices:
                sequence.append(sorted_active_lines[outward_idx])
                visited_indices.add(outward_idx)

            # Add return line if valid, not visited, and different from outward
            if 0 <= return_idx < n_lines and return_idx not in visited_indices:
                sequence.append(sorted_active_lines[return_idx])
                visited_indices.add(return_idx)

            # Move pointers for next iteration
            outward_idx += 1
            return_idx += 1

            # Safety break condition
            if outward_idx >= n_lines and return_idx >= n_lines:
                break
            
        # Ensure all lines are included (check for missed lines)
        if len(sequence) != n_lines:
            log.warning(f"Sequence generation incomplete. Expected {n_lines} lines, got {len(sequence)}. Adding missing lines.")
            missed_lines = set(sorted_active_lines) - set(sequence)
            sequence.extend(sorted(missed_lines))

        # Final check: ensure the user's specified first line is first
        if sequence and sequence[0] != first_line_num:
            try:
                sequence.remove(first_line_num)
            except ValueError:
                pass  # Should not happen at this point
            sequence.insert(0, first_line_num)

        log.info(f"Generated Racetrack Sequence (Length: {len(sequence)}): {sequence}")
        return sequence

    def _calculate_most_common_step(self, sorted_lines):
        """
        Calculates the most common interval between consecutive line numbers.

        Args:
            sorted_lines (list): Sorted list of line numbers

        Returns:
            int: Most common interval between lines, or 0 if no common interval found
        """
        if len(sorted_lines) < 2:
            return 0
            
        def _get_base_ln(line_id):
            try: return int(str(line_id).split('_')[0])
            except ValueError: return int(line_id)

        # Calculate differences between consecutive lines
        base_lines = sorted(list(set(_get_base_ln(x) for x in sorted_lines)))
        diffs = [base_lines[i+1] - base_lines[i] for i in range(len(base_lines) - 1)]

        # Find the most common difference
        counter = Counter(diffs)
        most_common = counter.most_common(1)

        if most_common and most_common[0][1] > 1:  # Ensure it appears multiple times
            return most_common[0][0]

        # If no clear common difference, return the average difference
        return int(sum(diffs) / len(diffs)) if diffs else 0

    def _find_closest_line_index(self, sorted_lines, target_line, current_idx, ideal_jump):
        """
        Finds the index of the closest line to the target line number.

        Args:
            sorted_lines (list): Sorted list of line numbers
            target_line (int): Target line number to find
            current_idx (int): Current position in the list
            ideal_jump (int): Ideal jump count for search window

        Returns:
            int: Index of the closest line to target, or -1 if not found
        """
        # Define search window around the ideal jump position
        search_range = 5  # Search range on each side of ideal position
        min_idx = max(0, current_idx + ideal_jump - search_range)
        max_idx = min(len(sorted_lines) - 1, current_idx + ideal_jump + search_range)

        # Find closest match within window
        closest_idx = -1
        min_diff = float('inf')
        
        def _get_base_ln(line_id):
            try: return int(str(line_id).split('_')[0])
            except ValueError: return int(line_id)

        for idx in range(min_idx, max_idx + 1):
            base_ln = _get_base_ln(sorted_lines[idx])
            diff = abs(base_ln - target_line)
            if diff < min_diff:
                min_diff = diff
                closest_idx = idx

        return closest_idx

    def _determine_next_line(self, current_line_id, remaining_lines, line_data):
        """
        Determines the next line to process in Teardrop mode.

        This function finds the numerically closest line to the current line
        from the set of remaining lines. For lines with equal distance,
        preference is given to lines with lower line numbers for predictability.

        Args:
            current_line_num (int): Current line being processed
            remaining_lines (set): Set of line numbers that haven't been processed
            line_data (dict): Dictionary of line information

        Returns:
            int: The next line number to process, or None if no lines remain
        """
        if not remaining_lines:
            return None

        # Convert to list for better performance in case of large sets
        remaining_list = list(remaining_lines)
        
        def _get_base_and_part(line_id):
            s = str(line_id).split('_')
            b = int(s[0])
            p = int(s[1]) if len(s) > 1 else 0
            return b, p
            
        current_base, current_part = _get_base_and_part(current_line_id)

        # Find closest line by numerical difference
        closest_line = None
        min_abs_diff = float('inf')

        for line_id in remaining_list:
            base_ln, part_idx = _get_base_and_part(line_id)
            abs_diff = abs(base_ln - current_base)

            is_better = False
            if abs_diff < min_abs_diff:
                is_better = True
            elif abs_diff == min_abs_diff:
                if base_ln == current_base:
                    if part_idx > current_part:
                        if closest_line is None or part_idx < _get_base_and_part(closest_line)[1]:
                            is_better = True
                    elif closest_line is None:
                        is_better = True
                else:
                    if closest_line is None or base_ln < _get_base_and_part(closest_line)[0]:
                        is_better = True
                        
            if is_better:
                min_abs_diff = abs_diff
                closest_line = line_id

        log.debug(f"Next line after {current_line_id}: {closest_line} (Difference: {min_abs_diff})")
        return closest_line

    # --- 11. Visualization ---

    # --- MODIFY _add_line_segments ---
    def _add_line_segments(self, line_num, is_reciprocal, line_data, required_layers, sim_params, result_segments):
        """
        Adds line and associated run-in segments to the result segments list.

        Args:
            line_num (int): Line number to add.
            is_reciprocal (bool): Whether line is acquired in reciprocal direction.
            line_data (dict): Dictionary of line data.
            required_layers (dict): Dictionary of required layers ('lines', 'runins').
            sim_params (dict): Simulation parameters (needed for run-in timing).
            result_segments (list): List to append the segments to.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            log.debug(f"Adding segments for Line {line_num} (Reciprocal: {is_reciprocal})")
            if line_num not in line_data:
                log.warning(f"Line {line_num} not found in line data.")
                return False

            line_info = line_data[line_num]
            line_geom = line_info.get('line_geom') # Get potentially deviated geometry

            if not line_geom or line_geom.isEmpty():
                log.warning(f"Line {line_num} has empty/invalid geometry in line_data.")
                # Fallback: Try getting from original layer (less ideal)
                lines_layer = required_layers.get('lines')
                if lines_layer:
                    req = QgsFeatureRequest().setFilterExpression(f"\"LineNum\" = {line_num}")
                    feats = list(lines_layer.getFeatures(req))
                    if feats: line_geom = feats[0].geometry()

            if not line_geom or line_geom.isEmpty():
                 log.error(f"Could not retrieve valid geometry for Line {line_num}.")
                 return False

            # --- Add Run-In Segment ---
            runins_layer = required_layers.get('runins')
            runin_location = "End" if is_reciprocal else "Start"
            runin_target_len = sim_params.get('run_in_length_meters', 500)
            runin_time_s = 0.0

            if runin_target_len > 0:
                runin_geom = self._find_runin_geom(runins_layer, line_num, runin_location, runin_target_len)
                if runin_geom and not runin_geom.isEmpty():
                    runin_time_s = self._calculate_runin_time(
                        runin_geom, sim_params, line_traversal_reciprocal=is_reciprocal
                    )
                    runin_segment_data = {
                        'Geometry': runin_geom,
                        'LineNum': line_num,
                        'SegmentType': 'RunIn',
                        'Direction': 'Entering ' + ('Highest SP' if is_reciprocal else 'Lowest SP'),
                        'Duration_s': runin_time_s,
                        'line_is_reciprocal': is_reciprocal,
                        'Label': f"RunIn L{line_num} ({runin_time_s:.1f}s)"
                    }
                    # Add run-in *before* the line segment
                    result_segments.append(runin_segment_data)
                    log.debug(f"  Added {runin_location} RunIn segment for Line {line_num}")
                else:
                    log.warning(f"  Could not find {runin_location} RunIn geometry for Line {line_num}")

            # --- Add Main Line Segment ---
            direction_label = "High→Low" if is_reciprocal else "Low→High"
            line_length = line_geom.length()
            shoot_mps = shooting_speed_mps(sim_params, bool(is_reciprocal))
            duration_s = line_length / shoot_mps if shoot_mps > 0 else 0.0

            # --- Calculate Heading based on actual segment points ---
            heading = None
            if line_geom.type() == QgsWkbTypes.LineGeometry:
                points = list(line_geom.vertices())
                if len(points) >= 2:
                    p_start = points[0]; p_end = points[-1]
                    # Use the direction specified by is_reciprocal
                    dx = p_end.x() - p_start.x()
                    dy = p_end.y() - p_start.y()
                    # Calculate QGIS heading (0=N, CW)
                    if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                        angle_rad = math.atan2(dx, dy)
                        heading_deg = math.degrees(angle_rad)
                        heading = (heading_deg + 360) % 360 # Use actual angle

                        # If reciprocal, the *travel* heading is reversed
                        if is_reciprocal:
                            heading = (heading + 180) % 360

            line_segment_data = {
                'Geometry': QgsGeometry(line_geom), # Use potentially deviated geometry
                'LineNum': line_num,
                'SegmentType': 'Line',
                'Direction': 'Reciprocal' if is_reciprocal else 'Normal',
                'Duration_s': duration_s,
                'Heading': heading, # Add the calculated heading
                'line_is_reciprocal': is_reciprocal,
                'Label': f"L{line_num} {direction_label} ({duration_s:.1f}s)"
            }
            result_segments.append(line_segment_data)
            log.debug(f"  Added Line segment {line_num} ({direction_label})")

            # --- Add Run-Out Segment ---
            runout_location = "Start" if is_reciprocal else "End"
            runout_target_len = sim_params.get('run_out_length_meters', 0)
            runout_time_s = 0.0

            if runout_target_len > 0:
                runout_geom = self._find_runin_geom(runins_layer, line_num, runout_location, runout_target_len)
                if runout_geom and not runout_geom.isEmpty():
                    runout_time_s = self._calculate_runin_time(
                        runout_geom, sim_params, line_traversal_reciprocal=is_reciprocal
                    )
                    runout_segment_data = {
                        'Geometry': runout_geom,
                        'LineNum': line_num,
                        'SegmentType': 'RunOut',
                        'Direction': 'Exiting ' + ('Lowest SP' if is_reciprocal else 'Highest SP'),
                        'Duration_s': runout_time_s,
                        'Heading': None,
                        'line_is_reciprocal': is_reciprocal,
                        'Label': f"RunOut L{line_num} ({runout_time_s:.1f}s)"
                    }
                    # Add run-out *after* the line segment
                    result_segments.append(runout_segment_data)
                    log.debug(f"  Added {runout_location} RunOut segment for Line {line_num}")
                else:
                    log.warning(f"  Could not find {runout_location} RunOut geometry for Line {line_num}")

            return True

        except Exception as e:
            log.exception(f"Error adding line/run-in segments for line {line_num}: {e}")
            return False
    # --- END MODIFICATION ---


    def _visualize_optimized_path(self, sequence, path_segments, start_datetime, source_crs, line_data):
        """
        Creates or updates the 'Optimized_Path' layer to visualize the
        optimized acquisition sequence.

        This function creates a styled layer showing the complete acquisition path including
        lines, turns, and run-ins with appropriate styling to differentiate segment types
        and highlight deviated line segments.

        Args:
            sequence (list): Ordered list of line numbers
            path_segments (list): List of path segment data to visualize
            start_datetime (datetime): Start time for the acquisition
            source_crs (QgsCoordinateReferenceSystem): Coordinate reference system for the layer
            line_data (dict): Dictionary containing line information including deviation flags
        """
        log.info("Visualizing optimized acquisition path...")

        # Validate input parameters
        if not path_segments:
            log.error("No path segments to visualize")
            return

        if not source_crs or not source_crs.isValid():
            log.error(f"Invalid CRS for visualization: {source_crs}")
            return

        # Single active visualization layer: always replace previous run.
        layer_name = "Optimized_Path"
        self._remove_layer_by_name(layer_name)
        self.optimized_path_layer = None

        try:
            # Create the memory layer with fields
            log.debug(f"Creating visualization layer '{layer_name}' with CRS {source_crs.authid()}")

            # Define fields for the layer
            fields = QgsFields()
            qvariant_by_name = {
                "Int": QVariant.Int,
                "String": QVariant.String,
                "Double": QVariant.Double,
                "DateTime": QVariant.DateTime,
                "Bool": QVariant.Bool,
            }
            if optimized_path_field_specs:
                for field_name, type_name, kwargs in optimized_path_field_specs():
                    fields.append(QgsField(field_name, qvariant_by_name[type_name], **kwargs))
            else:
                fields.append(QgsField("SeqOrder", QVariant.Int))
                fields.append(QgsField("LineNum", QVariant.String, len=50))
                fields.append(QgsField("SegmentType", QVariant.String, len=15))
                fields.append(QgsField("Length_m", QVariant.Double, len=10, prec=2))
                fields.append(QgsField("Duration_s", QVariant.Double, len=8, prec=1))
                fields.append(QgsField("Duration_hh_mm", QVariant.String, len=10))
                fields.append(QgsField("StartTime", QVariant.DateTime))
                fields.append(QgsField("EndTime", QVariant.DateTime))
                fields.append(QgsField("Heading", QVariant.Double, len=6, prec=1))
                fields.append(QgsField("Speed_kn", QVariant.Double, len=6, prec=2))
                fields.append(QgsField("Deviated", QVariant.Bool))
                fields.append(QgsField("DeviationFailed", QVariant.Bool))
                fields.append(QgsField("StartLine", QVariant.String, len=50))
                fields.append(QgsField("EndLine", QVariant.String, len=50))

            # Create URI and layer
            uri = f"LineString?crs={source_crs.authid()}&index=yes"
            layer = QgsVectorLayer(uri, layer_name, "memory")

            if not layer.isValid():
                raise ValueError(f"Failed to create valid memory layer with URI: {uri}")

            provider = layer.dataProvider()
            if not provider.addAttributes(fields):
                raise ValueError(f"Failed to add attributes: {provider.lastError()}")

            layer.updateFields()
            log.debug("Layer structure created successfully")

            # Cache speeds (knots) from last simulation parameters, if available.
            base_line_speed_kn = None
            base_turn_speed_kn = None
            try:
                params_for_speeds = self.last_sim_params or {}
                v_line = float(params_for_speeds.get("avg_shooting_speed_knots", 0.0) or 0.0)
                v_turn = float(params_for_speeds.get("avg_turn_speed_knots", 0.0) or 0.0)
                base_line_speed_kn = v_line if v_line > 0.0 else None
                base_turn_speed_kn = v_turn if v_turn > 0.0 else None
            except Exception:
                base_line_speed_kn = None
                base_turn_speed_kn = None

            # Start adding features
            layer.startEditing()
            current_time = start_datetime
            features_added = 0

            # Process each segment
            for i, seg_data in enumerate(path_segments):
                try:
                    # Extract segment data
                    if isinstance(seg_data, dict):
                        # Handle dictionary format
                        geom = seg_data.get('Geometry')
                        seg_type = seg_data.get('SegmentType', 'Unknown')
                        # Look for LineNum first, then fall back to StartLine
                        line_num = seg_data.get('LineNum')
                        start_line = seg_data.get('StartLine')
                        end_line = seg_data.get('EndLine')
                        if line_num is None or line_num == NULL:
                            line_num = seg_data.get('StartLine')
                        time_s = seg_data.get('Duration_s', 0)
                        heading = seg_data.get('Heading')
                    else:
                        # Handle tuple/list format
                        geom, seg_type, line_num, time_s = seg_data[:4]
                        heading = seg_data[4] if len(seg_data) > 4 else None
                        start_line = (
                            seg_data[2]
                            if len(seg_data) > 2
                            and seg_type in ("Turn", "Turn_Teardrop", "Turn_Racetrack")
                            else None
                        )
                        end_line = None

                    # Validate geometry
                    if not isinstance(geom, QgsGeometry) or geom.isEmpty():
                        log.warning(f"Skipping segment {i+1}: Invalid geometry")
                        continue

                    # Process time and length values
                    time_s = float(time_s if time_s is not None else 0.0)
                    time_s = max(0.0, time_s)  # Ensure non-negative
                    start_t = current_time
                    end_t = start_t + timedelta(seconds=time_s)
                    length = max(0.0, geom.length())

                    # Format values for display
                    q_start = QDateTime(start_t)
                    q_end = QDateTime(end_t)
                    if line_num is not None and line_num != NULL:
                        disp_line_num = str(line_num)
                    else:
                        disp_line_num = NULL
                    disp_heading = round(heading, 1) if heading is not None else NULL

                    # Format duration as hh:mm
                    duration_hh_mm = ""
                    if time_s is not None and time_s > 0:
                        hours = int(time_s // 3600)
                        minutes = int((time_s % 3600) // 60)
                        duration_hh_mm = f"{hours:02d}:{minutes:02d}"
                    else:
                        duration_hh_mm = "00:00"

                    # Per-leg Turn_Teardrop / Turn_Racetrack from reconstruction; legacy 'Turn' → global mode.
                    if seg_type == "Turn":
                        mode_key = str(
                            (self.last_sim_params or {}).get("acquisition_mode_key", "")
                        ).strip().casefold()
                        seg_type = "Turn_Teardrop" if mode_key == "teardrop" else "Turn_Racetrack"

                    # Get deviation flags from line_data if applicable
                    is_deviated = False
                    is_failed = False
                    if seg_type == 'Line' and line_num is not None and line_num != NULL:
                        line_info = line_data.get(line_num, {})
                        is_deviated = line_info.get('deviated', False)
                        is_failed = line_info.get('deviation_failed', False)

                    params_for_speeds = self.last_sim_params or {}
                    line_speed_kn = None
                    turn_speed_kn = None
                    if isinstance(seg_data, dict):
                        is_rec = seg_data.get("line_is_reciprocal")
                        if is_rec is not None:
                            if seg_type == "Line":
                                line_speed_kn = shooting_speed_knots(params_for_speeds, bool(is_rec))
                            elif seg_type in (
                                "RunIn",
                                "RunOut",
                                "Turn",
                                "Turn_Teardrop",
                                "Turn_Racetrack",
                            ):
                                turn_speed_kn = turn_speed_knots(params_for_speeds, bool(is_rec))

                    # Create feature and set attributes
                    feat = QgsFeature(fields)
                    feat.setGeometry(geom)
                    start_line_attr = str(start_line) if start_line is not None and start_line != NULL else NULL
                    end_line_attr = str(end_line) if end_line is not None and end_line != NULL else NULL
                    if build_optimized_path_attributes:
                        attrs = build_optimized_path_attributes(
                            seq_order=i + 1,
                            line_num=disp_line_num,
                            seg_type=seg_type,
                            length=round(length, 2),
                            time_s=round(time_s, 1),
                            duration_hh_mm=duration_hh_mm,
                            q_start=q_start,
                            q_end=q_end,
                            heading=disp_heading,
                            base_line_speed_kn=base_line_speed_kn,
                            base_turn_speed_kn=base_turn_speed_kn,
                            line_speed_kn=line_speed_kn,
                            turn_speed_kn=turn_speed_kn,
                            is_deviated=is_deviated,
                            is_failed=is_failed,
                            start_line=start_line_attr,
                            end_line=end_line_attr,
                            null_value=NULL,
                        )
                    else:
                        seg_speed_kn = NULL
                        if segment_speed_kn is not None:
                            seg_speed_kn = segment_speed_kn(
                                seg_type,
                                base_line_speed_kn,
                                base_turn_speed_kn,
                                line_speed_kn=line_speed_kn,
                                turn_speed_kn=turn_speed_kn,
                            )
                        elif seg_type == "Line" and base_line_speed_kn is not None:
                            seg_speed_kn = round(base_line_speed_kn, 2)
                        elif seg_type in ("RunIn", "RunOut", "Turn", "Turn_Teardrop", "Turn_Racetrack") and base_turn_speed_kn is not None:
                            seg_speed_kn = round(base_turn_speed_kn, 2)
                        attrs = [
                            i + 1,
                            disp_line_num,
                            seg_type,
                            round(length, 2),
                            round(time_s, 1),
                            duration_hh_mm,
                            q_start,
                            q_end,
                            disp_heading,
                            seg_speed_kn,
                            is_deviated,
                            is_failed,
                            start_line_attr,
                            end_line_attr,
                        ]
                    feat.setAttributes(attrs)

                    # Add feature to layer
                    if not provider.addFeature(feat):
                        log.warning(f"Failed to add feature {i+1}: {provider.lastError()}")
                    else:
                        features_added += 1

                    # Update current time for next segment
                    current_time = end_t

                except Exception as feature_error:
                    log.warning(f"Error processing segment {i+1}: {feature_error}")

            # Commit changes
            if not layer.commitChanges():
                raise ValueError(f"Failed to commit changes: {layer.dataProvider().lastError()}")

            log.debug(f"Added {features_added} features to visualization layer")

            # Apply styling with rule-based renderer
            self._apply_path_styling(layer)

            # Apply labeling
            self._apply_path_labeling(layer)

            # Do not create a separate turns layer; turns stay in Optimized_Path.
            layer.updateExtents()

            # Add layer to project
            self._add_layer_to_lookahead_group(layer)
            self.optimized_path_layer = layer

            log.info(f"Added visualization layer '{layer_name}' to project")

        except Exception as e:
            log.exception(f"Error creating visualization layer: {e}")
            if layer and layer.isValid():
                if layer.isEditable():
                    layer.rollBack()
                self._remove_layer_by_name(layer_name)
            self._pop_wait_cursor_if_busy()
            QMessageBox.critical(self, "Visualization Error", f"Failed to create path visualization: {str(e)}")

    def _apply_path_styling(self, layer):
        """
        Apply styling to a path layer with differentiated segment types and headings.

        Args:
            layer (QgsVectorLayer): The layer to style

        Returns:
            bool: True if successful, False otherwise
        """
        if not layer or not layer.isValid():
            log.warning("Cannot apply path styling to invalid layer")
            return False

        try:
            # Create rule-based renderer to handle different headings for line segments
            rules = []

            # === Line segments with heading 0-180 degrees (Low to High) - Blue with arrows ===
            blue_line_symbol = QgsLineSymbol.createSimple({
                'line_color': '#0000FF',  # Blue
                'line_width': '0.6',
                'line_style': 'solid'
            })
            
            # Add arrow marker to blue line
            blue_arrow = QgsMarkerLineSymbolLayer()
            blue_arrow.setPlacement(QgsMarkerLineSymbolLayer.FirstVertex)
            
            # Create arrow marker symbol
            blue_arrow_marker = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead',
                'color': '#0000FF',
                'size': '3',
                'outline_style': 'no'
            })
            blue_arrow.setSubSymbol(blue_arrow_marker)
            
            # Create regular interval arrows
            blue_interval_arrow = QgsMarkerLineSymbolLayer()
            blue_interval_arrow.setPlacement(QgsMarkerLineSymbolLayer.Interval)
            blue_interval_arrow.setInterval(25)
            blue_interval_arrow.setRotateMarker(True)
            
            blue_interval_marker = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead', 
                'color': '#0000FF',
                'size': '3',
                'outline_style': 'no'
            })
            blue_interval_arrow.setSubSymbol(blue_interval_marker)
            
            # Add arrow layers to symbol
            # blue_line_symbol.appendSymbolLayer(blue_arrow)
            # blue_line_symbol.appendSymbolLayer(blue_interval_arrow)
            
            # Create rule for low to high lines
            blue_line_rule = QgsRuleBasedRenderer.Rule(
                blue_line_symbol,
                filterExp=(
                    "\"SegmentType\" = 'Line' AND "
                    "(\"Heading\" IS NULL OR (\"Heading\" >= 0 AND \"Heading\" < 180))"
                ),
                label="Line (Low to High)",
            )
            rules.append(blue_line_rule)

            # === Line segments with heading 180-360 degrees (High to Low) - Purple with arrows ===
            green_line_symbol = QgsLineSymbol.createSimple({
                'line_color': '#800080',  # Purple
                'line_width': '0.6',
                'line_style': 'solid'
            })
            
            # Set marker to last vertex which effectively reverses direction
            green_arrow = QgsMarkerLineSymbolLayer()
            green_arrow.setPlacement(QgsMarkerLineSymbolLayer.LastVertex)
            
            # Create arrow marker symbol - use same as blue lines for consistency
            green_arrow_marker = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead',
                'color': '#800080',
                'size': '3',
                'outline_style': 'no'
            })
            green_arrow.setSubSymbol(green_arrow_marker)
            
            # Create regular interval arrows - set offset along line to flip them
            green_interval_arrow = QgsMarkerLineSymbolLayer()
            green_interval_arrow.setPlacement(QgsMarkerLineSymbolLayer.Interval)
            green_interval_arrow.setInterval(25)
            green_interval_arrow.setRotateMarker(True)
            green_interval_arrow.setOffsetAlongLine(12.5)  # Half the interval distance
            
            green_interval_marker = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead',
                'color': '#800080',
                'size': '3',
                'outline_style': 'no'
            })
            # Rotate marker 180 degrees using the QgsMarkerSymbol
            green_interval_marker.setAngle(180)
            green_interval_arrow.setSubSymbol(green_interval_marker)
            
            # Add arrow layers to symbol
            # green_line_symbol.appendSymbolLayer(green_arrow)
            # green_line_symbol.appendSymbolLayer(green_interval_arrow)
            
            # Create rule for high to low lines
            high_to_low_rule = QgsRuleBasedRenderer.Rule(
                green_line_symbol,
                filterExp="\"SegmentType\" = 'Line' AND \"Heading\" >= 180 AND \"Heading\" < 360",
                label="Line (High to Low)"
            )
            rules.append(high_to_low_rule)

            # === Turn segments - Orange with arrows ===
            turn_symbol = QgsLineSymbol.createSimple({
                'line_color': '#FF8800',  # Orange
                'line_width': '0.6',
                'line_style': 'solid'
            })
            
            # Add arrow marker to turn lines
            turn_arrow = QgsMarkerLineSymbolLayer()
            turn_arrow.setPlacement(QgsMarkerLineSymbolLayer.FirstVertex)
            
            # Create arrow marker symbol
            turn_arrow_marker = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead',
                'color': '#FF8800',
                'size': '3',
                'outline_style': 'no'
            })
            turn_arrow.setSubSymbol(turn_arrow_marker)
            
            # Create regular interval arrows
            turn_interval_arrow = QgsMarkerLineSymbolLayer()
            turn_interval_arrow.setPlacement(QgsMarkerLineSymbolLayer.Interval)
            turn_interval_arrow.setInterval(15)  # Shorter interval for turns
            turn_interval_arrow.setRotateMarker(True)
            
            turn_interval_marker = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead', 
                'color': '#FF8800',
                'size': '3',
                'outline_style': 'no'
            })
            turn_interval_arrow.setSubSymbol(turn_interval_marker)
            
            # Add arrow layers to symbol
            turn_symbol.appendSymbolLayer(turn_arrow)
            turn_symbol.appendSymbolLayer(turn_interval_arrow)
            
            # Create rule for turn segments
            mode_key = str((self.last_sim_params or {}).get("acquisition_mode_key", "")).strip().casefold()
            turn_rule_label = "Turn_Teardrop" if mode_key == "teardrop" else "Turn_Racetrack"
            turn_rule = QgsRuleBasedRenderer.Rule(
                turn_symbol,
                filterExp="\"SegmentType\" IN ('Turn_Racetrack','Turn_Teardrop','Turn')",
                label=turn_rule_label
            )
            rules.append(turn_rule)
            
            # === Run-in segments - Red with arrows ===
            runin_symbol = QgsLineSymbol.createSimple({
                'line_color': '#FF0000',  # Red
                'line_width': '0.6',
                'line_style': 'dash',
            })
            
            # Add arrow marker to runin lines
            runin_arrow = QgsMarkerLineSymbolLayer()
            runin_arrow.setPlacement(QgsMarkerLineSymbolLayer.FirstVertex)
            
            # Create arrow marker symbol
            runin_arrow_marker = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead',
                'color': '#FF0000',
                'size': '3',
                'outline_style': 'no'
            })
            runin_arrow.setSubSymbol(runin_arrow_marker)
            
            # Create regular interval arrows
            runin_interval_arrow = QgsMarkerLineSymbolLayer()
            runin_interval_arrow.setPlacement(QgsMarkerLineSymbolLayer.Interval)
            runin_interval_arrow.setInterval(15)  # Shorter interval for run-ins
            runin_interval_arrow.setRotateMarker(True)
            
            runin_interval_marker = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead', 
                'color': '#FF0000',
                'size': '3',
                'outline_style': 'no'
            })
            runin_interval_arrow.setSubSymbol(runin_interval_marker)
            
            # Add arrow layers to symbol
            # runin_symbol.appendSymbolLayer(runin_arrow)
            # runin_symbol.appendSymbolLayer(runin_interval_arrow)
            
            # Create rule for run-in segments
            runin_rule = QgsRuleBasedRenderer.Rule(
                runin_symbol.clone(),
                filterExp="\"SegmentType\" = 'RunIn'",
                label="Run-In"
            )
            rules.append(runin_rule)

            # Run-out is separate geometry in the same layer (SegmentType RunOut) — distinct style so it
            # does not merge visually with run-in (previously both used identical red symbols).
            runout_symbol = QgsLineSymbol.createSimple({
                "line_color": "#00897B",  # teal — distinct from red run-in and orange turns
                "line_width": "0.6",
                "line_style": "dash",
            })

            runout_rule = QgsRuleBasedRenderer.Rule(
                runout_symbol.clone(),
                filterExp="\"SegmentType\" = 'RunOut'",
                label="Run-Out",
            )
            rules.append(runout_rule)

            # We don't need a fallback rule as we've covered all segment types
            # and it will prevent unwanted 'Other' category from appearing in the legend

            # Create the root rule that contains all other rules
            root_rule = QgsRuleBasedRenderer.Rule(None)
            for rule in rules:
                root_rule.appendChild(rule)

            # Apply the rule-based renderer to the layer
            renderer = QgsRuleBasedRenderer(root_rule)
            layer.setRenderer(renderer)

            return True

        except Exception as e:
            log.exception(f"Error applying path styling: {e}")
            return False

    @staticmethod
    def _path_label_pin_to_segment_centroid(pal: QgsPalLayerSettings):
        """
        Pin each segment label to the middle of its line geometry (full feature, not the part
        clipped to the map canvas) and draw text parallel to the line. Implemented with QGIS
        native Line placement + strict line anchor — avoids geometry-generator + data-defined
        rotation, where ``$geometry`` in overrides is often the generated point so the angle
        never matches the segment.

        On older QGIS builds without QgsLabelLineSettings anchor clipping, falls back to the
        geometry-generator midpoint approach (may jitter slightly if clipping cannot be disabled).
        """
        lr_key = None
        rot_key = None
        try:
            lr_key = QgsPalLayerSettings.Property.LabelRotation
        except Exception:
            try:
                lr_key = QgsPalLayerSettings.LabelRotation
            except Exception:
                lr_key = None
        try:
            rot_key = QgsPalLayerSettings.Property.Rotation
        except Exception:
            rot_key = None

        def _clear_rotation_overrides():
            for key in (lr_key, rot_key):
                if key is not None:
                    try:
                        pal.dataDefinedProperties().setProperty(key, QgsProperty())
                    except Exception:
                        pass

        used_native_line = False
        try:
            _clear_rotation_overrides()
            try:
                pal.setGeometryGeneratorEnabled(False)
            except Exception:
                pass

            try:
                pal.placement = QgsPalLayerSettings.Line
            except Exception:
                try:
                    pal.setPlacement(Qgis.LabelPlacement.Line)
                except Exception:
                    raise RuntimeError("Line label placement not available")

            pal.centroidInside = False
            pal.centroidWhole = True

            ls = pal.lineSettings()
            ls.setLineAnchorPercent(0.5)
            ls.setAnchorType(QgsLabelLineSettings.AnchorType.Strict)
            try:
                ls.setAnchorClipping(QgsLabelLineSettings.AnchorClipping.UseEntireLine)
            except Exception:
                pass
            try:
                ls.setAnchorTextPoint(QgsLabelLineSettings.AnchorTextPoint.CenterOfText)
            except Exception:
                pass
            try:
                ls.setMergeLines(False)
            except Exception:
                pass
            try:
                ls.setPlacementFlags(Qgis.LabelLinePlacementFlag.OnLine)
            except Exception:
                try:
                    from qgis.core import QgsLabeling

                    ls.setPlacementFlags(QgsLabeling.LinePlacement.OnLine)
                except Exception:
                    pass
            try:
                pal.setLineSettings(ls)
            except Exception:
                pass
            used_native_line = True
        except Exception:
            used_native_line = False

        if not used_native_line:
            try:
                if lr_key is not None:
                    try:
                        pal.dataDefinedProperties().setProperty(lr_key, QgsProperty())
                    except Exception:
                        pass
                if rot_key is not None:
                    try:
                        pal.dataDefinedProperties().setProperty(rot_key, QgsProperty())
                    except Exception:
                        pass
                pal.setGeometryGeneratorEnabled(True)
                pal.setGeometryGenerator(
                    "coalesce("
                    "line_interpolate_point($geometry, length($geometry) / 2.0),"
                    "centroid($geometry)"
                    ")"
                )
                try:
                    pal.setGeometryGeneratorType(QgsWkbTypes.PointGeometry)
                except Exception:
                    try:
                        pal.setGeometryGeneratorType(QgsWkbTypes.Point)
                    except Exception:
                        pass
                pal.placement = QgsPalLayerSettings.AroundPoint
                pal.centroidInside = False
                pal.centroidWhole = True
                try:
                    pal.setRotationUnit(Qgis.AngleUnit.Degrees)
                except Exception:
                    pass
                rot_expr = (
                    "coalesce(degrees(line_interpolate_angle($geometry, length($geometry) / 2.0)), 0)"
                )
                for key in (rot_key, lr_key):
                    if key is not None:
                        try:
                            pal.dataDefinedProperties().setProperty(
                                key, QgsProperty.fromExpression(rot_expr)
                            )
                            break
                        except Exception:
                            pass
            except Exception:
                try:
                    pal.setGeometryGeneratorEnabled(False)
                except Exception:
                    pass
                pal.placement = QgsPalLayerSettings.Horizontal
                pal.centroidInside = True
                pal.centroidWhole = True
                _clear_rotation_overrides()
        try:
            obs = pal.obstacleSettings()
            obs.setIsObstacle(False)
            obs.setFactor(0.0)
        except Exception:
            pass

    def _apply_path_labeling(self, layer):
        """
        Apply rule-based labeling to the optimized path layer:
        - Line segments show LineNum with white buffer
        - Turn segments show Duration_hh_mm with white buffer
        - Segment labels use line placement with a strict mid-line anchor on the full geometry.

        Args:
            layer (QgsVectorLayer): The layer to apply labeling to
        """
        try:
            log.debug("Applying rule-based labeling to path layer...")

            # Create root rule for rule-based labeling
            rules = []

            # === RULE 1: Line segments - Show LineNum with white buffer ===
            line_settings = QgsPalLayerSettings()
            line_settings.isExpression = True
            line_settings.fieldName = "to_string(\"LineNum\") || ' ' || \"Duration_hh_mm\""
            line_settings.enabled = True

            # Format for line labels
            line_format = QgsTextFormat()
            line_format.setSize(5)  # Smaller font as requested
            line_format.setColor(QColor(0, 0, 0))  # Black text

            # Make font bold
            font = line_format.font()
            font.setBold(True)
            line_format.setFont(font)

            # Add white buffer around text
            line_buffer = QgsTextBufferSettings()
            line_buffer.setEnabled(True)
            line_buffer.setSize(0.5)  # Thick white buffer as requested
            line_buffer.setColor(QColor(255, 255, 255))  # Pure white
            line_format.setBuffer(line_buffer)

            # Apply format to settings
            line_settings.setFormat(line_format)
            LookaheadDockWidgetImpl._path_label_pin_to_segment_centroid(line_settings)

            # Create rule for line segments
            line_rule = QgsRuleBasedLabeling.Rule(line_settings)
            line_rule.setFilterExpression("\"SegmentType\" = 'Line'")  # Only for line segments
            line_rule.setDescription("Line Numbers")
            rules.append(line_rule)

            # === RULE 2: Turn segments - Show Duration_hh_mm with white buffer ===
            turn_settings = QgsPalLayerSettings()
            turn_settings.fieldName = "Duration_hh_mm"  # Use the formatted duration
            turn_settings.enabled = True

            # Format for turn labels
            turn_format = QgsTextFormat()
            turn_format.setSize(5)  # Keep small size for turn durations
            turn_format.setColor(QColor(200, 0, 0))  # Red text for turn durations

            # Make font bold
            font = turn_format.font()
            font.setBold(True)
            turn_format.setFont(font)

            # Add white buffer around text
            turn_buffer = QgsTextBufferSettings()
            turn_buffer.setEnabled(True)
            turn_buffer.setSize(0.5)  # Thick white buffer as requested
            turn_buffer.setColor(QColor(255, 255, 255))  # Pure white
            turn_format.setBuffer(turn_buffer)

            # Apply format to settings
            turn_settings.setFormat(turn_format)
            LookaheadDockWidgetImpl._path_label_pin_to_segment_centroid(turn_settings)

            # Create rule for turn segments
            mode_key = str((self.last_sim_params or {}).get("acquisition_mode_key", "")).strip().casefold()
            turn_rule_desc = "Turn_Teardrop Durations" if mode_key == "teardrop" else "Turn_Racetrack Durations"
            turn_rule = QgsRuleBasedLabeling.Rule(turn_settings)
            turn_rule.setFilterExpression("\"SegmentType\" IN ('Turn_Racetrack','Turn_Teardrop','Turn')")  # Only for turn segments
            turn_rule.setDescription(turn_rule_desc)
            rules.append(turn_rule)
            
            # === RULE 3: Run-in segments - Show Duration_hh_mm with white buffer ===
            runin_settings = QgsPalLayerSettings()
            runin_settings.fieldName = "Duration_hh_mm"  # Use the formatted duration
            runin_settings.enabled = True

            # Format for run-in labels
            runin_format = QgsTextFormat()
            runin_format.setSize(5)  # Keep small size for run-in durations
            runin_format.setColor(QColor(200, 0, 0))  # Red text for run-in durations

            # Make font bold
            font = runin_format.font()
            font.setBold(True)
            runin_format.setFont(font)

            # Add white buffer around text
            runin_buffer = QgsTextBufferSettings()
            runin_buffer.setEnabled(True)
            runin_buffer.setSize(0.5)  # Thick white buffer as requested
            runin_buffer.setColor(QColor(255, 255, 255))  # Pure white
            runin_format.setBuffer(runin_buffer)

            # Apply format to settings
            runin_settings.setFormat(runin_format)
            LookaheadDockWidgetImpl._path_label_pin_to_segment_centroid(runin_settings)

            # Create rule for run-in segments
            runin_rule = QgsRuleBasedLabeling.Rule(runin_settings)
            runin_rule.setFilterExpression("\"SegmentType\" = 'RunIn'")
            runin_rule.setDescription("Run-In Durations")
            rules.append(runin_rule)

            runout_settings = QgsPalLayerSettings()
            runout_settings.fieldName = "Duration_hh_mm"
            runout_settings.enabled = True
            runout_format = QgsTextFormat()
            runout_format.setSize(5)
            runout_format.setColor(QColor(0, 105, 92))  # teal, matches Run-Out line color
            font_ro = runout_format.font()
            font_ro.setBold(True)
            runout_format.setFont(font_ro)
            runout_buf = QgsTextBufferSettings()
            runout_buf.setEnabled(True)
            runout_buf.setSize(0.5)
            runout_buf.setColor(QColor(255, 255, 255))
            runout_format.setBuffer(runout_buf)
            runout_settings.setFormat(runout_format)
            LookaheadDockWidgetImpl._path_label_pin_to_segment_centroid(runout_settings)
            runout_lbl_rule = QgsRuleBasedLabeling.Rule(runout_settings)
            runout_lbl_rule.setFilterExpression("\"SegmentType\" = 'RunOut'")
            runout_lbl_rule.setDescription("Run-Out Durations")
            rules.append(runout_lbl_rule)

            # Create root rule and add all rules
            root_rule = QgsRuleBasedLabeling.Rule(None)
            for rule in rules:
                root_rule.appendChild(rule)

            # Create and apply rule-based labeling
            rule_labeling = QgsRuleBasedLabeling(root_rule)
            layer.setLabeling(rule_labeling)
            layer.setLabelsEnabled(True)

            log.debug("Rule-based path labeling applied successfully")

        except Exception as e:
            log.exception(f"Error applying path labeling: {e}")
            # Fallback: disable labels rather than fail completely
            try:
                if layer and layer.isValid():
                    layer.setLabelsEnabled(False)
            except Exception:
                pass

    def _create_turns_layer(self, path_segments, source_crs):
        """
        Creates a separate layer containing only turn segments for specialized visualization.

        Args:
            path_segments (list): List of path segment data
            source_crs (QgsCoordinateReferenceSystem): Coordinate reference system for the layer

        Returns:
            QgsVectorLayer: The created layer, or None if creation fails
        """
        try:
            # Mode-specific layer names so Racetrack and Teardrop can coexist.
            mode_key = None
            try:
                mode_key = (self.last_sim_params or {}).get("acquisition_mode_key")
            except Exception:
                mode_key = None
            mode_key = str(mode_key or "").strip().casefold()
            if mode_key == "teardrop":
                layer_name = "Turn_Teardrop"
            else:
                layer_name = "Turn_Racetrack"

            # Remove any existing layer with the same name
            self._remove_layer_by_name(layer_name)

            # Validate CRS
            if not source_crs or not source_crs.isValid():
                log.error("Invalid CRS for turn layer")
                return None

            # Create layer structure
            fields = QgsFields()
            fields.append(QgsField("TurnID", QVariant.Int))
            fields.append(QgsField("FromLine", QVariant.String, len=50))
            fields.append(QgsField("ToLine", QVariant.String, len=50))
            fields.append(QgsField("Length_m", QVariant.Double, len=10, prec=2))
            fields.append(QgsField("Duration_s", QVariant.Double, len=8, prec=1))
            fields.append(QgsField("DurationMin", QVariant.Double, len=5, prec=2))

            # Create layer
            uri = f"LineString?crs={source_crs.authid()}&index=yes"
            layer = QgsVectorLayer(uri, layer_name, "memory")

            if not layer.isValid():
                log.error(f"Failed to create valid turn layer with URI: {uri}")
                return None

            # Start editing
            provider = layer.dataProvider()
            provider.addAttributes(fields)
            layer.updateFields()

            layer.startEditing()
            turn_count = 0

            # Extract and add only turn segments
            for i, seg_data in enumerate(path_segments):
                try:
                    # Check if this is a turn segment
                    if isinstance(seg_data, dict):
                        # Dictionary format
                        seg_type = seg_data.get('SegmentType')
                        if seg_type not in ("Turn", "Turn_Teardrop", "Turn_Racetrack"):
                            continue

                        geom = seg_data.get('Geometry')
                        from_line = seg_data.get('StartLine')
                        to_line = seg_data.get('EndLine')
                        duration = seg_data.get('Duration_s', 0)
                    else:
                        # List/tuple format
                        if len(seg_data) < 3 or seg_data[1] not in (
                            "Turn",
                            "Turn_Teardrop",
                            "Turn_Racetrack",
                        ):
                            continue

                        geom, _, from_line, duration = seg_data[:4]
                        to_line = None

                    # Skip invalid geometries
                    if not isinstance(geom, QgsGeometry) or geom.isEmpty():
                        continue

                    # Calculate properties
                    length = geom.length()
                    duration_min = duration / 60.0 if duration else 0

                    # Create feature
                    feat = QgsFeature(fields)
                    feat.setGeometry(geom)

                    # Set attributes
                    feat.setAttributes([
                        turn_count + 1,              # TurnID
                        from_line,                   # FromLine
                        to_line,                     # ToLine
                        round(length, 2),            # Length_m
                        round(duration, 1),          # Duration_s
                        round(duration_min, 2)       # DurationMin
                    ])

                    # Add feature
                    provider.addFeature(feat)
                    turn_count += 1

                except Exception as e:
                    log.warning(f"Error processing turn segment {i}: {e}")

            # Commit changes
            if not layer.commitChanges():
                log.error(f"Failed to commit changes to turn layer: {layer.error()}")
                return None

            # Style the layer
            symbol = QgsLineSymbol.createSimple({
                'color': '0,150,0,255',     # Darker green
                'line_style': 'solid',
                'width': '0.6',
                'width_unit': 'MM'
            })
            layer.renderer().setSymbol(symbol)

            # Add to project
            self._add_layer_to_lookahead_group(layer)
            self.generated_turns_layer = layer
            log.info(f"Created specialized turn layer with {turn_count} segments")

            return layer

        except Exception as e:
            log.exception(f"Error creating turn segments layer: {e}")
            return None

    def _apply_turn_labeling(self, layer):
        """
        Apply labeling to turns showing duration in minutes.

        Args:
            layer (QgsVectorLayer): The layer to apply labeling to
        """
        try:
            log.debug("Applying turn duration labeling...")

            # Create label settings
            label_settings = QgsPalLayerSettings()

            # Configure label content - only show duration for turn segments, converting seconds to minutes
            label_settings.isExpression = True
            label_settings.expression = (
                "CASE WHEN \"SegmentType\" IN ('Turn','Turn_Teardrop','Turn_Racetrack') THEN "
                "format_number(\"Duration_s\" / 60.0, 1) || ' min' "
                "ELSE '' END"
            )

            # Create and apply text format
            text_format = QgsTextFormat()
            text_format.setSize(8)
            text_format.setColor(QColor(0, 100, 0))  # Dark green for turn times
            # Handle font weight differently - get font, set bold, update font
            font = text_format.font()
            font.setBold(True)
            text_format.setFont(font)
            text_format.setSizeUnit(QgsUnitTypes.RenderPoints)

            # Add background for better readability
            bg_buffer = QgsTextBufferSettings()
            bg_buffer.setEnabled(True)
            bg_buffer.setSize(0.6)
            bg_buffer.setColor(QColor(255, 255, 255, 230))
            text_format.setBuffer(bg_buffer)

            # Apply text format to label settings
            label_settings.setFormat(text_format)
            LookaheadDockWidgetImpl._path_label_pin_to_segment_centroid(label_settings)

            # Apply labeling to layer
            layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
            layer.setLabelsEnabled(True)

            log.debug("Turn labeling applied successfully")

        except Exception as e:
            log.exception(f"Error applying turn labeling: {e}")
            # Fallback: disable labels rather than fail completely
            try:
                if layer and layer.isValid():
                    layer.setLabelsEnabled(False)
            except Exception:
                pass

    def _visualize_peaks_and_tangents(self):
        """
        Creates a debug visualization of the NoGo zones and potential deviation paths.
        This helps with troubleshooting the deviation calculation algorithm.
        """
        try:
            # Get current parameters
            nogo_combo = getattr(self, "nogo_zone_combo", None)
            nogo_layer = nogo_combo.currentLayer() if nogo_combo is not None else None
            clearance_m = self.deviationClearanceDoubleSpinBox.value()
            turn_radius_m = self.turnRadiusDoubleSpinBox.value()
            
            if not nogo_layer or not nogo_layer.isValid():
                QMessageBox.warning(self, "Input Error", "Select a valid No-Go Zone layer.")
                return
                
            # Prepare buffered obstacle geometries
            avoidance_geom = self._prepare_avoidance_geometry(nogo_layer, clearance_m)
            if not avoidance_geom:
                QMessageBox.warning(self, "Visualization Error", "Failed to prepare NoGo geometries for visualization.")
                return
                
            # Create a temporary layer to visualize the buffered NoGo zones
            buffered_layer = QgsVectorLayer("Polygon?crs=EPSG:31984", "Buffered_NoGo_Zones", "memory")
            buffered_provider = buffered_layer.dataProvider()
            
            # Add the buffered geometry as a feature
            buff_feat = QgsFeature()
            buff_feat.setGeometry(avoidance_geom)
            buffered_provider.addFeature(buff_feat)
            
            # Style the buffered layer
            symbol = QgsFillSymbol.createSimple({
                'color': '#FF000055',  # Semi-transparent red
                'outline_color': '#FF0000',
                'outline_width': '0.6',
                'outline_style': 'solid',
                'style': 'solid'
            })
            buffered_layer.renderer().setSymbol(symbol)
            
            # Add to project
            self._add_layer_to_lookahead_group(buffered_layer)
            
            # Separate the geometry into distinct obstacles
            obstacle_geometries = self._separate_avoidance_geometry(avoidance_geom)
            
            # Create another layer to highlight the individual obstacle clusters
            clusters_layer = QgsVectorLayer("Polygon?crs=EPSG:31984", "NoGo_Clusters", "memory")
            clusters_provider = clusters_layer.dataProvider()
            
            # Add each cluster with a different attribute value
            clusters_provider.addAttributes([QgsField("Cluster_ID", QVariant.Int)])
            clusters_layer.updateFields()
            
            for i, obs_geom in enumerate(obstacle_geometries):
                feat = QgsFeature()
                feat.setGeometry(obs_geom)
                feat.setAttributes([i + 1])
                clusters_provider.addFeature(feat)
                
            # Style the clusters layer with random colors by category
            categories = []
            for i in range(len(obstacle_geometries)):
                symbol = QgsFillSymbol.createSimple({
                    'color': f'#{hash(str(i)) % 0xFFFFFF:06x}77',  # Semi-transparent random color
                    'outline_color': '#000000',
                    'outline_width': '0.6',
                    'outline_style': 'solid',
                    'style': 'solid'
                })
                category = QgsRendererCategory(i + 1, symbol, f"Cluster {i + 1}")
                categories.append(category)
                
            renderer = QgsCategorizedSymbolRenderer("Cluster_ID", categories)
            clusters_layer.setRenderer(renderer)
            
            # Add to project
            self._add_layer_to_lookahead_group(clusters_layer)
            
            QMessageBox.information(
                self, 
                "Debug Visualization Created", 
                f"Created visualization layers:\n" +
                f"1. Buffered_NoGo_Zones: Combined NoGo zones with {clearance_m}m buffer\n" +
                f"2. NoGo_Clusters: {len(obstacle_geometries)} distinct obstacle groups\n\n" +
                "These layers are for visualization only and can be removed when no longer needed."
            )
            
        except Exception as e:
            log.exception(f"Error creating debug visualization: {e}")
            QMessageBox.critical(self, "Visualization Error", f"Failed to create debug visualization:\n{str(e)}")
 
    def _create_temporary_polygon_layer(self, geometries, layer_name, color="#FF0000", opacity=0.5, parent_group=None):
        """Create a temporary polygon layer for visualization.

        Args:
            geometries (list): List of QgsGeometry objects representing polygons
            layer_name (str): Name for the layer
            color (str): Hex color code (default: red)
            opacity (float): Opacity of the fill (0.0-1.0, default: 0.5)
            parent_group (QgsLayerTreeGroup, optional): Parent group to add layer to

        Returns:
            QgsVectorLayer: The created vector layer
        """
        try:
            # Create a temporary polygon layer
            layer = QgsVectorLayer("Polygon?crs=epsg:31984", layer_name, "memory")
            dp = layer.dataProvider()
            
            # Add features
            features = []
            for geometry in geometries:
                if geometry and not geometry.isEmpty():
                    feat = QgsFeature()
                    feat.setGeometry(geometry)
                    features.append(feat)
            
            if features:
                dp.addFeatures(features)
                layer.updateExtents()
                
                # Set up polygon symbol with transparency
                symbol = QgsFillSymbol.createSimple({
                    'color': color,
                    'outline_color': color,
                    'outline_width': '0.6',
                    'outline_style': 'solid',
                    'style': 'solid'
                })
                symbol.setOpacity(opacity)
                layer.renderer().setSymbol(symbol)
                
                # Add layer to map
                QgsProject.instance().addMapLayer(layer, False)
                if parent_group:
                    parent_group.addLayer(layer)
                else:
                    self._get_or_create_group("Lookahead").insertLayer(0, layer)
                
                log.debug(f"Created temporary polygon layer: {layer_name}")
                return layer
            else:
                log.warning(f"No features to add to the polygon layer: {layer_name}")
                return None
                
        except Exception as e:
            log.exception(f"Error creating polygon layer: {e}")
            return None
        
    def _visualize_path(self, geometry, layer_name, color=None):
        """
        Debug visualizer that creates or updates a memory layer to display a geometry.
        Args:
            geometry (QgsGeometry): The geometry to visualize
            layer_name (str): Name for the visualization layer
            color (QColor, optional): Color for the geometry. Defaults to None (random color).
        Returns:
            bool: True if visualization was successful, False otherwise
        """
        # Validate input geometry
        if not geometry or not isinstance(geometry, QgsGeometry) or geometry.isEmpty():
            log.warning(f"Cannot visualize empty or invalid geometry for layer '{layer_name}'")
            return False
        log.debug(f"Visualizing geometry for layer: '{layer_name}'")
        try:
            # Remove existing layer with the same name if it exists
            existing_layer = QgsProject.instance().mapLayersByName(layer_name)
            if existing_layer:
                QgsProject.instance().removeMapLayer(existing_layer[0].id())
                log.debug(f"Removed existing layer '{layer_name}'")
            # Create a new memory layer
            layer = QgsVectorLayer("LineString?crs=EPSG:4326", layer_name, "memory")
            provider = layer.dataProvider()
            # Add fields for additional information
            provider.addAttributes([
                QgsField("Length", QVariant.Double, "double", 10, 2),
                QgsField("Description", QVariant.String, "string", 255)
            ])
            layer.updateFields()
            # Create feature with the geometry
            feature = QgsFeature()
            feature.setGeometry(geometry)
            # Set attributes
            length = geometry.length()
            feature.setAttributes([
                length,
                f"Visualization path ({length:.2f} m)"
            ])
            # Add feature to layer
            provider.addFeatures([feature])
            # Style the layer
            if not color:
                # Generate a random color if none specified
                color = QColor(
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255)
                )
            # Apply line symbology
            symbol = QgsLineSymbol.createSimple({
                'line_color': color.name(),
                'line_width': '0.6',
                'line_style': 'solid'
            })
            layer.renderer().setSymbol(symbol)
            # Add to project and refresh
            self._add_layer_to_lookahead_group(layer)
            layer.triggerRepaint()
            log.info(f"Successfully visualized geometry in layer '{layer_name}'")
            return True
        except Exception as e:
            log.exception(f"Error visualizing geometry for '{layer_name}': {e}")
            return False
    
    def _get_or_create_group(self, group_name, parent_name=None):
        """Get or create a layer group in the QGIS layer tree.

        Args:
            group_name (str): Name of the group to get or create
            parent_name (str, optional): Name of parent group. If None, uses root.

        Returns:
            QgsLayerTreeGroup: The group object
        """
        root = QgsProject.instance().layerTreeRoot()

        # Find parent group if specified
        if parent_name:
            parent_groups = root.findGroups(True, parent_name)
            if parent_groups:
                parent = parent_groups[0]
            else:
                # Create parent group if it doesn't exist
                parent = root.insertGroup(0, parent_name)
        else:
            parent = root

        # Find existing group
        for child in parent.children():
            if child.nodeType() == 0 and child.name() == group_name:  # NodeGroup = 0
                return child

        # Create new group at the top
        return parent.insertGroup(0, group_name)

    def _add_layer_to_lookahead_group(self, layer, visible=True):
        """Adds a layer to the QGIS project and places it in the 'Lookahead' group.

        If visible is False, the layer is registered and listed in the group but the
        tree item checkbox is off (user can enable it for debugging). Optimized_Path
        already shows final run-in/run-out geometry.
        """
        if not layer or not layer.isValid():
            return
        
        project = QgsProject.instance()
        # Add layer to project registry, but not directly to the layer tree root
        project.addMapLayer(layer, False)
        
        group = self._get_or_create_group("Lookahead")
        node = group.insertLayer(0, layer)
        if not visible:
            def _turn_off():
                try:
                    if node is not None:
                        node.setItemVisibilityChecked(False)
                        node.setExpanded(False)
                    n = project.layerTreeRoot().findLayer(layer.id())
                    if n is not None:
                        n.setItemVisibilityChecked(False)
                        n.setExpanded(False)
                except Exception:
                    pass
            _turn_off()
            # QGIS auto-checks newly inserted layers. Defer unchecking so it sticks.
            QtCore.QTimer.singleShot(0, _turn_off)
            QtCore.QTimer.singleShot(50, _turn_off)
            QtCore.QTimer.singleShot(250, _turn_off)
            QtCore.QTimer.singleShot(500, _turn_off)

    def _set_layer_visibility_by_names(self, layer_names, visible):
        """Toggle visibility for all project layers matching given names."""
        if not layer_names:
            return
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        for layer_name in layer_names:
            try:
                layers = project.mapLayersByName(layer_name)
            except Exception:
                layers = []
            for layer in layers:
                try:
                    node = root.findLayer(layer.id())
                    if node is not None:
                        node.setItemVisibilityChecked(bool(visible))
                except Exception as e:
                    log.debug("Layer visibility toggle skipped for %r: %s", layer_name, e)

    def _create_temporary_point_layer(self, points, layer_name, color="#FF0000", 
                                     marker_style="circle", size=5.0, parent_group=None):
        """Create a temporary point layer for visualization.

        Args:
            points (list): List of QgsPoint objects
            layer_name (str): Name for the layer
            color (str): Hex color code (default: red)
            marker_style (str): Style name ('circle', 'square', 'triangle', 'star')
            size (float): Size of marker
            parent_group (QgsLayerTreeGroup, optional): Parent group to add layer to

        Returns:
            QgsVectorLayer: The created point layer
        """
        try:
            # Create memory layer
            vl = QgsVectorLayer("Point?crs=epsg:31984", layer_name, "memory")
            dp = vl.dataProvider()

            # Add description field
            dp.addAttributes([QgsField("Description", QVariant.String)])
            vl.updateFields()

            # Create features from points
            features = []
            for i, point in enumerate(points):
                feat = QgsFeature()

                # Handle different point types
                if isinstance(point, QgsPoint):
                    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point)))
                elif isinstance(point, QgsPointXY):
                    feat.setGeometry(QgsGeometry.fromPointXY(point))
                else:
                    log.warning(f"Unsupported point type: {type(point)}")
                    continue

                feat.setAttributes([f"Point {i+1}"])
                features.append(feat)

            dp.addFeatures(features)
            vl.updateExtents()

            # Set style properties based on marker_style
            marker_name = "circle"
            if marker_style == "square":
                marker_name = "square"
            elif marker_style == "triangle":
                marker_name = "triangle"
            elif marker_style == "star":
                marker_name = "star"

            # Create the symbol
            symbol = QgsMarkerSymbol.createSimple({
                'name': marker_name,
                'color': color,
                'size': str(size)
            })
            vl.renderer().setSymbol(symbol)

            # Add to project with optional group
            QgsProject.instance().addMapLayer(vl, False)  # False = don't add to legend yet

            if parent_group:
                parent_group.addLayer(vl)
            else:
                self._get_or_create_group("Lookahead").insertLayer(0, vl)

            log.debug(f"Created temporary point layer: {layer_name}")
            return vl

        except Exception as e:
            log.exception(f"Error creating point layer: {e}")
            return None

    def _create_temporary_line_layer(self, geometries, layer_name, color="#FF0000", 
                                    width=0.6, line_style="solid", parent_group=None):
        """Create a temporary line layer for visualization.

        Args:
            geometries (list): List of QgsGeometry objects representing lines
            layer_name (str): Name for the layer
            color (str): Hex color code (default: red)
            width (float): Line width
            line_style (str): Style name ('solid', 'dash', 'dot')
            parent_group (QgsLayerTreeGroup, optional): Parent group to add layer to

        Returns:
            QgsVectorLayer: The created vector layer
        """
        try:
            # Create a temporary line layer
            vl = QgsVectorLayer("LineString?crs=epsg:31984", layer_name, "memory")
            dp = vl.dataProvider()

            # Add fields for additional information
            dp.addAttributes([
                QgsField("Length", QVariant.Double, "double", 10, 2),
                QgsField("Description", QVariant.String, "string", 255)
            ])
            vl.updateFields()

            # Add features
            features = []
            for i, geometry in enumerate(geometries):
                if geometry and not geometry.isEmpty():
                    # Convert to LineString if needed
                    if geometry.type() != QgsWkbTypes.LineGeometry:
                        log.warning(f"Geometry {i} is not a line, attempting to convert.")
                        if geometry.type() == QgsWkbTypes.PointGeometry:
                            log.warning(f"Cannot convert point to line. Skipping.")
                            continue
                        
                    feat = QgsFeature()
                    feat.setGeometry(geometry)

                    # Set attributes
                    length = geometry.length()
                    feat.setAttributes([
                        length,
                        f"Line {i+1} ({length:.2f} m)"
                    ])
                    features.append(feat)

            if features:
                dp.addFeatures(features)
                vl.updateExtents()

                # Set style properties based on line_style
                style_props = {
                    'color': color,
                    'line_width': str(width)
                }

                if line_style == 'dash':
                    style_props['line_style'] = 'dash'
                    style_props['customdash'] = '4;2'
                elif line_style == 'dot':
                    style_props['line_style'] = 'dot'
                    style_props['customdash'] = '1;2'
                else:  # Default to solid
                    style_props['line_style'] = 'solid'

                # Apply style
                symbol = QgsLineSymbol.createSimple(style_props)
                vl.renderer().setSymbol(symbol)

                # Add to project with optional group
                QgsProject.instance().addMapLayer(vl, False)  # False = don't add to legend yet

                if parent_group:
                    parent_group.addLayer(vl)
                else:
                    self._get_or_create_group("Lookahead").insertLayer(0, vl)

                log.debug(f"Created temporary line layer: {layer_name}")
                return vl
            else:
                log.warning(f"No features to add to the line layer: {layer_name}")
                return None

        except Exception as e:
            log.exception(f"Error creating line layer: {e}")
            return None

    def _visualize_middle_reference_line(self, line_geom, line_num, obstacle_idx, parent_group=None):
        """
        Create a visualization of the middle reference line for an obstacle.

        Args:
            line_geom (QgsGeometry): Line geometry
            line_num (int): Line number for identification
            obstacle_idx (int): Obstacle index
            parent_group (QgsLayerTreeGroup, optional): Parent group for the layer

        Returns:
            QgsVectorLayer: The created line layer
        """
        if not line_geom or line_geom.isEmpty():
            log.warning(f"Cannot visualize empty middle reference line for obstacle {obstacle_idx}")
            return None

        # Create a highlighted version of the line
        ref_line_layer = self._create_temporary_line_layer(
            [line_geom],
            f"Middle_Reference_Line_{obstacle_idx}",
            "#FFFF00",  # Yellow
            1.2,  # Slightly thicker
            "solid",
            parent_group=parent_group
        )

        # Add midpoint marker
        try:
            midpoint_geom = line_geom.interpolate(line_geom.length() / 2.0)
            if not midpoint_geom.isEmpty():
                midpoint = midpoint_geom.asPoint()
                midpoint_layer = self._create_temporary_point_layer(
                    [midpoint],
                    f"Middle_Reference_Line_Midpoint_{obstacle_idx}",
                    "#FFFF00",  # Yellow
                    "star",  # Use a star for better visibility
                    8.0,  # Larger size
                    parent_group=parent_group
                )

                # Add label
                if midpoint_layer:
                    label_settings = QgsPalLayerSettings()
                    label_settings.fieldName = "Description"
                    label_settings.enabled = True

                    text_format = QgsTextFormat()
                    text_format.setSize(8)
                    text_format.setColor(QColor("#000000"))

                    buffer_settings = QgsTextBufferSettings()
                    buffer_settings.setEnabled(True)
                    buffer_settings.setSize(1)
                    buffer_settings.setColor(QColor("#FFFFFF"))

                    text_format.setBuffer(buffer_settings)
                    label_settings.setFormat(text_format)

                    midpoint_layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
                    midpoint_layer.setLabelsEnabled(True)
                    midpoint_layer.triggerRepaint()
        except Exception as e:
            log.warning(f"Error adding midpoint marker: {e}")

        return ref_line_layer

    def _reconstruct_path(self, final_sequence_info, line_data, required_layers, sim_params, turn_cache):
        """
        Reconstructs the full path geometries (RunIns, Lines, Turns) from the sequence info.
        """
        if not final_sequence_info:
            return []

        sequence = final_sequence_info.get('seq', [])
        directions = final_sequence_info.get('state', {}).get('line_directions', {})
        result_segments = []
        custom_turns = final_sequence_info.get("custom_turns", {})

        if not sequence:
            return []

        mode_key = sim_params.get("acquisition_mode_key", "teardrop")

        for i, line_num in enumerate(sequence):
            direction_str = directions.get(line_num, 'low_to_high')
            is_reciprocal = (direction_str == 'high_to_low')

            # Add RunIn and Line segments for the current line
            self._add_line_segments(
                line_num, is_reciprocal, line_data, required_layers, sim_params, result_segments
            )

            # Build turn to the next line after current line segments, so order stays:
            # RunIn -> Line -> RunOut -> Turn.
            current_exit_pt, current_exit_hdg = self._get_next_exit_state(
                line_num, is_reciprocal, line_data, sim_params
            )
            if i >= len(sequence) - 1:
                continue

            next_line = sequence[i + 1]
            next_is_reciprocal = (directions.get(next_line, 'low_to_high') == 'high_to_low')
            next_line_info = line_data.get(next_line)
            if not next_line_info:
                continue

            p_entry, h_entry = self._get_entry_details(next_line_info, next_is_reciprocal, sim_params)
            turn_key = f"{line_num}_{next_line}"
            turn_override = custom_turns.get(turn_key, {})
            custom_radius = turn_override.get("radius")
            custom_flip = turn_override.get("flip", False)
            nudge_dx = float(turn_override.get("nudge_dx", 0) or 0)
            nudge_dy = float(turn_override.get("nudge_dy", 0) or 0)
            mid_loop_count = int(turn_override.get("mid_loop_count", 0) or 0)
            mid_loop_side = int(turn_override.get("mid_loop_side", 1) or 1)
            mid_loop_dx = float(turn_override.get("mid_loop_dx", 0) or 0)
            mid_loop_dy = float(turn_override.get("mid_loop_dy", 0) or 0)

            custom_mode_text = turn_override.get("mode")
            turn_mode_override = mode_key
            if custom_mode_text == "Teardrop":
                turn_mode_override = "teardrop"
            elif custom_mode_text == "Racetrack":
                turn_mode_override = "racetrack"

            turn_mode_for_type = turn_mode_override
            try:
                bf = str(line_num).split("_", 1)[0]
                bt = str(next_line).split("_", 1)[0]
                if bf == bt and is_reciprocal == next_is_reciprocal:
                    turn_mode_for_type = "racetrack"
            except Exception:
                pass
            seg_type_turn = (
                "Turn_Teardrop"
                if str(turn_mode_for_type).strip().casefold() == "teardrop"
                else "Turn_Racetrack"
            )

            if current_exit_pt and current_exit_hdg is not None and p_entry and h_entry is not None:
                turn_geom, turn_length, turn_time = self._get_cached_turn(
                    line_num, next_line, is_reciprocal, next_is_reciprocal,
                    current_exit_pt, current_exit_hdg, p_entry, h_entry,
                    sim_params, turn_cache, turn_mode=turn_mode_override,
                    custom_radius=custom_radius, custom_flip=custom_flip,
                    nudge_dx=nudge_dx, nudge_dy=nudge_dy,
                    mid_loop_count=mid_loop_count, mid_loop_side=mid_loop_side,
                    mid_loop_dx=mid_loop_dx, mid_loop_dy=mid_loop_dy,
                )

                if turn_geom:
                    result_segments.append({
                        'Geometry': turn_geom,
                        'SegmentType': seg_type_turn,
                        'StartLine': line_num,
                        'EndLine': next_line,
                        'Duration_s': turn_time,
                        'Heading': None,
                        'line_is_reciprocal': next_is_reciprocal,
                        'Label': f"Turn L{line_num} -> L{next_line} ({turn_time:.1f}s)"
                    })

        log.info(f"Path reconstruction complete with {len(result_segments)} segments")
        return result_segments

    def closeEvent(self, event):
        """Cleans up resources when the dock widget is closed."""
        log.debug("Dock widget close event.")
        self._save_dock_settings()

        # Clear layer references
        self.generated_lines_layer = None
        self.generated_runins_layer = None
        self.generated_turns_layer = None
        self.optimized_path_layer = None

        # Clear cached data
        self.last_line_data = None
        self.last_turn_cache = None
        self.last_simulation_result = None
        self.last_sim_params = None
        self.last_required_layers = None

        # Signal plugin closure and accept the event
        self.closingPlugin.emit()
        # Release logger file handles so plugin files can be deleted/uninstalled.
        shutdown_obn_logging()
        event.accept()
        log.info("Lookahead dock widget closed.")