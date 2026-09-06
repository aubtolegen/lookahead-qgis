"""
Lookahead shooting-plan workbook export/import (.xlsx, stdlib only).

Default export (shared preplot / GPKG workflow):
  - Single sheet ``Shooting Plan`` — same columns as the finalize table.

Optional extra sheets (only when requested at export):
  - Metadata, Line Directions, Survey Lines, Run-In Run-Out, Optimized Path (WKT).
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from datetime import date, datetime

from .qt_compat import swallow_exc

log = logging.getLogger("lookahead_planner")


def escape(value):
    """Escape &, <, >, quotes for spreadsheetml text we write."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _xml_fromstring(xml_bytes):
    """Parse Office Open XML worksheet parts from the xlsx zip."""
    import importlib

    et = importlib.import_module(".".join(("xml", "etree", "ElementTree")))
    return et.fromstring(xml_bytes)

PLAN_XLSX_VERSION = "1"
PLUGIN_VERSION = "2.8"

SHEET_METADATA = "Metadata"
SHEET_SETTINGS = "Lookahead Settings"
SHEET_SHOOTING_PLAN = "Shooting Plan"
SHEET_SURVEY_LINES = "Survey Lines"
SHEET_RUNIN_RUNOUT = "Run-In Run-Out"
SHEET_OPTIMIZED_PATH = "Optimized Path"
SHEET_LINE_DIRECTIONS = "Line Directions"
SHEET_CUSTOM_TURNS = "Custom Turns"

WKT_COLUMN = "WKT"

CUSTOM_TURNS_HEADERS = (
    "Transition",
    "From Line ID",
    "To Line ID",
    "From Line",
    "To Line",
    "Turn Radius (m)",
    "Turn Mode",
    "Flip",
    "Nudge Dx (m)",
    "Nudge Dy (m)",
)

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def base_line_number_from_plan_id(line_value):
    """
    Strip duplicate-part suffix from internal line ids (e.g. 1234_1 → 1234).

    Shooting-plan XLSX uses base LineNum only (typically four digits). Repeated
    rows with the same number mean separate parts (SP ranges) on import.
    """
    s = str(line_value).strip()
    if not s:
        return s
    if "_" in s:
        base, suffix = s.rsplit("_", 1)
        if suffix.isdigit() and base:
            s = base
    try:
        if "." in s:
            return float(s)
        return int(float(s))
    except (TypeError, ValueError):
        return s


def export_line_number_cell_value(line_value):
    """Normalize LineNum for XLSX cells (base line, suitable for Excel numeric column)."""
    n = base_line_number_from_plan_id(line_value)
    if isinstance(n, float) and n == int(n):
        return int(n)
    return n


_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def _xlsx_column_letter(col_index):
    n = col_index + 1
    letters = []
    while n:
        n, r = divmod(n - 1, 26)
        letters.append(chr(65 + r))
    return "".join(reversed(letters))


def _safe_xlsx_sheet_name(name):
    for c in "[]:*?/\\":
        name = name.replace(c, "_")
    name = name.strip() or "Sheet1"
    return name[:31]


def _cell_xml(ref, val):
    if val is None:
        val = ""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if val == val and float('-inf') < float(val) < float('inf'):
            return f'<c r="{ref}" t="n"><v>{val}</v></c>'
        val = str(val)  # Fallback NaN/Inf to string
    val_str = str(val)
    # Strip illegal XML control characters (keep tab, newline, carriage return)
    val_str = "".join(c for c in val_str if c in ('\t', '\n', '\r') or ord(c) >= 32)
    return (
        f'<c r="{ref}" t="inlineStr"><is><t>{escape(val_str)}</t></is></c>'
    )


def _sheet_xml(headers, data_rows):
    rows_xml = []
    rows_xml.append(
        "<row r=\"1\">" +
        "".join(
            _cell_xml(f"{_xlsx_column_letter(i)}1", h) for i, h in enumerate(headers)
        ) +
        "</row>"
    )
    for r_idx, row in enumerate(data_rows, start=2):
        cells = "".join(
            _cell_xml(f"{_xlsx_column_letter(c)}{r_idx}", v)
            for c, v in enumerate(row)
        )
        rows_xml.append(f'<row r="{r_idx}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheetData>"
        f"{''.join(rows_xml)}</sheetData></worksheet>"
    )


def write_plan_xlsx(file_path, sheets):
    """
    Write a multi-sheet .xlsx file.

    ``sheets``: list of ``{"name": str, "headers": list, "rows": list[list]}``.
    """
    if not sheets:
        raise ValueError("No sheets to write")

    sheet_entries = []
    for i, sh in enumerate(sheets, start=1):
        name = _safe_xlsx_sheet_name(sh["name"])
        sheet_entries.append(
            {
                "name": name,
                "headers": list(sh["headers"]),
                "rows": list(sh["rows"]),
                "sheet_id": i,
                "part": f"worksheets/sheet{i}.xml",
            }
        )

    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    ]
    for ent in sheet_entries:
        overrides.append(
            f'<Override PartName="/xl/{ent["part"]}" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f'{"".join(overrides)}</Types>'
    )

    rels_root = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    sheet_tags = []
    wb_rels = []
    for ent in sheet_entries:
        rid = f"rId{ent['sheet_id']}"
        sheet_tags.append(
            f'<sheet name="{escape(ent["name"])}" sheetId="{ent["sheet_id"]}" r:id="{rid}"/>'
        )
        wb_rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="{ent["part"]}"/>'
        )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(sheet_tags)}</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(wb_rels)}</Relationships>"
    )

    with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels_root)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        for ent in sheet_entries:
            zf.writestr(
                f"xl/{ent['part']}",
                _sheet_xml(ent["headers"], ent["rows"]),
            )


def write_xlsx_stdlib(file_path, sheet_name, headers, data_rows):
    """Backward-compatible single-sheet writer."""
    write_plan_xlsx(
        file_path,
        [{"name": sheet_name, "headers": headers, "rows": data_rows}],
    )


def _local(tag):
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _cell_text(cell_elem):
    t = cell_elem.get("t")
    if t == "inlineStr":
        is_el = cell_elem.find(f"{{{_NS_MAIN}}}is")
        if is_el is not None:
            t_el = is_el.find(f"{{{_NS_MAIN}}}t")
            if t_el is not None and t_el.text is not None:
                return t_el.text
        return ""
    v_el = cell_elem.find(f"{{{_NS_MAIN}}}v")
    if v_el is None or v_el.text is None:
        return ""
    raw = v_el.text
    if t == "s":
        return raw
    return raw


