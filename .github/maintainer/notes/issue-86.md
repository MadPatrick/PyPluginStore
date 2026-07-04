# ISSUE:86 - ownership ??

Status: open; diagnostic fix pushed to `master`.

Reporter:
- `Eddie-BS` reported on 2026-07-04 that Docker-based Domoticz build 18070 still logs Git ownership failures around self-update.

Intent:
- Make the ownership error actionable by telling users what owner PyPluginStore expects, not only that ownership is wrong.

Evidence:
- Logs show PyPluginStore tried the ownership repair path for `/opt/domoticz/userdata/plugins/00-PyPluginStore`.
- The reporter changed the host-side owner to `pi:pi` but still saw the error.
- In Docker setups, host-visible names can differ from the user and numeric UID/GID running Domoticz inside the container.

Assessment:
- The existing safe-directory retry remains the preferred path because it avoids changing host volume ownership.
- If Git still reaches the repair/failure path, the fallback message is too vague: "fix ownership manually" does not say which UID/GID should own the folder.
- The correct expectation is that the repository owner should match the OS user running the Domoticz process inside the same runtime environment.

Implemented fix:
- Expand Git ownership failure messages with:
  - current repository owner;
  - expected owner, based on the current Domoticz process UID/GID;
  - a note that the expected owner is the Domoticz process user.
- Preserve existing safe-directory retry and fallback behavior.
- Centralize Git result logging and user-facing failure messages through `HostRuntime`.
- Make the detached self-update helper run Git with `-c safe.directory=<repo>`, matching pre-flight behavior.
- Run managed plugin repository Git commands with per-command `safe.directory` up front instead of waiting for a dubious-ownership failure.
- Disable recursive ownership repair by default; it now requires the `Git Ownership Repair` setting to be explicitly enabled.
- Regenerated `plugin.py`.

Verification:
- Added focused regression coverage for the ownership failure message, managed-repo safe-directory command shape, clone behavior, self-update helper Git command shape, and opt-in ownership repair.
- `pytest tests/test_plugin_update_status.py -q`: 33 passed.
- `pytest -q`: 172 passed.
- `python3 -m py_compile plugin_core.py plugin.py`: passed.
- `git diff --check`: passed.

Recommended next step:
- After approval, comment on `ISSUE:86` explaining that the next build will log both current and expected ownership, and ask the reporter to retry from that build if the problem continues.
- Release PR #85 includes this fix for 2.15.1.
