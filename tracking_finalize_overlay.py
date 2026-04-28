from __future__ import annotations

import logging
import os
import math
from typing import Any, Dict, List, Optional, Tuple

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject
from qgis.gui import QgsVertexMarker, QgsMapCanvasItem
from qgis.PyQt import QtCore
from qgis.PyQt.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

log = logging.getLogger("lookahead_planner")

try:
    _QPAINTER_ANTIALIASING = QPainter.RenderHint.Antialiasing
    _QPAINTER_SMOOTH_PIXMAP_TRANSFORM = QPainter.RenderHint.SmoothPixmapTransform
except AttributeError:
    _QPAINTER_ANTIALIASING = QPainter.Antialiasing
    _QPAINTER_SMOOTH_PIXMAP_TRANSFORM = QPainter.SmoothPixmapTransform

_MARKER_ICONS = (
    QgsVertexMarker.ICON_BOX,
    QgsVertexMarker.ICON_CIRCLE,
    QgsVertexMarker.ICON_CROSS,
    getattr(QgsVertexMarker, "ICON_X", QgsVertexMarker.ICON_CROSS),
)

_MARKER_COLORS = (
    (230, 30, 30),
    (30, 120, 255),
    (30, 180, 60),
    (200, 120, 0),
    (160, 60, 200),
    (0, 160, 160),
)


class LookaheadSvgMarker(QgsMapCanvasItem):
    """Custom robust SVG marker to bypass external marker scaling/bounds issues."""

    def __init__(self, canvas, svg_path, length_m=0.0, width_m=0.0, size=35):
        super().__init__(canvas)
        from qgis.PyQt.QtSvg import QSvgRenderer
        self._canvas = canvas
        self.real_length_m = float(length_m) if length_m else 0.0
        self.real_width_m = float(width_m) if width_m else 0.0

        raw_size = float(size) if size else 35.0
        self.fixed_size_px = 40.0 if raw_size > 100 else raw_size
        self.heading = 0.0
        self.center_pt = None
        self.renderer = QSvgRenderer(svg_path)
        self.setZValue(250000)
        try:
            self.show()
        except Exception:
            pass

        self.px_length = self.fixed_size_px
        self.px_width = self.fixed_size_px

    def removeFromCanvas(self):
        sc = self.scene()
        if sc is not None:
            sc.removeItem(self)

    def setCenter(self, pt):
        self.center_pt = pt
        self._update_pos()

    def setHeading(self, heading):
        self.heading = heading
        self.update()

    def updatePosition(self):
        self._update_pos()

    # External PositionMarker-like API: _wire_position_marker connects these signals.
    def updateCrs(self):
        self._update_pos()

    def updateMapMagnification(self, *_args, **_kwargs):
        self._update_pos()

    def updateSize(self):
        self._update_pos()

    def _update_pos(self):
        if self.center_pt is None:
            self.setVisible(False)
            return

        self.setVisible(True)
        pt = self.toCanvasCoordinates(self.center_pt)

        mpp = self._canvas.mapSettings().mapUnitsPerPixel()
        new_l = self.fixed_size_px
        new_w = self.fixed_size_px

        if mpp > 0:
            if self.real_length_m > 0 and self.real_width_m > 0:
                new_l = self.real_length_m / mpp
                new_w = self.real_width_m / mpp
            elif self.real_length_m > 0:
                new_l = self.real_length_m / mpp
                new_w = new_l

            if self.real_width_m <= 0:
                view_box = self.renderer.viewBoxF()
                if not view_box.isEmpty() and view_box.height() > 0:
                    aspect = view_box.width() / view_box.height()
                    new_w = new_l * aspect

            min_px = 30.0
            if new_l < min_px and new_w < min_px:
                major = max(new_l, new_w)
                if major > 0:
                    scale = min_px / major
                    new_l *= scale
                    new_w *= scale

        self.prepareGeometryChange()
        self.px_length = max(new_l, 2.0)
        self.px_width = max(new_w, 2.0)

        diag = math.hypot(self.px_length, self.px_width)
        half_diag = diag / 2.0

        self.setPos(pt.x() - half_diag, pt.y() - half_diag)
        self.update()

    def boundingRect(self):
        from qgis.PyQt.QtCore import QRectF
        diag = math.hypot(self.px_length, self.px_width)
        return QRectF(0, 0, diag, diag)

    def paint(self, painter, option, widget=None):
        from qgis.PyQt.QtCore import QRectF
        if not self.renderer.isValid():
            return
        painter.save()
        painter.setRenderHint(_QPAINTER_ANTIALIASING, True)
        painter.setRenderHint(_QPAINTER_SMOOTH_PIXMAP_TRANSFORM, True)

        diag = math.hypot(self.px_length, self.px_width)
        half_diag = diag / 2.0

        painter.translate(half_diag, half_diag)
        painter.rotate(self.heading)

        rect = QRectF(
            -self.px_width / 2.0,
            -self.px_length / 2.0,
            self.px_width,
            self.px_length,
        )
        self.renderer.render(painter, rect)
        painter.restore()


