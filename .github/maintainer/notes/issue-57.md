# ISSUE:57 - Domoticz 2025.1 startup crash and missing update buttons

Status: open; follow-up local fix prepared.

Reporter:
- `Eddie-BS` reported that PyPluginStore did not show as a menu on Domoticz `2025.1` build `16682`.
- After enabling the custom menu, the reporter said detected plugins did not show a green `Update` button.
- Local reproduction with Domoticz `2025.1` worked for the menu, but startup logged an `AttributeError` for `Domoticz.SendNotification`.

Intent:
- Keep PyPluginStore compatible with older Domoticz builds where the Python plugin module does not expose native notification sending.
- Keep startup update checks and UI update badges backed by the same cached status data.

Assessment:
- The failing path is `onStart()` -> `CheckForUpdatePythonPlugin()` -> `fnSelectedNotify()` -> `Domoticz.SendNotification(...)`.
- Local Domoticz 2025.1 source in `/home/vincent/src/domoticz/hardware/plugins/Plugins.cpp` exposes `Notifier`, not `SendNotification`, to Python plugins.
- Native update notifications should degrade gracefully rather than aborting plugin startup.
- `CheckForUpdatePythonPlugin()` computed `getGitUpdateStatus(...)` for startup notifications but did not write the result to `self.update_status`.
- The HTML page reads cached update statuses, so startup checks could find an available update while the UI still showed `unknown` until heartbeat/manual refresh.

Local fix:
- Added `sendDomoticzNotification()` wrapper.
- `fnSelectedNotify()` and the setup folder warning now use the wrapper.
- Missing native notification API logs a skip message and does not raise.
- `CheckForUpdatePythonPlugin()` now caches `available`, `current`, and `unknown` outcomes for UI reuse.
- Regenerated `plugin.py`.

Verification:
- `pytest -q`: 118 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.

Public action:
- Commented once after the notification compatibility fix.
- No follow-up public action yet for the update-status cache fix.
