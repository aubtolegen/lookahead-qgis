"""Qt5/Qt6 and QGIS 3/4 enum access via nested names resolved with getattr."""

from qgis.core import (
    Qgis,
    QgsFeatureRequest,
    QgsMapLayer,
    QgsMarkerLineSymbolLayer,
    QgsPalLayerSettings,
    QgsTask,
    QgsUnitTypes,
    QgsVectorFileWriter,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import Qt, QEvent
from qgis.PyQt.QtGui import QFont, QPainter, QPalette
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHeaderView,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSlider,
    QStyle,
    QToolButton,
)

try:
    from qgis.core import QgsMapLayerProxyModel
except ImportError:
    from qgis.gui import QgsMapLayerProxyModel

from qgis.gui import QgsVertexMarker


def swallow_exc():
    """No-op for optional QGIS/Qt APIs that differ by version."""
    return None


def _enum(owner, enum_name, member):
    nested = getattr(owner, enum_name, None)
    if nested is not None:
        val = getattr(nested, member, None)
        if val is not None:
            return val
    val = getattr(owner, member, None)
    if val is not None:
        return val
    raise AttributeError(
        "%s.%s.%s" % (getattr(owner, "__name__", owner), enum_name, member)
    )


def _first_enum(*specs):
    last_err = None
    for spec in specs:
        try:
            if len(spec) == 3:
                return _enum(*spec)
            owner, member = spec
            val = getattr(owner, member, None)
            if val is not None:
                return val
            raise AttributeError(member)
        except AttributeError as err:
            last_err = err
    raise AttributeError(last_err)


def _enum_optional(owner, enum_name, member, default=None):
    try:
        return _enum(owner, enum_name, member)
    except AttributeError:
        return default


def _wkb_geometry(legacy_name, qgis4_name):
    geom_enum = getattr(QgsWkbTypes, "GeometryType", None)
    if geom_enum is None:
        geom_enum = getattr(Qgis, "GeometryType", None)
    if geom_enum is not None:
        for name in (legacy_name, qgis4_name):
            val = getattr(geom_enum, name, None)
            if val is not None:
                return val
    val = getattr(QgsWkbTypes, legacy_name, None)
    if val is not None:
        return val
    raise AttributeError(legacy_name)


def _wkb_type(member):
    type_enum = getattr(QgsWkbTypes, "Type", None)
    if type_enum is not None:
        val = getattr(type_enum, member, None)
        if val is not None:
            return val
    val = getattr(QgsWkbTypes, member, None)
    if val is not None:
        return val
    qgis_wkb = getattr(Qgis, "WkbType", None)
    if qgis_wkb is not None:
        val = getattr(qgis_wkb, member, None)
        if val is not None:
            return val
    raise AttributeError(member)


