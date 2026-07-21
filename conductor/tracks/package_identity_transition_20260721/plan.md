# Plan: Explicit Package Identities and Automatic Release Transitions

## Phase 1: Versioned Package Contracts and Legacy Readers

- [x] Task: Add failing tests for strict registry-v2 package arrays, release-index-v2 record arrays, duplicate rejection, explicit Domoticz identity, and deterministic serialization `2718cf1`
- [x] Task: Implement shared v2 package records and parsers while confining v1 support to migration adapters `f937f42`
- [x] Task: Add failing upgrade tests for cached metadata pairs, local registry backup/rewrite, install metadata, and transaction journals `d7aa516`
- [x] Task: Implement atomic v1-to-v2 host-state upgrades and staged remote-v2 fallback behavior `ef9ceb8`
- [x] Task: Conductor - User Manual Verification 'Versioned Package Contracts and Legacy Readers' (waived by user; automated coverage used)

## Phase 2: Shared Identity and Release Evidence

- [x] Task: Add failing generator/runtime parity tests using the SMA mismatch and provider-neutral package identity fixtures `8e5c943`
- [x] Task: Implement one package/Domoticz/repository identity certifier for generator and runtime `8e5c943`
- [x] Task: Add failing evidence tests for commit source ZIPs, equivalent attached ZIPs, reviewed build ZIP manifests, ambiguous assets, and unverifiable continuity `8067dca`
- [x] Task: Replace the migration boolean with explicit evidence and source-commit contracts across all provider adapters `8067dca`
- [x] Task: Conductor - User Manual Verification 'Shared Identity and Release Evidence' (waived by user; automated coverage used)

## Phase 3: Automatic Channel Evolution and Durable Abort

- [x] Task: Add failing lifecycle tests for Git-only, first indexed release, notify-only transition, automatic clean migration, keep-Git preference, and every blocked working-tree state `8067dca` `1339fa9`
- [x] Task: Implement safe configured-remote refresh and automatic package-preserving Git-to-release migration `8067dca`
- [x] Task: Add failing abort/restart tests for identity rejection, every durable cleanup boundary, missing legacy staging parents, repeated abort, and primary-error preservation `8067dca`
- [x] Task: Implement abort-pending cleanup, idempotent terminal state, and safe legacy journal repair `8067dca`
- [x] Task: Conductor - User Manual Verification 'Automatic Channel Evolution and Durable Abort' (waived by user; automated coverage used)

## Phase 4: Public Data, Weekly Automation, and Cutover

- [x] Task: Add a deterministic migration command and convert registry, release index, and applicable public sidecars to explicit package records `0d0057d`
- [x] Task: Update scanners, platform detection, cleanup, validation, and weekly PR generation to consume and emit v2 only `f73ce9b` `acb4120`
- [x] Task: Add CI gates that runtime-certify every changed release, audit all indexed packages, simulate old-deployment upgrades, and run provider/transaction matrices on Linux and Windows `300416d`
- [x] Task: Regenerate plugin.py and update release management, local registry, maintainer, and rollout documentation `98eae8a` `77b1499`
- [x] Task: Run the full test suite, generation/validation checks, workflow-security checks, and a final migration/data-integrity audit (1,294 tests passed; 257 live repositories validated)
- [x] Task: Conductor - User Manual Verification 'Public Data, Weekly Automation, and Cutover' (waived by user; automated coverage used)
