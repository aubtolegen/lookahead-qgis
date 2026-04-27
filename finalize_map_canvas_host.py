from __future__ import annotations

import math

from qgis.core import QgsDistanceArea, QgsPointXY, QgsProject, QgsUnitTypes
from qgis.gui import QgsMapCanvas
from qgis.PyQt import QtCore, QtGui, QtWidgets

try:
    from qgis.core import Qgis
except ImportError:  # QGIS < 3.30
    Qgis = None

try:
    _QT_ALIGN_CENTER = QtCore.Qt.AlignmentFlag.AlignCenter
    _QT_ALIGN_HCENTER = QtCore.Qt.AlignmentFlag.AlignHCenter
    _QT_ALIGN_TOP = QtCore.Qt.AlignmentFlag.AlignTop
except AttributeError:
    _QT_ALIGN_CENTER = QtCore.Qt.AlignCenter
    _QT_ALIGN_HCENTER = QtCore.Qt.AlignHCenter
    _QT_ALIGN_TOP = QtCore.Qt.AlignTop

try:
    _QT_WA_TRANSLUCENT_BACKGROUND = QtCore.Qt.WidgetAttribute.WA_TranslucentBackground
    _QT_WA_TRANSPARENT_FOR_MOUSE_EVENTS = QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
    _QT_NO_BRUSH = QtCore.Qt.BrushStyle.NoBrush
except AttributeError:
    _QT_WA_TRANSLUCENT_BACKGROUND = QtCore.Qt.WA_TranslucentBackground
    _QT_WA_TRANSPARENT_FOR_MOUSE_EVENTS = QtCore.Qt.WA_TransparentForMouseEvents
    _QT_NO_BRUSH = QtCore.Qt.NoBrush

try:
    _QPAINTER_ANTIALIASING = QtGui.QPainter.RenderHint.Antialiasing
except AttributeError:
    _QPAINTER_ANTIALIASING = QtGui.QPainter.Antialiasing


def _nice_distance_m(d: float) -> float:
    """Largest 1/2/5×10ⁿ metres not exceeding d."""
    if d <= 0 or not math.isfinite(d):
        return 0.0
    exp = math.floor(math.log10(d))
    for mul in (5.0, 2.0, 1.0):
        cand = mul * (10.0**exp)
        if cand <= d * 1.0000001:
            return cand
    return 10.0**exp


def _meters_unit():
    if Qgis is not None:
        return Qgis.DistanceUnit.Meters
    return QgsUnitTypes.DistanceUnit.DistanceMeters


def _distance_meters_between(canvas: QgsMapCanvas, p1: QgsPointXY, p2: QgsPointXY) -> float:
    """Ground distance in metres for the segment (geodesic if geographic, else planar + unit conversion)."""
    try:
        crs = canvas.mapSettings().destinationCrs()
        ctx = QgsProject.instance().transformContext()
    except Exception:
        return 0.0
    da = QgsDistanceArea()
    try:
        da.setSourceCrs(crs, ctx)
    except Exception:
        return 0.0
    try:
        is_geo = crs.isGeographic()
    except Exception:
        is_geo = False
    if is_geo:
        try:
            da.setEllipsoid(QgsProject.instance().ellipsoid())
        except Exception:
            pass
        try:
            return float(da.measureLine(p1, p2))
        except Exception:
            return 0.0
    # Projected: planar length in map units, convert to metres
    d_plan = math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
    try:
        src = crs.mapUnits()
        fac = float(QgsUnitTypes.fromUnitToUnitFactor(src, _meters_unit()))
        if fac > 0.0 and math.isfinite(fac):
            return float(d_plan * fac)
    except Exception:
        pass
    # Fallback: treat map units as metres (typical projected maritime CRS)
    return float(d_plan)


