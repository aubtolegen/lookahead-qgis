# Lookahead (QGIS Plugin)

Lookahead is a QGIS plugin for planning, optimizing, and simulating OBN source-line acquisition workflows.

## Supported Environment

- QGIS: 3.16+
- Platform: Windows (primary test environment)

## Installation

1. Copy the plugin folder into your QGIS profile plugins directory.
2. Start QGIS.
3. Enable **Lookahead** in Plugin Manager.

## Quick Start

1. Import SPS data.
2. Refresh line list and assign statuses.
3. Generate lookahead lines.
4. Generate deviations (if No-Go zones are used).
5. Run simulation.
6. Finalize lookahead plan and review timeline/calendar.

## Troubleshooting

- **No output layers after generation**
  - Ensure the SPS layer is valid and has required fields.
  - Check status filters and selected line range.
- **Simulation timing looks wrong**
  - Re-run simulation after changing speeds, turn mode, run-in/run-out, or sequence.
- **Unexpected geometry behavior**
  - Use a projected CRS in meters (for example UTM) for planning and simulation.
- **External tracking markers not shown**
  - Tracking overlay integration is optional and depends on a compatible external tracking plugin being present and active.

## Support / Bug Reports

- Contact: `aub.tolegen@gmail.com`
- When reporting issues, include:
  - QGIS version
  - OS version
  - Steps to reproduce
  - Screenshots and sample data (if possible)

## Licensing

- Main project license: GNU GPL-2.0 (`LICENSE`)
- Third-party / upstream attribution: `THIRD_PARTY_NOTICES.md`
