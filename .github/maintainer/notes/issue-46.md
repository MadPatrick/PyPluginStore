# ISSUE:46 - Installed plugins not marked installed after v2.11.0

Status: open; local fix prepared.

Reporter:
- MadPatrick reported that after updating from `v2.9.1` to `v2.11.0`, some plugins were no longer marked as installed.
- Report included screenshots comparing `v2.9.1` and `v2.11.0`.

Intent:
- Restore installed-state compatibility for plugins that were installed before the v2.11.0 pre-existing install detection work, including installs whose local folder name differs from the registry key.

Assessment:
- Regression was introduced by `4cdf56a` (`feat: detect pre-existing plugin installs`), released in `v2.11.0`.
- The new detection path required readable/matching Domoticz `plugin.py` metadata before marking a registry-known folder as installed.
- In `v2.9.1`, a folder with the registry key was treated as installed directly.
- Screenshot comparison showed `APC_UPS`, `Bmw`, `HP_iLo`, `Solaredge_modbustcp`, and `Somfy` visible as installed in `v2.9.1` but missing in `v2.11.0`.
- The missing cards point to both exact-key compatibility and flexible folder-name detection. Examples include local aliases such as `APC_UPS` pointing to a repository folder like `domoticz-apc-ups-plugin`, and punctuation/case variants such as `HP_iLo` vs `Domoticz_HP_ilo`.

Local fix:
- Installed detection now uses confidence tiers:
  - matching git remote URL;
  - matching `plugin.py` `externallink`;
  - exact registry-key folder;
  - unique repository/archive folder name, including flexible punctuation/case normalization;
  - unique `plugin.py` key/name metadata.
- A recognized `plugin.py` `externallink` now overrides exact folder-key and folder-name inference, but not a matching git remote.
- Git repositories with an unmatched remote can still continue through exact folder-key, repository/archive folder, flexible folder, and metadata key/name matching.
- Unknown `plugin.py` `externallink` values no longer block later exact folder-key or metadata key/name matching.
- Unique repository/archive folder matching also indexes Domoticz-affix-stripped names. For example, `APC UPS-main` can match repository `Domoticz_apc_ups_plugin` on branch `main`.
- Flexible folder-name matching in the plugin and plugin-name cleanup in the UI should be maintained together. The accepted install folder variants should match the names users see in the UI to avoid confusing mismatches.
- Ambiguous normalized matches are rejected.
- Inferred folder matches with clearly conflicting metadata are skipped, then matching continues to later tiers such as unique `plugin.py` key/name metadata.
- Matching now uses structured candidate evidence internally, including source, priority, and a short detail string.
- `getInstalledPlugins()` stores match details for registry matches and unmanaged local folders; API responses include `installed_match_details` for support/debugging.
- Added regression coverage for exact folders without metadata, exact folders with conflicting metadata, recognized externallinks overriding exact folders, repository-named folders without metadata, flexible punctuation variants, local alias-to-repo-folder matches, Domoticz-affix-stripped branch folder matches, git remotes without metadata, git remotes overriding conflicting externallinks, unmatched git remotes falling back to externallink, unmatched git remotes continuing to exact/repository-folder matching, unknown externallinks continuing to metadata key/name matching, invalid folder inference falling back to metadata key/name matching, externallink matches, metadata key/name matches, ambiguous normalized names, selected match source details, local-folder details, and API diagnostics.
- Regenerated `plugin.py` from `plugin_core.py`.

Verification:
- `pytest -q`: 95 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.

Recommended next step:
- Ship the local fix as a patch release.
- After approval, comment on `ISSUE:46` explaining that installed detection now prefers git remotes, then recognized externallinks, then exact keys, repo-folder aliases, Domoticz-affix-stripped folder names, and plugin metadata while still rejecting ambiguous matches.
