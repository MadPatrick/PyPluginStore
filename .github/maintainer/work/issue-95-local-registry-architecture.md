# Issue 95 Local Registry Management Architecture

Status: implemented; automated verification passed; awaiting manual UI verification

Decision date: 2026-07-16

Issue: [ISSUE:95](https://github.com/adrighem/PyPluginStore/issues/95)

## Intent

Let users create, inspect, edit, and delete `registry_local.json` entries from the PyPluginStore UI without exposing the complete JSON document to the browser for replacement.

This is a registry CRUD and persistence feature, not only a settings form. It must preserve the public-registry overlay behavior, prevent accidental data loss, and leave malformed or concurrently edited files untouched.

## Approved Product Decisions

- Add a visible **Local registry** button to the page header. Do not hide the only management action in a three-dot menu.
- Open one native `<dialog>` and switch between entry-list and entry-form views. Do not nest dialogs.
- Keep a plugin key immutable while editing. Renaming requires creating a new entry and deleting the old one.
- Use one host-agnostic **Repository source** field instead of separate owner and repository inputs.
- Include only these form fields:
  - Plugin key
  - Repository source
  - Description
  - Branch, defaulting to `master`
- Do not expose or persist platform controls for UI-created or UI-edited entries. They normalize to unknown.
- Allow users to select an existing public plugin and prefill its key, repository source, description, and branch before creating an override.
- Validate locally when saving. Do not contact the repository automatically.
- Allow deletion of an installed plugin's local override after warning that the plugin remains installed and may become **Repo mismatch**.
- If `registry_local.json` is malformed, show its path and parse error and keep the manager read-only. Do not include a raw JSON recovery editor in v1.
- Protect every mutation with a registry revision. Reject stale writes and offer **Reload entries**.
- Save changed entries in canonical object format while preserving untouched entries' existing list/object structure and insertion order. Whole-file whitespace may be normalized.
- When the last entry is deleted, persist a valid `{}` document rather than removing the file.

## Non-Goals for v1

- Raw JSON editing, upload, or download.
- Automatic repository access or branch verification.
- Repository credential management.
- Platform selection or platform detection.
- Plugin-key renaming.
- Bulk import, bulk edit, or whole-document replacement.
- Automatically installing a newly added registry entry.
- Automatically removing an installed plugin when its override is deleted.

## Architecture Overview

```text
Local registry dialog
        |
        v
get / upsert / delete API actions
        |
        v
LocalRegistryService
  - structured reads and parse errors
  - validation and canonicalization
  - revision checks
  - atomic persistence
        |
        v
registry_local.json
        |
        v
Reapply cached public registry + local overrides
        |
        v
Reload plugin cards
```

The browser sends one entry per mutation. It never sends the complete local registry back to the plugin. This keeps requests below `API_PAYLOAD_MAX_LENGTH` and makes the backend authoritative for validation, conflict detection, and persistence.

## Backend Components

### `LocalRegistryService`

Add a focused service beside `RegistryService`. Keep `BasePlugin.handleApiCommand()` responsible only for dispatch and response construction.

Responsibilities:

- Read the exact local-registry bytes and parse the top-level object.
- Distinguish a missing file, an empty object, malformed JSON, an invalid top-level value, and a valid registry.
- Calculate a revision from the exact stored bytes.
- Convert supported legacy list/object entries into the UI representation.
- Validate and canonicalize one changed entry.
- Create, update, or delete one entry without rebuilding untouched entry values.
- Verify the expected revision immediately before writing.
- Persist through the existing atomic-write primitive.
- Return the updated document and revision only after persistence succeeds.

Suggested structured read result:

```python
LocalRegistryDocument(
    entries={},
    revision="sha256:...",
    exists=True,
    writable=True,
    error="",
)
```

A missing file is a valid empty registry with a deterministic missing-file revision. A malformed file is not an empty registry and must never enter a mutation path.

### Atomic persistence

Reuse and extend `HostRuntime.write_json_atomic()`:

1. Serialize the complete next document to a temporary file in the plugin directory.
2. Finish and close the temporary file.
3. Replace `registry_local.json` with `os.replace()`.
4. Remove a leftover temporary file after a failed write when possible.

Allow the helper to preserve insertion order for the local registry rather than forcing key sorting. JSON indentation and whitespace may be normalized. If writing or replacing fails, report the filesystem error and do not alter in-memory registry state.

### Public-registry cache and reapplication

Refactor registry loading into two concerns:

1. Fetch or load the selected public registry and retain its raw mapping as the current base registry.
2. Apply a supplied local mapping over that base and normalize the merged result.

`fetch_registry()` continues to refresh the public source and update-time data. A successful local mutation reuses the cached public mapping and applies the new local document without another network request.

This is required for correct deletion behavior: deleting a local override must immediately reveal the original public entry again. If no usable public cache exists, fall back to the existing full registry-fetch path.

## Local Entry Model

### UI representation

```json
{
  "key": "MyPlugin",
  "repository_source": "https://github.com/example/domoticz-my-plugin",
  "description": "Local plugin override.",
  "branch": "main",
  "overrides_public": false,
  "installed": false,
  "valid": true,
  "errors": []
}
```

`overrides_public`, `installed`, `valid`, and `errors` are derived response metadata and are not written to disk.

### Canonical persisted representation

```json
{
  "MyPlugin": {
    "owner": "https://github.com/example/domoticz-my-plugin",
    "description": "Local plugin override.",
    "branch": "main"
  }
}
```

Store the complete source in `owner` and omit `repository`. This is already supported by the registry normalization and clone-URL paths and works for HTTPS, SSH, hosted-path, and `file://` sources.

Do not write `platform` or `platforms`. If an existing entry containing platform metadata is edited through the UI, the newly canonicalized entry drops that metadata and therefore normalizes to unknown. Untouched legacy entries retain their current values and representation.

### Repository source examples

- `https://github.com/owner/repository`
- `git@github.com:owner/repository.git`
- `gitlab.com/group/repository`
- `codeberg.org/owner/repository`
- `file:///srv/git/repository.git`

Do not encourage embedding usernames, passwords, or access tokens in repository URLs. Private access should use SSH keys or the Git credential configuration of the Domoticz OS user.

## Validation

All validation is authoritative on the backend. Frontend validation only improves feedback.

### Plugin key

- Reuse `HostRuntime.validate_plugin_key()`.
- Trim surrounding whitespace.
- Reject an empty key, path separators, `.`/`..`, leading `.`, control characters, and excessive length.
- On update, require the submitted key to match the existing key.
- On create, reject a key already present in the local registry.

### Repository source

- Require a non-empty string.
- Reject NUL and control characters.
- Accept the source shapes already supported by `build_git_clone_url()`, including arbitrary HTTP(S), SSH, Git scp-style, supported hosted paths, and `file://` URLs.
- Reject embedded HTTP(S) credentials to avoid persisting secrets through the UI.
- Enforce a length that leaves the complete command payload below `API_PAYLOAD_MAX_LENGTH`.
- Do not call Git or the network while validating.

### Description and branch

- Description is optional, trimmed, and length-limited.
- Branch defaults to `master` when blank.
- Reject control characters and excessive length in a branch.
- Keep values as Git arguments; never construct shell command strings.

Suggested limits should be tested against the serialized API payload rather than chosen independently. A practical starting point is 128 characters for a key, 1,000 for a repository source, 500 for a description, and 255 for a branch.

## Revision and Concurrency Contract

Use a SHA-256 digest of the exact file bytes as the revision. Use a distinct deterministic revision for a missing file so missing and `{}` are distinguishable states.

Every mutation includes `expected_revision`. The service rereads the file and compares revisions immediately before creating the next document. A mismatch returns a conflict without writing.

Conflict response:

```json
{
  "status": "error",
  "action": "upsert_local_registry_entry",
  "code": "registry_conflict",
  "message": "registry_local.json changed after it was loaded.",
  "reload_required": true
}
```

The dialog keeps the user's form values visible and offers **Reload entries**. It must not retry a stale mutation automatically.

## API Contract

Add explicit local-registry actions to `handleApiCommand()`.

### `get_local_registry`

Request:

```json
{
  "action": "get_local_registry"
}
```

Successful response:

```json
{
  "status": "success",
  "action": "get_local_registry",
  "entries": [],
  "revision": "sha256:...",
  "path": "/path/to/registry_local.json"
}
```

Malformed-file response:

```json
{
  "status": "error",
  "action": "get_local_registry",
  "code": "invalid_local_registry",
  "message": "Expected property name at line 4 column 1.",
  "path": "/path/to/registry_local.json",
  "read_only": true
}
```

### `upsert_local_registry_entry`

Use one action for create and update while keeping the operation unambiguous:

- `original_key` is omitted or empty for create. The key must not already exist locally.
- `original_key` is present for update. It must exist and equal `entry.key`.

Request:

```json
{
  "action": "upsert_local_registry_entry",
  "expected_revision": "sha256:...",
  "original_key": "MyPlugin",
  "entry": {
    "key": "MyPlugin",
    "repository_source": "git@github.com:example/domoticz-my-plugin.git",
    "description": "Local override.",
    "branch": "main"
  }
}
```

Successful response:

```json
{
  "status": "success",
  "action": "upsert_local_registry_entry",
  "plugin_key": "MyPlugin",
  "revision": "sha256:..."
}
```

### `delete_local_registry_entry`

Request:

```json
{
  "action": "delete_local_registry_entry",
  "expected_revision": "sha256:...",
  "plugin_key": "MyPlugin"
}
```

Reject missing keys rather than silently succeeding. After deleting the final entry, atomically write `{}`.

After a successful mutation, the UI reloads plugin data through the existing list flow so badges, public overrides, installed matching, and repo-mismatch state are rendered from backend truth.

## User Interface

### Entry point

Add a visible **Local registry** button in the existing header action group, before refresh and restart actions.

### Dialog structure

Use one native `<dialog aria-labelledby="local-registry-title">` with:

- A heading and explicit close button.
- A status/error region.
- An entry-list view.
- An entry-form view.
- No nested modal or custom focus trap.

The native dialog provides modal focus containment, Escape handling, and focus restoration. Preserve a clear close path for pointer and keyboard users. Warn before discarding a dirty form.

### Entry-list view

- Sort entries by plugin key for display without changing file order.
- Show key, repository source, and branch.
- Mark public overrides and installed entries.
- Provide **Add entry**, **Edit**, and **Delete** controls.
- Disable all mutation controls when the file is malformed or not writable.
- Offer **Reload entries** after a revision conflict.

### Add flow

Offer two starting points inside the form view:

1. Select an existing public plugin to create an override. Populate the form from the already loaded public plugin cache.
2. Start with a blank entry for a private or otherwise unpublished plugin.

Selecting a public plugin prefills the key, repository source, description, and branch. The user can then change the source, description, or branch. The key becomes immutable once the entry is created.

### Delete flow

Always confirm deletion. If the entry is installed, explain:

- The installed plugin directory will not be removed.
- The public registry entry, if any, becomes active again.
- The installed checkout may then show **Repo mismatch**, which disables managed updates until configuration matches.

After confirmation, send the current revision with the delete request.

### Error presentation

- Put field validation beside the affected input.
- Use a dialog-level `role="alert"` for persistence, permission, parse, or conflict errors.
- Keep the form populated after a failed save.
- Do not rely on browser alerts for validation errors.

Reuse the existing Domoticz-derived theme variables so the dialog follows default and custom themes.

## Failure Handling

| Failure | Required behavior |
| --- | --- |
| Missing file | Show an empty writable registry and create the file on first save. |
| Empty `{}` file | Show an empty writable registry. |
| Malformed JSON | Show path and parse error; disable mutations; never overwrite. |
| Non-object top level | Treat as malformed and remain read-only. |
| Invalid legacy entry | Show the affected key and validation errors; allow deletion or best-effort repair; never silently drop it or block unrelated valid entries. |
| Permission denied | Keep disk and in-memory state unchanged; show the failing path. |
| Revision conflict | Keep form values; require reload before another mutation. |
| Invalid entry | Keep form values and show field-specific errors. |
| Registry reapply failure | Report failure and reload from disk; never claim success with stale cards. |

## Security Boundaries

- This feature has the same effective authority as existing install, update, and remove commands sent through the Domoticz API bridge.
- Keep request-size enforcement in place.
- Never interpolate form values into shell command strings.
- Do not log repository URLs containing credentials. Prefer rejecting HTTP(S) userinfo entirely.
- Do not expose arbitrary filesystem writing; the service always targets `get_local_registry_file()`.
- Do not allow the browser to supply a file path.
- Keep plugin-key path validation on every mutation, even though the key is only registry data at save time.

## Test Plan

### Backend service tests

- Missing file returns an empty document and stable missing-file revision.
- `{}` returns an empty document with a file revision.
- Object and legacy list entries convert to the expected UI representation.
- Malformed JSON and non-object roots return structured read-only errors.
- Create writes a canonical object entry.
- Update preserves the immutable key and canonicalizes only that entry.
- Delete preserves untouched entry representations and insertion order.
- Deleting the final entry writes `{}`.
- No changed entry contains platform metadata.
- Invalid keys, sources, descriptions, and branches do not write.
- Stale revisions do not write.
- Atomic-write and replace failures preserve the original file.
- Embedded HTTP(S) credentials are rejected.

### Registry integration tests

- Adding a local entry updates `local_plugin_keys` and merged plugin data.
- Adding an override replaces the public definition in memory.
- Deleting an override restores the cached public definition.
- Deleting an installed override can produce repo-mismatch state without removing the plugin.
- Local mutations do not fetch the remote registry when a public cache is available.
- Full registry refresh updates the public cache used by later mutations.

### API tests

- Get, create, update, and delete dispatch to the service correctly.
- Success responses include the new revision.
- Validation, malformed-file, permission, and conflict errors use stable error codes.
- Create cannot overwrite an existing local key.
- Update cannot rename a key or update a missing key.
- Requests remain below `API_PAYLOAD_MAX_LENGTH` at accepted field limits.

### UI tests

- The visible header button and native dialog are present and labelled.
- List and form views switch without nested dialogs.
- Existing public plugins prefill the form.
- Edit keeps the key disabled or read-only.
- No platform controls exist.
- Save and delete include the current revision.
- Installed deletion displays the mismatch warning.
- Malformed-file and permission responses disable mutations.
- Conflict errors preserve form data and expose **Reload entries**.
- JavaScript syntax checks continue to pass.
- Theme smoke tests cover dialog variables under the existing theme derivation path.

### Generated artifact and full verification

- Edit `plugin_core.py`, then regenerate `plugin.py` with `.github/scripts/generate_plugin.py`.
- Run the focused backend and UI tests.
- Run the complete pytest suite.
- Run Python compilation checks for `plugin_core.py`, `plugin.py`, and the generator.
- Run `git diff --check`.

## Implementation Slices

### Slice 1: Persistence service

- Add structured local-registry reads, revisions, validation, and atomic CRUD.
- Add focused service tests.
- Do not change the UI yet.

Checkpoint: backend tests prove malformed files, stale revisions, invalid entries, and failed writes cannot destroy existing data.

### Slice 2: Registry integration and API

- Split public-source loading from local-overlay application.
- Cache the selected public registry.
- Add get/upsert/delete API actions and response codes.
- Regenerate `plugin.py`.

Checkpoint: API tests prove add/edit/delete immediately update merged backend state and deletion restores public overrides.

### Slice 3: Dialog UI

- Add the visible header button and native dialog.
- Implement list/form views, public-entry prefill, immutable keys, revision handling, and deletion warnings.
- Add UI smoke and behavior tests.

Checkpoint: a manual browser pass verifies keyboard operation, narrow-screen layout, and blending with default plus representative custom Domoticz themes.

### Slice 4: Documentation and final QA

- Update `README.md` and `docs/registry_local.md` to make the UI the primary workflow while retaining the file format as an advanced/manual option.
- Complete full-suite, generated-file, syntax, and diff verification.

Checkpoint: the feature is ready for a conventional issue-referenced commit, but commenting on or closing `ISSUE:95` remains a separate approved public action.

## Acceptance Criteria

- Users can list, add, edit, and delete local-registry entries without editing JSON.
- UI-created or edited entries contain no platform metadata.
- Public entries can seed a new override.
- Editing cannot rename a key.
- Saving never performs repository network access.
- A malformed file, stale revision, invalid entry, or failed write cannot overwrite valid existing content.
- Deleting the last entry leaves `{}`.
- Deleting an override immediately restores the public entry in the UI.
- Installed plugins are never removed as a side effect of registry management.
- Backend and frontend errors are actionable and preserve user-entered form data.
- Existing manual `registry_local.json` files remain compatible.

## Confidence and Remaining Risk

Confidence is high in the service and API boundaries because they extend the existing registry merge, command dispatch, and atomic JSON patterns.

The main implementation risks are:

- Domoticz installations where the plugin directory is readable but not writable.
- Existing local registries containing unusual but currently tolerated legacy values.
- Response size and browser behavior with very large local registries.
- Theme-specific dialog styling across older custom Domoticz themes.

These risks are covered by structured errors, per-entry requests, preservation of untouched values, focused tests, and a manual theme/browser checkpoint before shipping.

## Implementation Record

- `35b30ec` adds the revisioned persistence service and failure-path tests.
- `b147193` adds public-registry caching, overlay reapplication, and CRUD API actions.
- `697d93d` adds the accessible native dialog and UI behavior tests.
- Full verification on 2026-07-16 passed with 226 tests, Python compilation, generated-runtime freshness, registry validation, and `git diff --check`.
- `pytest-cov` is not installed in the repository environment, so no percentage coverage report was produced; focused persistence, API, integration, and UI branches are covered directly.
