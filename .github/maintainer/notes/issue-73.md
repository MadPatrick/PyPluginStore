# ISSUE:73 - update availiable ?

Status: open; fix implemented locally.

Reporter:
- `Eddie-BS` reported on 2026-07-01 that PyPluginStore sent a notification saying updates were available for the SolarEdge modbustcp plugin, but manual update check or update commands via the UI report "already Up-To-Date".

Intent:
- Ensure updates are robustly pulled and branch changes applied correctly, even if the local checkout is in detached HEAD state, lacks a tracked upstream branch, or is on a different branch than the one configured in the registry.

Assessment:
- If a plugin's local checkout is in detached HEAD (e.g. checked out to a specific tag or old commit) or has no upstream branch configured, generic `git pull --force` will fail or do nothing, leading to a silent discrepancy where the update status reports "available" but the pull is a no-op.
- To make updates robust, PyPluginStore should check out the registered branch name from `plugin_data` and pull with explicit target reference: `git pull --force origin <branch>`. This guarantees updates are fetched and applied cleanly.

Recommended next step:
- Ask the reporter to update PyPluginStore and test the robust update pulling behavior.

Verification:
- Updated `tests/test_plugin_update_status.py` to assert the updated branch-aware update sequence.
