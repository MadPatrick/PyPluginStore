# ISSUE:65 - timeout on selfupdate

Status: open; local fix prepared.

Reporter:
- `Eddie-BS` reported on 2026-06-29 that self-update ends with:
  `Error: Timeout waiting for plugin response.`

Intent:
- Self-update should acknowledge the custom UI instead of timing out while PyPluginStore updates its own live plugin files.

Assessment:
- Normal plugin updates run synchronously and then write a response to the API bridge.
- Updating `00-PyPluginStore` can modify/reload the live plugin before the bridge response is read by the browser.
- The provided log stops after:
  `Self update requested for PyPluginStore.`
  `Resetting and Updating Plugin:00-PyPluginStore`
- This is consistent with the plugin being interrupted/reloaded during its own update path.

Local fix:
- PyPluginStore self-update now schedules a detached helper instead of running `git reset` and `git pull` synchronously in the API command handler.
- The API bridge gets a success response before the helper mutates the live plugin files.
- The helper writes command output to `self_update.log`.
- The custom UI displays the backend self-update message and skips the immediate `list_plugins` reload for the manager self-update, avoiding a reload race.
- Normal plugin updates still run synchronously and keep existing response behavior.
- `plugin.py` was regenerated from `plugin_core.py`.

Verification:
- `pytest -q`: 125 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.
- `python .github/scripts/validate_plugins.py`: passed for 328 plugins.

Public action:
- None taken. After push/release, comment on `ISSUE:65` with the self-update timeout fix.
