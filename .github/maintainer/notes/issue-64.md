# ISSUE:64 - RFC: Support Release-Based & Archive (ZIP) Plugin Updates

Status: open; implementation complete locally and ready for review/push.

Author:
- `adrighem` opened the RFC on 2026-06-29.

Intent:
- Add non-git install/update strategies so PyPluginStore can install GitHub releases or arbitrary ZIP archives.
- Track installed archive metadata locally because archive installs do not have `.git`.
- Prefer stable release artifacts over branch tips where plugin authors publish releases.

Assessment:
- Release archives should be the preferred delivery path when repository automation has validated and checksum-pinned a stable release.
- Forge discovery belongs in scanner automation. Runtime hosts should consume a normalized `release_index.json`, avoiding API-rate and provider-specific behavior.
- Git remains supported for plugins without a validated release and as an explicit channel. Failed release verification must never silently fall back to Git.
- Existing Git installs migrate during their normal update transaction only after clean-tree, ancestry, preservation, staging, and rollback checks pass.
- The authenticated rollout scan certified 47 of 257 registry records: 46 GitHub releases and one GitLab release. It found no eligible release for 208 entries, rejected one unsafe archive, and retained one provider failure. Both Codeberg/Forgejo entries currently have no published release; Gitea and generic have no registered pilot entry.
- The largest risks are untrusted ZIP extraction, preserving plugin-local runtime data, release mutation, Windows locks, and accidentally downgrading a branch-ahead checkout.

Implementation:
- Release-first selection, safe ZIP staging, dependency snapshots, rollback, UI status/actions, and Git-to-release migration are implemented in the Conductor track.
- Migration preflight is read-only and forge-neutral. Automatic migration requires a clean equal/descendant checkout; manual migration uses one-use content-bound approval for local data and ahead/diverged replacement.
- The initial reviewed `release_index.json` contains 47 commit-addressed source archives. Git remains the fallback before Release activation and an explicit choice for existing Git checkouts; release-managed failures remain fail-closed.

Recommended next step:
- Review and push the local commits, let the weekly report/PR workflow refresh the expiring index, and monitor the GitHub/GitLab pilot before expanding coverage.
- Add live Codeberg/Forgejo or Gitea entries only when registered plugins publish suitable releases; keep their contract fixtures as the gate until then.

Architecture:
- `conductor/tracks/release_first_plugin_management_20260718/spec.md`

Public action:
- None taken.

Verification:
- `pytest -q`: 1109 passed.
- `python .github/scripts/validate_plugins.py`: passed for the 257-record registry.
- `yamllint .github/workflows`, generated `plugin.py` freshness, Python compilation, and `git diff --check`: passed.
- Manual Linux, Windows, and Domoticz verification was waived by the user; automated Linux/Windows transaction paths remain covered.
