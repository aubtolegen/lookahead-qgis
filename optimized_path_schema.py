TURN_SEGMENT_TYPES = {"RunIn", "RunOut", "Turn", "Turn_Teardrop", "Turn_Racetrack"}


def optimized_path_field_specs():
    """
    Return ``Optimized_Path`` attribute schema as ``(name, type_name, kwargs)`` tuples.

    This helper is intentionally pure Python so it can be unit-tested without QGIS.
    """
    return [
        ("SeqOrder", "Int", {}),
        ("LineNum", "String", {"len": 50}),
        ("SegmentType", "String", {"len": 15}),
        ("Length_m", "Double", {"len": 10, "prec": 2}),
        ("Duration_s", "Double", {"len": 8, "prec": 1}),
        ("Duration_hh_mm", "String", {"len": 10}),
        ("StartTime", "DateTime", {}),
        ("EndTime", "DateTime", {}),
        ("Heading", "Double", {"len": 6, "prec": 1}),
        ("Speed_kn", "Double", {"len": 6, "prec": 2}),
        ("Deviated", "Bool", {}),
        ("DeviationFailed", "Bool", {}),
        ("StartLine", "String", {"len": 50}),
        ("EndLine", "String", {"len": 50}),
    ]


def optimized_path_field_names():
    return [name for name, _type_name, _kwargs in optimized_path_field_specs()]


def segment_speed_kn(
    seg_type,
    base_line_speed_kn=None,
    base_turn_speed_kn=None,
    *,
    line_speed_kn=None,
    turn_speed_kn=None,
):
    """
    Return effective segment speed in knots for the given segment type.

    Per-direction overrides (``line_speed_kn`` / ``turn_speed_kn``) take precedence
    over the legacy single base speeds when provided.
    """
    if seg_type == "Line":
        v = line_speed_kn if line_speed_kn is not None else base_line_speed_kn
        return round(v, 2) if v is not None else None
    if seg_type in TURN_SEGMENT_TYPES or seg_type in ("RunIn", "RunOut"):
        v = turn_speed_kn if turn_speed_kn is not None else base_turn_speed_kn
        return round(v, 2) if v is not None else None
    return None


def build_optimized_path_attributes(
    *,
    seq_order,
    line_num,
    seg_type,
    length,
    time_s,
    duration_hh_mm,
    q_start,
    q_end,
    heading,
    base_line_speed_kn=None,
    base_turn_speed_kn=None,
    line_speed_kn=None,
    turn_speed_kn=None,
    is_deviated,
    is_failed,
    start_line,
    end_line,
    null_value,
):
    """
    Build attribute values in the exact schema order for ``Optimized_Path``.
    """
    seg_speed_kn = segment_speed_kn(
        seg_type,
        base_line_speed_kn,
        base_turn_speed_kn,
        line_speed_kn=line_speed_kn,
        turn_speed_kn=turn_speed_kn,
    )
    return [
        seq_order,
        line_num,
        seg_type,
        length,
        time_s,
        duration_hh_mm,
        q_start,
        q_end,
        heading,
        seg_speed_kn if seg_speed_kn is not None else null_value,
        is_deviated,
        is_failed,
        start_line,
        end_line,
    ]
