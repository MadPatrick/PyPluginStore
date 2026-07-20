# Release and Git Management

PyPluginStore prefers a verified stable release when the public registry and its matching `release_index.json` authorize one. Certification is a reviewed, per-plugin opt-in: publishing a release on a supported host does not activate Release by itself. Git remains supported for plugins without a certified release and for users who explicitly keep an existing Git checkout on Git.

## How release-first selection works

Release discovery happens in repository automation, not on the Domoticz host. GitHub, GitLab, Codeberg/Forgejo, Gitea, and generic HTTPS manifest adapters all produce the same provider-neutral descriptor: repository identity, release ID, version, immutable commit or source revision, archive URL and length, archive SHA-256, canonical tree SHA-256, and archive layout.

Provider handling is deliberately separate at discovery time:

| Source | Stable selection | Preferred artifact |
| --- | --- | --- |
| GitHub | Published, non-draft, non-prerelease release matching reviewed tag policy | Commit-addressed source ZIP; reviewed attached ZIP only after source-tree equivalence |
| GitLab | Non-upcoming release matching reviewed tag policy, ordered by release time | Commit-addressed repository ZIP; reviewed asset link only after source-tree equivalence |
| Codeberg/Forgejo | Published release selected from the release list with reviewed tag and pagination policy | Commit-addressed source ZIP; same equivalence rule for attachments |
| Gitea | Its own API adapter and fixtures, with explicit API/web bases for self-hosted instances | Commit-addressed source ZIP; same equivalence rule for attachments |
| Generic HTTPS | Strict versioned publisher manifest with an immutable source revision | Manifest ZIP after independent download, hash, layout, and identity certification |

Provider responses are scanner inputs, not runtime authority. The generated index is the only provider-neutral release contract consumed by an installation.

The adapters follow the hosts' published contracts: [GitHub Releases](https://docs.github.com/en/rest/releases/releases), [GitHub source archives](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives), [GitLab Releases](https://docs.gitlab.com/api/releases/), [GitLab repository archives](https://docs.gitlab.com/api/repositories/), [Forgejo releases](https://forgejo.org/docs/latest/user/releases/), [Forgejo API usage](https://forgejo.org/docs/latest/user/api-usage/), and the [Gitea API](https://docs.gitea.com/api/1.21/). GitHub explicitly guarantees stable extracted contents for a commit-addressed archive while allowing its compression bytes to change; this is why the index records both the transport digest and a canonical extracted-tree digest.

The initial rollout pilots suitable registered GitHub and GitLab releases. Codeberg/Forgejo, Gitea, and generic manifest support is validated with provider-contract fixtures and live endpoint responses until a registered plugin publishes a suitable release; this support table does not claim that live Codeberg or Gitea releases are currently certified.

The runtime accepts `registry.json` and `release_index.json` as one exact pair. It caches complete generations and uses an increasing sequence and expiry time to reject stale operational metadata. If the selected index has no release for a plugin that has never used Release, PyPluginStore uses Git. An explicit local keep-Git preference also overrides release preference while the installed folder remains a valid Git checkout. If a release-managed plugin loses fresh or valid metadata, it pauses instead of silently changing channels.

Release activation then follows this order:

1. Download the exact indexed ZIP with HTTPS redirect and destination checks.
2. Verify its byte length and SHA-256 digest.
3. Safely inspect and extract every member with traversal, collision, link, compression, file-count, and size protections.
4. Verify the canonical tree, source path, root `plugin.py`, Python compilation, and registry identity.
5. Inventory and apply only permitted host-local data.
6. Build and validate a complete staged `.shared_deps` snapshot.
7. Atomically replace dependencies and code while retaining the previous state for rollback.

There is no automatic Git fallback after a release download, verification, dependency, or activation failure.

## Migrating an existing Git installation

Migration is part of the normal **Update** action. It does not reset, clean, stash, fetch, or rewrite the checkout during preflight.

Automatic migration is allowed only when all of these are true:

- the configured fetch repository matches the registry across any supported forge;
- the release artifact is marked migration-eligible and names a Git commit;
- the installed `HEAD` equals the release commit or is its ancestor;
- there is no Git index lock, unresolved operation, submodule, tracked change, or unknown untracked file;
- every preserved path is safe under the reviewed mutable-path policy.