def _posiview_qcolor(value) -> QColor:
    """Color conversion compatible with external marker-label properties."""
    if value is None:
        return QColor("black")
    try:
        return QColor.fromRgba(int(value))
    except (TypeError, ValueError):
        try:
            return QColor(str(value))
        except Exception:
            return QColor("black")


def _posiview_marker_label_spec(mob) -> Optional[Tuple[str, float, QColor]]:
    """
    Match external ``MarkerLabel``-like data: ``Name``, ``showLabel``, ``labelDistance``,
    marker ``color``, and optional ``extraText`` when ``showExtraText`` is enabled.
    """
    mk = getattr(mob, "marker", None)
    if mk is None:
        nm = str(getattr(mob, "name", "") or "").strip()
        return (nm, 50.0, QColor("black")) if nm else None
    try:
        props = mk.properties()
    except Exception:
        props = {}
    if not bool(props.get("showLabel", True)):
        return None
    base = str(props.get("Name", getattr(mob, "name", "")) or "").strip()
    extra = ""
    if bool(props.get("showExtraText", False)):
        inner = getattr(mk, "label", None)
        if inner is not None:
            extra = str(getattr(inner, "extraText", "") or "")
    full = (base + extra) if extra else base
    full = str(full or "").strip()
    if not full:
        return None
    try:
        ldist = float(props.get("labelDistance", 50) or 50)
    except (TypeError, ValueError):
        ldist = 50.0
    ldist = max(8.0, ldist)
    return (full, ldist, _posiview_qcolor(props.get("color", "black")))


class FinalizePosiViewNameTag(QgsMapCanvasItem):
    """External marker-label style leader line + text (canvas pixel space)."""

    def __init__(self, canvas):
        super().__init__(canvas)
        # QGIS 3.44+: QgsMapCanvasItem may not expose ``canvas()`` in Python; keep the ref.
        self._map_canvas = canvas
        self._center_map: Optional[QgsPointXY] = None
        self._text = ""
        self._label_distance = 50.0
        self._line_color = QColor("black")
        self._label_rect = QtCore.QRectF(0.0, 0.0, 1.0, 1.0)
        self.setZValue(250010.0)
        try:
            self.show()
        except Exception:
            pass

    def removeFromCanvas(self):
        sc = self.scene()
        if sc is not None:
            sc.removeItem(self)

    def set_posiview_style(self, text: str, label_distance: float, line_color: QColor):
        t = str(text or "").strip()
        if t != self._text or float(label_distance) != self._label_distance or line_color != self._line_color:
            self.prepareGeometryChange()
        self._text = t
        self._label_distance = max(8.0, float(label_distance))
        self._line_color = line_color
        self._rebuild_label_rect()
        self.update()

    def setMapCenter(self, pt: Optional[QgsPointXY]):
        if pt is None:
            self._center_map = None
        else:
            try:
                self._center_map = QgsPointXY(float(pt.x()), float(pt.y()))
            except Exception:
                self._center_map = None
        self._layout()

    def updatePosition(self):
        self._layout()

    def _rebuild_label_rect(self):
        """Match external marker-label bounding-rect geometry."""
        from qgis.PyQt.QtCore import QPointF, QRectF

        cv = self._map_canvas
        f = cv.font() if cv is not None else QFont()
        fm = QFontMetricsF(f)
        ld = self._label_distance
        br = fm.boundingRect(self._text or " ")
        rect = QRectF(br).translated(QPointF(ld, -ld / 2.0))
        rect.setBottomLeft(QPointF(0.0, 0.0))
        self._label_rect = rect

    def _layout(self):
        if self._center_map is None or not self._text:
            self.setVisible(False)
            return
        try:
            cc = self.toCanvasCoordinates(self._center_map)
        except Exception:
            self.setVisible(False)
            return
        self.setPos(cc.x(), cc.y())
        self.setVisible(True)
        self.update()

    def boundingRect(self):
        return QtCore.QRectF(self._label_rect)

    def paint(self, painter, option, widget=None):
        from qgis.PyQt.QtCore import QPointF

        if not self._text or self._center_map is None:
            return
        painter.setRenderHint(_QPAINTER_ANTIALIASING, True)
        pen = QPen(self._line_color)
        pen.setWidth(1)
        painter.setPen(pen)
        ld = self._label_distance
        painter.drawLine(QPointF(0.0, 0.0), QPointF(ld, -ld / 2.0))
        painter.drawText(QPointF(ld + 2.0, -ld / 2.0 + 2.0), self._text)


