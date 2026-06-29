# ISSUE:65 - timeout on selfupdate

Status: closed; fix shipped.

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
- PyPluginStore self-update now runs synchronous pre-flight checks before scheduling any file mutation.
- Pre-flight refuses self-update when:
  - `git` is unavailable;
  - the manager folder is not the git work-tree root;
  - tracked local files are modified;
  - the branch has no upstream;
  - the branch has diverged or has local commits;
  - the upstream candidate is missing required runtime files;
  - the upstream `plugin.py` or `plugin_core.py` has invalid Python syntax.
- PyPluginStore self-update now schedules a detached helper only after pre-flight passes.
- The API bridge gets a success response before the helper mutates the live plugin files.
- The helper repeats the clean tracked-file check, fetches the upstream remote, and applies the update with `git merge --ff-only`.
- The helper no longer uses `git reset --hard HEAD` or `git pull --force` for self-update.
- The helper writes command output to `self_update.log`.
- The custom UI displays the backend self-update message and skips the immediate `list_plugins` reload for the manager self-update, avoiding a reload race.
- Normal plugin updates still run synchronously and keep existing response behavior.
- `plugin.py` was regenerated from `plugin_core.py`.

Verification:
- `pytest -q`: 130 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.
- `python .github/scripts/validate_plugins.py`: not rerun for this code-only follow-up.

Public action:
- Initial timeout mitigation was pushed as `47e2d73`.
- Stricter pre-flight hardening was pushed as `28c7f43`.
- Master workflows passed for `28c7f43`: release-please, Generate Plugin XML Header, Validate Plugins, and CodeQL.
- `ISSUE:65` was closed on 2026-06-29.
