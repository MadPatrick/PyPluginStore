# Maintainer Runs

## 2026-07-22 - ISSUE:117 reply and ISSUE:111 local-override hardening

Scope:
- Reviewed current repository and GitHub state for `adrighem/PyPluginStore`.
- Active public items:
  - Open issues: `ISSUE:87`, `ISSUE:111`.
  - Open pull requests: none.
- Posted the approved `ISSUE:117` restart/hard-refresh reply after confirming its
  screenshot showed an older deployed custom page.
- The reporter confirmed restart/refresh resolved `ISSUE:117` and closed it.
- Reproduced `ISSUE:111` against the code before `PR:116`: one legacy transaction
  with a missing staging root caused lifecycle lookup for an unrelated package to
  raise `Release transaction path must be a real directory.` Current `master`
  isolates the malformed transaction and returns an empty unrelated lifecycle.
- Added local-registry hardening so a valid local override ignores persisted
  Release preferences/targets, an invalid existing local registry pauses Release
  management, and Local cards cannot offer **Switch to Release**.
- Created focused local commit `0ad164b` with a `Refs #111` footer.
- Removed the public **Use Git** action from the UI and executable API. Stale
  clients receive guidance to create a Local registry override instead.
- Preserved legacy and rollback-created `keep_git` safety holds so restoring a
  Git backup cannot immediately reinstall the same Release.
- Updated user and contributor documentation for the Local override path,
  including verified Rollback or remove/reinstall for an existing Release folder.
- Created focused policy commit `691ea74` with a `Refs #111` footer.

Verification:
- Full sanitized suite: 1,314 tests passed.
- Focused Release policy, lifecycle, management, migration, and UI suite: 126
  tests passed.
- Generated runtime parity, Python compilation, `git diff --check`, and live
  validation of all 257 registry entries passed.
- Current `master` validation, generated-runtime verification, CodeQL, weekly
  scan, and release workflows are green.
- Dependabot, code scanning, and secret scanning alerts are clear.
- The branch push produced no GitHub Actions runs or check runs because current
  workflows trigger only for `master`, pull requests, schedules, or manual runs.

Notes:
- Approved public actions were the `ISSUE:117` comment and the branch push:
  `https://github.com/adrighem/PyPluginStore/issues/117#issuecomment-5042788930`.
- Pushed `fix/issue-111-local-overrides` with commits `0ad164b`, `691ea74`, and
  `db0f85d`; final maintainer-state commits followed. No `ISSUE:111` comment or
  pull request was created.
- The installed maintainer skill still lacks its referenced guidance and triage
  script, so this run used the documented manual fallback with `gh-helper`,
  direct `gh`, standalone reproduction, tests, and repository analysis.
- The three pre-existing untracked notes remain untouched.
- Recommended next public action is to open a pull request from the pushed branch
  after approval, monitor its required checks, then request reporter confirmation.
  `ISSUE:117` needs no further action.

## 2026-07-18 - Release-first implementation and multi-forge pilot

Scope:
- Completed `ISSUE:64` locally through the Conductor release-first track.
- Finished GitHub, GitLab, Codeberg/Forgejo, Gitea, and generic provider contracts,
  including live failure/no-release classification and authenticated discovery.
- Implemented pinned Release install/update, dependency snapshots, durable
  rollback, explicit Git retention, and safe Git-to-release upgrade migration.
- Published the initial 47-entry index: 46 GitHub and one GitLab release.

Verification:
- `pytest -q`: 1118 passed.
- Release-focused suite: 839 passed.
- Registry schema and release-index binding passed for all 256 managed records;
  the earlier rollout validation covered the full 257-record registry.
- Generated runtime freshness, Python compilation, workflow security tests,
  workflow YAML parsing, and diff checks passed. Plain `yamllint` continues to
  report pre-existing style violations in untouched workflows.
- Final security review found no release, correctness, or security blockers.
- Manual Linux, Windows, and Domoticz verification was waived by the user.

Notes:
- Both Codeberg/Forgejo entries currently have no published release. Gitea and
  generic have no registered pilot entry; provider fixtures remain authoritative
  until live candidates exist.
- One archive was rejected for a Unicode/case-fold path collision and one missing
  repository remained a provider failure; neither entered the index.
- No push, issue comment, label, close, or other public GitHub action was taken.
- The preserved autostash and three pre-existing untracked maintainer notes remain
  untouched.

