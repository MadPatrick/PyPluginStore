# ISSUE:56 - Startup update check logs errors

Status: open; local fix prepared.

Reporter:
- `Eddie-BS` reports several `Something went wrong with update check` errors during Domoticz startup on `v2.11.1`.

Intent:
- Avoid noisy error logs when scheduled update checks cannot determine status for an installed plugin.

Assessment:
- The scheduled `AllNotify` path duplicated git update-check logic and logged `Error` when fetch or ahead/behind status could not be determined.
- The UI update-status path already represents non-checkable states as `unknown`.

Local fix:
- `CheckForUpdatePythonPlugin()` now reuses `getGitUpdateStatus()`.
- It sends notifications only for `available`.
- It logs `current` as normal and leaves `unknown` as debug-only.

Verification:
- Added tests for `unknown` without error and for notification when update is available.

Public action:
- None yet. Requires approval before commenting or closing.
