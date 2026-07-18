# Release-First Plugin Installation and Updates

Issue: https://github.com/adrighem/PyPluginStore/issues/64

## Objective

Make stable release archives the preferred way to install and update plugins.
Keep Git fully supported for repositories without a usable release and for users
who explicitly choose Git. Existing Git installations must have a safe migration
path during the normal plugin upgrade flow.

The runtime must not encode a GitHub-only release model. GitHub, GitLab,
Codeberg/Forgejo, Gitea, and generic HTTPS release manifests must produce the
same normalized release descriptor before an artifact reaches a Domoticz host.

## Architectural Decision

Resolve releases centrally in repository automation and publish a generated
`release_index.json` beside `registry.json` and `update_times.json`.

- Forge adapters discover a stable release, resolve its tag to a commit, choose
  a ZIP artifact, download and validate it, and calculate its SHA-256 digest.
- `release_index.json` is target metadata: it records the commit-addressed URL,
  transport digest/length, release identity, canonical source tree, and archive
  layout accepted by maintenance.
- The runtime consumes this normalized index. It does not call forge APIs to
  discover public releases, so installations do not share unauthenticated API
  limits and provider behavior cannot leak into the UI.
- `registry.json` remains the source of repository identity and optional release
  policy. Existing list entries remain valid. Release activation follows the
  explicit predicate below; invalid metadata after activation is never mistaken
  for an ordinary Git-only entry.
- The bundled registry and release index form one fallback pair. A fetched pair
  replaces it only after complete schema, hash, freshness, and cross-reference
  validation, then both files are cached atomically.
- The index has a monotonic sequence and bounded freshness. These are operational
  staleness guards in v1, not cryptographic rollback protection.

This model deliberately resembles a small targets manifest: the curated index,
not a mutable tag or release URL by itself, authorizes the bytes installed by a
host.

## Normalized Release Index

The document and each entry must be self-contained and deterministic:

```json
{
  "schema_version": 1,
  "sequence": 42,
  "generated_at": "2026-07-18T08:00:00Z",
  "expires_at": "2026-07-25T08:00:00Z",
  "registry_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "plugins": {
    "ExamplePlugin": {
      "revision": 7,
      "release_id": "gitlab:group/example-plugin:v1.4.0",
      "supersedes": [
        "gitlab:group/example-plugin:v1.2.0",
        "gitlab:group/example-plugin:v1.3.0"
      ],
      "provider": "gitlab",
      "repository_identity": "gitlab.com/group/example-plugin",
      "version": "1.4.0",
      "tag": "v1.4.0",
      "released_at": "2026-07-18T07:00:00Z",
      "commit": "0123456789abcdef0123456789abcdef01234567",
      "artifact": {
        "kind": "source_zip",
        "provenance": "forge_source_archive",
        "migration_eligible": true,
        "url": "https://gitlab.com/api/v4/projects/group%2Fexample-plugin/repository/archive.zip?sha=0123456789abcdef0123456789abcdef01234567",
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "size": 123456,
        "tree_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "root_prefix": "example-plugin-v1.4.0",
        "source_path": "."
      }
    }
  }
}
```

Requirements:

- `sequence` must increase for every published index and `expires_at` limits the
  lifetime of remotely fetched metadata. `registry_sha256` is the SHA-256 of the
  exact published `registry.json` bytes, binding the validated pair without a
  platform-dependent JSON canonicalization step.
- `repository_identity` must match the registry entry after normalization.
- Public artifacts require HTTPS, a lowercase 64-character SHA-256 digest, a
  positive byte length, a stable release identity, and an immutable source
  revision. Forge entries require the tag's resolved commit SHA; a generic entry
  without one is not eligible for automatic migration from Git.
- `source_path` is a validated relative path for packaged subdirectories. The
  default is the source archive root after removing its single wrapper folder.
