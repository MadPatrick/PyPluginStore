# ISSUE:55 - NUT_UPS plugin not found

Status: open; local fix prepared.

Reporter:
- `Eddie-BS` reports `https://github.com/999LV/NUT_UPS/` is installed but not shown.

Intent:
- Add the public plugin to the registry so existing installs can be detected and managed.

Assessment:
- Repository exists, is not archived, and has `plugin.py` on `master`.
- `plugin.py` declares key `NUT_UPS` and name `UPS Monitor`.

Local fix:
- Added `NUT_UPS` to `registry.json`.
- Added update time `2019-05-24T06:10:53Z` to `update_times.json`.

Verification:
- Registry validator passed for the new entry.

Public action:
- None yet. Requires approval before commenting or closing.
