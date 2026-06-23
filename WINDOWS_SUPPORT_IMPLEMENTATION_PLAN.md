# Windows Support Implementation Plan

## Goal

Add Windows support for PyPluginStore while preserving existing Linux behavior.
The implementation should keep platform-specific behavior isolated, keep the
registry and plugin-management workflow shared, and avoid scattering
`platform.system()` checks through the codebase.

## Implementation Status

Implemented on 2026-06-23.

| Phase | Original plan | Implemented features |
| --- | --- | --- |
| 1 | Preserve Linux behavior behind a host runtime. | Added `HostRuntime`, `LinuxHostRuntime`, `WindowsHostRuntime`, and `make_host_runtime()`. Routed path helpers, Git execution, UI permissions, dependency install, and restart scheduling through the runtime while preserving Linux commands. |
| 2 | Enable Windows startup/runtime behavior. | Removed the Windows startup block. Added Windows no-op web permission handling, Windows service restart command groups, and Windows detached process flags. Restart API now reports scheduling failures. |
| 3 | Improve dependency installer targeting. | Dependency install now prefers `uv pip install --python sys.executable`, then `sys.executable -m pip`, then standalone `pip3`/`pip`, all targeting `.shared_deps`. |
| 4 | Harden filesystem safety and locked-file handling. | Added validated plugin keys, `commonpath`/`normcase` path containment checks, safe plugin directory resolution, Windows locked-file detection, and `pending_operations.json` retries for deferred remove/update operations. |
| 5 | Add optional registry platform metadata. | Existing list registry entries remain valid. Object-style entries and list entries with optional platform metadata are normalized into `plugin_platforms`, exposed through the API, and rendered as Linux/Windows badges in the UI. |
| 6 | Add Windows CI and focused tests. | CI now runs unit tests on Ubuntu and Windows, with registry validation kept on Ubuntu. Tests cover host selection, path safety, restart scheduling, dependency command selection, platform normalization, UI badges, and queued locked-file removal. |
| 7 | Update docs and generated plugin. | README now documents Linux and Windows installation, restart behavior, dependency management, and third-party plugin platform caveats. `plugin.py` is regenerated from `plugin_core.py` during final verification. |

## Current State

PyPluginStore is mostly platform-neutral already. It uses argument-list
subprocess calls, JSON registries, `os.path`, and a shared Domoticz custom UI.

The main Windows blockers are:

- `onStart()` exits immediately on Windows.
- Domoticz restart is hard-coded to Linux service commands.
- Dependency installation assumes Linux-style `uv`, `pip3`, or `pip` command
  availability.
- File permission handling uses `chmod`, which is not meaningful on Windows.
- Plugin deletion/update paths need stronger Windows-safe path validation and
  locked-file handling.
- CI currently validates on Linux only.

## Architecture

Introduce a small host runtime abstraction and keep `BasePlugin` focused on
plugin-manager behavior.

```python
class HostRuntime:
    def plugins_dir(self): ...
    def domoticz_dir(self): ...
    def shared_deps_dir(self): ...
    def make_web_readable(self, path): ...
    def restart_domoticz(self): ...
    def install_requirements(self, requirements_file, target_dir): ...
    def run_git(self, args, cwd, timeout=30): ...
```

Provide concrete implementations:

- `LinuxHostRuntime`
- `WindowsHostRuntime`

Add a single factory:

```python
def make_host_runtime(parameters):
    if platform.system() == "Windows":
        return WindowsHostRuntime(parameters)
    return LinuxHostRuntime(parameters)
```

`BasePlugin` should call `self.host` for operating-system behavior. Ideally,
`platform.system()` only appears in the factory and diagnostic logging.

## Phase 1: Preserve Linux Behavior Behind Host Runtime

Create the host runtime abstraction without changing external behavior.

Tasks:

- Add `HostRuntime`, `LinuxHostRuntime`, and `make_host_runtime()`.
- Move path helpers into the runtime:
  - plugin home folder
  - current plugin folder
  - Domoticz root folder
  - plugins folder
  - shared dependency folder
  - custom UI template and image directories
- Move process helpers into the runtime:
  - Git environment creation
  - Git command execution
  - dependency command discovery
  - Domoticz restart scheduling
- Replace direct path recomputation in `BasePlugin` with runtime methods.
- Keep Linux restart commands unchanged:
  - `sudo -n systemctl restart domoticz.service`
  - `systemctl restart domoticz.service`
  - `sudo -n service domoticz restart`
  - `service domoticz restart`
- Keep `plugin_core.py` as the source file and regenerate `plugin.py`.

Acceptance criteria:

- Existing Linux tests pass unchanged.
- Generated `plugin.py` is current.
- No Windows support is claimed yet.
- Linux behavior is equivalent to the current release.

## Phase 2: Enable Windows Runtime

Remove the Windows startup block and implement Windows-specific host behavior.

Tasks:

- Replace the Windows early return in `onStart()` with capability logging.
- Make `make_web_readable(path)` a no-op on Windows.
- Implement Windows detached restart scheduling.
- Try Windows restart commands in a separate helper process, for example:
  - `sc stop Domoticz` followed by `sc start Domoticz`
  - PowerShell `Restart-Service` where available