- `tree_sha256` hashes the validated artifact before local mutable files are
  overlaid. Compute each regular file's lowercase content SHA-256, then hash
  records of `NFC POSIX path + NUL + decimal size + NUL + file digest + LF`,
  sorted by UTF-8 path bytes. Directory entries, timestamps, and modes are
  excluded; Unicode-normalized and case-fold collisions are rejected.
- `root_prefix` records the wrapper observed by automation so runtime extraction
  cannot choose a different layout.
- `revision` is a curator-controlled, per-plugin monotonic integer. A higher
  revision must name a different accepted release; `supersedes` lists all earlier
  accepted identities on its channel so hosts can safely skip revisions. Scanner
  review rejects regressions, missing lineage, and forks.
- `version` and `released_at` are display metadata, not update-ordering inputs.
  A runtime update requires a higher revision; a lower revision is an explicit
  downgrade, never an automatic update.
- Forge-generated source archives are addressed by resolved commit. Their ZIP
  bytes may be recompressed by a provider, so `sha256` is transport integrity for
  the published index generation while commit plus `tree_sha256` is the source
  identity. Automation may refresh size/digest/root metadata without raising the
  plugin revision only after the canonical tree remains identical.
- For attached assets and generic artifacts, changed bytes for the same release
  identity are a mutation alert unless a new reviewed plugin revision is created.
  Any changed canonical tree at the same forge commit is always quarantined.
- Prereleases, drafts, upcoming releases, and tag-only snapshots are excluded by
  default. Registry policy may opt into a named non-stable channel later.

### V1 trust and fallback model

V1 trusts the TLS endpoint and the reviewed PyPluginStore repository distribution
channel for registry/index authenticity. Artifact hashes prevent corruption or a
release changing independently of the accepted index; they do not protect a host
when that distribution channel is compromised. Sequence and expiry catch stale or
accidentally rolled-back metadata only because they are unsigned.

The runtime never replaces a valid cached pair with an expired, mismatched, or
lower-sequence remote pair. Once the cached pair expires, installed plugins keep
running but release installs, updates, and migrations pause until fresh metadata
is available. A fresh bundled pair may seed a host that has never accepted a
newer sequence; an expired bundle remains usable for registry display/Git only
and must not authorize a release mutation. Existing explicit Git management
remains available independently. Signed TUF-style root, timestamp, snapshot, and
targets metadata is the intended later defense against a malicious rollback,
freeze, or high-sequence attack.

Cache complete generations under
`.pypluginstore/metadata/generations/<sequence>/`, with the exact registry, index,
and their hashes. Write and fsync a temporary generation directory, rename it,
atomically raise the separately stored `metadata/trust-state.json` watermark, then
atomically replace `metadata/current.json`. Startup ignores incomplete
generations, validates the pointer and watermark, and recovers the highest complete
generation at or above the watermark after a crash. Crash-injection tests cover
every write, fsync, rename, watermark, pointer, and recovery boundary.

For one plugin revision, the same release identity with a different commit, tree
digest, provenance, or predecessor set is quarantined as mutation. An attached or
generic artifact digest change is also quarantined. A generated-source transport
digest may change only with a newer valid index sequence and the same commit/tree.
The runtime rejects an entry whose revision is below installed metadata. At equal
revision it requires identical release identity, commit, tree, and provenance and
treats a generated-source transport digest difference as already current.

## Registry Delivery Policy

Existing registry list entries receive an implicit `release_if_indexed` policy
with Git supported. An object entry may add an optional versioned `delivery`
policy with these concepts:

```json
{
  "preferred": "release_if_indexed",
  "git_supported": true,
  "release": {
    "provider": "gitlab",
    "channel": "stable",
    "tag_pattern": "^v[0-9]+\\.[0-9]+\\.[0-9]+$",
    "artifact": "source_zip",
    "source_path": ".",
    "mutable_paths": ["config.json"]
  }
}
```

