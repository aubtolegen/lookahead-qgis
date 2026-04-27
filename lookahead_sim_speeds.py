KNOTS_TO_MPS = 0.514444

_DEFAULT_SHOOTING_MPS = 4.0
_DEFAULT_TURN_MPS = 4.0


def shooting_speed_mps(sim_params, line_is_reciprocal):
    """
    Shooting (line acquisition) speed in m/s for the given traversal direction.

    Args:
        sim_params: Parameter dict from the dock / simulation.
        line_is_reciprocal: True if the line is shot High→Low (reciprocal).
    """
    l2h = float(sim_params.get("avg_shooting_speed_low_to_high_mps") or 0.0)
    h2l = float(sim_params.get("avg_shooting_speed_high_to_low_mps") or 0.0)
    legacy = float(sim_params.get("avg_shooting_speed_mps") or 0.0)
    if line_is_reciprocal:
        v = h2l if h2l > 0.0 else legacy
    else:
        v = l2h if l2h > 0.0 else legacy
    if not v or v <= 0.0:
        v = _DEFAULT_SHOOTING_MPS
    return v


def turn_speed_mps(sim_params, line_is_reciprocal):
    """
    Turn / run-in / run-out speed in m/s for the given line traversal direction.
    """
    l2h = float(sim_params.get("avg_turn_speed_low_to_high_mps") or 0.0)
    h2l = float(sim_params.get("avg_turn_speed_high_to_low_mps") or 0.0)
    legacy = float(sim_params.get("avg_turn_speed_mps") or 0.0)
    if line_is_reciprocal:
        v = h2l if h2l > 0.0 else legacy
    else:
        v = l2h if l2h > 0.0 else legacy
    if not v or v <= 0.0:
        v = _DEFAULT_TURN_MPS
    return v


def shooting_speed_knots(sim_params, line_is_reciprocal):
    return shooting_speed_mps(sim_params, line_is_reciprocal) / KNOTS_TO_MPS


def turn_speed_knots(sim_params, line_is_reciprocal):
    return turn_speed_mps(sim_params, line_is_reciprocal) / KNOTS_TO_MPS
