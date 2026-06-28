# ISSUE:57 - Domoticz 2025.1 startup crash on SendNotification

Status: open; local fix prepared.

Reporter:
- `Eddie-BS` reported that PyPluginStore did not show as a menu on Domoticz `2025.1` build `16682`.
- Local reproduction with Domoticz `2025.1` worked for the menu, but startup logged an `AttributeError` for `Domoticz.SendNotification`.

Intent:
- Keep PyPluginStore compatible with older Domoticz builds where the Python plugin module does not expose native notification sending.

Assessment:
- The failing path is `onStart()` -> `CheckForUpdatePythonPlugin()` -> `fnSelectedNotify()` -> `Domoticz.SendNotification(...)`.
- Local Domoticz 2025.1 source in `/home/vincent/src/domoticz/hardware/plugins/Plugins.cpp` exposes `Notifier`, not `SendNotification`, to Python plugins.
- Native update notifications should degrade gracefully rather than aborting plugin startup.

Local fix:
- Added `sendDomoticzNotification()` wrapper.
- `fnSelectedNotify()` and the setup folder warning now use the wrapper.
- Missing native notification API logs a skip message and does not raise.
- Regenerated `plugin.py`.

Verification:
- `pytest -q`: 117 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.

Public action:
- None yet. Requires approval before commenting or closing.
