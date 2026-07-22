# Track Specification: Explicit Package Identities and Release Transitions

> Historical note (2026-07-22): The public **Use Git** action and explicit
> fallback choice described below were superseded by the current product
> policy. Intentional ongoing Git management now requires a Local registry
> override; legacy and rollback-created keep-Git holds remain internal safety
> state.

## Overview

Replace package-keyed public metadata with explicit, versioned `package_id`
records. Keep the PyPluginStore package identity, Domoticz runtime identity, and
repository identity distinct. Make the normal lifecycle from Git-only upstream
development to release-first ZIP delivery automatic when continuity can be
proved, while retaining Git as an explicit supported channel.

This track also closes the release identity-certification gap and the
pre-activation transaction cleanup defect exposed by `Domoticz-SMA-Inverter`.

## Background

The current `registry.json` is an object whose property names act as package
identifiers. Those identifiers are also called `plugin_key` throughout runtime
metadata even though Domoticz has its own `<plugin key="...">` runtime identity.
For `Domoticz-SMA-Inverter`, the package identifier is
`Domoticz-SMA-Inverter` while the Domoticz key is `SMA`. The weekly release
generator accepted an artifact that the runtime could not certify, and failure
cleanup then removed a directory required to persist the rollback journal.

The current release workflow does discover a newly published forge release for
an existing Git package. Commit-addressed forge source ZIPs are migration
eligible, but custom attached ZIPs are always marked ineligible even when they
can be tied safely to the release commit.

## Functional Requirements

### Versioned package registry

- Publish `registry.json` schema version 2 as an object with `schema_version`
  and a `packages` array. Every package is a named object containing an explicit
  immutable `package_id`; package IDs must not be JSON object property names.
- Remove positional registry records and the synthetic `Idle` record from the
  published schema.
- Store a provider-neutral canonical HTTPS repository URL and branch,
  description, platforms, delivery policy, and Domoticz identity
  in each package record. Do not retain the legacy owner/repository split.
- Represent the Domoticz runtime contract separately as `domoticz_key`. It is
  exact compatibility metadata, not a display name or repository heuristic.
- Reject exact or case-folded duplicate package IDs, duplicate normalized
  repository identities, and malformed or unknown schema fields before
  partially loading a registry.
- Preserve current package-ID values during migration except where they are not
  portable. Resolve the existing `Domoticz-Shelly-Plugin` /
  `Domoticz-Shelly-plugin` case-fold collision with a distinct ID for the newer
  Codeberg package, and map an existing installation using repository identity
  plus Domoticz key without renaming its physical folder.
- Expose normalized internal maps keyed by `package_id` to the existing UI and
  operation layer; the public serialized registry must remain record-based.

### Versioned release metadata

- Publish release-index schema version 2 with `releases` and `tombstones` record
  arrays containing explicit `package_id` fields; package IDs must not be JSON
  object property names.
- Bind the observed `domoticz_key` and `plugin.py` SHA-256 to each certified
  release so runtime validation repeats the exact CI contract.
- Rename persisted release install and transaction identity fields from
  `plugin_key` to `package_id` in their next schema versions.
- Keep the registry-byte digest, monotonic sequence, expiry, immutable release
  identity, artifact digests, and predecessor guarantees.

### Upgrade path

- New runtime code may read legacy schema-v1 registry, release-index, install
  metadata, transaction journals, and local-registry documents only at explicit
  migration boundaries. It must normalize them immediately to the v2 in-memory
  model.
- The repository publishes only v2 public metadata after cutover; it must not
  publish parallel legacy package-keyed documents.
- Trusted cached v1 registry/index byte pairs must remain readable until normal
  cache retention removes them; their bytes must not be rewritten because that
  would invalidate their digest binding.
- On first successful load, a valid host-local v1 `registry_local.json` must be
  backed up and atomically rewritten as v2. Failed validation must leave the
  original file untouched.
- V1 install metadata and transaction journals must be upgraded lazily and
  atomically when acted upon. Recovery must remain restart-safe.
- An older manager that encounters remote v2 metadata must retain its last
  trusted v1 pair and continue to support its Git-based self-update path, so it
  can upgrade to a v2-capable manager.

### Shared package and runtime identity certification

- Use one provider-neutral certifier in release generation and runtime staging.
- Certification must bind `package_id`, normalized repository identity,
  selected source path, and exact `domoticz_key` from the single root
  `plugin.py` tag.
- A missing identity may be proposed during initial onboarding, but release
  publication must not authorize the candidate until the proposed registry
  identity is present in the same reviewed metadata change.
