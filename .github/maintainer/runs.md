# Maintainer Runs

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