# --- Qt ---
QT_USER_ROLE = int(_enum(Qt, "ItemDataRole", "UserRole"))
QT_BACKGROUND_ROLE = _enum(Qt, "ItemDataRole", "BackgroundRole")
QT_FOREGROUND_ROLE = _enum(Qt, "ItemDataRole", "ForegroundRole")
QT_FONT_ROLE = _enum(Qt, "ItemDataRole", "FontRole")
QT_WAIT_CURSOR = _enum(Qt, "CursorShape", "WaitCursor")
QT_ALIGN_LEFT = _enum(Qt, "AlignmentFlag", "AlignLeft")
QT_ALIGN_RIGHT = _enum(Qt, "AlignmentFlag", "AlignRight")
QT_ALIGN_CENTER = _enum(Qt, "AlignmentFlag", "AlignCenter")
QT_ALIGN_VCENTER = _enum(Qt, "AlignmentFlag", "AlignVCenter")
QT_ALIGN_HCENTER = _enum(Qt, "AlignmentFlag", "AlignHCenter")
QT_ALIGN_TOP = _enum(Qt, "AlignmentFlag", "AlignTop")
QT_ALIGN_LEADING = _enum_optional(Qt, "AlignmentFlag", "AlignLeading", QT_ALIGN_LEFT)
QT_SCROLLBAR_ALWAYS_OFF = _enum(Qt, "ScrollBarPolicy", "ScrollBarAlwaysOff")
QT_SCROLLBAR_AS_NEEDED = _enum(Qt, "ScrollBarPolicy", "ScrollBarAsNeeded")
QT_SCROLLBAR_ALWAYS_ON = _enum(Qt, "ScrollBarPolicy", "ScrollBarAlwaysOn")
QT_ELIDE_NONE = _enum(Qt, "TextElideMode", "ElideNone")
QT_ELIDE_MIDDLE = _enum(Qt, "TextElideMode", "ElideMiddle")
QT_ELIDE_RIGHT = _enum(Qt, "TextElideMode", "ElideRight")
QT_VERTICAL = _enum(Qt, "Orientation", "Vertical")
QT_HORIZONTAL = _enum(Qt, "Orientation", "Horizontal")
QT_LEFT_BUTTON = _enum(Qt, "MouseButton", "LeftButton")
QT_RIGHT_BUTTON = _enum(Qt, "MouseButton", "RightButton")
QT_SHIFT_MODIFIER = _enum(Qt, "KeyboardModifier", "ShiftModifier")
QT_CONTROL_MODIFIER = _enum(Qt, "KeyboardModifier", "ControlModifier")
QT_WINDOW_MODAL = _enum(Qt, "WindowModality", "WindowModal")
QT_NON_MODAL = _enum(Qt, "WindowModality", "NonModal")
QT_KEEP_ASPECT_RATIO = _enum(Qt, "AspectRatioMode", "KeepAspectRatio")
QT_SMOOTH_TRANSFORMATION = _enum(Qt, "TransformationMode", "SmoothTransformation")
QT_TEXT_BROWSER_INTERACTION = _enum(Qt, "TextInteractionFlag", "TextBrowserInteraction")
QT_ISO_DATE = _enum(Qt, "DateFormat", "ISODate")
QT_MATCH_EXACTLY = _enum(Qt, "MatchFlag", "MatchExactly")
QT_RICH_TEXT = _enum(Qt, "TextFormat", "RichText")
QT_WINDOW_MAXIMIZE_BUTTON_HINT = _enum(Qt, "WindowType", "WindowMaximizeButtonHint")
QT_ITEM_IS_EDITABLE = _enum(Qt, "ItemFlag", "ItemIsEditable")
QT_COLOR_WHITE = _enum(Qt, "GlobalColor", "white")
QT_NO_CONTEXT_MENU = _enum(Qt, "ContextMenuPolicy", "NoContextMenu")
QT_KEY_ESCAPE = _enum(Qt, "Key", "Key_Escape")
QT_WIDGET_WITH_CHILDREN_SHORTCUT = _enum(
    Qt, "ShortcutContext", "WidgetWithChildrenShortcut")
QT_WA_DELETE_ON_CLOSE = _enum(Qt, "WidgetAttribute", "WA_DeleteOnClose")
QT_WA_TRANSLUCENT_BACKGROUND = _enum(
    Qt, "WidgetAttribute", "WA_TranslucentBackground")
QT_WA_TRANSPARENT_FOR_MOUSE_EVENTS = _enum(
    Qt, "WidgetAttribute", "WA_TransparentForMouseEvents")
QT_NO_BRUSH = _enum(Qt, "BrushStyle", "NoBrush")
QT_RIGHT_DOCK_AREA = _enum(Qt, "DockWidgetArea", "RightDockWidgetArea")
QT_LEFT_TO_RIGHT = _enum(Qt, "LayoutDirection", "LeftToRight")
QPT_NO_WRAP = _enum(QPlainTextEdit, "LineWrapMode", "NoWrap")