- Once recorded, a Domoticz key change is a breaking compatibility event and
  must be blocked pending explicit review; names and folder heuristics cannot
  silently authorize it.
- The same rules must apply to GitHub, GitLab, Codeberg/Forgejo, Gitea, and
  generic HTTPS release descriptors.

### Automatic Git-to-release evolution

- A package retains the same `package_id` when its maintainer moves from branch
  development to releases. No registry identity rename is permitted or needed.
- `release_if_indexed` packages without a certified release use Git. When the
  weekly scan first certifies a stable release, new installs become
  release-first and existing Git installs receive a migration decision.
- Replace the artifact `migration_eligible` boolean with explicit migration
  evidence that distinguishes at least: commit-addressed source tree,
  source-equivalent attached ZIP, reviewed non-equivalent release asset, and no
  Git continuity proof.
- For attached ZIPs, automation must also certify the forge release commit and
  the corresponding commit-addressed source tree. Canonically equivalent
  selected trees may migrate automatically.
- A non-equivalent build ZIP may migrate automatically only when an explicit,
  reviewed registry policy and a validated release manifest bind it to the
  package, Domoticz key, repository, and immutable source commit. Otherwise it
  remains available for a manual reviewed channel switch only.
- Automatic migration must refresh only the configured Git remote metadata,
  prove that installed `HEAD` is equal to or an ancestor of the release source
  commit, and leave the working tree and current branch unchanged during
  preflight.
- Dirty, unknown, ahead, diverged, mismatched, submodule, or locked checkouts
  remain on Git with an actionable blocked state. An explicit keep-Git
  preference always wins.
- Notify-only mode reports the available channel transition without executing
  it; automatic-update mode executes only fully proven transitions.

### Transaction abort and recovery

- Separate canonical transaction path derivation from phase-specific filesystem
  validation so a journal remains loadable after payload cleanup.
- Persist an aborting phase before deleting pre-activation payloads, retain the
  operation container while its journal is retained, and persist `rolled_back`
  after cleanup.
- Abort must be idempotent and preserve the primary release error.
- Startup must safely repair legacy pre-activation journals whose staging
  operation directory was removed by the existing defect. It must not silently
  repair a transaction that may have changed live state.

## Non-Functional Requirements

- Runtime parsing and migration use only the Python standard library and remain
  compatible with supported Linux/Raspberry Pi and Windows Domoticz hosts.
- All metadata writes and state upgrades are atomic, fsync-backed where the
  existing state model requires it, symlink-safe, and fail closed.
- Provider adapters remain isolated from the normalized package, identity, and
  migration contracts.
- Weekly automation may retain a previously trusted release after transient
  provider failure, but must never publish a new runtime-incompatible entry.
- Public v2 output is deterministic and sorted by `package_id`.
- Public update-time records and CI-only platform-detection records must also
  use versioned arrays with explicit `package_id` fields rather than keyed maps.

## Acceptance Criteria

- `registry.json` and `release_index.json` contain no package identifiers as
  object property names and pass strict v2 validation.
- All current public registry records migrate losslessly to explicit package
  records, excluding the obsolete `Idle` sentinel.
- A simulated existing deployment with cached v1 public metadata, v1 local
  registry data, v1 install metadata, and a v1 transaction journal upgrades
  without losing package state or release history.
- The exact SMA artifact certifies as package `Domoticz-SMA-Inverter` with
  Domoticz key `SMA`, or is held on Git until that reviewed mapping is present;
  it never reaches a runtime-only identity failure.
- A package with no releases installs and updates through Git, then switches to
  Release after a later weekly scan without changing `package_id`.
- Clean Git checkouts migrate automatically for commit source ZIPs and
  source-equivalent attached ZIPs on every supported provider model.
- Unsafe or insufficiently proven transitions remain untouched and explain why.
- A staged identity failure records one reloadable rolled-back transaction and
  does not emit the secondary “path must be a real directory” error.
- Linux and Windows test matrices, generator freshness, registry validation,
  full release tests, and workflow-security checks pass.

## Out of Scope

- Automatically accepting a changed Domoticz runtime key.
- Silently selecting one of multiple unmanifested release assets.
- Falling back to Git after a release verification or activation failure.
- Release-based self-update for PyPluginStore itself.
- Preserving executable local modifications during automatic migration.

## Dependencies

- Existing hardened ZIP downloader/extractor, release provider adapters,
  release metadata store, migration preflight, and transaction manager.
- Existing Git-based PyPluginStore self-update path for old-deployment cutover.
