# ISSUE:54 - Icon missing on Docker based Domoticz

Status: open; local mitigation prepared.

Reporter:
- `Eddie-BS` reports the PyPluginStore icon missing in Docker based Domoticz.

Intent:
- Make the custom UI icon more robust across Domoticz path/layout differences.

Assessment:
- Existing startup logic copies `pypluginstore-icon.png` to `www/images`.
- The UI referenced `images/pypluginstore-icon.png`, which can be sensitive to the page base path.

Local fix:
- Kept the existing relative path.
- Added a root-relative fallback to `/images/pypluginstore-icon.png`.

Verification:
- UI smoke tests cover the existing asset and fallback.

Public action:
- None yet. Requires approval before commenting. If the fallback does not fix Docker, request the image URL/network error from browser dev tools.