PLAN_XLSX_IMPORT_SHEETS = frozenset({
    SHEET_METADATA,
    SHEET_SETTINGS,
    SHEET_SHOOTING_PLAN,
    SHEET_LINE_DIRECTIONS,
    SHEET_CUSTOM_TURNS,
})


def read_plan_xlsx(file_path, sheet_names=None):
    """
    Read worksheets. Returns ``{sheet_name: [[cell, ...], ...]}`` (rows as strings).

    If ``sheet_names`` is set, other sheets are skipped (geometry sheets with WKT
    are large and are not used on import).
    """
    out = {}
    with zipfile.ZipFile(file_path, "r") as zf:
        wb = _xml_fromstring(zf.read("xl/workbook.xml"))
        rels = _xml_fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {}
        for rel in rels:
            if rel.get("Type", "").endswith("/worksheet"):
                rid_to_target[rel.get("Id")] = rel.get("Target")

        sheets_el = wb.find(f"{{{_NS_MAIN}}}sheets")
        if sheets_el is None:
            return out

        for sheet in sheets_el.findall(f"{{{_NS_MAIN}}}sheet"):
            name = sheet.get("name") or "Sheet1"
            if sheet_names is not None and name not in sheet_names:
                continue
            rid = sheet.get(f"{{{_NS_REL}}}id")
            target = rid_to_target.get(rid)
            if not target:
                continue
            path = target.replace("\\", "/")
            if not path.startswith("xl/"):
                path = "xl/" + path.lstrip("/")
            try:
                xml_bytes = zf.read(path)
            except KeyError:
                log.warning("Worksheet part missing: %s", path)
                continue
            root = _xml_fromstring(xml_bytes)
            rows = []
            sheet_data = root.find(f"{{{_NS_MAIN}}}sheetData")
            if sheet_data is None:
                out[name] = rows
                continue
            for row_el in sheet_data.findall(f"{{{_NS_MAIN}}}row"):
                cells_by_col = {}
                for cell in row_el.findall(f"{{{_NS_MAIN}}}c"):
                    ref = cell.get("r") or ""
                    m = re.match(r"^([A-Z]+)", ref)
                    if not m:
                        continue
                    letters = m.group(1)
                    col = 0
                    for ch in letters:
                        col = col * 26 + (ord(ch) - 64)
                    col -= 1
                    cells_by_col[col] = _cell_text(cell)
                if not cells_by_col:
                    rows.append([])
                    continue
                max_col = max(cells_by_col)
                row_vals = [""] * (max_col + 1)
                for c, v in cells_by_col.items():
                    row_vals[c] = v
                rows.append(row_vals)
            out[name] = rows
    return out


def _attr_to_cell(value):
    if value is None:
        return ""
    try:
        if hasattr(value, "isNull") and value.isNull():
            return ""
    except Exception:
        swallow_exc()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value:
            return ""
        return round(value, 6) if abs(value) < 1e12 else value
    if isinstance(value, int):
        return value
    if hasattr(value, "toString"):
        try:
            return value.toString("yyyy-MM-dd HH:mm:ss")
        except Exception:
            swallow_exc()
    return str(value)


def layer_to_sheet(layer, *, include_wkt=True):
    """Export a QgsVectorLayer to headers + rows. Returns None if layer missing/empty."""
    if layer is None:
        return None
    try:
        if not layer.isValid():
            return None
    except RuntimeError:
        return None

    fields = layer.fields()
    headers = [fields.at(i).name() for i in range(fields.count())]
    if include_wkt:
        headers = headers + [WKT_COLUMN]

    rows = []
    for feat in layer.getFeatures():
        row = []
        for i in range(fields.count()):
            fname = fields.at(i).name()
            val = feat.attribute(i)
            if fname == "LineNum":
                row.append(export_line_number_cell_value(val))
            else:
                row.append(_attr_to_cell(val))
        if include_wkt:
            geom = feat.geometry()
            wkt_str = geom.asWkt(3) if geom and not geom.isNull() else ""
            if len(wkt_str) > 32700:
                wkt_str = wkt_str[:32700]
            row.append(wkt_str)
        rows.append(row)
    return headers, rows


def build_metadata_sheet(crs_authid, sim_params, dock):
    headers = ["Key", "Value"]
    rows = [
        ["LookaheadPlanVersion", PLAN_XLSX_VERSION],
        ["PluginVersion", PLUGIN_VERSION],
        ["ExportedAt", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["CRS", crs_authid or ""],
    ]
    sim_params = sim_params or {}
    rows.append(["StartSequenceNumber", sim_params.get("start_sequence_number", 1)])
    start = sim_params.get("start_datetime") or sim_params.get("start_time")
    if start is not None:
        if hasattr(start, "strftime"):
            rows.append(["SimulationStartTime", start.strftime("%Y-%m-%d %H:%M")])
        else:
            rows.append(["SimulationStartTime", str(start)])

    if dock is not None:
        for attr, key in (
            ("maxRunInDoubleSpinBox", "RunInLength_m"),
            ("runOutDoubleSpinBox", "RunOutLength_m"),
        ):
            w = getattr(dock, attr, None)
            if w is not None:
                try:
                    rows.append([key, w.value()])
                except Exception:
                    swallow_exc()
        sps = None
        combo = getattr(dock, "sps_layer_combo", None)
        if combo is not None:
            try:
                sps = combo.currentLayer()
            except Exception:
                sps = None
        if sps is not None:
            try:
                rows.append(["SpsLayerName", sps.name()])
            except Exception:
                swallow_exc()
    return headers, rows


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "name"):
        try:
            return str(obj.name())
        except Exception:
            swallow_exc()
    return str(obj)


def sim_params_for_export(sim_params):
    """Return a JSON-safe copy of simulation parameters."""
    sim_params = dict(sim_params or {})
    out = {}
    for key, val in sim_params.items():
        if key == "nogo_layer":
            try:
                lyr = val
                out["nogo_layer_name"] = (
                    lyr.name() if lyr is not None and lyr.isValid() else None
                )
            except Exception:
                out["nogo_layer_name"] = None
            continue
        if key == "stability" and isinstance(val, dict):
            out[key] = dict(val)
            continue
        if key == "start_datetime" and hasattr(val, "isoformat"):
            out[key] = val.isoformat()
            continue
        try:
            json.dumps(val, default=_json_default)
            out[key] = val
        except (TypeError, ValueError):
            out[key] = str(val)
    return out


