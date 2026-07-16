# Local Registry UI Management

## Context

Issue #95 asks PyPluginStore to manage `registry_local.json` through the custom UI instead of requiring users to edit JSON. The approved detailed architecture is recorded in `.github/maintainer/work/issue-95-local-registry-architecture.md` and is authoritative for this track.

## Goals

- Let users list, add, edit, and delete local registry entries from the UI.
- Keep local registry persistence atomic and protect mutations with byte-based revisions.
- Preserve malformed files and untouched legacy entry representations.
- Reapply local overrides over the cached public registry without an unnecessary network request.
- Use a visible header action and one accessible native `<dialog>` for list and form views.
- Keep backend validation authoritative and error responses actionable.

## Acceptance Criteria

- Missing and empty local registries are writable; malformed registries remain read-only.
- Create and update write one canonical object entry without platform metadata.
- Update cannot rename a key; delete cannot silently ignore a missing key.
- Stale revisions and persistence failures leave the existing file unchanged.
- Deleting an override immediately restores the cached public entry.
- API actions expose entries, revisions, paths, stable error codes, and field errors.
- The UI preserves form values after errors and supports keyboard-native dialog behavior.
- Deleting an installed override warns that the plugin remains installed and may become a repository mismatch.
- Documentation presents the UI as the primary workflow and JSON editing as the advanced workflow.
- `plugin.py` is regenerated and the complete test suite passes.

## Out Of Scope

- Raw JSON editing, upload, download, or bulk replacement.
- Repository access, branch verification, or credential management while saving.
- Platform selection, plugin-key renaming, or automatic install/removal.
- Any new framework or dependency.
