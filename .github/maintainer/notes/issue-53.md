# ISSUE:53 - Hidden API Payload device breaks UI bridge

Status: open; local fix prepared.

Reporter:
- `mvveelen` hid the text device `PyPluginStore - API Payload` because it clutters Utilities.
- After hiding it, the custom UI could no longer load plugins.

Intent:
- Let users hide the payload bridge device without breaking the custom UI.

Assessment:
- The custom UI queried Domoticz devices with `used=true`.
- Hidden devices can be excluded from that result, so the UI failed to find `PPM_API_PAYLOAD`.

Local fix:
- Changed the UI bridge lookup to use `getdevices&filter=all&used=all`.
- Added UI smoke coverage for hidden-device lookup.

Verification:
- `pytest -q`: passed.

Public action:
- None yet. Requires approval before commenting or closing.
