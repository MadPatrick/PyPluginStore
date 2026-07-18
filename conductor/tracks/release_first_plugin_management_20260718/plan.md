# Plan: Release-First Plugin Installation and Updates

## Phase 1: Contracts and Backward-Compatible Metadata

- [x] Task: Add failing tests for legacy registry entries, delivery policy, normalized entries, per-plugin revision/predecessor ordering, pair sequence/freshness/registry binding, and invalid index rejection `216f1c1`
- [x] Task: Add release descriptor and delivery-mode models without changing Git behavior `602573a`
- [x] Task: Add generation-directory registry/index caching, a durable highest-sequence watermark, bundled bootstrap/expiry rules, atomic pointer recovery, and crash-injection tests under the unsigned-v1 trust model `db4d87d`
- [x] Task: Add install metadata parsing, artifact/preserved-file audit hashes, and atomic `.pypluginstore.json` writes `a56a101`
- [x] Task: Add manager-owned atomic channel preferences so an explicit keep-Git choice survives updates without modifying plugin checkouts `72eebcd`
- [x] Task: Conductor - User Manual Verification 'Contracts and Backward-Compatible Metadata' (waived by user; automated checkpoint `78eae1c`)

## Phase 2: Multi-Forge Release Resolution

- [x] Task: Add fixture-driven failing tests for GitHub, GitLab, Forgejo/Codeberg, Gitea, and generic manifest candidates `ee0f109`
- [x] Task: Implement the shared release-provider interface and normalized candidate model `9c9fe43`
- [x] Task: Implement GitHub stable release resolution, source-ZIP preference, and attached-asset provenance checks `54cf8f8`
- [~] Task: Implement GitLab release-list filtering with reviewed tag policy, encoded project paths, source-ZIP preference, and attached-asset provenance checks
- [ ] Task: Implement Forgejo/Codeberg stable release and asset/source-ZIP resolution
- [ ] Task: Implement a distinct Gitea stable release and asset/source-ZIP adapter
- [ ] Task: Implement generic HTTPS manifest resolution
- [ ] Task: Add SSRF-safe bounded downloads, commit-addressed source archives, transport digest/length checks, canonical-tree identity, asset mutation detection, caching, and report-only index generation
- [ ] Task: Extend registry validation and weekly PR automation for `release_index.json`
- [ ] Task: Conductor - User Manual Verification 'Multi-Forge Release Resolution' (Protocol in workflow.md)

## Phase 3: Hardened ZIP Staging and Rollback

- [ ] Task: Add failing archive tests for traversal, absolute/UNC/drive paths, links/devices, control bytes, encryption, duplicate/case collisions, Windows reserved paths, ambiguous roots, manager metadata, bombs, size limits, and malformed ZIPs
- [ ] Task: Implement the SSRF-safe bounded streaming downloader and member-by-member safe ZIP extractor
- [ ] Task: Add canonical cross-platform tree hashing, wrapper/source-path resolution, flexible `plugin.py` identity certification, and compilation validation
- [ ] Task: Add same-filesystem manager-owned transaction journals, staging, backup, two-rename replacement, and immediate rollback
- [ ] Task: Add idempotent queued replacement for Windows locked-file behavior
- [ ] Task: Conductor - User Manual Verification 'Hardened ZIP Staging and Rollback' (Protocol in workflow.md)

## Phase 4: Release-First Install, Update, and UI

- [ ] Task: Add failing activation/order/status tests for release-if-indexed, required release, Git-only, explicit Git, unavailable/de-certified metadata, predecessor gaps, mutations, recompressed source ZIPs, downgrade confirmation, and fail-closed cases
- [ ] Task: Replace the single Git strategy field with a release-aware coordinator that retains `GitInstallUpdateStrategy`
- [ ] Task: Implement release-first new installs and release-to-release updates
- [ ] Task: Implement local-data inventory and reviewed mutable overlays for release updates, rollback, and channel switches
- [ ] Task: Stage, validate, atomically swap, and roll back complete shared-dependency snapshots before code activation
- [ ] Task: Implement retained-backup rollback and backup pruning
- [ ] Task: Add release/Git channel, version, verification, and rollback fields to API responses
- [ ] Task: Add UI channel badges, release status, explicit Git selection, verification errors, and rollback actions
- [ ] Task: Regenerate `plugin.py` and update runtime/user documentation
- [ ] Task: Conductor - User Manual Verification 'Release-First Install, Update, and UI' (Protocol in workflow.md)

## Phase 5: Git-to-Release Upgrade Migration

- [ ] Task: Add failing migration tests for clean/equal, clean/descendant, dirty, ahead, diverged, submodule, index-lock, missing-Git, and repository-mismatch states
- [ ] Task: Add failing preservation tests for approved mutable overlays, unknown tracked/untracked blockers, collisions, escaping links, caches, Unicode normalization, Windows case-folding, and audit hashes
- [ ] Task: Implement migration preflight and explicit blocked states
- [ ] Task: Implement reviewed preservation policy, explicit manual inventory approval, and staged Git-to-release replacement during update
- [ ] Task: Implement safe automatic-update migration rules and explicit downgrade/Git-channel confirmation
- [ ] Task: Add migration source and preserved-path audit data to install metadata and rollback
- [ ] Task: Verify dependency-and-code rollback on failure for new installs, release updates, and Git migrations, including restart-pending and compatibility warnings
- [ ] Task: Document upgrade, blocked migration, backup, rollback, and Git retention workflows
- [ ] Task: Conductor - User Manual Verification 'Git-to-Release Upgrade Migration' (Protocol in workflow.md)

## Phase 6: Pilot and Progressive Rollout

- [ ] Task: Run report-only release discovery across the registry and document coverage, exclusions, sizes, and layouts
- [ ] Task: Pilot certified GitHub and GitLab releases; validate Codeberg/Forgejo, Gitea, and generic contracts with live responses and recorded fixtures until registered releases are available
- [ ] Task: Exercise clean Git migration and rollback on Linux and Windows/Domoticz test installations
- [ ] Task: Enable release-index PR generation for validated candidates and retain per-entry opt-outs/overrides
- [ ] Task: Run the full test suite, registry validation, generator freshness, static workflow checks, and security review
- [ ] Task: Update maintainer decisions, patterns, contributor guidance, and rollout notes
- [ ] Task: Conductor - User Manual Verification 'Pilot and Progressive Rollout' (Protocol in workflow.md)