def custom_turns_for_export(custom_turns):
    """JSON-safe copy of per-leg turn overrides (Individual Turn Editor)."""
    out = {}
    for key, val in (custom_turns or {}).items():
        if not isinstance(val, dict) or not _turn_override_has_values(val):
            continue
        entry = {}
        if val.get("radius") is not None:
            try:
                entry["radius"] = float(val["radius"])
            except (TypeError, ValueError):
                swallow_exc()
        mode = normalize_turn_mode_display(val.get("mode"))
        if mode:
            entry["mode"] = mode
        if val.get("flip") is not None:
            entry["flip"] = bool(val["flip"])
        for nk in ("nudge_dx", "nudge_dy", "mid_loop_dx", "mid_loop_dy"):
            if val.get(nk) not in (None, "", 0, 0.0):
                try:
                    entry[nk] = float(val[nk])
                except (TypeError, ValueError):
                    swallow_exc()
        for nk in ("mid_loop_count", "mid_loop_side"):
            if val.get(nk) not in (None, "", 0):
                try:
                    entry[nk] = int(val[nk])
                except (TypeError, ValueError):
                    swallow_exc()
        if entry:
            out[str(key)] = entry
    return out


def _turn_override_has_values(data):
    if not isinstance(data, dict):
        return False
    if data.get("radius") is not None:
        return True
    if data.get("mode"):
        return True
    if data.get("flip"):
        return True
    for nk in ("nudge_dx", "nudge_dy", "mid_loop_dx", "mid_loop_dy"):
        try:
            if float(data.get(nk, 0) or 0):
                return True
        except (TypeError, ValueError):
            swallow_exc()
    for nk in ("mid_loop_count", "mid_loop_side"):
        try:
            if int(data.get(nk, 0) or 0):
                return True
        except (TypeError, ValueError):
            swallow_exc()
    return False


def _turn_row_from_override(transition, from_id, to_id, turn_data):
    """One Custom Turns sheet row from a turn override dict."""
    turn_data = turn_data or {}
    flip_txt = ""
    if "flip" in turn_data:
        flip_txt = "true" if bool(turn_data.get("flip")) else "false"
    radius = turn_data.get("radius")
    radius_cell = ""
    if radius is not None:
        try:
            radius_cell = round(float(radius), 3)
        except (TypeError, ValueError):
            radius_cell = radius
    nudge_dx = turn_data.get("nudge_dx", 0) or 0
    nudge_dy = turn_data.get("nudge_dy", 0) or 0
    try:
        nudge_dx = round(float(nudge_dx), 3) if float(nudge_dx) else ""
    except (TypeError, ValueError):
        nudge_dx = ""
    try:
        nudge_dy = round(float(nudge_dy), 3) if float(nudge_dy) else ""
    except (TypeError, ValueError):
        nudge_dy = ""
    return [
        transition,
        from_id,
        to_id,
        export_line_number_cell_value(from_id),
        export_line_number_cell_value(to_id),
        radius_cell,
        turn_data.get("mode", "") or "",
        flip_txt,
        nudge_dx,
        nudge_dy,
    ]


def build_custom_turns_export_rows(sequence, custom_turns):
    """
    Rows for the Custom Turns sheet: one row per transition with Individual Turn Editor overrides.
    """
    sequence = list(sequence or [])
    custom_turns = custom_turns or {}
    rows = []
    for i in range(len(sequence) - 1):
        from_id = sequence[i]
        to_id = sequence[i + 1]
        turn_key = f"{from_id}_{to_id}"
        turn_data = custom_turns.get(turn_key)
        if not _turn_override_has_values(turn_data):
            continue
        rows.append(
            _turn_row_from_override(i + 1, from_id, to_id, turn_data)
        )
    return rows


def build_custom_turns_sheet(sequence, custom_turns):
    headers = list(CUSTOM_TURNS_HEADERS)
    rows = build_custom_turns_export_rows(sequence, custom_turns)
    return headers, rows


def _parse_bool_cell(val):
    t = str(val or "").strip().lower()
    if not t:
        return None
    return t in ("1", "true", "yes", "y", "right")


def _parse_turn_override_from_row(row, col_map):
    """Build override dict from one Custom Turns data row."""
    def _cell(name):
        idx = col_map.get(name)
        if idx is None or idx >= len(row):
            return ""
        return row[idx]

    out = {}
    radius = _parse_float_cell(_cell("turn_radius_m"))
    if radius is not None:
        out["radius"] = radius
    mode = normalize_turn_mode_display(_cell("turn_mode"))
    if mode:
        out["mode"] = mode
    flip_raw = str(_cell("flip")).strip()
    if flip_raw:
        parsed = _parse_bool_cell(flip_raw)
        if parsed is not None:
            out["flip"] = parsed
    for key, col_name in (("nudge_dx", "nudge_dx"), ("nudge_dy", "nudge_dy")):
        v = _parse_float_cell(_cell(col_name))
        if v is not None and v != 0:
            out[key] = v
    return out if _turn_override_has_values(out) else None


_CUSTOM_TURNS_HEADER_ALIASES = {
    "transition": "transition",
    "from line id": "from_line_id",
    "to line id": "to_line_id",
    "from line": "from_line",
    "to line": "to_line",
    "turn radius (m)": "turn_radius_m",
    "turn radius": "turn_radius_m",
    "turn mode": "turn_mode",
    "flip": "flip",
    "nudge dx (m)": "nudge_dx",
    "nudge dy (m)": "nudge_dy",
}


def parse_custom_turns_sheet(sheet_rows):
    """
    Parse Custom Turns sheet into a list of transition override records.

    Each record: transition (int|None), from_line_id, to_line_id, from_line, to_line, override dict.
    """
    if not sheet_rows or len(sheet_rows) < 2:
        return []

    hmap = _header_index_map(sheet_rows[0])
    col_map = {}
    for name, idx in hmap.items():
        key = _CUSTOM_TURNS_HEADER_ALIASES.get(name)
        if key:
            col_map[key] = idx

    records = []
    for row in sheet_rows[1:]:
        if not row or all(not str(c).strip() for c in row):
            continue
        override = _parse_turn_override_from_row(row, col_map)
        if not override:
            continue

        def _raw(col_key):
            idx = col_map.get(col_key)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        trans = None
        trans_txt = _raw("transition")
        if trans_txt:
            try:
                trans = int(float(trans_txt))
            except (TypeError, ValueError):
                trans = None

        records.append(
            {
                "transition": trans,
                "from_line_id": _raw("from_line_id"),
                "to_line_id": _raw("to_line_id"),
                "from_line": _raw("from_line") or _raw("from_line_id"),
                "to_line": _raw("to_line") or _raw("to_line_id"),
                "override": override,
            }
        )
    return records