class _NorthRoseWidget(QtWidgets.QWidget):
    """Fixed rose: N at top of the widget (screen up), independent of map rotation."""

    def __init__(self, canvas: QgsMapCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas  # kept for API symmetry; drawing is not rotation-linked
        self.setFixedSize(56, 56)
        self.setAttribute(_QT_WA_TRANSLUCENT_BACKGROUND, True)
        self.setAttribute(_QT_WA_TRANSPARENT_FOR_MOUSE_EVENTS, True)
        self.setStyleSheet("background: rgba(255,255,255,210); border-radius: 28px;")

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(_QPAINTER_ANTIALIASING, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.translate(cx, cy)
        r = min(cx, cy) - 6
        pen = QtGui.QPen(QtGui.QColor(45, 45, 55))
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.setBrush(_QT_NO_BRUSH)
        p.drawEllipse(QtCore.QPointF(0, 0), r, r)
        # Ticks and labels stay inside the circle so nothing clips at the widget edge
        # (old W label sat outside the left bound and looked like a smudge).
        r_tick_out = r - 1.5
        r_tick_in = r - 6.0
        r_lab = r - 11.0
        lab_half = 7.0
        for deg, lbl in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            rad = math.radians(deg)
            sn, cs = math.sin(rad), math.cos(rad)
            x1, y1 = r_tick_in * sn, -r_tick_in * cs
            x2, y2 = r_tick_out * sn, -r_tick_out * cs
            p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
            tx = r_lab * sn
            ty = -r_lab * cs
            bold = lbl == "N"
            f = p.font()
            f.setBold(bold)
            f.setPointSize(8 if bold else 7)
            p.setFont(f)
            p.drawText(
                QtCore.QRectF(tx - lab_half, ty - lab_half, 2 * lab_half, 2 * lab_half),
                _QT_ALIGN_CENTER,
                lbl,
            )


class _HorizontalScaleBarWidget(QtWidgets.QWidget):
    """Ruler-style bar with ground distance label (metres / km)."""

    BAR_W = 118
    MARGIN = 8

    def __init__(self, canvas: QgsMapCanvas, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._label_txt = ""
        self._draw_w = float(self.BAR_W)
        # Taller so the caption under the ticks is not clipped
        self.setFixedSize(self.BAR_W + self.MARGIN * 2 + 16, 42)
        self.setAttribute(_QT_WA_TRANSLUCENT_BACKGROUND, True)
        self.setAttribute(_QT_WA_TRANSPARENT_FOR_MOUSE_EVENTS, True)
        self.setStyleSheet("background: rgba(255,255,255,215); border-radius: 4px;")

    def _refresh_metrics(self):
        c = self._canvas
        self._label_txt = ""
        self._draw_w = float(self.BAR_W)
        try:
            ext = c.extent()
            center = ext.center()
            mupp = float(c.mapSettings().mapUnitsPerPixel())
        except Exception:
            return
        if mupp <= 0.0 or not math.isfinite(mupp):
            return
        half_mu = 0.5 * mupp * float(self.BAR_W)
        p1 = QgsPointXY(center.x() - half_mu, center.y())
        p2 = QgsPointXY(center.x() + half_mu, center.y())
        d_full = _distance_meters_between(c, p1, p2)
        if d_full <= 0.0 or not math.isfinite(d_full):
            self._label_txt = "—"
            return
        d = _nice_distance_m(d_full)
        if d <= 0.0:
            self._label_txt = "—"
            return
        frac = d / max(d_full, 1e-30)
        self._draw_w = max(8.0, float(self.BAR_W) * min(1.0, frac))
        if d >= 1000.0:
            self._label_txt = f"{d/1000.0:g} km"
        else:
            self._label_txt = f"{d:g} m"

    def paintEvent(self, _e):
        self._refresh_metrics()
        p = QtGui.QPainter(self)
        p.setRenderHint(_QPAINTER_ANTIALIASING, True)
        ymid = 14.0
        bw = getattr(self, "_draw_w", float(self.BAR_W))
        x1 = float(self.width() - self.MARGIN)
        x0 = x1 - bw
        pen = QtGui.QPen(QtGui.QColor(35, 35, 40))
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(x0, ymid), QtCore.QPointF(x1, ymid))
        p.drawLine(QtCore.QPointF(x0, ymid - 5), QtCore.QPointF(x0, ymid + 5))
        p.drawLine(QtCore.QPointF(x0 + bw / 2.0, ymid - 4), QtCore.QPointF(x0 + bw / 2.0, ymid + 4))
        p.drawLine(QtCore.QPointF(x1, ymid - 5), QtCore.QPointF(x1, ymid + 5))
        lf = QtGui.QFont()
        lf.setPointSize(8)
        p.setFont(lf)
        p.drawText(
            QtCore.QRectF(x0 - 20, 24, bw + 40, 16),
            _QT_ALIGN_HCENTER | _QT_ALIGN_TOP,
            self._label_txt or "—",
        )


class FinalizeMapCanvasHost(QtWidgets.QWidget):
    """
    QgsMapCanvas edge-to-edge: north rose (top-right, fixed N up), scale bar (bottom-right).
    """

    def __init__(self, canvas: QgsMapCanvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        canvas.setParent(self)
        self._rose = _NorthRoseWidget(canvas, self)
        self._scale = _HorizontalScaleBarWidget(canvas, self)
        self._margin = 8

        def _upd():
            self._rose.update()
            self._scale.update()

        for sig_name in ("extentsChanged", "scaleChanged", "destinationCrsChanged"):
            sig = getattr(canvas, sig_name, None)
            if sig is not None and hasattr(sig, "connect"):
                try:
                    sig.connect(_upd)
                except Exception:
                    pass
        rot_sig = getattr(canvas, "rotationChanged", None)
        if rot_sig is not None and hasattr(rot_sig, "connect"):
            try:
                rot_sig.connect(_upd)
            except Exception:
                pass

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        if w > 0 and h > 0:
            self.canvas.setGeometry(0, 0, w, h)
            sw, sh = self._scale.width(), self._scale.height()
            rw, rh = self._rose.width(), self._rose.height()
            m = self._margin
            sx = w - sw - 2
            sy = h - sh - 2
            self._scale.setGeometry(sx, sy, sw, sh)
            self._rose.setGeometry(w - rw - m, m, rw, rh)
            self._scale.raise_()
            self._rose.raise_()
        super().resizeEvent(event)

    def minimumSizeHint(self) -> QtCore.QSize:
        try:
            return self.canvas.minimumSizeHint()
        except Exception:
            return QtCore.QSize(200, 200)
