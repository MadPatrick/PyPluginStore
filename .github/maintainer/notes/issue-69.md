# ISSUE:69 - new update not seen ...

Status: open; local fix prepared.

Reporter:
- `Eddie-BS` reported on 2026-06-29 that recent releases were not detected by the installed plugin.

Intent:
- PyPluginStore should show that a newer manager release/update is available without requiring a manual `git pull`.

Assessment:
- The report arrived after the `v2.13.1` release and after the self-update timeout fixes.
- The error log is decisive:
  `fatal: detected dubious ownership in repository at '/opt/domoticz/userdata/plugins/00-PyPluginStore'`.
- Git refuses `git fetch` before PyPluginStore can compare local `HEAD` with the upstream branch.
- PyPluginStore then reports update status `unknown`, so the custom UI will not show an available update.
- This is not a release-please, registry cache, or UI refresh issue. It is a local repository ownership/trust problem.
- The reporter says `2.13` was obtained manually with `git pull`; if that pull was run as a different OS user than the Domoticz service user, it can leave the checkout in a state where Git refuses future commands from Domoticz.
- The current self-update pre-flight will also reject this installation, because the same Git safety check will fail during repository verification or fetch.

Recommended next step:
- Ship explicit handling for Git's `dubious ownership` error.
- PyPluginStore logs a clear ownership mismatch error, tries to repair ownership for managed plugin repositories under the Domoticz plugins folder, and retries the Git command once.
- PyPluginStore does not run or suggest `git config safe.directory`.
- If ownership repair fails, update detection remains `unknown`, but the log and self-update pre-flight message tell the user to fix plugin folder ownership manually.
- The same handling applies to self-update pre-flight because all pre-flight Git calls go through `HostRuntime.run_git()`.

Verification:
- Focused tests cover successful repair/retry, failed repair messaging without `safe.directory`, and self-update pre-flight ownership failure.

Public action:
- None taken.