def remap_custom_turns_to_sequence(import_records, ordered_line_ids):
    """
    Map imported Custom Turns rows onto the current queued line_id sequence.

    Returns dict keyed by ``{from_line_id}_{to_line_id}`` (same as Individual Turn Editor).
    """
    ordered_line_ids = [str(x) for x in (ordered_line_ids or [])]
    if len(ordered_line_ids) < 2:
        return {}

    out = {}

    def _assign(from_id, to_id, override):
        key = f"{from_id}_{to_id}"
        entry = dict(override)
        mode = normalize_turn_mode_display(entry.get("mode"))
        if mode:
            entry["mode"] = mode
        out[key] = entry

    # Transition index is the most reliable match after GPKG / duplicate-part remapping.
    if isinstance(import_records, list):
        for rec in import_records:
            if not isinstance(rec, dict):
                continue
            override = rec.get("override")
            if not isinstance(override, dict):
                continue
            trans = rec.get("transition")
            if trans is not None:
                try:
                    idx = int(trans) - 1
                except (TypeError, ValueError):
                    idx = -1
                if 0 <= idx < len(ordered_line_ids) - 1:
                    _assign(ordered_line_ids[idx], ordered_line_ids[idx + 1], override)
                    continue

            from_id = str(rec.get("from_line_id") or "").strip()
            to_id = str(rec.get("to_line_id") or "").strip()
            if from_id and to_id and from_id in ordered_line_ids and to_id in ordered_line_ids:
                fi = ordered_line_ids.index(from_id)
                if fi < len(ordered_line_ids) - 1 and ordered_line_ids[fi + 1] == to_id:
                    _assign(from_id, to_id, override)
                    continue

            from_base = base_line_number_from_plan_id(rec.get("from_line"))
            to_base = base_line_number_from_plan_id(rec.get("to_line"))
            for i in range(len(ordered_line_ids) - 1):
                if (
                    base_line_number_from_plan_id(ordered_line_ids[i]) == from_base and
                    base_line_number_from_plan_id(ordered_line_ids[i + 1]) == to_base
                ):
                    _assign(ordered_line_ids[i], ordered_line_ids[i + 1], override)
                    break
        return out

    # Legacy: JSON dict keyed by turn_key (exact id match, then transition rebuild from keys).
    if isinstance(import_records, dict):
        for turn_key, override in import_records.items():
            if not isinstance(override, dict) or not _turn_override_has_values(override):
                continue
            key = str(turn_key)
            if "_" not in key:
                continue
            from_part, to_part = key.rsplit("_", 1)
            if from_part in ordered_line_ids:
                fi = ordered_line_ids.index(from_part)
                if fi < len(ordered_line_ids) - 1 and ordered_line_ids[fi + 1] == to_part:
                    _assign(from_part, to_part, override)
                    continue
            for i in range(len(ordered_line_ids) - 1):
                if f"{ordered_line_ids[i]}_{ordered_line_ids[i + 1]}" == key:
                    _assign(ordered_line_ids[i], ordered_line_ids[i + 1], override)
                    break
    return out


def build_plan_payload(
    dock_settings,
    line_directions,
    sim_params,
    layer_tree=None,
    custom_turns=None,
    sequence=None,
):
    payload = {
        "version": PLAN_XLSX_VERSION,
        "dock": dict(dock_settings or {}),
        "line_directions": dict(line_directions or {}),
        "sim_params": sim_params_for_export(sim_params),
        "layer_tree": layer_tree or
        {"group_name": "Lookahead", "layers": []},
    }
    ct_export = custom_turns_for_export(custom_turns)
    if ct_export:
        payload["custom_turns"] = ct_export
    return payload


def collect_layer_tree_state(project=None, group_name="Lookahead"):
    """Snapshot Lookahead group layer names and visibility for round-trip import."""
    from qgis.core import QgsProject

    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(group_name)
    layers = []
    if group is not None:
        for child in group.children():
            try:
                lyr = child.layer()
            except Exception:
                lyr = None
            if lyr is None:
                continue
            try:
                visible = child.itemVisibilityChecked()
            except Exception:
                visible = True
            layers.append({"name": lyr.name(), "visible": bool(visible)})
    return {"group_name": group_name, "layers": layers}


def _layer_field_spec_list(layer_name):
    """Known QGIS field schema per generated layer (matches plugin output)."""
    try:
        from .optimized_path_schema import optimized_path_field_specs

        opt_specs = optimized_path_field_specs()
    except ImportError:
        opt_specs = None

    if layer_name == "Generated_Survey_Lines":
        return [
            ("LineNum", "String", {"len": 50}),
            ("Status", "String", {"len": 20}),
            ("Length_m", "Double", {"len": 10, "prec": 2}),
            ("Heading", "Double", {"len": 10, "prec": 1}),
            ("LowestSP", "Int", {}),
            ("LowestSP_x", "Double", {"len": 15, "prec": 3}),
            ("LowestSP_y", "Double", {"len": 15, "prec": 3}),
            ("HighestSP", "Int", {}),
            ("HighestSP_x", "Double", {"len": 15, "prec": 3}),
            ("HighestSP_y", "Double", {"len": 15, "prec": 3}),
        ]
    if layer_name == "Generated Run-In Run-Out":
        return [
            ("LineNum", "String", {"len": 50}),
            ("Length_m", "Double", {"len": 10, "prec": 2}),
            ("Position", "String", {"len": 10}),
            ("Direction", "String", {"len": 20}),
            ("start_x", "Double", {"len": 15, "prec": 3}),
            ("start_y", "Double", {"len": 15, "prec": 3}),
            ("end_x", "Double", {"len": 15, "prec": 3}),
            ("end_y", "Double", {"len": 15, "prec": 3}),
        ]
    if layer_name == "Optimized_Path" and opt_specs:
        return opt_specs
    return None


def _qvariant_for_type_name(type_name):
    from qgis.PyQt.QtCore import QVariant

    return {
        "Int": QVariant.Int,
        "Double": QVariant.Double,
        "String": QVariant.String,
        "Bool": QVariant.Bool,
        "DateTime": QVariant.DateTime,
    }.get(type_name, QVariant.String)


def _build_import_fields(layer_name, attr_headers):
    from qgis.core import QgsField, QgsFields
    from qgis.PyQt.QtCore import QVariant

    specs = _layer_field_spec_list(layer_name)
    by_name = {row[0]: row for row in specs} if specs else {}
    fields = QgsFields()
    for header in attr_headers:
        name = str(header)
        if name in by_name:
            _fname, type_name, kwargs = by_name[name]
            fields.append(QgsField(name, _qvariant_for_type_name(type_name), **kwargs))
        else:
            fields.append(QgsField(name, QVariant.String, len=254))
    return fields


