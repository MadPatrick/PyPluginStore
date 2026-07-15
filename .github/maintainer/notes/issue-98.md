# ISSUE:98 - Place Local beside platform badges

Status: implemented; awaiting public action.

Intent:
- Show the `Local` badge on the same row as `Linux` and `Windows`, directly below the title and `Installed` row.

Decision:
- Keep the explicit multiline card-header structure.
- Render known platform badges first and append `Local` to that same row.
- Render the row for local-only entries even when no known platform is available.
- Keep `Non-Git`, repository mismatch, and self-update status badges on the separate status row.

Verification:
- `pytest -q tests/test_ui_smoke.py`: 27 passed.
- `pytest -q`: 203 passed.
- `git diff --check`: passed.

Confidence:
- High. The change only moves badge placement and preserves the existing badge styles and warning/status layout.

Public action:
- None. Commenting on or closing `ISSUE:98` requires approval.