The effective release activation predicate is: local preference is not "keep
Git", registry policy permits release, and a fresh accepted pair contains a
certified matching entry. `git_supported` defaults to true. Provider/API bases,
tag policy, artifact/source-path overrides, and mutable paths are reviewed registry
data, not values accepted from a release response at runtime. A local "keep Git"
choice overrides release preference on that host.

Store explicit channel choices atomically in manager-owned
`.pypluginstore/channels.json`, keyed by normalized plugin identity. Do not add a
preference file to a Git checkout or infer consent from an untracked file.

Once a host accepts a release entry, missing, expired, invalid, or mismatched
metadata produces `release_metadata_unavailable`; it never silently changes the
plugin to Git. Deliberate de-certification requires reviewed registry policy plus
an index tombstone/reason. A plugin that has never had an accepted entry and uses
`release_if_indexed` stays on Git. Explicit `preferred: "release"` requires an
entry and reports unavailable if none exists.

## Provider Adapters

All adapters return the same internal `ReleaseCandidate` model. Provider code is
limited to scanner automation; downloading, validation, hashing, and index
serialization are shared.

### GitHub

- Use the releases API and ignore drafts and prereleases.
- Resolve the release tag to a commit and fetch the source ZIP by commit, not by
  mutable tag. A configured attached ZIP is eligible for automatic Git migration
  only when scanner validation proves its normalized tree equals that commit's
  source tree.
- Verify GitHub's asset digest when present, then independently calculate and
  publish SHA-256.
- Record whether the release is immutable for diagnostics, but do not rely on
  immutability being enabled.

### GitLab

- List `/projects/:id/releases` and explicitly reject upcoming releases. GitLab
  has no portable draft/prerelease flag, so release-preferred entries require a
  reviewed stable `tag_pattern`; `permalink/latest` is insufficient when filtering.
- Select the newest released candidate matching policy, without assuming SemVer
  ordering, and retain `released_at` for display.
- Prefer the resolved commit's repository ZIP. A configured asset follows the
  same source-tree equivalence rule as GitHub.
- Cache results and avoid repeated archive downloads because GitLab rate-limits
  repository archive requests.

### Codeberg and Forgejo hosts

- Use the Forgejo-compatible release-list endpoint and apply the reviewed tag
  policy locally. Do not rely on `/releases/latest`, whose ordering cannot express
  the complete stable-selection policy.
- Resolve the tag and request its commit-addressed source archive. Configured
  assets follow the same source-tree equivalence rule before they become
  migration-eligible.
- Calculate SHA-256 because the common API does not guarantee an artifact digest.
- Treat API compatibility as a provider capability. Codeberg is enabled by
  default; other public or self-hosted bases require explicit registry policy,
  including the API/web bases and the reviewed server response-page cap. This
  avoids treating a server-capped short page as the end of a result set.
- Use the returned attachment URL. External Forgejo assets are not implicitly
  trusted as ordinary uploaded attachments and require a separate reviewed policy.

### Gitea hosts

- Use a distinct adapter and fixture contract even where endpoints resemble
  Forgejo. The projects can diverge and must not be coupled by an assumed shared
  implementation.
- Require explicitly configured API/web bases and a reviewed response-page cap
  for public or self-hosted instances, then normalize host-returned asset URLs and
  source ZIPs through the same validation pipeline.

### Generic HTTPS manifest

Support non-forge hosting with a strict versioned manifest containing
`release_id`, `version`, `released_at`, `url`, `sha256`, `size`, immutable
`source_revision`, and optional `commit`/`source_path`. Repository automation
validates it, binds it to the configured repository identity, assigns the
curator-controlled revision/lineage, and pins it into the same index. The
publisher manifest is scanner input, not a runtime trust root; runtime consumes
only curator-generated index records. Public manifests and artifacts require
HTTPS. Runtime `file://` archives, local manifest discovery, and private-host
authentication are not part of v1; local registries continue to support Git.