# --- Qt widgets / gui ---
QT_TOOLBUTTON_TEXT_ONLY = _enum(Qt, "ToolButtonStyle", "ToolButtonTextOnly")
QT_MENU_BUTTON_POPUP = _enum(QToolButton, "ToolButtonPopupMode", "MenuButtonPopup")
QT_INSTANT_POPUP = _enum(QToolButton, "ToolButtonPopupMode", "InstantPopup")
QSP_PREFERRED = _enum(QSizePolicy, "Policy", "Preferred")
QSP_EXPANDING = _enum(QSizePolicy, "Policy", "Expanding")
QSP_FIXED = _enum(QSizePolicy, "Policy", "Fixed")
QSP_MAXIMUM = _enum(QSizePolicy, "Policy", "Maximum")
QFRAME_NO_FRAME = _enum(QFrame, "Shape", "NoFrame")
QAIV_EXTENDED_SELECTION = _enum(QAbstractItemView, "SelectionMode", "ExtendedSelection")
QAIV_SELECT_ROWS = _enum(QAbstractItemView, "SelectionBehavior", "SelectRows")
QAIV_SINGLE_SELECTION = _enum(QAbstractItemView, "SelectionMode", "SingleSelection")
QAIV_NO_EDIT_TRIGGERS = _enum(QAbstractItemView, "EditTrigger", "NoEditTriggers")
QDIALOG_ACCEPTED = _enum(QDialog, "DialogCode", "Accepted")
QDIALOGBUTTONBOX_OK = _enum(QDialogButtonBox, "StandardButton", "Ok")
QDIALOGBUTTONBOX_CANCEL = _enum(QDialogButtonBox, "StandardButton", "Cancel")
QFILEDIALOG_DONT_CONFIRM_OVERWRITE = _enum(QFileDialog, "Option", "DontConfirmOverwrite")
QEVENT_MOUSE_MOVE = _enum(QEvent, "Type", "MouseMove")
QEVENT_MOUSE_BUTTON_PRESS = _enum(QEvent, "Type", "MouseButtonPress")
QSTYLE_CE_ITEMVIEWITEM = _enum(QStyle, "ControlElement", "CE_ItemViewItem")
QSTYLE_SE_ITEMVIEWITEMTEXT = _enum(QStyle, "SubElement", "SE_ItemViewItemText")
QSTYLE_STATE_SELECTED = _enum(QStyle, "StateFlag", "State_Selected")
QFONT_SANS_SERIF = _enum(QFont, "StyleHint", "SansSerif")
QPALETTE_TEXT = _enum(QPalette, "ColorRole", "Text")
QPALETTE_HIGHLIGHTED_TEXT = _enum(QPalette, "ColorRole", "HighlightedText")
QT_HEADER_RESIZE_TO_CONTENTS = _enum(QHeaderView, "ResizeMode", "ResizeToContents")
QT_HEADER_STRETCH = _enum(QHeaderView, "ResizeMode", "Stretch")
QT_HEADER_FIXED = _enum(QHeaderView, "ResizeMode", "Fixed")
QSLIDER_TICKS_BELOW = _enum(QSlider, "TickPosition", "TicksBelow")
QPAINTER_ANTIALIASING = _enum(QPainter, "RenderHint", "Antialiasing")
QPAINTER_SMOOTH_PIXMAP_TRANSFORM = _enum(
    QPainter, "RenderHint", "SmoothPixmapTransform")
MSGBOX_YES = _enum(QMessageBox, "StandardButton", "Yes")
MSGBOX_NO = _enum(QMessageBox, "StandardButton", "No")
MSGBOX_OK = _enum(QMessageBox, "StandardButton", "Ok")
MSGBOX_ICON_WARNING = _enum(QMessageBox, "Icon", "Warning")
MSGBOX_ICON_CRITICAL = _enum(QMessageBox, "Icon", "Critical")
MSGBOX_ICON_INFORMATION = _enum(QMessageBox, "Icon", "Information")

