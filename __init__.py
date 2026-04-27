def classFactory(iface):
    from .lookahead_plugin import LookaheadPlanner
    return LookaheadPlanner(iface)
