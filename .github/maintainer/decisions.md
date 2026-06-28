# Maintainer Decisions

## 2026-06-28 - Resolve new discovery and bridge regressions locally

Decision: implement a local fix batch for `ISSUE:52`, `ISSUE:53`, `ISSUE:54`, `ISSUE:55`, and `ISSUE:56` before taking public action.

Rationale:
- The missing-plugin reports are valid public registry gaps for live repositories with usable `plugin.py` files.
- The hidden API payload report is caused by the UI bridge searching only `used=true` devices; hidden Domoticz devices must still be discoverable for command transport.
- The Docker icon report is low-risk to improve with a root-relative image fallback while preserving the existing relative image path.
- The `ISSUE:46` follow-up shows that local registry aliases should prevail when they collide with public repository aliases; local overlays are explicit user intent.
- Scheduled update checks should not create error log lines for installed plugins whose git state cannot be checked. The UI can still show `unknown`.

Implementation notes:
- Added public registry entries for `Domoticz-SMA-SunnyBoy` and `NUT_UPS`, plus update timestamps from the current repository heads.
- `build_installed_plugin_lookup()` now prunes public lookup candidates when local registry candidates share the same lookup key.
- `choose_installed_plugin_match()` prefers local candidates when candidate evidence conflicts.
- `CheckForUpdatePythonPlugin()` now uses `getGitUpdateStatus()` and only notifies when status is `available`; `unknown` is debug-only.
- `pypluginstore.html` now queries `getdevices` with `used=all` and adds a fallback icon URL.
- `plugin.py` was regenerated from `plugin_core.py`.

Verification:
- `pytest -q`: 115 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.
- `python .github/scripts/validate_plugins.py`: passed for 324 plugins.

Public action:
- None yet. Requires approval before commenting on issues, closing issues, or merging/releasing.

## 2026-06-27 - Preserve and broaden installed plugin detection

Decision: use tiered installed-plugin detection that prefers matching git remotes first, then recognized `plugin.py` `externallink`, then exact registry-key folders, unique repository/archive folder names, and unique `plugin.py` key/name metadata.

Rationale:
- This preserves the pre-`v2.11.0` behavior for plugins installed by PyPluginStore under their canonical registry key.
- Some real plugin folders use local aliases or repository names rather than registry keys, especially local overlay entries.
- The actual git remote is the strongest available identity signal when it matches the loaded registry.
- A recognized `plugin.py` `externallink` is stronger than folder naming and can support private forks whose git remote is not in the public registry.
- The `ISSUE:46` screenshots show missing installed cards consistent with repo-folder aliases and punctuation/case variants.
- Ambiguous normalized matches should still be skipped, and inferred folder matches with clearly conflicting metadata should not be accepted as that inferred plugin.

Implementation notes:
- Matching git remotes no longer require `plugin.py` metadata.
- `plugin.py` `externallink` can identify an arbitrary local folder and overrides exact folder-key and folder-name inference when it points to a unique loaded registry entry.
- A git repo with an unmatched remote can continue through later folder and metadata matching.
- An unknown `plugin.py` `externallink` can continue through later exact folder-key and metadata key/name matching.
- If inferred repository/archive folder matching conflicts with local metadata, the inferred candidate is skipped and matching continues to later metadata key/name matching.
- Repository/archive folder names can match with flexible punctuation/case normalization when the result is unique.
- Repository/archive folder names also index Domoticz-affix-stripped forms, so `APC UPS-main` can match `Domoticz_apc_ups_plugin` on branch `main`.
- `plugin.py` key/name can identify an arbitrary local folder when the result is unique.
- Matching uses structured candidate evidence with source, priority, and detail fields; `match_installed_plugin_key()` remains as a string-returning compatibility wrapper.
- `list_plugins` and `refresh_update_status` responses include `installed_match_details` for diagnostics.
- `plugin.py` was regenerated from `plugin_core.py`.

Verification:
- `pytest -q`: 95 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.

Public action:
- None yet. Requires approval before commenting on `ISSUE:46` or shipping.

## 2026-06-20 - Implement local registry overlay from PR:32 intent

Decision: accept the feature direction from `PR:32` but implement it locally instead of merging the contributor branch.

Rationale:
- The feature helps users manage private, forked, or locally modified plugins from the same UI.
- The PR patch removed dynamic remote registry fetching, which would regress a core project feature.
- The PR documented `register_local.json` while implementing `registry_local.json`.
- The PR UI expected `local_plugins` from the backend, but the backend did not provide it.

Implementation notes:
- Shipped to `master` as `36f3bcf`.
- Keep remote `registry.json` fetch as primary source.
- Keep bundled `registry.json` as offline fallback.
- Overlay ignored `registry_local.json` entries after the public registry.
- Return `local_plugins` in API responses so the UI can show a Local badge.
- Support full Git clone URLs for private/local registry entries.
- Report git clone failures through the API instead of always returning install success.

Verification:
- `pytest -q`: 52 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.

Public action:
- Commented on and closed `PR:32`.