def _wire_finalize_name_tag(canvas, tag: "FinalizePosiViewNameTag") -> None:
    """Keep label anchored after pan/zoom/CRS (same idea as vessel SVG marker)."""
    if getattr(tag, "_lookahead_name_tag_wired", False):
        return
    tag._lookahead_name_tag_wired = True
    connections: List[Tuple[Any, Any]] = []

    def _upd():
        tag.updatePosition()

    for sig_name in ("extentsChanged", "scaleChanged", "destinationCrsChanged"):
        sig = getattr(canvas, sig_name, None)
        if sig is not None and hasattr(sig, "connect"):
            try:
                sig.connect(_upd)
                connections.append((sig, _upd))
            except Exception:
                pass
    rot = getattr(canvas, "rotationChanged", None)
    if rot is not None and hasattr(rot, "connect"):
        try:
            rot.connect(_upd)
            connections.append((rot, _upd))
        except Exception:
            pass
    # type: ignore[attr-defined]
    tag._lookahead_name_tag_connections = connections


def _unwire_finalize_name_tag(tag: Optional["FinalizePosiViewNameTag"]) -> None:
    if tag is None:
        return
    for sig, slot in getattr(tag, "_lookahead_name_tag_connections", []) or []:
        try:
            sig.disconnect(slot)
        except TypeError:
            pass
    try:
        del tag._lookahead_name_tag_connections
    except AttributeError:
        pass
    try:
        del tag._lookahead_name_tag_wired
    except AttributeError:
        pass


def _import_posiview_position_marker():
    import importlib

    for mod in ("PosiView.position_marker", "posiview.position_marker"):
        try:
            m = importlib.import_module(mod)
            pm = getattr(m, "PositionMarker", None)
            if pm is not None:
                return pm
        except Exception:
            continue
    return None


def _resolve_posiview_plugin():
    """Return external tracking plugin instance (plugin keys may vary by locale/install)."""
    try:
        from qgis.utils import plugins  # type: ignore
    except Exception:
        return None
    best = None
    for key, inst in (plugins or {}).items():
        if inst is None:
            continue
        key_l = str(key).lower()
        if "posiview" not in key_l:
            continue
        if hasattr(inst, "project") and hasattr(inst.project, "mobileItems"):
            # Prefer exact package name match when multiple candidates exist.
            if key_l == "posiview":
                return inst
            best = inst
    return best


def _position_crs_from_posiview_main_canvas(pv) -> Optional[QgsCoordinateReferenceSystem]:
    """CRS of ``MobileItem.coordinates`` in the host map canvas."""
    try:
        if pv is None:
            return None
        iface = getattr(pv, "iface", None)
        if iface is None:
            return None
        c = iface.mapCanvas().mapSettings().destinationCrs()
        if c is not None and c.isValid():
            return c
    except Exception:
        return None
    return None


def _posiview_tracking_enabled(pv) -> bool:
    try:
        acts = getattr(pv, "actions", None) or {}
        load = acts.get("loadAction")
        if load is None:
            return True
        return bool(load.isChecked())
    except Exception:
        return False


