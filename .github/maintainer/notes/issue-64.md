# ISSUE:64 - RFC: Support Release-Based & Archive (ZIP) Plugin Updates

Status: open; RFC/backlog.

Author:
- `adrighem` opened the RFC on 2026-06-29.

Intent:
- Add non-git install/update strategies so PyPluginStore can install GitHub releases or arbitrary ZIP archives.
- Track installed archive metadata locally because archive installs do not have `.git`.
- Prefer stable release artifacts over branch tips where plugin authors publish releases.

Assessment:
- The direction is valuable but broad: registry schema, install/update strategy selection, archive validation, rollback, metadata migration, and UI state all change.
- The RFC should stay as a design/backlog item while user-facing regressions are handled first.
- The biggest implementation risk is preserving current git behavior and installed-plugin detection for existing users.

Recommended next step:
- Keep open as an RFC.
- When picked up, split into smaller implementation issues:
  1. registry schema compatibility and parser tests;
  2. local `.pypluginstore.json` metadata read/write;
  3. archive download/extract/validate into a temporary folder;
  4. atomic replacement and rollback;
  5. update-status support for release/tag/archive strategies.

Public action:
- None taken.