A manual **Update** or **Use Release** action presents an exact, content-bound channel-change challenge before migration. The challenge also covers reviewed local data or replacement of ahead/diverged history when either needs consent. One challenge can bind all applicable decisions. Approval tokens are opaque, short-lived, one-use, and bound to the plugin, action, release target, source commit, and current inventory. If anything changes after approval, preflight stops and asks for a new review.

Common blocked states:

- **Repository mismatch:** the checkout belongs to another remote; add the intended local registry entry or keep managing it yourself.
- **Local changes:** commit/revert them, or manually approve only a reviewed mutable data path.
- **Unknown local files:** move or remove them, or approve safe non-code files when offered.
- **Waiting for release:** the installed commit is ahead, diverged, missing locally, or the selected artifact cannot prove source equivalence.
- **Release metadata unavailable:** refresh after connectivity/index expiry is resolved; PyPluginStore will not downgrade to Git implicitly.

## Local-data preservation

Registry maintainers may review data locations such as `config/settings.json` or a runtime-state directory as mutable. On release update, migration, rollback, and a safely staged channel replacement, PyPluginStore inventories the installed tree against its prior artifact and preservation audit.

It never carries forward executable code, `plugin.py`, links, special files, Git/manager metadata, non-portable names, or colliding paths. Known disposable caches are ignored. Declared mutable paths that remain safe can be carried automatically; changed or unknown safe data requires exact manual inventory approval. Modifying the source inventory invalidates that approval before any copy begins. Unapproved files stay in the untouched checkout because activation cannot start.

## Dependencies, restart, backup, and rollback

Release operations copy the full live `.shared_deps` tree into staging and run `uv` or `python -m pip` against that snapshot. Compatibility conflicts pause before activation. Code is not changed when dependency snapshotting, installation, or validation fails.

After activation, the card shows **Restart required** because Python modules already loaded in the Domoticz process cannot be replaced in memory. Restart Domoticz before testing the new version.

PyPluginStore retains the immediately previous code and dependency trees as one rollback set. **Rollback** validates both the live target and retained backup before restoring them together, then requires a restart. When the backup is the Git checkout replaced during migration, rollback also restores the keep-Git channel choice. A later successful operation may prune an older backup only after the newer rollback snapshot is verified.

## Choosing Git explicitly

Use **Use Git** when the registry permits Git and you intentionally want branch-based management. For an existing Git checkout, the choice is stored under the manager's `.pypluginstore` state directory, never inside the plugin checkout, so it survives later updates.

A release-managed folder has no `.git` directory, so changing a preference alone cannot turn it into a safe Git checkout. PyPluginStore refuses that direct switch. Restore a verified Git migration backup with **Rollback** when one is available. A fresh clone, if offered by a future recovery flow, must be a separate confirmed replacement that verifies the repository and resulting commit and applies the same preservation and rollback rules. Without a verified backup or such a confirmed fresh clone, the release installation remains untouched.

Private repositories, forks, local/LAN repositories, and `registry_local.json` entries stay Git-managed. See [`registry_local.json` How-To](registry_local.md).

## Staged rollout and verification

Maintainers run release discovery in report-only mode first, review provider coverage and exclusions, and certify a small pilot in `release_index.json`. The weekly automation repeats the preview, generates candidate index changes, validates the registry/index binding, and proposes the diff through a pull request. Only reviewed indexed plugins become release-preferred; opt-outs and provider/source-path overrides remain available as the pilot expands.

The initial 2026-07 report examined 257 registry records. It certified 47 commit-addressed source ZIPs (46 GitHub and one GitLab), found no eligible stable release for 208 entries (including both Codeberg/Forgejo entries), rejected one archive for a Unicode/case-fold path collision, and could not reach one missing repository. The certified archives use root wrappers with `source_path` set to `.`, range from 5,728 to 3,249,818 bytes, and total 8,563,577 bytes. No live Codeberg/Forgejo, Gitea, or generic release is represented in that first index.

## Trust boundary

The v1 index is delivered through the PyPluginStore repository channel and HTTPS. Its sequence and expiry are staleness protections, while artifact and tree hashes detect corruption or mutation relative to that accepted index. They are not a cryptographic defense if the registry distribution channel itself is compromised. Signed metadata is a future hardening step.
