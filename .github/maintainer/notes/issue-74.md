# ISSUE:74 - not installed from git but detected ...

Status: open; fix implemented locally.

Reporter:
- `Eddie-BS` reported on 2026-07-01 that a manually installed/copied plugin folder without Git tracking is detected as installed but logged as ignored. They requested a visual indication of this unmanaged state in the web UI.

Intent:
- Clearly show in the web interface when an installed plugin is unmanaged (not cloned via Git) and cannot be updated via PyPluginStore.

Assessment:
- Currently, unmanaged/non-Git plugins are detected as installed, but their update status is "unknown", causing them to render in the UI with a gray "Update" button that says "Update status unknown" on hover.
- To make this obvious, we added an `"is_git": is_git_repo` boolean to `"installed_match_details"`. The UI now parses this and renders a clear "Non-Git" badge next to the "Installed" badge, and disables the "Update" button with an informative tooltip.

Recommended next step:
- Show the visual improvements to the reporter.

Verification:
- Added assertions in `tests/test_plugin_registry.py` checking that `is_git` is correctly populated for both Git and non-Git directories.
