# Plan: Explicit Package Identities and Automatic Release Transitions

## Phase 1: Versioned Package Contracts and Legacy Readers

- [~] Task: Add failing tests for strict registry-v2 package arrays, release-index-v2 record arrays, duplicate rejection, explicit Domoticz identity, and deterministic serialization
- [ ] Task: Implement shared v2 package records and parsers while confining v1 support to migration adapters
- [ ] Task: Add failing upgrade tests for cached metadata pairs, local registry backup/rewrite, install metadata, and transaction journals
- [ ] Task: Implement atomic v1-to-v2 host-state upgrades and old-manager remote-v2 fallback behavior
- [ ] Task: Conductor - User Manual Verification 'Versioned Package Contracts and Legacy Readers' (Protocol in workflow.md)

## Phase 2: Shared Identity and Release Evidence

- [ ] Task: Add failing generator/runtime parity tests using the SMA mismatch and provider-neutral package identity fixtures
- [ ] Task: Implement one package/Domoticz/repository identity certifier for generator and runtime
- [ ] Task: Add failing evidence tests for commit source ZIPs, equivalent attached ZIPs, reviewed build ZIP manifests, ambiguous assets, and unverifiable continuity
- [ ] Task: Replace the migration boolean with explicit evidence and source-commit contracts across all provider adapters
- [ ] Task: Conductor - User Manual Verification 'Shared Identity and Release Evidence' (Protocol in workflow.md)

## Phase 3: Automatic Channel Evolution and Durable Abort

- [ ] Task: Add failing lifecycle tests for Git-only, first indexed release, notify-only transition, automatic clean migration, keep-Git preference, and every blocked working-tree state
- [ ] Task: Implement safe configured-remote refresh and automatic package-preserving Git-to-release migration
- [ ] Task: Add failing abort/restart tests for identity rejection, every durable cleanup boundary, missing legacy staging parents, repeated abort, and primary-error preservation
- [ ] Task: Implement abort-pending cleanup, idempotent terminal state, and safe legacy journal repair
- [ ] Task: Conductor - User Manual Verification 'Automatic Channel Evolution and Durable Abort' (Protocol in workflow.md)

## Phase 4: Public Data, Weekly Automation, and Cutover

- [ ] Task: Add a deterministic migration command and convert registry, release index, and applicable public sidecars to explicit package records
- [ ] Task: Update scanners, platform detection, cleanup, validation, and weekly PR generation to consume and emit v2 only
- [ ] Task: Add CI gates that runtime-certify every changed release, audit all indexed packages, simulate old-deployment upgrades, and run provider/transaction matrices on Linux and Windows
- [ ] Task: Regenerate plugin.py and update release management, local registry, maintainer, and rollout documentation
- [ ] Task: Run the full test suite, generation/validation checks, workflow-security checks, and a final migration/data-integrity audit
- [ ] Task: Conductor - User Manual Verification 'Public Data, Weekly Automation, and Cutover' (Protocol in workflow.md)