def _transform_point_to_canvas(
    canvas,
    mob,
    pt: QgsPointXY,
    position_space_crs: Optional[QgsCoordinateReferenceSystem] = None,
) -> Optional[QgsPointXY]:
    """
    Transform ``pt`` into ``canvas`` destination CRS.

    ``position_space_crs`` should be the external tracking map canvas CRS (where
    ``MobileItem.coordinates`` already live). If ``mob.crs`` is valid it wins.
    """
    if pt is None or mob is None:
        return None
    try:
        c_src = getattr(mob, "crs", None)
        if c_src is None or not c_src.isValid():
            c_src = position_space_crs
        if c_src is None or not c_src.isValid():
            c_src = QgsProject.instance().crs()
        if c_src is None or not c_src.isValid():
            c_src = QgsCoordinateReferenceSystem("EPSG:4326")

        c_dest = canvas.mapSettings().destinationCrs()
        if not c_dest.isValid():
            c_dest = QgsProject.instance().crs()

        if c_dest.isValid() and c_src.isValid() and c_dest.authid() != c_src.authid():
            xform = QgsCoordinateTransform(
                c_src, c_dest, QgsProject.instance())
            return xform.transform(pt)
    except Exception:
        return None
    return QgsPointXY(float(pt.x()), float(pt.y()))


def _marker_signature(mob) -> Tuple[Any, ...]:
    """Detect marker style changes so we can rebuild clones."""
    try:
        d = dict(mob.marker.properties())
        d["_lookahead_name"] = getattr(mob, "name", "")
        # Bumps when clone defaults (e.g. lockScale for finalize canvases) change — forces rebuild.
        d["_lookahead_pv_clone_rev"] = 2
        return tuple(sorted(d.items(), key=lambda kv: str(kv[0])))
    except Exception:
        return (id(getattr(mob, "marker", None)),)


def _clone_marker_params(mob) -> dict:
    """Params for ``PositionMarker(canvas, params)`` — same look as main map, no trail."""
    p = dict(mob.marker.properties())
    p["Name"] = getattr(mob, "name", "Item")
    p["trackLength"] = 0
    p["TrackLength"] = 0
    p["defaultIcon"] = False
    p["DefaultIcon"] = False
    p["minSize"] = 0
    p["MinSize"] = 0
    # Source marker reads ``type`` (not shapeType); keep kind in sync.
    try:
        mt = getattr(mob.marker, "type", None) or p.get("type") or "BOX"
        p["type"] = str(mt).upper()
    except Exception:
        p["type"] = "BOX"
    # Main map vs Finalize canvases use very different scales. With lockScale=True, the source marker
    # uses paintLength = length * f with no floor → tiny svgRect on wide-extent maps: label
    # still paints, SVG hull is effectively invisible.
    p["lockScale"] = False

    # IMPORTANT: Force fixed pixel size before marker initialization.
    # Changing fixedSize after creation can leave QGraphicsItem boundingRect stale,
    # and QGIS may stop drawing the marker (appears invisible).
    p["fixedSize"] = True
    p["FixedSize"] = True
    if p.get("size", 0) <= 0 and p.get("Size", 0) <= 0:
        p["size"] = 35
        p["Size"] = 35

    if hasattr(mob, "length"):
        p["shapeLength"] = mob.length
        p["ShapeLength"] = mob.length
    if hasattr(mob, "width"):
        p["shapeWidth"] = mob.width
        p["ShapeWidth"] = mob.width
    if "Size" not in p and "size" not in p:
        p["Size"] = getattr(mob.marker, "size", 35)
    if "size" not in p:
        p["size"] = p.get("Size", 35)
    try:
        abs_svg = mob.marker.resolveSvgPath(mob.marker.svgPath)
        if abs_svg and os.path.isfile(abs_svg):
            p["svgPath"] = abs_svg
            p["SvgPath"] = abs_svg
            if str(p.get("type", "")).upper() == "SVG":
                p["type"] = "SVG"
    except Exception:
        pass
    # Avoid zero-length geometry if project/settings left length unset.
    try:
        ln = float(p.get("length", 0) or 0)
        if ln <= 0:
            p["length"] = float(getattr(mob.marker, "length", 98.0) or 98.0)
    except Exception:
        p["length"] = 98.0
    return p


