# ISSUE:73 - update availiable ?

Status: open; follow-up fix implemented locally.

Reporter:
- `Eddie-BS` reported on 2026-07-01 that PyPluginStore sent a notification saying updates were available for the SolarEdge modbustcp plugin, but manual update check or update commands via the UI report "already Up-To-Date".

Intent:
- Ensure updates are robustly pulled and branch changes applied correctly, even if the local checkout is in detached HEAD state, lacks a tracked upstream branch, or is on a different branch than the one configured in the registry.
- Follow-up from 2026-07-06: local branch overrides should not show misleading public/default-branch metadata, older remote version labels, or repository links that open the wrong branch.

Assessment:
- If a plugin's local checkout is in detached HEAD (e.g. checked out to a specific tag or old commit) or has no upstream branch configured, generic `git pull --force` will fail or do nothing, leading to a silent discrepancy where the update status reports "available" but the pull is a no-op.
- To make updates robust, PyPluginStore should check out the registered branch name from `plugin_data` and pull with explicit target reference: `git pull --force origin <branch>`. This guarantees updates are fetched and applied cleanly.
- The latest reporter screenshot showed a local override to `meters`, installed version `2.0.5.5`, remote branch version `2.0.4`, a misleading green Update state, public/default branch update time, and a Repo button that opened the repository default branch.
- The public `update_times.json` value is keyed by plugin key and represents the public registry branch, so it must not overwrite local override entries during registry load.

Recommended next step:
- Ask the reporter to update PyPluginStore and test the local branch override behavior.

Verification:
- Updated `tests/test_plugin_update_status.py` to assert configured-branch status checks and local override update timestamps.
- Updated `tests/test_plugin_registry.py` to assert local override timestamps are ignored and remote version metadata is fetched from the override branch.
- Updated `tests/test_ui_smoke.py` to assert branch-aware Repo links for GitHub, GitLab, and Codeberg, plus installed-newer-than-remote version wording.