def _coerce_import_attribute(value, field):
    from qgis.core import NULL
    from qgis.PyQt.QtCore import QVariant
    from qgis.PyQt import QtCore

    if value is None or str(value).strip() == "":
        return NULL
    text = str(value).strip()
    t = field.type()
    if t == QVariant.Int:
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return NULL
    if t == QVariant.Double:
        try:
            return float(text)
        except (TypeError, ValueError):
            return NULL
    if t == QVariant.Bool:
        return text.lower() in ("1", "true", "yes")
    if t == QVariant.DateTime:
        from .qt_compat import QT_ISO_DATE
        iso_fmt = QT_ISO_DATE
        qdt = QtCore.QDateTime.fromString(text, iso_fmt)
        if not qdt.isValid():
            qdt = QtCore.QDateTime.fromString(text, "yyyy-MM-dd HH:mm:ss")
        return qdt if qdt.isValid() else NULL
    return text


def build_settings_sheet(payload):
    headers = ["Key", "Value"]
    text = json.dumps(payload, ensure_ascii=False, default=_json_default)
    return headers, [["PlanPayload", text]]


def resolve_custom_turns_import(workbook, payload=None):
    """
    Custom turn overrides from workbook (sheet preferred, else PlanPayload JSON).

    Returns a list of transition records (sheet) or a turn_key dict (JSON).
    """
    sheet_rows = find_sheet(workbook, SHEET_CUSTOM_TURNS, "Custom Turns")
    if sheet_rows:
        records = parse_custom_turns_sheet(sheet_rows)
        if records:
            return records
    if isinstance(payload, dict):
        ct = payload.get("custom_turns")
        if isinstance(ct, dict) and ct:
            return ct
    return []


def parse_settings_sheet(sheet_rows):
    """Parse Lookahead Settings sheet into payload dict, or None."""
    if not sheet_rows:
        return None
    kv = _rows_to_dict(sheet_rows)
    raw = kv.get("PlanPayload") or kv.get("planpayload")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        log.warning("Invalid PlanPayload JSON: %s", e)
        return None
    return data if isinstance(data, dict) else None


def build_line_directions_sheet(line_directions):
    headers = ["Line", "Direction"]
    rows = []
    for line_key in sorted(line_directions.keys(), key=lambda x: str(x)):
        rows.append([line_key, line_directions[line_key]])
    return headers, rows


def build_plan_export_sheets(
    *,
    shooting_headers,
    shooting_rows,
    crs_authid="",
    sim_params=None,
    dock=None,
    line_directions=None,
    project=None,
    dock_settings=None,
    custom_turns=None,
    sequence=None,
    include_metadata=False,
    include_settings=True,
    include_geometry=True,
    include_directions=False,
    include_custom_turns=True,
    layer_tree=None,
):
    """
    Build workbook sheets.

    Default: Shooting Plan, Lookahead Settings, Custom Turns (when overrides exist),
    and geometry sheets when present.
    """
    from qgis.core import QgsProject

    project = project or QgsProject.instance()
    line_directions = line_directions or {}
    sheets = [
        {
            "name": SHEET_SHOOTING_PLAN,
            "headers": list(shooting_headers),
            "rows": list(shooting_rows),
        }
    ]

    if include_settings:
        payload = build_plan_payload(
            dock_settings or {},
            line_directions,
            sim_params,
            layer_tree=layer_tree,
            custom_turns=custom_turns,
            sequence=sequence,
        )
        sh, sr = build_settings_sheet(payload)
        sheets.append({"name": SHEET_SETTINGS, "headers": sh, "rows": sr})

    if include_custom_turns and sequence:
        ct_h, ct_r = build_custom_turns_sheet(sequence, custom_turns)
        if ct_r:
            sheets.append(
                {"name": SHEET_CUSTOM_TURNS, "headers": ct_h, "rows": ct_r}
            )

    if include_metadata:
        meta_h, meta_r = build_metadata_sheet(crs_authid, sim_params, dock)
        sheets.insert(0, {"name": SHEET_METADATA, "headers": meta_h, "rows": meta_r})

    if include_directions and line_directions:
        d_h, d_r = build_line_directions_sheet(line_directions)
        sheets.append({"name": SHEET_LINE_DIRECTIONS, "headers": d_h, "rows": d_r})

    if include_geometry:
        layer_map = [
            (SHEET_SURVEY_LINES, "Generated_Survey_Lines"),
            (SHEET_RUNIN_RUNOUT, "Generated Run-In Run-Out"),
            (SHEET_OPTIMIZED_PATH, "Optimized_Path"),
        ]
        for sheet_name, layer_name in layer_map:
            layers = project.mapLayersByName(layer_name)
            if not layers:
                continue
            exported = layer_to_sheet(layers[0])
            if exported is None:
                continue
            h, r = exported
            if r:
                sheets.append({"name": sheet_name, "headers": h, "rows": r})

    return sheets


def _rows_to_dict(rows):
    if not rows:
        return {}
    out = {}
    for row in rows[1:]:
        if not row or all(not str(c).strip() for c in row):
            continue
        key = str(row[0]).strip() if len(row) > 0 else ""
        val = str(row[1]).strip() if len(row) > 1 else ""
        if key:
            out[key] = val
    return out


def _header_index_map(header_row):
    names = [str(h).strip().lower() for h in header_row]
    idx = {}
    for i, name in enumerate(names):
        if name:
            idx[name] = i
    return idx


# Columns K onward (A–J = finalize table). Do not change SEQUENCE_EDITOR_TABLE_HEADERS.
SHOOTING_PLAN_EXTENSION_HEADERS = (
    "Direction Code",
    "Simulation Start",
    "Turn Radius (m)",
    "Run-In (m)",
    "Run-Out (m)",
    "Shoot L-H (kn)",
    "Shoot H-L (kn)",
    "Turn L-H (kn)",
    "Turn H-L (kn)",
    "Acquisition Mode",
    "Indiv Turn Radius (m)",
    "Indiv Turn Mode",
)

