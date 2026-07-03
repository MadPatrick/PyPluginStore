# ISSUE:81 - docker domoticz 18063 does not detect newer PyPluginStore

Status: open; fix implemented in this maintenance pass.

Reporter:
- `Eddie-BS` reported on 2026-07-02 that Docker-based Domoticz build 18063 running PyPluginStore 2.14.1 did not detect a newer PyPluginStore release.

Intent:
- Make self-update detection reliable in Docker installs where Git reports dubious repository ownership.

Evidence:
- Logs show the first Git command hit dubious ownership and retried with the `safe.directory` bypass.
- Later self-update status still ended as `Could not determine update status for 00-PyPluginStore.`

Assessment:
- The runtime recorded the repository as already handled after the first ownership failure.
- That accidentally skipped the `safe.directory` bypass for later Git commands in the same repository, such as `git log` or `git rev-list`.
- In Docker volume-mount setups, every Git command can hit the same dubious-ownership check, so the bypass must be available for each command.

Implemented fix:
- Retry every dubious-ownership Git command with `-c safe.directory=<repo>`.
- Keep the log line to once per repository to avoid noisy logs.
- Keep the recursive chown fallback limited to once per repository.

Verification:
- Added a regression test proving a second Git command in the same repo also receives the `safe.directory` bypass.
- `pytest tests/test_plugin_update_status.py` passed.
- `pytest` passed.

Recommended next step:
- Ask the reporter to update PyPluginStore and confirm self-update detection works in the Docker install.
