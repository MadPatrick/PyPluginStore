# Robust PyPluginStore Self-Update State

## Context

PyPluginStore currently handles normal plugin updates synchronously, but handles manager self-update asynchronously through a detached helper. The API response says scheduling succeeded, while the actual apply phase happens after the response. If the helper fails, the frontend can lose the available-version signal and the user sees no clear completion or failure state.

## Goals

- Treat `00-PyPluginStore` self-update as an explicit asynchronous operation.
- Persist self-update phase, message, timestamps, target reference, commits, and log path in a small state file.
- Surface self-update state through the existing API bridge.
- Keep the existing safety behavior: do not mutate live manager files before the UI receives a response.
- Log self-update phase starts and important transitions to the main Domoticz log, with a reference to `self_update.log` whenever helper output is relevant.
- Let the frontend show scheduled/running/applied/failed state instead of presenting a plain success alert only.

## Acceptance Criteria

- Starting manager self-update writes durable state before launching the detached helper.
- Pre-flight failure writes inspectable state and returns a clear API error.
- The detached helper writes `running`, `applied_needs_reload`, or `failed` state atomically.
- `list_plugins`, `refresh_update_status`, and a dedicated status action expose the current self-update state.
- Frontend manager update handling stores the returned state, renders it on the manager card, and polls for status after scheduling.
- Main Domoticz logs include self-update phase starts and reference `self_update.log` for helper diagnostics.
- Focused backend and UI smoke tests cover the new behavior.
- `plugin.py` is regenerated from `plugin_core.py`.

## Out Of Scope

- Replacing the Domoticz text-device API bridge.
- Automatically restarting Domoticz after manager self-update.
- Changing normal third-party plugin update semantics.
- Changing release-please or release branch behavior.