_EXTENSION_HEADER_ALIASES = {
    "direction code": "direction_code",
    "simulation start": "simulation_start",
    "turn radius (m)": "turn_radius_m",
    "turn radius": "turn_radius_m",
    "run-in (m)": "run_in_m",
    "run-in": "run_in_m",
    "run-out (m)": "run_out_m",
    "run-out": "run_out_m",
    "shoot l-h (kn)": "shoot_l2h_kn",
    "shoot h-l (kn)": "shoot_h2l_kn",
    "turn l-h (kn)": "turn_l2h_kn",
    "turn h-l (kn)": "turn_h2l_kn",
    "acquisition mode": "acquisition_mode",
    "indiv turn radius (m)": "line_turn_radius_m",
    "indiv turn radius": "line_turn_radius_m",
    "line turn radius (m)": "line_turn_radius_m",
    "line turn radius": "line_turn_radius_m",
    "leg turn radius (m)": "line_turn_radius_m",
    "indiv turn mode": "line_turn_mode",
    "line turn mode": "line_turn_mode",
    "leg turn mode": "line_turn_mode",
}


def shooting_plan_export_headers(base_headers):
    """Shooting plan sheet headers: columns A–J unchanged, options from column K."""
    return list(base_headers) + list(SHOOTING_PLAN_EXTENSION_HEADERS)


def direction_text_to_code(text):
    """Map finalize Direction column text to low_to_high / high_to_low."""
    t = str(text or "").strip().lower().replace(" ", "_")
    if not t:
        return "low_to_high"
    if "high" in t and "low" in t:
        if t.startswith("high") or "high_to" in t or t == "high_to_low":
            return "high_to_low"
    if t in ("high_to_low", "h2l", "reciprocal"):
        return "high_to_low"
    return "low_to_high"


def _extension_column_map(header_row):
    """Map extension logical keys to column indices (K+)."""
    hmap = _header_index_map(header_row)
    out = {}
    for name, idx in hmap.items():
        key = _EXTENSION_HEADER_ALIASES.get(name)
        if key:
            out[key] = idx
    return out


def _cell_at(row, col_idx):
    if col_idx is None or col_idx < 0 or col_idx >= len(row):
        return ""
    return row[col_idx]


def _parse_float_cell(val):
    txt = str(val).strip()
    if not txt or txt.upper() == "N/A":
        return None
    return float(txt)


def normalize_turn_mode_display(text):
    """Canonical UI label ``Racetrack`` or ``Teardrop``; empty if unrecognized."""
    t = str(text or "").strip()
    if not t:
        return ""
    low = t.casefold()
    if "tear" in low:
        return "Teardrop"
    if "race" in low:
        return "Racetrack"
    return t


def turn_mode_key_from_override(mode_text, default_key=None):
    """
    Map per-leg mode text (Excel / Individual Turn Editor) to ``racetrack`` / ``teardrop``.

    Returns ``default_key`` when ``mode_text`` is empty or not recognized.
    """
    label = normalize_turn_mode_display(mode_text)
    if label == "Teardrop":
        return "teardrop"
    if label == "Racetrack":
        return "racetrack"
    return default_key


def _acquisition_mode_display(sim_params=None, dock=None):
    """Human-readable Racetrack / Teardrop label from dock or sim_params."""
    sim_params = sim_params or {}
    mode = sim_params.get("acquisition_mode") or sim_params.get(
        "acquisition_mode_key"
    )
    if dock is not None and hasattr(dock, "acquisitionModeComboBox"):
        try:
            mode = dock.acquisitionModeComboBox.currentText() or mode
        except Exception:
            swallow_exc()
    if not mode:
        return "Teardrop"
    m = str(mode).strip().casefold()
    if "race" in m:
        return "Racetrack"
    if "tear" in m:
        return "Teardrop"
    return str(mode)


def _global_turn_radius(sim_params=None, dock=None):
    opts = collect_dock_plan_options(dock, sim_params)
    r = opts.get("turn_radius_m")
    if r is not None:
        return r
    sim_params = sim_params or {}
    for key in ("turn_radius_meters", "turn_radius_m"):
        if key in sim_params and sim_params[key] is not None:
            try:
                return float(sim_params[key])
            except (TypeError, ValueError):
                swallow_exc()
    return None


def effective_leg_turn_for_export(sequence, row_idx, custom_turns, sim_params=None, dock=None):
    """
    Turn radius and mode for the transition leaving this shooting-plan row.

    Uses Individual Turn Editor overrides when set; otherwise global dock defaults.
    Last row has no outgoing turn → empty strings.
    """
    sequence = list(sequence or [])
    if row_idx < 0 or row_idx >= len(sequence) - 1:
        return "", ""

    from_id = sequence[row_idx]
    to_id = sequence[row_idx + 1]
    turn_key = f"{from_id}_{to_id}"
    override = (custom_turns or {}).get(turn_key, {})

    radius = override.get("radius")
    if radius is None:
        radius = _global_turn_radius(sim_params, dock)
    radius_cell = ""
    if radius is not None:
        try:
            radius_cell = round(float(radius), 3)
        except (TypeError, ValueError):
            radius_cell = radius

    mode = override.get("mode")
    if not mode:
        mode = _acquisition_mode_display(sim_params, dock)
    return radius_cell, str(mode or "")


def custom_turns_from_shooting_plan_legs(row_leg_turns, ordered_line_ids):
    """
    Build custom_turns dict from per-row Indiv Turn Radius / Indiv Turn Mode columns.

    Row *i* describes the turn from ordered_line_ids[i] → ordered_line_ids[i + 1].
    """
    ordered_line_ids = [str(x) for x in (ordered_line_ids or [])]
    out = {}
    for i, leg in enumerate(row_leg_turns or []):
        if i >= len(ordered_line_ids) - 1:
            break
        if not isinstance(leg, dict) or not _turn_override_has_values(leg):
            continue
        key = f"{ordered_line_ids[i]}_{ordered_line_ids[i + 1]}"
        out[key] = dict(leg)
    return out


