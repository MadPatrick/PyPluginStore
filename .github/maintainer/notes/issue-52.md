# ISSUE:52 - Missing Domoticz-SMA-SunnyBoy plugin

Status: open; local fix prepared.

Reporter:
- `mvveelen` reports an older forked plugin not shown after scanning installed plugin folders.
- Target repository: `https://github.com/rklomp/Domoticz-SMA-SunnyBoy`.

Intent:
- Add the public plugin to the registry so existing installs can be detected and managed.

Assessment:
- Repository exists, is not archived, and has `plugin.py` on `master`.
- `plugin.py` declares key `SMASunnyBoy` and name `SMA Sunny Boy Solar Inverter`.
- Existing registry has `Domoticz-SMA-Inverter`, but not this SunnyBoy repository.

Local fix:
- Added `Domoticz-SMA-SunnyBoy` to `registry.json`.
- Added update time `2021-05-26T16:00:26Z` to `update_times.json`.

Verification:
- Registry validator passed for the new entry.

Public action:
- None yet. Requires approval before commenting or closing.