## 2026-07-18 - Maintenance recovery, CI hardening, and release-first design

Scope:
- Reconciled the interrupted autostash against `v2.18.0`, preserving the July 16
  maintainer state and the unique registry-validator timeout history.
- Hardened all GitHub Actions workflows with read-only defaults, per-job write
  grants, immutable action pins, non-persisted pull-request checkout credentials,
  and generated-file verification on pull requests.
- Researched release-first plugin management for GitHub, GitLab,
  Forgejo/Codeberg, Gitea, and generic HTTPS sources.
- Prepared the provider-neutral release-index architecture and safe Git-to-release
  upgrade migration track for `ISSUE:64`.

Verification:
- `pytest -q -p no:cacheprovider`: 231 passed.
- `actionlint` 1.7.12: passed.
- Generated `plugin.py` parity: passed.
- Registry validation: passed for all 256 entries.
- JSON validation and `git diff --check`: passed.

Notes:
- Local implementation commits: `53366d2` (Actions hardening) and `23642ff`
  (release-first architecture and migration track).
- Changed the repository default workflow token from write to read and disabled
  workflow pull-request review approval.
- Full-SHA repository enforcement remains deferred until these pinned workflow
  definitions are on `master`; the proposed branch ruleset is documented to start
  in evaluation.
- No push, issue/PR comment, label, close, merge, or ruleset activation was taken.
- The recovery stash and three pre-existing untracked maintainer notes remain
  intact for explicit cleanup after review.

## 2026-07-18 - Read-only maintenance triage

Scope:
- Reviewed current repository and GitHub state for `adrighem/PyPluginStore`.
- Latest release: `v2.18.0`.
- Active public items:
  - Open issues: `ISSUE:64`, `ISSUE:87`.
  - Open pull requests: none.
- Latest Linux, Windows, CodeQL, release, and weekly scan workflow runs passed.
- Dependabot, code scanning, and secret scanning alerts are clear.

Verification:
- `pytest -q`: 225 passed in the non-mutating suite.
- Generated `plugin.py` parity: passed.
- Registry validation: passed for all 256 entries.

Notes:
- No public GitHub actions were taken.
- Pending local work is to harden `.github/workflows/generate_plugin.yml` and prepare the release-first plugin-management architecture and Git-to-release upgrade migration path, retaining Git support.

## 2026-07-16 - ISSUE:95 local registry UI management

Scope:
- Merged and released `PR:100` as v2.17.1, closing `ISSUE:98`.
- Implemented safe UI-based management of `registry_local.json` for `ISSUE:95`.
- Added revisioned atomic persistence, cached public-overlay reapplication, structured CRUD API actions, and an accessible native dialog.
- Updated README and advanced local-registry documentation.

Verification:
- `pytest -q`: 226 passed.
- Python compilation, generated runtime freshness, registry validation, and `git diff --check`: passed.
- Deployed `plugin.py` and `pypluginstore.html` to pietje with backup `/tmp/pypluginstore-manual-test-20260716T185205Z`.
- Manual add, edit, delete, responsive layout, and theme verification: passed.

Notes:
- Conductor checkpoint: `7132bcd`.
- Public comment or closure for `ISSUE:95` remains approval-gated.

## 2026-07-06 - Maintenance triage and validator timeout hardening

Scope:
- Reviewed current GitHub state for `adrighem/PyPluginStore`.
- Active public items:
  - Open issues: `ISSUE:64`, `ISSUE:87`, `ISSUE:91`.
  - Open pull requests: `PR:90` Release Please for `v2.16.0`.
- `gh-helper` found no unread inbox, no Dependabot alerts, and no code scanning alerts.
- `PR:90` is mergeable and generated-only release metadata, but required PR workflows `Validate Plugins` and `Generate Plugin XML Header` are `action_required`; CodeQL passed and the same validation workflow passed on `master`.

Prepared local changes:
- Added a 30 second timeout around `git ls-remote` in `.github/scripts/validate_plugins.py` so one slow remote cannot block registry validation indefinitely.
- Added regression coverage for passing the timeout and returning `False` cleanly on `subprocess.TimeoutExpired`.

Verification:
- `pytest tests/test_registry_scripts.py -q`: 67 passed.
- `pytest -q`: 178 passed.
- `python .github/scripts/validate_plugins.py`: passed for 254 plugins.
- `git diff --check`: passed.

