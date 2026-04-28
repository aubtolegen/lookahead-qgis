import json
import os
from qgis.PyQt.QtCore import QSettings

SETTINGS_FILENAME = "lookahead_settings.json"
LEGACY_SPS_FILENAME = "sps_preplot_parsing_config.json"
VERSION = 2
SETTINGS_KEY = "Lookahead/settings_json"

# Defaults merged into dock["stability"] on load (tuning run-in match + teardrop heuristics).
DOCK_STABILITY_DEFAULTS = {
    "runin_connect_tolerance_m": 10.0,
    "teardrop_loop_chord_factor": 3.5,
    "teardrop_loop_circumference_factor": 1.05,
    "teardrop_loop_min_chord_m": 5.0,
}


def _merge_dock_stability(dock):
    if not isinstance(dock, dict):
        return
    s = dock.get("stability")
    if not isinstance(s, dict):
        s = {}
    for k, v in DOCK_STABILITY_DEFAULTS.items():
        s.setdefault(k, v)
    dock["stability"] = s


def _plugin_dir():
    return os.path.dirname(os.path.abspath(__file__))


def settings_path():
    # Kept for backward compatibility and one-time migration only.
    return os.path.join(_plugin_dir(), SETTINGS_FILENAME)


def _load_from_qsettings():
    try:
        raw = QSettings().value(SETTINGS_KEY, "", type=str)
    except Exception:
        raw = ""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _save_to_qsettings(data):
    try:
        QSettings().setValue(SETTINGS_KEY, json.dumps(data, ensure_ascii=False))
        return True
    except Exception:
        return False


def load_settings():
    """
    Load full settings dict: version, sps_parsing (dict|None), dock (dict).
    Migrates legacy sps_preplot_parsing_config.json on first run.
    """
    data = _load_from_qsettings()
    if isinstance(data, dict):
        data.setdefault("version", VERSION)
        dock = data.get("dock")
        if not isinstance(dock, dict):
            data["dock"] = {}
        _merge_dock_stability(data["dock"])
        if "sps_parsing" not in data:
            data["sps_parsing"] = None
        if "csv_parsing" not in data:
            data["csv_parsing"] = None
        return data

    path = settings_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("version", VERSION)
                dock = data.get("dock")
                if not isinstance(dock, dict):
                    data["dock"] = {}
                _merge_dock_stability(data["dock"])
                if "sps_parsing" not in data:
                    data["sps_parsing"] = None
                if "csv_parsing" not in data:
                    data["csv_parsing"] = None
                # Migrate local JSON storage to QGIS profile settings.
                _save_to_qsettings(data)
                try:
                    os.remove(path)
                except OSError:
                    pass
                return data
        except (OSError, ValueError, TypeError):
            pass

    sps = None
    legacy = os.path.join(_plugin_dir(), LEGACY_SPS_FILENAME)
    if os.path.isfile(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                sps = raw
        except (OSError, ValueError, TypeError):
            pass

    dock = {}
    _merge_dock_stability(dock)
    data = {"version": VERSION, "sps_parsing": sps,
            "csv_parsing": None, "dock": dock}
    _save_to_qsettings(data)
    return data


def save_settings(data):
    """Atomic write of full settings dict."""
    if not isinstance(data, dict):
        return
    data = dict(data)
    data.setdefault("version", VERSION)
    if not isinstance(data.get("dock"), dict):
        data["dock"] = {}
    _merge_dock_stability(data["dock"])
    _save_to_qsettings(data)


def get_sps_parsing():
    return load_settings().get("sps_parsing")


def set_sps_parsing(mapping):
    data = load_settings()
    data["sps_parsing"] = dict(mapping) if mapping else None
    save_settings(data)


def clear_sps_parsing():
    data = load_settings()
    data["sps_parsing"] = None
    save_settings(data)
    legacy = os.path.join(_plugin_dir(), LEGACY_SPS_FILENAME)
    try:
        if os.path.isfile(legacy):
            os.remove(legacy)
    except OSError:
        pass


def get_csv_parsing():
    return load_settings().get("csv_parsing")


def set_csv_parsing(mapping):
    data = load_settings()
    data["csv_parsing"] = dict(mapping) if mapping else None
    save_settings(data)


def clear_csv_parsing():
    data = load_settings()
    data["csv_parsing"] = None
    save_settings(data)


def get_dock():
    d = load_settings().get("dock")
    return d if isinstance(d, dict) else {}


def update_dock(partial):
    data = load_settings()
    dock = data.get("dock")
    if not isinstance(dock, dict):
        dock = {}
    dock.update(partial)
    data["dock"] = dock
    save_settings(data)
