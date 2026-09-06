import math
import logging
from collections import defaultdict
from qgis.core import QgsTask, QgsGeometry, QgsPointXY, QgsMessageLog, Qgis
from .qt_compat import swallow_exc, QGS_TASK_CAN_CANCEL as _QGS_TASK_CAN_CANCEL

class GenerateLinesTask(QgsTask):
    """
    Background task for generating survey lines and run-ins/run-outs.
    """
    def __init__(self, description, on_finished_callback, lines_to_process_info, by_line_points, custom_line_sp_bounds, src_idx, max_run_in_length, max_run_out_length, center_source_tokens):
        super().__init__(description, _QGS_TASK_CAN_CANCEL)
        self.lines_to_process_info = lines_to_process_info
        self.by_line_points = by_line_points
        self.custom_line_sp_bounds = custom_line_sp_bounds
        self.src_idx = src_idx
        self.max_run_in_length = max_run_in_length
        self.max_run_out_length = max_run_out_length
        self.center_source_tokens = center_source_tokens
        self.on_finished_callback = on_finished_callback
        
        self.generated_lines_data = []
        self.generated_runins_data = []
        self.exception = None

    def run(self):
        try:
            total_lines = len(self.lines_to_process_info)
            for i, info in enumerate(self.lines_to_process_info):
                if self.isCanceled():
                    return False
                
                self.setProgress((i / total_lines) * 100)
                
                line_id = info['line_id']
                base_ln = info['base_ln']
                
                rows = self.by_line_points.get(base_ln) or []
                custom_bounds = self.custom_line_sp_bounds.get(line_id)
                if custom_bounds:
                    min_sp, max_sp = custom_bounds
                    rows = [r for r in rows if min_sp <= r["sp"] <= max_sp]
                
                rows.sort(key=lambda r: r["sp"])
                if len(rows) < 2:
                    continue
                
                meta = self._centerline_geometry_meta_from_line_rows(rows, self.src_idx)
                if meta is None:
                    continue
                
                lowest_sp = meta["lowest_sp"]
                highest_sp = meta["highest_sp"]
                rep_low = meta["rep_low"]
                line_status = "To Be Acquired"
                line_heading = rep_low["heading"]
                lowest_sp_point = meta["line_start_xy"]
                highest_sp_point = meta["line_end_xy"]
                
                line_geometry = QgsGeometry.fromPolylineXY([lowest_sp_point, highest_sp_point])
                
                if line_geometry and not line_geometry.isNull():
                    self.generated_lines_data.append({
                        "geom": line_geometry,
                        "attrs": [
                            line_id,
                            line_status,
                            line_geometry.length(),
                            line_heading,
                            lowest_sp, lowest_sp_point.x(), lowest_sp_point.y(),
                            highest_sp, highest_sp_point.x(), highest_sp_point.y()
                        ]
                    })
                    
                    heading_value = None
                    if line_heading is not None:
                        try:
                            heading_value = float(line_heading)
                        except (ValueError, TypeError):
                            swallow_exc()
                    
                    if heading_value is not None and math.isfinite(heading_value):
                        rad = math.radians(heading_value)
                        vx = math.sin(rad)
                        vy = math.cos(rad)
                        
                        start_point = lowest_sp_point
                        if self.max_run_in_length > 0:
                            runin_start_point = QgsPointXY(start_point.x() - vx * self.max_run_in_length, start_point.y() - vy * self.max_run_in_length)
                            start_runin_geom = QgsGeometry.fromPolylineXY([runin_start_point, start_point])
                            if start_runin_geom and not start_runin_geom.isEmpty():
                                self.generated_runins_data.append({
                                    "geom": start_runin_geom,
                                    "attrs": [
                                        line_id, start_runin_geom.length(), "Start", "Low to High SP",
                                        runin_start_point.x(), runin_start_point.y(),
                                        start_point.x(), start_point.y()
                                    ]
                                })
                        
                        end_point = highest_sp_point
                        end_extent_m = self.max_run_out_length if self.max_run_out_length > 0 else self.max_run_in_length
                        if end_extent_m > 0:
                            runin_end_point = QgsPointXY(end_point.x() + vx * end_extent_m, end_point.y() + vy * end_extent_m)
                            end_runin_geom = QgsGeometry.fromPolylineXY([end_point, runin_end_point])
                            if end_runin_geom and not end_runin_geom.isEmpty():
                                self.generated_runins_data.append({
                                    "geom": end_runin_geom,
                                    "attrs": [
                                        line_id, end_runin_geom.length(), "End", "High to Low SP",
                                        end_point.x(), end_point.y(),
                                        runin_end_point.x(), runin_end_point.y()
                                    ]
                                })
            return True
        except Exception as e:
            self.exception = e
            return False

    def _centerline_geometry_meta_from_line_rows(self, rows, src_idx):
        sp_groups = defaultdict(list)
        for r in rows:
            sp_groups[r["sp"]].append(r)
        sorted_sps = sorted(sp_groups.keys())
        if len(sorted_sps) < 2: return None
        
        low_sp = sorted_sps[0]
        high_sp = sorted_sps[-1]
        
        rep_low = self._attr_rep_row_for_sp_group(sp_groups[low_sp], src_idx)
        rep_high = self._attr_rep_row_for_sp_group(sp_groups[high_sp], src_idx)
        if rep_low is None or rep_high is None: return None
        
        center_rows = []
        if src_idx >= 0:
            center_rows = [r for r in rows if self._is_center_source_position_value(r.get("_src"))]
            
        if len(center_rows) >= 2:
            c_sps = sorted(list(set(r["sp"] for r in center_rows)))
            pts = [self._xy_mean_xy([r for r in center_rows if r["sp"] == sp]) for sp in c_sps]
        else:
            pts = [self._xy_mean_xy(sp_groups[sp]) for sp in sorted_sps]
            
        if len(pts) < 2: return None
        n = len(pts)
        mean_x = sum(p.x() for p in pts) / n
        mean_y = sum(p.y() for p in pts) / n
        
        ixx = sum((p.x() - mean_x)**2 for p in pts)
        iyy = sum((p.y() - mean_y)**2 for p in pts)
        ixy = sum((p.x() - mean_x) * (p.y() - mean_y) for p in pts)
        if ixx == 0 and iyy == 0: return None
        
        angle = 0.5 * math.atan2(2 * ixy, ixx - iyy)
        ux = math.cos(angle)
        uy = math.sin(angle)
        
        dx = pts[-1].x() - pts[0].x()
        dy = pts[-1].y() - pts[0].y()
        if (ux * dx + uy * dy) < 0:
            ux, uy = -ux, -uy
            
        t_low, t_high = None, None
        for r in rows:
            t = (r["xy"].x() - mean_x) * ux + (r["xy"].y() - mean_y) * uy
            if t_low is None or t < t_low: t_low = t
            if t_high is None or t > t_high: t_high = t
            
        if t_low is None or t_high is None: return None
        return {
            "lowest_sp": low_sp, "highest_sp": high_sp,
            "rep_low": rep_low, "rep_high": rep_high,
            "line_start_xy": QgsPointXY(mean_x + t_low * ux, mean_y + t_low * uy),
            "line_end_xy": QgsPointXY(mean_x + t_high * ux, mean_y + t_high * uy)
        }

    def _attr_rep_row_for_sp_group(self, group_rows, src_idx):
        if not group_rows: return None
        if src_idx >= 0:
            for r in group_rows:
                if self._is_center_source_position_value(r.get("_src")): return r
        return group_rows[0]

    def _is_center_source_position_value(self, val):
        if val is None: return False
        t = str(val).strip().casefold().replace("-", "_").replace(" ", "_")
        if not t: return False
        if t in self.center_source_tokens: return True
        if t in ("port", "p", "starboard", "stbd", "sb", "ps", "stb"): return False
        if "center" in t or "centre" in t or "vessel" in t or "cntline" in t or "gun_center" in t: return True
        return False

    def _xy_mean_xy(self, group_rows):
        sx = sum(r["xy"].x() for r in group_rows) / len(group_rows)
        sy = sum(r["xy"].y() for r in group_rows) / len(group_rows)
        return QgsPointXY(sx, sy)

    def finished(self, result):
        if self.on_finished_callback:
            self.on_finished_callback(self.exception, self.generated_lines_data, self.generated_runins_data)