All provider and generic downloads enforce a public-fetch policy in scanner and
runtime code: HTTPS on every redirect, bounded redirects and DNS resolution,
rejection of loopback/private/link-local/reserved destinations after every
resolution, connecting only to an approved resolved address, authorization
stripping on cross-origin redirects, and optional reviewed origin allowlists.
Tests cover cross-origin redirects and DNS rebinding.
An attached asset that intentionally differs from the tag source may be manually
certified for new and release-to-release installs, but is marked
`migration_eligible: false` and cannot use Git ancestry for migration safety.

## Release Selection and Fallback

1. Release delivery becomes preferred only when the registry/local policy and a
   fresh accepted `release_index.json` entry satisfy the activation predicate.
2. New installs use the pinned release archive.
3. Release-managed installs update only to a higher per-plugin revision whose
   predecessor chain includes the installed release identity. A fork or gap needs
   curator review; a downgrade needs explicit user confirmation.
4. If download, digest, extraction, or validation fails, fail closed. Never run a
   branch update automatically as a fallback for the failed artifact. A future
   explicit recovery action may acquire the exact index-pinned tag/commit through
   Git, but it must verify the resulting commit and remain visibly Git-managed.
5. If no release-index entry exists, use the current Git behavior.
6. The UI may offer an explicit "Use Git channel" action when the registry entry
   permits it. Switching channels writes local management metadata and requires
   the same staged replacement and rollback guarantees.

Step 5 applies only when release delivery was never activated or has been
explicitly de-certified. Any invalid/unavailable metadata after activation is a
blocked release state, not "no entry" and not a Git fallback.

## Runtime Install Metadata

Release-managed plugin folders contain `.pypluginstore.json`:

```json
{
  "schema": 1,
  "plugin_key": "ExamplePlugin",
  "management_mode": "release",
  "repository_identity": "gitlab.com/group/example-plugin",
  "version": "1.4.0",
  "tag": "v1.4.0",
  "release_id": "gitlab:group/example-plugin:v1.4.0",
  "release_revision": 7,
  "released_at": "2026-07-18T07:00:00Z",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "artifact_tree_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "artifact_provenance": "forge_source_archive",
  "artifact_files": {
    "plugin.py": {
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "size": 4096
    }
  },
  "preserved_files": {},
  "index_sequence": 42,
  "installed_at": "2026-07-18T08:00:00Z"
}
```

The per-file artifact manifest records every pristine regular file before local
overlays. It is required to distinguish modified packaged files from reviewed
mutable data during later updates and rollback; the aggregate tree digest alone
cannot provide that inventory. The file is written into staging only after
validation and moves into place with the release. Atomic writes are required for
later metadata changes. Invalid or unknown metadata never grants permission to
delete or overwrite another folder.

## Safe ZIP Pipeline

V1 supports ZIP only. Every install or update follows the same pipeline:

1. Stream the artifact into a manager-owned staging directory while enforcing the
   public-fetch policy, connect/read timeouts, redirect limits, maximum compressed
   bytes, expected length, and SHA-256.
2. Inspect all members before writing. Reject absolute/UNC/drive paths, `..`, NUL
   or control bytes, backslash traversal, encrypted members, symlinks, hardlinks,
   devices/FIFOs, duplicate or case-fold-colliding names, Windows reserved names,
   trailing dots/spaces, excessive file counts, oversized members, excessive
   total expansion, and suspicious compression ratios.
3. Extract member-by-member into a newly created empty directory and verify every
   resolved path remains inside it. Do not call `extractall()` on untrusted input.
4. Require the indexed wrapper/root layout, then resolve `source_path` without
   following links. Reject missing, multiple, or otherwise ambiguous roots.
5. Require a non-empty root `plugin.py`, parse its Domoticz metadata, and compile
   Python sources before mutation. Identity certification reuses the current
   tiered repository, external-link, key, folder-name, and plugin metadata matching
   rules; it reports ambiguity rather than requiring strict key equality.
6. Reject an archive-provided `.pypluginstore.json` or manager-reserved path.
   Write manager-owned metadata only after validation, then perform the staged
   replacement.