- Treat restart as a capability:
  - report success only when the restart command is scheduled
  - log clearly when permissions or service names are not configured
- Add a runtime method for supported restart command discovery.
- Ensure subprocess detaching uses Windows-compatible flags instead of
  `start_new_session=True`.

Acceptance criteria:

- PyPluginStore starts on Windows.
- Registry loading, custom UI installation, listing, install, update, remove,
  and update-status checks work where Git and permissions are available.
- Restart failures are logged as capability/configuration issues, not generic
  plugin failures.

## Phase 3: Dependency Installation Strategy

Make dependency installation target the Python runtime Domoticz is actually
using.

Tasks:

- Prefer `uv` only when it can install for the correct interpreter.
- Fall back to `[sys.executable, "-m", "pip", "install", ...]`.
- Only use standalone `pip3` or `pip` when the Python executable fallback is
  unavailable or invalid.
- Use `shutil.which()` for command detection.
- Keep dependencies installed into `.shared_deps`.
- Keep `.shared_deps` injected into `sys.path` before managed plugins load.
- Improve logs to show the selected installer and target directory.

Acceptance criteria:

- Linux dependency installation continues to work.
- Windows installs dependencies into the same `.shared_deps` model.
- The selected installer matches the running Python wherever possible.

## Phase 4: Filesystem Safety And Locked Files

Harden path validation and account for Windows file locking.

Tasks:

- Replace string-prefix path validation with `os.path.commonpath()`.
- Use `os.path.normcase()` when comparing paths on case-insensitive systems.
- Keep plugin keys restricted to visible folder names with no separators.
- Add a safe helper for resolving a plugin directory inside `plugins_dir`.
- Detect failed remove/update operations caused by locked files.
- Add a pending-operation file for deferred remove/update retries on next
  startup.
- Process pending operations early in `onStart()`, before normal update logic.

Acceptance criteria:

- Path traversal attempts are rejected on Linux and Windows.
- Removing one plugin cannot delete outside the plugins directory.
- Windows locked-file failures return a clear message and can be retried after
  restart.

## Phase 5: Registry Platform Metadata

Keep the existing registry format working, but prepare for platform-aware UI.

Tasks:

- Preserve support for the existing list format:
  - owner
  - repository
  - description
  - branch
- Add an internal registry normalizer that can later accept object-style
  entries.
- Add optional platform metadata:
  - `linux`
  - `windows`
  - `unknown`
- Do not require every existing registry entry to be classified immediately.
- Expose normalized platform metadata through the existing API response.
- Add UI badges or filters after backend normalization is stable.

Acceptance criteria:

- Existing `registry.json` remains valid.
- Local registry overlays still work.
- Plugins with unknown platform support remain installable unless explicitly
  blocked by policy.

## Phase 6: CI And Test Coverage

Add automated coverage before documenting Windows as supported.

Tasks:

- Update `.github/workflows/validate.yml` to run unit tests on:
  - `ubuntu-latest`
  - `windows-latest`
- Keep slow or network-heavy registry validation on one OS if necessary.
- Add tests for:
  - runtime factory selection
  - Linux path behavior
  - Windows path behavior
  - safe plugin path resolution
  - Windows `chmod` no-op behavior
  - dependency installer selection
  - restart command scheduling
  - generated `plugin.py` freshness
- Add Windows-specific fake subprocess tests instead of requiring a real
  Domoticz Windows service in CI.

Acceptance criteria:

- Unit tests pass on Linux and Windows runners.
- Registry validation still runs in CI.
- No test requires a real Domoticz service.

## Phase 7: Documentation

Update documentation only after runtime support and CI are in place.

Tasks:

- Replace the Linux-only README note with a supported-platforms section.
- Document Windows prerequisites:
  - Domoticz with Python plugin support
  - Git available on `PATH`
  - Python package installer available through the Domoticz Python runtime
  - service permissions if using the restart button
- Provide Linux and Windows install examples.
- Document restart behavior separately for Linux and Windows.
- Document that managed third-party plugins may still be Linux-only.

Acceptance criteria:

- README accurately describes supported manager behavior.
- README does not imply every registry plugin works on Windows.
- Manual dependency installation examples include Windows paths.

## Suggested PR Breakdown

1. Host runtime abstraction with Linux behavior preserved.
2. Path safety cleanup and focused tests.
3. Windows runtime implementation.
4. Dependency installer improvements.
5. Windows CI matrix.
6. Optional registry platform metadata and UI badges.
7. README update once support is verified.

## Risks

- Some third-party Domoticz plugins may use Linux-only libraries or shell
  commands.
- Windows may lock plugin files during update or removal.
- Domoticz Windows service naming and permissions may vary by installation.
- Installing Python dependencies for the wrong interpreter can lead to subtle
  runtime import failures.

## Non-Goals

- Guarantee every registry plugin works on Windows.
- Replace Git-based install/update behavior.
- Add a new package manager or global dependency installation model.
- Rewrite the custom UI as part of platform support.
