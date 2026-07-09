# ISSUE:94 - docker version does not update

Status: open; needs one diagnostic check before deciding whether to fix code.

Reporter:
- `Eddie-BS` reported on 2026-07-09 that Docker-based PyPluginStore detects an update for the manager, but pressing Update leaves the visible version unchanged after refresh, retries, and a Domoticz restart.

Intent:
- Make `00-PyPluginStore` self-update visibly and reliably in Docker installs.

Evidence:
- The first screenshot shows `Installed: v2.15.2 | Available: v2.16.0`.
- The second screenshot still shows `Installed: v2.15.2` after pressing Update, but no longer shows an available version.
- The issue log reaches:
  `PyPluginStore: UpdatePythonPlugin called`
  `PyPluginStore: Self update requested for PyPluginStore.`
- That means the UI command reached the self-update branch and did not use the normal plugin update path.
- Current self-update schedules a detached Python helper after pre-flight and writes helper output to `self_update.log`; failures after scheduling are not shown in Domoticz logs.
- `master` currently points at `11d2e0b` (`fix: keep API payload device disabled`) and still declares `version="2.16.0"` in `plugin.py`.
- The `2.16.1` version bump exists only in open release PR `PR:93`; it is not on `master` yet.

Assessment:
- This looks like a real failed self-update from `v2.15.2` to `v2.16.0`, or at minimum a failure to surface whether the detached helper completed.
- After scheduling a manager self-update, the plugin sets `update_status["00-PyPluginStore"] = "unknown"` and the UI intentionally skips the immediate reload for the manager update. On the next plain `list_plugins`, available-version text only appears when cached status is still `available`, so the UI can hide the available version even if the helper failed.
- The likely failure point is the detached self-update helper. The decisive artifact is `self_update.log` in the PyPluginStore plugin folder.
- Related history: `ISSUE:65` fixed self-update bridge timeouts, `ISSUE:69` and `ISSUE:81` fixed Docker Git ownership/update detection paths. This report is about the post-preflight helper/apply phase plus weak failure visibility in the UI.

Recommended next step:
- Ask the reporter to check the local commit hash after pressing Update:
  `git -C /opt/domoticz/userdata/plugins/00-PyPluginStore rev-parse --short HEAD`
- Ask for `/opt/domoticz/userdata/plugins/00-PyPluginStore/self_update.log`.
- Consider a code follow-up: make `list_plugins` or the manager card surface a pending/failed self-update state from `self_update.log`, or trigger an explicit status refresh after the detached helper window so a failed helper does not look like the update disappeared.
- Separately merge `PR:93` if the intended visible release after `v2.16.0` is `2.16.1`; that is not the root of this report because the screenshots target `v2.16.0`.

Confidence:
- High that the issue reached the self-update scheduler and then lost user-visible confirmation.
- Medium that the helper itself failed until the reporter provides `self_update.log` or the local commit hash.
