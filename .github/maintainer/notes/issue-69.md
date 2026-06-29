# ISSUE:69 - new update not seen ...

Status: open; needs investigation.

Reporter:
- `Eddie-BS` reported on 2026-06-29 that recent releases were not detected by the installed plugin.

Intent:
- PyPluginStore should show that a newer manager release/update is available without requiring a manual `git pull`.

Assessment:
- The report arrived after the `v2.13.1` release and after the self-update timeout fixes.
- The reporter says `2.13` was obtained manually with `git pull`, which suggests update discovery, cached update status, or the self-update path may still be failing in at least one real installation.
- This should be investigated before merging the next release-please PR, because it may affect whether users can discover or apply the new fix.

Recommended next step:
- Reproduce update discovery from an installed `v2.13.0`/`v2.13.1` checkout.
- Check whether the manager's own update status is refreshed after releases and whether cached `update_times.cache.json` values can hide a new release.
- Ask for the plugin log only if local reproduction does not show the failing path.

Public action:
- None taken.