def _repair_clone_svg_renderer(pm, mob) -> None:
    """Rebuild QSvgRenderer on the clone if the path is valid (handles failed relative paths)."""
    try:
        from qgis.PyQt.QtSvg import QSvgRenderer
    except ImportError:
        return
    path = ""
    try:
        path = getattr(mob.marker, "svgPath", "")
        if hasattr(mob.marker, "resolveSvgPath"):
            path = mob.marker.resolveSvgPath(path) or path
    except Exception:
        pass

    if not path or not os.path.isfile(path):
        try:
            props = pm.properties() if hasattr(pm, "properties") else {}
            if isinstance(props, dict):
                path = props.get("SvgPath", props.get("svgPath", path))
        except Exception:
            pass

    if not path or not os.path.isfile(path):
        return
    path = path.replace('\\', '/')
    try:
        r = QSvgRenderer(path)
        if r.isValid():
            pm.svgRenderer = r
            pm.svg = r
            pm._svg = r
            pm.mSvg = r
            pm.renderer = r
            pm._svg_keepalive = r  # Keep C++ object alive; prevent Python GC cleanup
            pm.type = "SVG"
            pm.Type = "SVG"
            pm.shapeType = "SVG"
            pm.ShapeType = "SVG"
            pm.svgPath = path
            pm.SvgPath = path

            if hasattr(pm, "updateSize"):
                pm.updateSize()
    except Exception:
        pass


def _wire_position_marker(canvas, pm) -> None:
    connections: List[Tuple[Any, Any]] = []

    def _reg(sig, slot):
        sig.connect(slot)
        connections.append((sig, slot))

    def _on_scale():
        if hasattr(pm, "updateSize"):
            pm.updateSize()
        if hasattr(pm, "updatePosition"):
            pm.updatePosition()

    _reg(canvas.scaleChanged, _on_scale)

    def _on_crs():
        if hasattr(pm, "updateCrs"):
            pm.updateCrs()
        if hasattr(pm, "updateSize"):
            pm.updateSize()
        if hasattr(pm, "updatePosition"):
            pm.updatePosition()

    _reg(canvas.destinationCrsChanged, _on_crs)
    # After setExtent / first layout, map scale and viewport are valid — refresh SVG/SHAPE bounds.
    ext_sig = getattr(canvas, "extentsChanged", None)
    if ext_sig is not None and hasattr(ext_sig, "connect"):
        try:
            _reg(ext_sig, _on_scale)
        except Exception:
            pass
    if hasattr(canvas, "magnificationChanged") and hasattr(pm, "updateMapMagnification"):
        _reg(canvas.magnificationChanged, pm.updateMapMagnification)
    if hasattr(canvas, "rotationChanged"):
        _reg(canvas.rotationChanged, _on_scale)
    pm._lookahead_connections = connections  # type: ignore[attr-defined]


def _unwire_and_remove_position_marker(pm) -> None:
    for sig, slot in getattr(pm, "_lookahead_connections", []) or []:
        try:
            sig.disconnect(slot)
        except TypeError:
            pass
    try:
        del pm._lookahead_connections
    except AttributeError:
        pass
    try:
        pm.removeFromCanvas()
    except Exception:
        try:
            sc = pm.scene()
            if sc is not None:
                sc.removeItem(pm)
        except Exception:
            pass