def collect_dock_plan_options(dock, sim_params=None):
    """Snapshot dock speeds, times, and turn settings for XLSX columns K–T."""
    sim_params = sim_params or {}
    opts = {}

    if dock is not None and hasattr(dock, "startDateTimeEdit"):
        try:
            opts["simulation_start"] = dock.startDateTimeEdit.dateTime().toString(
                "yyyy-MM-dd HH:mm"
            )
        except Exception:
            swallow_exc()
    if not opts.get("simulation_start"):
        for key in ("start_datetime", "start_time"):
            v = sim_params.get(key)
            if v is not None:
                if hasattr(v, "strftime"):
                    opts["simulation_start"] = v.strftime("%Y-%m-%d %H:%M")
                else:
                    opts["simulation_start"] = str(v)
                break

    def _dock_spin(attr, opt_key, sim_keys=()):
        w = getattr(dock, attr, None) if dock is not None else None
        if w is not None:
            try:
                opts[opt_key] = float(w.value())
                return
            except Exception:
                swallow_exc()
        for sk in sim_keys:
            if sk in sim_params and sim_params[sk] is not None:
                try:
                    opts[opt_key] = float(sim_params[sk])
                except (TypeError, ValueError):
                    swallow_exc()
                return

    _dock_spin("turnRadiusDoubleSpinBox", "turn_radius_m", ("turn_radius_meters",))
    _dock_spin("maxRunInDoubleSpinBox", "run_in_m", ("run_in_length_meters",))
    _dock_spin("runOutDoubleSpinBox", "run_out_m", ("run_out_length_meters",))
    _dock_spin(
        "acqSpeedPrimaryDoubleSpinBox",
        "shoot_l2h_kn",
        ("avg_shooting_speed_low_to_high_knots", "avg_shooting_speed_knots"),
    )
    _dock_spin(
        "acqSpeedHighToLowDoubleSpinBox",
        "shoot_h2l_kn",
        ("avg_shooting_speed_high_to_low_knots",),
    )
    _dock_spin(
        "turnSpeedDoubleSpinBox",
        "turn_l2h_kn",
        ("avg_turn_speed_low_to_high_knots", "avg_turn_speed_knots"),
    )
    _dock_spin(
        "turnSpeedHighToLowDoubleSpinBox",
        "turn_h2l_kn",
        ("avg_turn_speed_high_to_low_knots",),
    )

    mode = sim_params.get("acquisition_mode") or sim_params.get("acquisition_mode_key")
    if dock is not None and hasattr(dock, "acquisitionModeComboBox"):
        try:
            mode = dock.acquisitionModeComboBox.currentText() or mode
        except Exception:
            swallow_exc()
    if mode:
        opts["acquisition_mode"] = str(mode)

    if dock is not None and hasattr(dock, "deviationClearanceDoubleSpinBox"):
        try:
            opts["deviation_clearance_m"] = float(
                dock.deviationClearanceDoubleSpinBox.value()
            )
        except Exception:
            swallow_exc()

    return opts


def build_extension_cells_for_export(
    dock,
    sim_params,
    line_id,
    line_directions,
    direction_display_text="",
    *,
    leg_turn_radius="",
    leg_turn_mode="",
    include_global_columns=True,
):
    """
    One row's extension cells (K onward).

    Columns K–T (global dock defaults) are written only on the first data row
    (``include_global_columns=True``); other rows leave L–T blank. Column K
    (Direction Code) is written on every row from the Direction column. Columns
    U–V (Indiv Turn radius/mode) are filled on every row that has an outgoing
    turn (last row blank).
    """
    leg_cells = [leg_turn_radius, leg_turn_mode]
    n_global = len(SHOOTING_PLAN_EXTENSION_HEADERS) - len(leg_cells)
    code = direction_text_to_code(direction_display_text)
    if code not in ("low_to_high", "high_to_low"):
        directions = line_directions or {}
        code = directions.get(line_id) or directions.get(str(line_id))
        if code not in ("low_to_high", "high_to_low"):
            code = "low_to_high"

    if not include_global_columns:
        return [code] + ([""] * (n_global - 1)) + leg_cells

    opts = collect_dock_plan_options(dock, sim_params)

    return [
        code,
        opts.get("simulation_start", ""),
        opts.get("turn_radius_m", ""),
        opts.get("run_in_m", ""),
        opts.get("run_out_m", ""),
        opts.get("shoot_l2h_kn", ""),
        opts.get("shoot_h2l_kn", ""),
        opts.get("turn_l2h_kn", ""),
        opts.get("turn_h2l_kn", ""),
        opts.get("acquisition_mode", ""),
    ] + leg_cells


def _merge_dock_options_from_row(options, row, ext_map):
    """Fill options dict from one sheet row (first non-empty wins)."""
    for key, col in ext_map.items():
        if key in options and options[key] not in (None, ""):
            continue
        raw = str(_cell_at(row, col)).strip()
        if not raw:
            continue
        if key == "direction_code":
            options[key] = direction_text_to_code(raw)
        elif key == "acquisition_mode":
            options[key] = raw
        elif key == "simulation_start":
            options[key] = raw
        else:
            try:
                options[key] = float(raw)
            except (TypeError, ValueError):
                options[key] = raw


def parse_shooting_plan_import(sheet_rows, parse_int):
    """
    Parse Shooting Plan sheet: sequence rows, dock options (K+), per-row directions.

    Returns dict with seq_rows, dock_options, row_directions, row_leg_turns
    (aligned with import order).
    """
    if not sheet_rows or len(sheet_rows) < 2:
        return {
            "seq_rows": [],
            "dock_options": {},
            "row_directions": [],
            "row_leg_turns": [],
        }

    hmap = _header_index_map(sheet_rows[0])
    ext_map = _extension_column_map(sheet_rows[0])
    i_leg_r = ext_map.get("line_turn_radius_m")
    i_leg_m = ext_map.get("line_turn_mode")
    i_seq = hmap.get("seq", 0)
    i_line = hmap.get("line", 1)
    i_sp0 = hmap.get("start sp", 2)
    i_sp1 = hmap.get("end sp", 3)
    i_dir = hmap.get("direction", 8)
    i_dir_code = ext_map.get("direction_code")
    i_shoot_start = hmap.get("shoot start (local)", 4)

    entries = []
    dock_options = {}

    for row in sheet_rows[1:]:
        if not row or all(not str(c).strip() for c in row):
            continue

        if not dock_options.get("simulation_start"):
            raw_start = str(_cell_at(row, i_shoot_start)).strip()
            if raw_start and raw_start.upper() != "N/A":
                dock_options["simulation_start"] = raw_start
        try:
            seq_num = parse_int(_cell_at(row, i_seq))
            raw_line = _cell_at(row, i_line)
            line_num = base_line_number_from_plan_id(raw_line)
            if isinstance(line_num, str):
                line_num = parse_int(line_num)
            elif isinstance(line_num, float):
                line_num = int(line_num)
        except Exception:
            swallow_exc()
            continue

        sp_bounds = None
        a_txt = str(_cell_at(row, i_sp0)).strip()
        b_txt = str(_cell_at(row, i_sp1)).strip()
        if a_txt and b_txt:
            try:
                a = parse_int(a_txt)
                b = parse_int(b_txt)
                sp_bounds = (min(a, b), max(a, b))
            except Exception:
                sp_bounds = None

        dir_text = _cell_at(row, i_dir)
        if i_dir_code is not None:
            dir_code_raw = str(_cell_at(row, i_dir_code)).strip()
            if dir_code_raw:
                dir_code = direction_text_to_code(dir_code_raw)
            else:
                dir_code = direction_text_to_code(dir_text)
        else:
            dir_code = direction_text_to_code(dir_text)

        leg_override = {}
        if i_leg_r is not None:
            leg_r = _parse_float_cell(_cell_at(row, i_leg_r))
            if leg_r is not None:
                leg_override["radius"] = leg_r
        if i_leg_m is not None:
            leg_mode = normalize_turn_mode_display(_cell_at(row, i_leg_m))
            if leg_mode:
                leg_override["mode"] = leg_mode
        entries.append(
            {
                "seq": seq_num,
                "line": line_num,
                "sp_bounds": sp_bounds,
                "direction_code": dir_code,
                "leg_turn": leg_override if leg_override else None,
            }
        )
        _merge_dock_options_from_row(dock_options, row, ext_map)

    entries.sort(key=lambda x: (x["seq"], x["line"]))
    return {
        "seq_rows": [(e["seq"], e["line"], e["sp_bounds"]) for e in entries],
        "row_directions": [e["direction_code"] for e in entries],
        "dock_options": dock_options,
        "row_leg_turns": [e.get("leg_turn") for e in entries],
    }


