# Manager Runtime Identity and Coherence

## Context

PyPluginStore can expose three different generations at once:

- Git has updated the installed files.
- Domoticz still runs Python loaded before that update.
- Domoticz or the browser still serves an older copied custom page.

The current installed-version label is read from `plugin.py` on disk, so it can
show the new release even while the backend or custom page is older. The custom
page is copied to `www/templates` using file modification times rather than
content identity.

## Goals

- Give releases and arbitrary Git updates one manager identity contract.
- Keep the semantic product version for users.
- Use a deterministic SHA-256 build ID for exact runtime equality.
- Report Git `HEAD`, when available, as diagnostic provenance rather than the
  equality key.
- Compare the browser page, deployed Domoticz template, loaded backend, and
  installed files.
- Surface all coherence and self-update guidance through
  `#pypluginstore-status`.
- Keep the UI read-only when an identity-aware page does not match the backend
  or installed files, while preserving status and restart recovery.

## Functional Requirements

### Identity contract

- Identity schema v1 contains `product_version`, `build_id`, and optional
  `git_commit`.
- The build ID hashes a fixed, framed allowlist of runtime files:
  `plugin.py`, `package_registry.py`, `package_identity.py`, and
  `pypluginstore.html`.
- The loaded backend identity is captured once before detached self-update can
  change files on disk.
- The installed identity is recalculated from the manager folder.
- Missing, symlinked, oversized, or unreadable identity files produce an
  explicit unverifiable state, never a match.
- A Git-only change that leaves the runtime bundle unchanged remains coherent;
  the different Git commit is informational.

### Custom-page deployment

- The source HTML contains a valid development identity placeholder.
- Startup injects the frozen backend identity into captured source HTML.
- Startup compares the desired rendered bytes with the deployed template,
  rather than comparing mtimes.
- Template writes are atomic and preserve the previous complete file on error.
- The deployed template identity and exact rendered-byte match are included in
  the backend verdict.

### API and mutation safety

- Every frontend command includes the identity embedded in the running page.
- Existing `list_plugins` performs the healthy-path page-load handshake without
  an additional bridge round trip.
- API responses include the current manager identity verdict.
- Identity-aware mismatched clients cannot install, update, remove, roll back,
  switch release channel, or mutate the Local registry.
- Read-only operations, self-update status, and Domoticz restart remain
  available for diagnosis and recovery.
- Legacy clients without an identity remain compatible for read-only status and
  restart recovery during rollout, but mutations are rejected and the response
  identifies them as legacy.

### Frontend behavior

- `#pypluginstore-status` always carries manager version/coherence and
  self-update guidance.
- A coherent page shows a concise version, build, and optional Git revision.
- Mismatch messages distinguish restart required, custom-page deployment
  failure, browser hard-refresh required, update in progress, and unverifiable
  installation.
- Mutating controls are disabled while an identity-aware mismatch exists.
- The `self-update-detail` card span, its styles, renderer, and call sites are
  removed completely.
- The existing compact self-update badge may remain, but it must not carry the
  detailed guidance.

### Self-update integration

- Scheduled or running self-update is reported as update in progress.
- After the helper changes runtime bundle files, the old backend reports restart
  required.
- When a helper update changes only Git provenance or other non-runtime files,
  the matching runtime and installed build IDs remain coherent without restart.
- After backend reload and template deployment, an old browser page reports
  hard-refresh required.
- Final self-update confirmation does not claim full coherence until the loaded
  backend and installed bundle agree.

## Acceptance Criteria

- A release version bump is visible in frontend, backend, and installed
  identities.
- A same-version Git code update changes the build ID and requires reload.
- A documentation-only Git update does not require reload.
- The sequence `A running -> B installed -> B loaded -> B browser` produces
  restart, refresh, then coherent states.
- A stale destination with a newer mtime is replaced by content.
- Old frontend/new backend and new frontend/old backend combinations fail
  safely and explain recovery in `#pypluginstore-status`.
- Identity-aware mismatches reject backend mutations even if JavaScript control
  disabling is bypassed.
- Focused backend, deployment, frontend, and self-update tests pass.
- `plugin.py` is regenerated and the complete sanitized test suite passes.

## Out of Scope

- Cryptographic authenticity or trusted-upstream attestation.
- Replacing the Domoticz text-device API bridge.
- Automatically restarting Domoticz or force-reloading the browser.
- Treating documentation, registry data, or development scripts as runtime
  identity inputs.