Initial limits should be constants with tests and conservative defaults: 50 MiB
compressed, 250 MiB expanded, 5,000 entries, 50 MiB per file, and a maximum 100:1
compression ratio. They can be revised from observed registry data.

## Atomic Replacement and Rollback

Transactions, staging, and backups live under the manager folder so they remain
on the same filesystem without appearing as top-level Domoticz plugins:

- `.pypluginstore/transactions/<operation-id>.json`
- `.pypluginstore/staging/<plugin-key>/<operation-id>`
- `.pypluginstore/backups/<plugin-key>/<operation-id>`

Replacement sequence:

1. Fully prepare and validate code plus any dependency staging.
2. Persist the transaction, then move current dependency/code targets into their
   backup locations in a documented order.
3. Move dependency/code staging into their original paths. The updated plugin
   cannot run until restart completes the whole journaled transaction.
4. If any activation step fails, immediately restore every moved backup.
5. Retain one known-good backup set and expose a rollback operation. A later successful
   update may prune the older backup.

Persist and fsync a transaction journal before each rename. Recovery resumes or
rolls back from the last durable state; the two directory renames must remain on
the same filesystem.

On locked-file errors, queue the complete operation descriptor for the next
startup. PyPluginStore's `00-` loading recommendation lets queued replacement run
before later plugins are loaded. Pending operations must be idempotent and bind to
the expected current digest/commit so stale operations cannot overwrite newer
state.

### Dependency transaction

Requirements are never installed directly into the live shared dependency
directory. Build a complete staged snapshot of the current shared dependency tree,
apply `pip --target` to that snapshot, and validate it before plugin mutation. The
journal records `dependencies_staged`, `dependencies_backed_up`, and
`dependencies_activated`; same-filesystem renames retain the prior snapshot.

Only after dependencies are restorable may code activation begin. Any dependency
or code failure restores both prior directories (or removes both parts of a failed
new install). The transaction enters `restart_pending` before the new plugin can
run because already-imported Python modules cannot be rolled back in memory. If a
safe dependency snapshot cannot be created, leave code untouched and report a
blocked/manual-dependency state. Compatibility conflicts between plugins remain a
shared-dependency limitation and must be surfaced before confirmation.

## Local-Data Preservation for Every Replacement

The reviewed `mutable_paths` policy applies to Git migration, release-to-release
updates, release rollback, and explicit channel switches. Before replacing an
installed directory, inventory it against `.pypluginstore.json`, the recorded
artifact tree, and preserved-file hashes:

- automatically carry forward only declared mutable paths whose type and size
  remain safe;
- block on unknown new or modified paths, with an explicit manual inventory flow;
- validate the pristine new artifact tree before overlaying mutable data, then
  hash every overlay separately in the new metadata;
- allow a declared mutable path to replace its packaged default, but never allow
  preserved executable code, `plugin.py`, manager metadata, or reserved paths.

This avoids silently losing runtime data on later release updates after `.git` is
gone and keeps the canonical artifact tree distinct from host-local state.

## Git-to-Release Migration During Upgrade

Migration is part of `update`, not a separate bulk rewrite.

### Preflight

For a Git-installed plugin with a valid release-index entry:

1. Confirm the Git remote matches the registry entry.
2. Reject index locks, unresolved Git operations, and submodules in v1. Automatic
   migration also rejects all tracked changes. Manual migration may preserve a
   changed path only when reviewed policy declares it mutable and the user
   approves its exact inventory; all other changes report
   `migration_blocked_local_changes` without reset.
3. Require `migration_eligible` source provenance and resolve the release commit.
   Automatic migration is allowed only when the
   release commit equals or descends from the installed `HEAD`. If the installed
   branch is ahead or diverged, report `migration_waiting_for_release` or require
   explicit downgrade confirmation.
