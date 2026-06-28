# Maintainer Runs

## 2026-06-28 - API payload bridge cleanup

Scope:
- Reviewed new `ISSUE:60` from `Eddie-BS`.
- Confirmed current public state:
  - Open issues: `ISSUE:30`, `ISSUE:60`.
  - Open pull requests: `PR:59` Release Please for `v2.12.1`.
  - Latest release: `v2.12.0` published on 2026-06-28.
  - Open code scanning alerts: 0.
- Diagnosed `ISSUE:60` as a stale custom-UI bridge response being treated as a new inbound command.
- Added requested registry entry `MarstekCT` for `Haaibaai/Domoticz-Marstek`, using default branch `main` and pushed timestamp `2025-08-03T17:11:36Z`.
- Prepared a local fix:
  - Ignore empty API payload values.
  - Clear and ignore large stale API responses, including truncated response strings.
  - Preserve the oversized-request guard for true inbound requests.
  - Clear the browser bridge before sending a command and after consuming a response.
  - Regenerated `plugin.py` from `plugin_core.py`.

Verification:
- `pytest -q`: 123 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.
- `python .github/scripts/validate_plugins.py`: passed for 327 plugins.

Notes:
- Installed open-source-maintainer skill references and triage script are still missing on disk, so this run used direct `gh` and local repository analysis.
- Product changes committed locally as `66ae709`.
- Recommended next action after push is to watch workflows, let Release Please update or supersede `PR:59`, and comment on `ISSUE:60` once the fix is available.

## 2026-06-28 - Update-status cache follow-up

Scope:
- Re-reviewed `ISSUE:57` after the reporter noted that detected plugins did not show green `Update` buttons.
- Identified that `CheckForUpdatePythonPlugin()` computed startup update status for notifications but did not populate the `self.update_status` cache used by the custom UI.
- Prepared a follow-up fix so startup checks cache `available`, `current`, and `unknown` outcomes.
- Regenerated `plugin.py` from `plugin_core.py`.

Verification:
- `pytest -q`: 118 passed.
- `python -m py_compile plugin_core.py plugin.py`: passed.
- `git diff --check`: passed.

Notes:
- No public GitHub actions were taken.

## 2026-06-28 - Domoticz 2025.1 notification compatibility

Scope:
- Reviewed `ISSUE:57`, reported against Domoticz `2025.1` build `16682`.
- Reproduced the likely failure path from the provided log: `Mode4=AllNotify` calls `CheckForUpdatePythonPlugin()`, which calls `fnSelectedNotify()`, which assumed `Domoticz.SendNotification` exists.
- Inspected local Domoticz 2025.1 source in `/home/vincent/src/domoticz`; `hardware/plugins/Plugins.cpp` exposes `Notifier`, but not `SendNotification`, to Python plugins.
- Prepared a local compatibility fix:
  - Added `sendDomoticzNotification()` as a guarded wrapper.
  - Setup folder warnings and update notifications now skip native notification delivery with a log entry when the API is absent.
  - Regenerated `plugin.py` from `plugin_core.py`.

Verification:
- `pytest -q`: 117 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.

Notes:
- No public GitHub actions were taken.
- Recommended next action is to push this fix and add a concise `ISSUE:57` comment after approval.

## 2026-06-28

Scope:
- Reviewed current GitHub state for `adrighem/PyPluginStore`.
- Active public items: `ISSUE:30`, `ISSUE:52`, `ISSUE:53`, `ISSUE:54`, `ISSUE:55`, `ISSUE:56`.
- Open pull requests: `PR:49` Release Please for `v2.12.0`.
- Confirmed `ISSUE:46` is closed and `v2.11.1` was released on 2026-06-27.
- Implemented local fixes for the new issue cluster:
  - Added registry entries for `rklomp/Domoticz-SMA-SunnyBoy` and `999LV/NUT_UPS`.
  - Made the custom UI bridge search all Domoticz devices, including hidden devices, so hiding `PyPluginStore - API Payload` does not break command transport.
  - Added an icon fallback from `images/pypluginstore-icon.png` to `/images/pypluginstore-icon.png`.
  - Made local registry candidates win when they collide with public registry repository aliases.
  - Changed scheduled update checks to treat non-checkable git state as `unknown` debug output rather than user-facing error logs.
- Regenerated `plugin.py` from `plugin_core.py`.

Verification:
- `pytest -q`: 115 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.
- `python .github/scripts/validate_plugins.py`: passed for 324 plugins.
- Open code scanning alerts: 0.

Notes:
- Installed open-source-maintainer skill references and triage script are still missing on disk, so this run used direct `gh` and local repository analysis.
- No public GitHub actions were taken.
- Recommended next action is to ship the local fixes, then comment on `ISSUE:52`, `ISSUE:53`, `ISSUE:54`, `ISSUE:55`, and `ISSUE:56` after human approval.
- `PR:49` should wait until this fix batch is included, or be superseded by the next Release Please update after merging.

## 2026-06-27

Scope:
- Reviewed current GitHub state for `adrighem/PyPluginStore`.
- Active public items: `ISSUE:30`, `ISSUE:46`.
- Open pull requests: none.
- Investigated `ISSUE:46`, a regression report from MadPatrick after updating from `v2.9.1` to `v2.11.0`.
- Compared the issue screenshots and identified cards visible in `v2.9.1` but missing in `v2.11.0`: `APC_UPS`, `Bmw`, `HP_iLo`, `Solaredge_modbustcp`, and `Somfy`.
- Prepared a local fix restoring exact registry-folder installed detection compatibility and adding flexible detection for repo-folder aliases, Domoticz-affix-stripped folder names, git remotes, externallinks, private-fork fallback, and plugin metadata.
- Regenerated `plugin.py` from `plugin_core.py`.

Verification:
- `pytest -q`: 91 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.

Notes:
- Installed open-source-maintainer skill references and triage script are still missing on disk, so this run used direct `gh`, GitHub MCP, and local repository analysis.
- No public GitHub actions were taken.
- `ISSUE:30` remains open as an ideas/discussion issue.
- Recommended next public action is a patch release plus a concise comment on `ISSUE:46` after human approval.

## 2026-06-20

Scope:
- Reviewed current GitHub state for `adrighem/PyPluginStore`.
- Active public items: `ISSUE:30`, `PR:32`.
- Implemented local registry overlay from `PR:32` intent without public GitHub actions.
- After approval, pushed implementation commit `36f3bcf` to `master`, commented on `PR:32`, and closed it.
- Updated `PR:33` release notes to credit MadPatrick, removed stale `Melotron/Python` registry entry to restore validation, approved and merged `PR:33`, and confirmed `v2.8.0` was published.
- Fixed code scanning alerts `#5` through `#8` by replacing clone URL substring checks with parsed hostname checks, pushed `66bcd4c`, and confirmed `gh-helper code adrighem/PyPluginStore` reports no items.
- Approved and merged `PR:34`, confirming release `v2.8.1` was published.

Verification:
- `pytest -q`: 52 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.

Notes:
- Installed open-source-maintainer skill references and triage script were missing on disk, so this run used direct `gh` and local repository analysis.
- `ISSUE:30` remains open as an ideas/discussion issue.
- Post-merge workflows for `PR:33` completed successfully: Generate Plugin XML Header, release-please, CodeQL, and Validate Plugins.
- Push workflows for `66bcd4c` completed successfully: Generate Plugin XML Header, CodeQL, and Validate Plugins.
- Release Please opened `PR:34` for `2.8.1`.
- Post-merge workflows for `PR:34` completed successfully: Generate Plugin XML Header, release-please, CodeQL, and Validate Plugins.
