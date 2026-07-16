# ISSUE:95 - Manage registry_local via the UI

Status: implemented and manually verified; awaiting push and public follow-up approval.

Intent:
- Let users manage local registry entries without editing JSON.
- Preserve manual-file compatibility and prevent stale, malformed, or failed writes from losing data.

Implementation:
- Added exact-byte revisions, atomic CRUD persistence, structured validation errors, and cached public-overlay reapplication.
- Added a visible Local registry action and one accessible native dialog with list/form views, public-entry prefill, immutable keys, inline deletion confirmation, and conflict reloads.
- Made the UI workflow primary in README and registry-local documentation.

Verification:
- `pytest -q`: 226 passed.
- Python compilation: passed.
- Generated `plugin.py`: current.
- Registry validation: passed.
- `git diff --check`: passed.
- Manual UI verification on pietje: passed for add, edit, delete, responsive layout, and theme behavior.
- Percentage coverage unavailable because `pytest-cov` is not installed; focused tests cover the new service, API, integration, and UI branches.

Public action:
- Push is approved as part of the implementation workflow.
- Issue commenting or closure remains approval-gated.
