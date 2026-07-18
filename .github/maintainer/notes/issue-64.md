# ISSUE:64 - RFC: Support Release-Based & Archive (ZIP) Plugin Updates

Status: open; implementation-ready architecture and backlog.

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
- The 2026-07-18 registry baseline found only 54 of 256 entries reporting a latest stable release candidate (about 21%); archive layout and plugin identity are not yet certified, so release preference must roll out per validated index entry rather than through a global mode switch.
- The largest risks are untrusted ZIP extraction, preserving plugin-local runtime data, release mutation, Windows locks, and accidentally downgrading a branch-ahead checkout.

Recommended next step:
- Implement the phased Conductor track at `conductor/tracks/release_first_plugin_management_20260718/`.
- Start with contracts and report-only multi-forge release resolution. Do not change runtime install behavior until the generated index and safe ZIP pipeline are independently validated.
- Pilot certified GitHub and GitLab entries, validate Codeberg/Forgejo and Gitea adapters independently, and activate those providers when suitable registered releases exist.

Architecture:
- `conductor/tracks/release_first_plugin_management_20260718/spec.md`

Public action:
- None taken.
