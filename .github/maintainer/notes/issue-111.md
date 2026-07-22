# ISSUE:111 - Use release function is giving errorr

Status: open; original failure fixed in `v2.21.0`, with additional local-registry
safeguards pushed on `fix/issue-111-local-overrides`.

Author:
- `MadPatrick` opened the issue on 2026-07-21 with repeated release lifecycle
  path errors and inappropriate release-switch actions across installed plugins.

Intent:
- Keep one plugin's invalid or interrupted release transaction from affecting
  other plugin cards.
- Show a release switch only when migration is actionable.
- Preserve supported public/local registry override behavior.

Assessment:
- The original error is reproducible against the code before `PR:116`: a legacy
  release transaction whose staging directory had already been removed caused an
  unrelated package lifecycle lookup to raise `Release transaction path must be
  a real directory.`
- On current `master`, the same journal returns an empty lifecycle state for the
  unrelated package. `PR:116` fixed the fan-out by identifying the transaction
  before validating its package paths, and it shipped in `v2.21.0`.
- The reporter later found the same plugin represented by the public and local
  registries. A matching local package is a supported Git-only override.
- Two follow-up gaps remained: a saved Release preference was still consulted for
  a valid local override, and a malformed existing `registry_local.json` could
  silently expose public Release actions. The local fix ignores Release
  preferences/targets for local entries, pauses Release management while an
  existing local registry cannot be loaded, and prevents the UI from offering a
  Release switch on Local cards.
- Public Release cards no longer offer **Use Git**. Ongoing Git management now
  requires a local override; legacy and rollback-created keep-Git holds remain
  internal safety state so a restored backup is not immediately remigrated.

Verification:
- Standalone legacy-journal reproduction failed on pre-`PR:116` code and passed
  on current `master` with the expected empty unrelated-package lifecycle state.
- Full sanitized suite: 1,314 tests passed.
- Generated runtime parity, Python compilation, registry validation for all 257
  entries, and `git diff --check` passed.

Recommended next step:
- Keep open.
- Open a pull request from the pushed branch after approval, monitor its required
  checks, then ask the reporter to verify the intended local override after
  restarting Domoticz.

Public action:
- Pushed `fix/issue-111-local-overrides`; no issue comment or pull request was
  created.