# --- QGIS ---
QGIS_INFO = _enum(Qgis, "MessageLevel", "Info")
QGIS_WARNING = _enum(Qgis, "MessageLevel", "Warning")
QGIS_CRITICAL = _enum(Qgis, "MessageLevel", "Critical")
QGS_TASK_CAN_CANCEL = _enum(QgsTask, "Flag", "CanCancel")
QGS_REQUEST_NO_GEOMETRY = _enum(QgsFeatureRequest, "Flag", "NoGeometry")
QGS_REQUEST_NO_FLAGS = _enum(QgsFeatureRequest, "Flag", "NoFlags")
QGS_REQUEST_SUBSET_OF_ATTRIBUTES = _enum(
    QgsFeatureRequest, "Flag", "SubsetOfAttributes")
QGS_REQUEST_NO_GEOMETRY_SIMPLIFY = _enum_optional(
    QgsFeatureRequest, "Flag", "NoGeometrySimplify")
FR_GEOMETRY_NO_CHECK = _enum(
    QgsFeatureRequest, "InvalidGeometryCheck", "GeometryNoCheck")
QGSMAPLAYERPROXYMODEL_POINTLAYER = _first_enum(
    (QgsMapLayerProxyModel, "Filter", "PointLayer"),
    (Qgis, "LayerFilter", "PointLayer"),
)
QGSMAPLAYERPROXYMODEL_POLYGONLAYER = _first_enum(
    (QgsMapLayerProxyModel, "Filter", "PolygonLayer"),
    (Qgis, "LayerFilter", "PolygonLayer"),
)
QGSMAPLAYERPROXYMODEL_VECTORLAYER = _first_enum(
    (QgsMapLayerProxyModel, "Filter", "VectorLayer"),
    (Qgis, "LayerFilter", "VectorLayer"),
)
QGS_ML_FIRST_VERTEX = _enum(QgsMarkerLineSymbolLayer, "Placement", "FirstVertex")
QGS_ML_INTERVAL = _enum(QgsMarkerLineSymbolLayer, "Placement", "Interval")
ML_VECTOR_LAYER = _first_enum(
    (QgsMapLayer, "LayerType", "VectorLayer"),
    (Qgis, "LayerType", "VectorLayer"),
    (QgsMapLayer, "VectorLayer"),
)
VF_NO_ERROR = _enum(QgsVectorFileWriter, "WriterError", "NoError")
UNIT_RENDER_POINTS = _enum(QgsUnitTypes, "RenderUnit", "RenderPoints")
PAL_LABEL_ROTATION = _enum(QgsPalLayerSettings, "Property", "LabelRotation")
PAL_PLACEMENT_LINE = _enum(QgsPalLayerSettings, "Placement", "Line")
PAL_AROUND_POINT = _enum(QgsPalLayerSettings, "Placement", "AroundPoint")
PAL_HORIZONTAL = _enum(QgsPalLayerSettings, "Placement", "Horizontal")
VM_ICON_CIRCLE = _enum(QgsVertexMarker, "IconType", "ICON_CIRCLE")
VM_ICON_CROSS = _enum(QgsVertexMarker, "IconType", "ICON_CROSS")

WKB_LINE_GEOMETRY = _wkb_geometry("LineGeometry", "Line")
WKB_POINT_GEOMETRY = _wkb_geometry("PointGeometry", "Point")
WKB_POLYGON_GEOMETRY = _wkb_geometry("PolygonGeometry", "Polygon")
WKB_POINT = _wkb_type("Point")
WKB_POLYGON = _wkb_type("Polygon")
WKB_MULTIPOLYGON = _wkb_type("MultiPolygon")
WKB_LINESTRING = _wkb_type("LineString")
WKB_MULTILINESTRING = _wkb_type("MultiLineString")