def shooting_plan_to_sequence_rows(sheet_rows, parse_int):
    """
    Parse Shooting Plan sheet rows into [(seq, line_num, sp_bounds|None), ...].
    """
    if not sheet_rows or len(sheet_rows) < 2:
        return []

    hmap = _header_index_map(sheet_rows[0])
    i_seq = hmap.get("seq", 0)
    i_line = hmap.get("line", 1)
    i_sp0 = hmap.get("start sp", 2)
    i_sp1 = hmap.get("end sp", 3)

    seq_rows = []
    for row in sheet_rows[1:]:
        if not row or all(not str(c).strip() for c in row):
            continue
        try:
            seq_num = parse_int(row[i_seq] if i_seq < len(row) else "")
            raw_line = row[i_line] if i_line < len(row) else ""
            line_num = base_line_number_from_plan_id(raw_line)
            if isinstance(line_num, str):
                line_num = parse_int(line_num)
            elif isinstance(line_num, float):
                line_num = int(line_num)
        except Exception:
            swallow_exc()
            continue
        sp_bounds = None
        if i_sp0 < len(row) and i_sp1 < len(row):
            a_txt = str(row[i_sp0]).strip()
            b_txt = str(row[i_sp1]).strip()
            if a_txt and b_txt:
                try:
                    a = parse_int(a_txt)
                    b = parse_int(b_txt)
                    sp_bounds = (min(a, b), max(a, b))
                except Exception:
                    sp_bounds = None
        seq_rows.append((seq_num, line_num, sp_bounds))
    seq_rows.sort(key=lambda x: (x[0], x[1]))
    return seq_rows


def sheet_table_from_rows(sheet_rows):
    """First row headers, rest data (skip fully empty rows)."""
    if not sheet_rows:
        return [], []
    headers = [str(c) for c in sheet_rows[0]]
    data = []
    for row in sheet_rows[1:]:
        if not row or all(not str(c).strip() for c in row):
            continue
        padded = list(row) + [""] * (len(headers) - len(row))
        data.append(padded[: len(headers)])
    return headers, data


def find_sheet(workbook, *preferred_names):
    """Return sheet rows for the first matching name (exact, then case-insensitive)."""
    if not workbook:
        return None
    for name in preferred_names:
        if name in workbook:
            return workbook[name]
    lower_map = {k.lower(): k for k in workbook}
    for name in preferred_names:
        key = lower_map.get(name.lower())
        if key:
            return workbook[key]
    return None


def parse_metadata_sheet(workbook):
    rows = find_sheet(workbook, SHEET_METADATA)
    if not rows:
        return {}
    return _rows_to_dict(rows)


def is_lookahead_plan_workbook(workbook):
    meta = parse_metadata_sheet(workbook)
    if meta.get("LookaheadPlanVersion"):
        return True
    if find_sheet(workbook, SHEET_SETTINGS) is not None:
        return True
    return find_sheet(workbook, SHEET_SHOOTING_PLAN) is not None


def create_memory_layer_from_sheet(
    layer_name,
    sheet_rows,
    crs,
    geometry_type_name="LineString",
):
    """
    Build an in-memory QgsVectorLayer from a worksheet (headers + WKT column).
    Returns (layer, feature_count) or (None, 0).
    """
    from qgis.core import (
        QgsFeature,
        QgsGeometry,
        QgsVectorLayer,
    )

    headers, data = sheet_table_from_rows(sheet_rows)
    if not headers or not data:
        return None, 0

    wkt_idx = None
    for i, h in enumerate(headers):
        if str(h).strip().upper() == WKT_COLUMN:
            wkt_idx = i
            break
    if wkt_idx is None:
        log.warning("Sheet for %s has no WKT column", layer_name)
        return None, 0

    attr_headers = [h for i, h in enumerate(headers) if i != wkt_idx]
    fields = _build_import_fields(layer_name, attr_headers)

    uri = f"{geometry_type_name}?crs={crs.authid()}" if crs and crs.isValid() else f"{geometry_type_name}?crs=EPSG:4326"
    layer = QgsVectorLayer(uri, layer_name, "memory")
    if not layer.isValid():
        log.warning("Could not create memory layer %s", layer_name)
        return None, 0

    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()
    name_to_idx = {fields.at(i).name(): i for i in range(fields.count())}

    features = []
    for row in data:
        wkt = str(row[wkt_idx]).strip() if wkt_idx < len(row) else ""
        if not wkt:
            continue
        geom = QgsGeometry.fromWkt(wkt)
        if geom is None or geom.isNull():
            continue
        attrs = [""] * fields.count()
        for col_in, hname in enumerate(headers):
            if col_in == wkt_idx:
                continue
            fi = name_to_idx.get(str(hname))
            if fi is not None and col_in < len(row):
                attrs[fi] = _coerce_import_attribute(row[col_in], fields.at(fi))
        feat = QgsFeature(layer.fields())
        feat.setGeometry(geom)
        feat.setAttributes(attrs)
        features.append(feat)

    if not features:
        return None, 0

    if not provider.addFeatures(features):
        log.warning("addFeatures failed for %s: %s", layer_name, provider.lastError())
        return None, 0

    layer.updateExtents()
    return layer, len(features)