4. Inventory untracked files with Git. Ignore known disposable caches, preserve
   only paths declared mutable by reviewed registry policy, and block automatic
   migration on any other untracked path. Manual migration may explicitly approve
   additional non-code paths after showing the inventory; `.git`, manager
   internals, and non-mutable archive code are never copied.
5. Reject symlinks that escape the plugin and case-insensitive/Unicode collisions.
   An approved mutable path may replace its packaged default; all other collisions
   block migration. `plugin.py`, executable code, and manager-reserved paths can
   never be preservation overlays.

### Migration transaction

1. Stage and validate the release exactly like a new install, including its
   artifact tree digest before any local overlay.
2. Copy approved preserved paths into staging, reapply file-type/path/size safety
   checks, and hash each final preserved file separately.
3. Build and validate the complete staged dependency snapshot.
4. Record the migration source commit, original artifact tree digest, and
   preserved-path hashes in install metadata.
5. Move the complete Git checkout and live dependency tree to rollback locations.
6. Activate the staged dependency and release trees under the durable journal,
   then enter restart-pending. Any failure restores both snapshots before another
   operation begins.

Persist these recoverable states in the journal:

`legacy_git` -> `preflight` -> `target_pinned` -> `staged_verified` ->
`dependencies_staged` -> `git_backed_up` -> `dependencies_backed_up` ->
`dependencies_activated` -> `release_activated` -> `restart_pending` ->
`release_managed`.

Preflight may instead enter a specific blocked state. Any failure after
`git_backed_up` attempts rollback before another operation can begin.

### Automatic updates

- Manual Update performs migration when preflight is safe and explains the mode
  change before execution.
- Automatic update may migrate only a clean checkout whose release commit equals
  or descends from `HEAD`. Any ambiguity leaves the Git checkout untouched and
  emits a visible blocked status/notification.
- A failed release verification never causes an automatic Git update.
- Users may explicitly retain or switch back to Git. Restoring the migration
  backup is the preferred immediate rollback; a fresh Git clone is a separate,
  confirmed operation.

## Update Status and UI States

Add forge-neutral states:

- `current`
- `available`
- `migration_available`
- `migration_blocked_local_changes`
- `migration_waiting_for_release`
- `release_metadata_unavailable`
- `migration_blocked_local_files`
- `dependency_transaction_blocked`
- `verification_failed`
- `rollback_available`
- `git_current` / `git_available` where the mode must be explicit
- `unknown`

Cards show the active channel (`Release` or `Git`), installed release/tag, and why
a migration is blocked. Existing Git status remains supported.

## Registry and Scanner Rollout

1. Introduce schema/model support without changing any install behavior.
2. Generate release metadata in report-only mode and measure coverage, archive
   sizes, layouts, and ambiguous releases.
   The 2026-07-18 baseline found only 54 of 256 registry entries reporting a
   latest stable release candidate; archive roots, identity, and safety remain to
   be validated. Certification must be gradual because a flag-day switch could
   strand at least roughly 79% of the registry.
3. Pilot real certified GitHub and GitLab releases. Validate Codeberg/Forgejo,
   Gitea, and generic provider contracts with live responses and recorded fixtures;
   enable an actual provider rollout only when a registered plugin publishes a
   suitable release.
4. Review and commit the first `release_index.json`; only indexed plugins become
   release-preferred.
5. Expand automatically only after source ZIP validation passes. Keep explicit
   opt-outs and asset/source-path overrides.
6. Preserve public review: automated index changes are proposed through a pull
   request, never pushed directly by the scanner.

## Acceptance Criteria

- Existing list and object registry entries remain valid.
- Public runtime release checks require no GitHub, GitLab, Forgejo/Codeberg, or
  Gitea API calls.
- Runtime atomically validates registry/index pairs, rejects expired,
  lower-sequence, registry-mismatched, and mutated metadata, and pauses release
  mutations when no fresh non-downgrade pair is available. The documentation does
  not claim this unsigned v1 design resists distribution-channel compromise.