Notes:
- Installed open-source-maintainer reference files and triage script are still missing on disk, so this run used `gh-helper`, direct `gh`, local tests, and repository analysis.
- No public GitHub actions were taken.
- Recommended next public action is to commit/push the local validator hardening if it should be included before `v2.16.0`, then let Release Please refresh `PR:90`, approve/run the pending PR workflows, and merge it if they pass.

## 2026-07-06 - API bridge error response CI fix

Scope:
- Reviewed current GitHub state for `adrighem/PyPluginStore`.
- Active public items:
  - Open issues: `ISSUE:64`, `ISSUE:87`.
  - Open pull requests: `PR:90` Release Please for `v2.16.0`.
- `gh-helper` found no unread inbox, no Dependabot alerts, and no code scanning alerts.
- Investigated failing `Validate Plugins` workflow on `master`; the only failing test was `tests/test_ui_smoke.py::test_api_bridge_accepts_error_response_without_action` on Linux and Windows.

Prepared local changes:
- Updated `pollResponse()` in `pypluginstore.html` to accept same-transaction backend error responses that omit the `action` field.
- Preserved strict action matching for normal responses and stale-response cleanup through `clearApiBridgePayload()`.

Verification:
- `pytest tests/test_ui_smoke.py::test_api_bridge_accepts_error_response_without_action -q`: passed.
- `pytest -q`: 177 passed.
- `python .github/scripts/validate_plugins.py`: passed for 254 plugins.
- `git diff --check`: passed.

Notes:
- Installed open-source-maintainer reference files and triage script are still missing on disk, so this run used `gh-helper`, direct `gh`, local tests, and repository analysis.
- No public GitHub actions were taken.
- Recommended next action is to commit and push the CI fix, then rerun/watch `Validate Plugins` before merging `PR:90`.

## 2026-07-05 - PR:88 scan hardening and rerun

Scope:
- Reviewed `PR:88`, the automated weekly registry scan PR.
- Identified that GitHub discovery did not require a root-level `plugin.py`, while GitLab and Codeberg discovery already did.
- Closed `PR:88` after confirming it added non-plugin repositories such as `domoticz-mcp`, `wiki`, and `ha-domoticz-sync`.

Prepared local changes:
- Updated `.github/scripts/scan_github_plugins.py` so all discovery paths use the same root `plugin.py` gate.
- Added a defensive add-path check so future discovery sources cannot add a candidate without a root `plugin.py`.
- Added JSON request timeouts for scanner API calls.
- Reran the weekly scan with the improved logic.

Scan result:
- Added `Domoticz-Indevolt-plugin`.
- Updated five existing registry entries/metadata records.
- Skipped `domoticz-mcp`, `wiki`, `ha-domoticz-sync`, and similar repositories because they lack a root `plugin.py`.

Verification:
- `pytest -q`: 174 passed.
- `python .github/scripts/validate_plugins.py`: passed for 254 plugins.

Notes:
- Installed open-source-maintainer reference files are still missing on disk, so this run used the main skill contract, repo maintainer context, direct `gh`, and local repository analysis.

## 2026-07-01 - Git indicators and robust branch-aware updates

Scope:
- Active public items:
  - Open issues: `ISSUE:30`, `ISSUE:64`, `ISSUE:73`, `ISSUE:74`.
- Diagnosed `ISSUE:74` where non-Git/unmanaged plugins are displayed similarly to standard plugins in the UI, and added explicit `Non-Git` badges and update-disabling logic to make this clear.
- Diagnosed `ISSUE:73` where updates can fail or falsely report being up-to-date in detached HEAD or untracked local configurations, and updated `UpdatePythonPlugin` to check out and pull the registered branch explicitly.

Prepared local changes:
- `getInstalledPlugins` in `plugin_core.py` now populates and returns an `is_git` property inside `installed_match_details`.
- `UpdatePythonPlugin` in `plugin_core.py` now implements the robust fetch-and-reset flow (`git fetch origin`, `git diff --quiet`, `git checkout -B <branch> origin/<branch>`, `git reset --hard origin/<branch>`).
- `pypluginstore.html` now parses `is_git` and renders a `Non-Git` badge for unmanaged plugins, as well as disabling the Update button with a clear tooltip.
- Regenerated `plugin.py`.

