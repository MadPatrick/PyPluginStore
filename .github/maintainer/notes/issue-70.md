# ISSUE:70 - owner of plugins on docker based domoticz

Status: open; fix implemented locally.

Reporter:
- `Eddie-BS` reported on 2026-06-30 that restarting Docker-based Domoticz complains about file ownership for every plugin on startup.

Intent:
- Eliminate permission/ownership conflicts and resulting startup log spam in Docker setups without breaking the user's host file permissions.

Assessment:
- In Docker volume-mount environments, files on the host are typically owned by the host user (UID 1000).
- When Domoticz starts inside the container as a different user (e.g. root or UID 1001), Git's strict security checks report "dubious ownership".
- The previous implementation attempted to resolve this by recursively running `chown` on the entire plugin directory.
- This caused a cyclic file ownership fight: on restart, host permissions were changed to root, forcing the user/entrypoint to revert them back, leading to recurring log spam and host file management issues.
- Passing `-c safe.directory=<repo_dir>` to the retried Git command allows it to run successfully without any filesystem or ownership changes, solving the problem permanently and silently.

Recommended next step:
- Present the fix to the reporter and ask them to test.

Verification:
- Focused tests in `tests/test_plugin_update_status.py` verify that `run_git` retries using the `safe.directory` bypass and avoids calling `repair_git_repository_ownership` (chown) in the common case.