- GitHub, GitLab, Forgejo/Codeberg, Gitea, and generic manifest adapters produce
  identical normalized descriptors and runtime behavior from certified releases
  or provider-contract fixtures.
- New installs prefer release archives when a valid index entry exists and use Git
  otherwise.
- Existing clean Git installs migrate only from source-proven release artifacts,
  without changing the plugin folder name or losing approved local files.
- Dirty, ahead, diverged, locked, malformed, oversized, traversal, collision, and
  digest-mismatch cases fail safely with actionable status.
- Release updates and migrations keep a restorable backup.
- Release updates, rollback, migration, and channel switches preserve only
  reviewed mutable data and block unknown local changes.
- Dependency changes are staged outside the live shared tree and code/dependency
  snapshots roll back together before restart on any failure.
- Git-only install, update, update-status, local override, and removal behavior
  remains covered by regression tests.
- Linux and Windows CI pass; `plugin.py` is regenerated from `plugin_core.py`.
- User documentation explains release preference, Git fallback, migration,
  backups, rollback, and local-registry configuration.

## Out of Scope for V1

- Release-based PyPluginStore self-update; the existing guarded Git self-update
  remains unchanged.
- TAR extraction or executable/binary package formats.
- Blind installation from mutable branch archives or unpinned URLs.
- Runtime discovery against public forge APIs.
- Automatic authentication to private forges or private release assets.
- Full TUF/Sigstore/GPG verification. The schema should remain extensible for
  signatures and attestations after digest-pinned delivery is established.
- Automatically migrating dirty, ahead, diverged, or submodule-based Git trees.

## Research Basis

- GitHub release responses expose tags, source archive URLs, immutability, asset
  sizes, and SHA-256 asset digests:
  https://docs.github.com/en/rest/releases/releases
- GitHub immutable releases lock tags/assets and create attestations, but this is
  not assumed for third-party repositories:
  https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases
- GitHub documents that generated source archives may change compression details,
  so commit/tree identity is distinct from transport bytes:
  https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives
- GitLab exposes releases, latest-release permalinks, asset links, and repository
  ZIP archives; its latest release is ordered by release time rather than SemVer:
  https://docs.gitlab.com/api/releases/
  https://docs.gitlab.com/api/repositories/
  https://docs.gitlab.com/user/project/repository/
- Forgejo exposes a Swagger-described API and release/source-archive model used by
  Codeberg:
  https://forgejo.org/docs/latest/user/api-usage/
  https://forgejo.org/docs/latest/user/releases/
- Gitea publishes its own API contract and is kept behind a distinct adapter:
  https://docs.gitea.com/1.25/development/api-usage
- Python documents archive traversal and expansion hazards and recommends resolved
  path containment plus explicit resource limits:
  https://docs.python.org/3/library/zipfile.html
  https://docs.python.org/3/library/tarfile.html
- TUF defines signed role separation and rollback/freeze protections that the
  unsigned v1 index intentionally does not claim:
  https://theupdateframework.io/security/

## Risks and Open Questions

- Some plugins publish releases inconsistently or keep installable files in a
  subdirectory. Report-only discovery must quantify this before broad rollout.
- Plugin runtime data conventions are not standardized. Unknown untracked files
  block automatic migration; reviewed mutable-path policy and an explicit manual
  inventory prevent silent data loss without copying arbitrary code into a
  release install.
- A journaled multi-directory replacement has short gaps and Windows locks may
  defer it. Recovery and idempotency tests are mandatory.
- Shared Python dependencies can conflict across plugins. Snapshot rollback avoids
  partial filesystem mutation but cannot guarantee semantic compatibility; longer
  term, per-plugin dependency isolation may be needed.
- A curated SHA-256 index protects against artifact mutation, not compromise of
  the PyPluginStore registry itself. A future TUF-style signed metadata layer can
  strengthen rollback, freeze, and key-compromise defenses without changing the
  provider-neutral runtime contract.