Verification:
- `pytest`: 133 passed.
- `python3 .github/scripts/validate_plugins.py`: passed for all 328 plugins.

Notes:
- Product changes committed locally on master.
- Drafted responses to close both `ISSUE:74` and `ISSUE:73` upon approval.

## 2026-07-01 - Docker Git ownership bypass and Luxtronik registry integration

Scope:
- Reviewed current GitHub state for `adrighem/PyPluginStore`.
- Active public items:
  - Open issues: `ISSUE:30`, `ISSUE:64`, `ISSUE:70`.
  - Open pull requests: `PR:71`.
  - Latest release: `v2.14.0`, published on 2026-06-29.
- Investigated `ISSUE:70`, where Docker-based Domoticz restarts log-spammed because of Git ownership checks triggering `chown` recursively on the host, causing host file permissions friction.
- Evaluated `PR:71` by `Rouzax` pointing the Luxtronik plugin at its `dist` branch and changing its key/installation directory to `luxtronikex` to match its runtime key, while preserving its Windows support.

Prepared local changes:
- `handle_git_ownership_failure` in `plugin_core.py` now implements an automatic first-time Git retry with `-c safe.directory=<path>`. This allows Git commands inside the container to execute successfully without changing any host-level file ownership or permissions, resolving `ISSUE:70` cleanly and permanently and eliminating log spam.
- Fallback to the original `repair_git_repository_ownership` (chown) is preserved if the `safe.directory` retry still reports dubious ownership.
- Wrote robust mock-environment unit tests in `tests/test_plugin_update_status.py` verifying both successful `safe.directory` bypass (with zero `chown` calls) and chown fallback.
- Updated `registry.json` and `update_times.json` for Luxtronik to key `luxtronikex` and branch `dist`, keeping both Linux and Windows support.
- Updated `tests/test_ui_smoke.py` to write script content to temporary files rather than passing them via stdin, to ensure compatibility with Node/Bun shims on local machines.
- Regenerated `plugin.py` from `plugin_core.py`.

Verification:
- `pytest`: 133 passed.
- `python3 .github/scripts/validate_plugins.py`: passed for all 328 plugins.

Notes:
- Product changes committed locally on master.
- Drafted responses to close both `ISSUE:70` and `PR:71` upon approval.

## 2026-06-29 - Self-update timeout and Luxtronik Windows metadata

Scope:
- Reviewed current GitHub state for `adrighem/PyPluginStore`.
- Active public items:
  - Open issues: `ISSUE:30`, `ISSUE:64`, `ISSUE:69`.
  - Open pull requests: `PR:66`, `PR:68`.
  - Latest release: `v2.13.1`, published on 2026-06-29.
- Investigated `ISSUE:65`, where self-update timed out in the custom UI after logging the start of the update.
- Fetched `PR:66` as `origin/pr/66`; its registry-only diff matches the local metadata change.
- Kept `ISSUE:64` as an RFC/backlog item because release/archive update support is broader than this maintenance pass.
- Noted new `ISSUE:69`, where update discovery still may not show the latest release to the reporter.

Prepared local changes:
- Self-update now runs pre-flight checks before scheduling any file mutation.
- Pre-flight rejects dirty tracked files, missing upstreams, diverged/local-commit branches, missing required candidate files, and invalid Python syntax in the candidate runtime files.
- Self-update now schedules a detached helper that repeats the clean tracked-file check and applies the update with `git merge --ff-only` after the UI bridge has received a response.
- Self-update helper output goes to `self_update.log`.
- The custom UI displays backend success messages and skips immediate list reload only for PyPluginStore self-update.
- `luxtronik-domoticz-plugin-v2` now advertises both `linux` and `windows` platform support via local commit `1814323`, preserving the PR author.
- Regenerated `plugin.py` from `plugin_core.py`.

Verification:
- `pytest -q`: 130 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.
- `python .github/scripts/validate_plugins.py`: passed for 328 plugins after the PR66 registry update.

Notes:
- Installed open-source-maintainer skill references and triage script are still missing on disk, so this run used direct `gh` and local repository analysis.
- Pushed `ISSUE:65` fixes as `47e2d73` and `28c7f43`; master workflows passed.
- No public comments, issue closes, or PR closes were taken in this cleanup pass.
- Recommended next action is to investigate `ISSUE:69` before merging release-please `PR:68`.

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