class PosiViewFinalizeOverlay:
    """Timer-driven markers for external tracking mobiles on two QgsMapCanvas instances."""

    def __init__(self, dialog, turn_canvas, calendar_canvas):
        self._dialog = dialog
        self._turn = turn_canvas
        self._cal = calendar_canvas
        self._iface = None
        try:
            p = dialog.parent()
            self._iface = getattr(p, "iface", None) if p is not None else None
        except Exception:
            self._iface = None

        self._markers_turn: Dict[str, Any] = {}
        self._markers_cal: Dict[str, Any] = {}
        self._tags_turn: Dict[str, FinalizePosiViewNameTag] = {}
        self._tags_cal: Dict[str, FinalizePosiViewNameTag] = {}
        self._active = False
        self._PositionMarker = _import_posiview_position_marker()

        self._timer = QtCore.QTimer(dialog)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._tick)

    def set_enabled(self, on: bool):
        self._active = bool(on)
        if self._active:
            self._timer.start()
            self._tick()
        else:
            self._timer.stop()
            self._clear_markers()

    def teardown(self):
        self._timer.stop()
        try:
            self._timer.timeout.disconnect(self._tick)
        except TypeError:
            pass
        self._clear_markers()

    def _clear_markers(self):
        for store, canvas in ((self._markers_turn, self._turn), (self._markers_cal, self._cal)):
            for _name, m in list(store.items()):
                self._dispose_marker(canvas, m)
            store.clear()
        for tags in (self._tags_turn, self._tags_cal):
            for _name, t in list(tags.items()):
                self._dispose_name_tag(t)
            tags.clear()
        self._refresh_finalize_canvases()

    def _dispose_name_tag(self, tag: Optional[FinalizePosiViewNameTag]):
        if tag is None:
            return
        _unwire_finalize_name_tag(tag)
        try:
            tag.removeFromCanvas()
        except Exception:
            try:
                sc = tag.scene()
                if sc is not None:
                    sc.removeItem(tag)
            except Exception:
                pass

    def _ensure_name_tag(
        self,
        canvas,
        tags_store: Dict[str, FinalizePosiViewNameTag],
        name: str,
        map_xy: Optional[QgsPointXY],
        mob: Optional[Any],
    ):
        if canvas is None:
            return
        if map_xy is None or mob is None:
            t = tags_store.get(name)
            if t is not None:
                t.setMapCenter(None)
            return
        spec = _posiview_marker_label_spec(mob)
        if spec is None:
            t = tags_store.get(name)
            if t is not None:
                t.setMapCenter(None)
            return
        text, ldist, col = spec
        tag = tags_store.get(name)
        if tag is None:
            tag = FinalizePosiViewNameTag(canvas)
            _wire_finalize_name_tag(canvas, tag)
            tags_store[name] = tag
        tag.set_posiview_style(text, ldist, col)
        tag.setMapCenter(map_xy)

    def _refresh_finalize_canvases(self):
        for c in (self._turn, self._cal):
            if c is None:
                continue
            try:
                c.refresh()
            except Exception:
                pass

    def _dispose_marker(self, canvas, m):
        if m is None:
            return
        if hasattr(m, "removeFromCanvas") and callable(getattr(m, "removeFromCanvas")):
            _unwire_and_remove_position_marker(m)
            return
        try:
            sc = m.scene()
            if sc is not None:
                sc.removeItem(m)
        except Exception:
            pass

    def _ensure_vertex_marker(self, canvas, store: Dict[str, Any], name: str, idx: int) -> QgsVertexMarker:
        m = store.get(name)
        if m is not None and isinstance(m, QgsVertexMarker):
            return m
        if m is not None:
            self._dispose_marker(canvas, m)
        vm = QgsVertexMarker(canvas)
        vm.setIconType(_MARKER_ICONS[idx % len(_MARKER_ICONS)])
        r, g, b = _MARKER_COLORS[idx % len(_MARKER_COLORS)]
        vm.setColor(QColor(r, g, b))
        vm.setIconSize(16)
        vm.setPenWidth(3)
        try:
            vm.setZValue(240000.0)
        except Exception:
            pass
        try:
            vm.setToolTip(name)
        except Exception:
            pass
        store[name] = vm
        return vm

    def _ensure_canvas_marker(
        self, canvas, store: Dict[str, Any], name: str, mob, mi_idx: int
    ) -> Any:
        sig = _marker_signature(mob)
        existing = store.get(name)
        if existing is not None and getattr(existing, "_lookahead_sig", None) == sig:
            return existing
        if existing is not None:
            self._dispose_marker(canvas, existing)
            store.pop(name, None)

        params = _clone_marker_params(mob)

        # --- Direct SVG injection bypassing external marker clone path ---
        try:
            svg_path = params.get("svgPath") or params.get("SvgPath")
            if svg_path:
                try:
                    rsv = getattr(getattr(mob, "marker", None),
                                  "resolveSvgPath", None)
                    if callable(rsv):
                        svg_path = rsv(svg_path) or svg_path
                except Exception:
                    pass
                svg_path = str(svg_path).strip() or None
            shape_type = str(params.get("type", "")).upper()
            if not shape_type:
                shape_type = str(params.get("shapeType", "")).upper()

            if shape_type == "SVG" and svg_path and os.path.isfile(svg_path):
                l_m = 0.0
                w_m = 0.0
                try:
                    l_m = float(params.get("shapeLength",
                                params.get("length", 0)))
                    w_m = float(params.get(
                        "shapeWidth", params.get("width", 0)))
                except (ValueError, TypeError):
                    pass

                sm = LookaheadSvgMarker(
                    canvas, svg_path, length_m=l_m, width_m=w_m, size=params.get("size", 40))
                sm._lookahead_sig = sig
                try:
                    sm.setToolTip(getattr(mob, "name", name))
                except Exception:
                    pass
                store[name] = sm
                _wire_position_marker(canvas, sm)
                return sm
        except Exception as e:
            log.debug("LookaheadSvgMarker init failed: %s", e)

        # Do not clone external PositionMarker on non-primary canvases.
        # This avoids trail artifacts and renderer crashes.
        vm = self._ensure_vertex_marker(canvas, store, name, mi_idx)
        vm._lookahead_sig = sig
        return vm

    def _apply_position(self, pm, xy: QgsPointXY, mob):
        if isinstance(pm, LookaheadSvgMarker):
            pm.setCenter(xy)
            try:
                h = getattr(mob, "heading", None)
                if h is not None and float(h) > -9000.0:
                    pm.setHeading(float(h))
            except (TypeError, ValueError):
                pass
            return

        try:
            pm.setCenter(xy)
            pm.show()
        except Exception:
            log.debug("vertex setCenter failed", exc_info=True)

    def _tick(self):
        if not self._active:
            return
        pv = _resolve_posiview_plugin()
        if pv is None or not _posiview_tracking_enabled(pv):
            self._clear_markers()
            return

        try:
            mobiles = getattr(pv.project, "mobileItems", None) or {}
        except Exception:
            self._clear_markers()
            return

        # MobileItem.coordinates are in main iface.mapCanvas() CRS, not WGS84 (mob.crs is unset).
        pos_space = _position_crs_from_posiview_main_canvas(pv)

        active_names: List[Tuple[str, object]] = []
        for name, mob in mobiles.items():
            try:
                if not getattr(mob, "enabled", True):
                    continue

                # Ignore virtual compass markers from tracking plugin
                # (Finalize canvases already provide their own compass rose).
                n_lower = str(name).lower()
                if "compass" in n_lower or "rose" in n_lower:
                    continue
                try:
                    svg_path = str(
                        getattr(getattr(mob, "marker", None), "svgPath", "")).lower()
                    if "compass" in svg_path or "rose" in svg_path:
                        continue
                except Exception:
                    pass

                xy = getattr(mob, "coordinates", None)
                if xy is None:
                    continue
                # Ignore invalid GPS origin markers (0, 0) to avoid map artifacts.
                if abs(xy.x()) < 1e-6 and abs(xy.y()) < 1e-6:
                    continue
            except Exception:
                continue
            active_names.append((str(name), mob))

        names_set = {n for n, _ in active_names}

        for store, canvas, tags in (
            (self._markers_turn, self._turn, self._tags_turn),
            (self._markers_cal, self._cal, self._tags_cal),
        ):
            for n in list(store.keys()):
                if n not in names_set:
                    self._dispose_marker(canvas, store.pop(n, None))
            for n in list(tags.keys()):
                if n not in names_set:
                    self._dispose_name_tag(tags.pop(n, None))

        for mi_idx, (name, mob) in enumerate(active_names):
            try:
                src_xy = getattr(mob, "coordinates", None)
            except Exception:
                continue
            if src_xy is None:
                continue

            for store, canvas, tags_store in (
                (self._markers_turn, self._turn, self._tags_turn),
                (self._markers_cal, self._cal, self._tags_cal),
            ):
                if canvas is None:
                    continue

                xy = _transform_point_to_canvas(canvas, mob, src_xy, pos_space)
                if xy is None:
                    pm = store.get(name)
                    if pm:
                        if isinstance(pm, LookaheadSvgMarker):
                            pm.setCenter(None)
                        elif hasattr(pm, "hide"):
                            pm.hide()
                    self._ensure_name_tag(canvas, tags_store, name, None, None)
                    continue
                pm = self._ensure_canvas_marker(
                    canvas, store, name, mob, mi_idx)
                self._apply_position(pm, xy, mob)
                self._ensure_name_tag(canvas, tags_store, name, xy, mob)

        self._refresh_finalize_canvases()
