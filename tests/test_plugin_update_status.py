from datetime import datetime
from pathlib import Path

from plugin_core_helpers import configure_home, write_plugin_py


class FakeGitResult:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


DUBIOUS_OWNERSHIP_ERROR = (
    "fatal: detected dubious ownership in repository at '/tmp/Plugin'\n"
    "To add an exception for this directory, call:\n"
    "\tgit config --global --add safe.directory /tmp/Plugin\n"
)


def recorded_messages(plugin_core_module, level):
    return [args[0] for args, _ in plugin_core_module.Domoticz.calls[level] if args]


def test_run_git_bypasses_dubious_ownership_with_safe_directory(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / ".git").mkdir()
    runtime = plugin_core_module.LinuxHostRuntime(plugin_core_module.Parameters)
    calls = []
    repairs = []

    def fake_run(command, cwd=None, **kwargs):
        calls.append((command, Path(cwd)))
        if len(calls) == 1:
            return FakeGitResult(stderr=DUBIOUS_OWNERSHIP_ERROR, returncode=128)
        return FakeGitResult(stdout="ok\n", returncode=0)

    monkeypatch.setattr(plugin_core_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        runtime,
        "repair_git_repository_ownership",
        lambda cwd: repairs.append(Path(cwd)) or True,
    )

    result = runtime.run_git(["git", "fetch", "--quiet"], manager_dir)

    assert result.returncode == 0
    assert len(calls) == 2
    assert calls[0] == (["git", "fetch", "--quiet"], manager_dir)
    assert calls[1][0] == ["git", "-c", "safe.directory=" + str(manager_dir.resolve()), "fetch", "--quiet"]
    assert len(repairs) == 0  # No chown repair should have been called!
    assert any("retrying with safe.directory bypass" in message for message in recorded_messages(plugin_core_module, "Log"))
    assert not any("ownership does not match the Domoticz user" in message for message in recorded_messages(plugin_core_module, "Error"))


def test_run_git_falls_back_to_repair_when_bypass_fails(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / ".git").mkdir()
    runtime = plugin_core_module.LinuxHostRuntime(plugin_core_module.Parameters)
    calls = []
    repairs = []

    def fake_run(command, cwd=None, **kwargs):
        calls.append((command, Path(cwd)))
        if len(calls) <= 2:
            return FakeGitResult(stderr=DUBIOUS_OWNERSHIP_ERROR, returncode=128)
        return FakeGitResult(stdout="ok\n", returncode=0)

    monkeypatch.setattr(plugin_core_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        runtime,
        "repair_git_repository_ownership",
        lambda cwd: repairs.append(Path(cwd)) or True,
    )

    result = runtime.run_git(["git", "fetch", "--quiet"], manager_dir)

    assert result.returncode == 0
    assert len(calls) == 3
    assert calls[0] == (["git", "fetch", "--quiet"], manager_dir)
    assert calls[1][0] == ["git", "-c", "safe.directory=" + str(manager_dir.resolve()), "fetch", "--quiet"]
    assert calls[2] == (["git", "fetch", "--quiet"], manager_dir)
    assert repairs == [manager_dir.resolve()]  # chown repair called on fallback!
    assert any("retrying with safe.directory bypass" in message for message in recorded_messages(plugin_core_module, "Log"))
    assert any("ownership does not match the Domoticz user" in message for message in recorded_messages(plugin_core_module, "Error"))
    assert any("Fixed plugin repository ownership" in message for message in recorded_messages(plugin_core_module, "Log"))


def test_get_git_update_status_reports_available(plugin_core_module, tmp_path, monkeypatch):
    plugin_dir = tmp_path / "Plugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()

    monkeypatch.setattr(plugin, "fetch_git_repo", lambda actual_dir: True)
    monkeypatch.setattr(plugin, "get_git_remote_ref", lambda actual_dir: "origin/main")
    monkeypatch.setattr(plugin, "get_git_ahead_behind", lambda actual_dir, ref: (0, 2))

    assert plugin.getGitUpdateStatus(plugin_dir) == "available"


def test_get_git_update_status_reports_current(plugin_core_module, tmp_path, monkeypatch):
    plugin_dir = tmp_path / "Plugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()

    monkeypatch.setattr(plugin, "fetch_git_repo", lambda actual_dir: True)
    monkeypatch.setattr(plugin, "get_git_remote_ref", lambda actual_dir: "origin/main")
    monkeypatch.setattr(plugin, "get_git_ahead_behind", lambda actual_dir, ref: (0, 0))

    assert plugin.getGitUpdateStatus(plugin_dir) == "current"


def test_get_git_update_status_reports_unknown_without_git(plugin_core_module, tmp_path):
    plugin = plugin_core_module.BasePlugin()

    assert plugin.getGitUpdateStatus(tmp_path / "Plugin") == "unknown"


def test_get_git_update_status_refreshes_local_update_time(plugin_core_module, tmp_path, monkeypatch):
    configure_home(plugin_core_module, tmp_path)
    plugin_dir = tmp_path / "Plugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "Plugin": ["owner", "repo", "description", "main", "2026-01-01T00:00:00Z"],
    }
    plugin.update_times = {"Plugin": "2026-01-01T00:00:00Z"}
    saved_update_times = []

    monkeypatch.setattr(plugin, "fetch_git_repo", lambda actual_dir: True)
    monkeypatch.setattr(plugin, "get_git_remote_ref", lambda actual_dir: "origin/main")
    monkeypatch.setattr(plugin, "get_git_remote_commit_date", lambda actual_dir, ref: "2026-06-14T15:10:03Z")
    monkeypatch.setattr(plugin, "get_git_remote_url", lambda actual_dir, remote: "https://github.com/owner/repo.git")
    monkeypatch.setattr(plugin, "get_git_ahead_behind", lambda actual_dir, ref: (0, 1))
    monkeypatch.setattr(plugin, "save_update_times_cache", lambda update_times: saved_update_times.append(dict(update_times)) or True)

    assert plugin.getGitUpdateStatus(plugin_dir, "Plugin") == "available"
    assert plugin.plugin_data["Plugin"][4] == "2026-06-14T15:10:03Z"
    assert saved_update_times == [{"Plugin": "2026-06-14T15:10:03Z"}]


def test_get_installed_update_status_skips_unmanaged_plugins(plugin_core_module, tmp_path, monkeypatch):
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "KnownPlugin": ["owner", "repo", "description", "main", ""],
    }
    checked_plugins = []

    def fake_status(plugin_dir, plugin_key=None, fetch_first=True):
        checked_plugins.append(plugin_key)
        return "current"

    monkeypatch.setattr(plugin, "getGitUpdateStatus", fake_status)

    assert plugin.getInstalledUpdateStatuses(["KnownPlugin", "LooseFolder"], tmp_path) == {
        "KnownPlugin": "current",
        "LooseFolder": "unknown",
    }
    assert checked_plugins == ["KnownPlugin"]
    assert plugin.update_status == {
        "KnownPlugin": "current",
        "LooseFolder": "unknown",
    }


def test_refresh_installed_update_statuses_checks_managed_plugins_in_order(plugin_core_module, tmp_path, monkeypatch):
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "FirstPlugin": ["owner", "repo", "description", "main", ""],
        "SecondPlugin": ["owner", "repo", "description", "main", ""],
    }
    checked_plugins = []

    def fake_status(plugin_dir, plugin_key=None, fetch_first=True):
        checked_plugins.append(plugin_key)
        return {
            "FirstPlugin": "current",
            "SecondPlugin": "available",
        }[plugin_key]

    monkeypatch.setattr(plugin, "getGitUpdateStatus", fake_status)

    assert plugin.refreshInstalledUpdateStatuses(
        ["FirstPlugin", "LooseFolder", "SecondPlugin"],
        tmp_path,
    ) == {
        "FirstPlugin": "current",
        "LooseFolder": "unknown",
        "SecondPlugin": "available",
    }
    assert checked_plugins == ["FirstPlugin", "SecondPlugin"]
    assert plugin.update_status == {
        "FirstPlugin": "current",
        "LooseFolder": "unknown",
        "SecondPlugin": "available",
    }


def test_refresh_installed_update_status_uses_detected_folder(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "Domoticz-deCONZ"
    write_plugin_py(plugin_dir, key="DECONZ", name="deCONZ")
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "deCONZ": ["Smanar", "Domoticz-deCONZ", "description", "master", ""],
    }
    checked_plugins = []

    def fake_status(actual_plugin_dir, plugin_key=None, fetch_first=True):
        checked_plugins.append((Path(actual_plugin_dir), plugin_key))
        return "current"

    monkeypatch.setattr(plugin, "getGitUpdateStatus", fake_status)

    installed = plugin.getInstalledPlugins(plugins_dir)

    assert plugin.refreshInstalledUpdateStatuses(installed, plugins_dir)["deCONZ"] == "current"
    assert checked_plugins == [(plugin_dir, "deCONZ")]


def test_update_command_refreshes_cached_status_for_next_list(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "OtherPlugin"
    (plugin_dir / ".git").mkdir(parents=True)
    write_plugin_py(plugin_dir, key="OTHER", name="OtherPlugin")
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }
    plugin.update_status = {"OtherPlugin": "available"}
    responses = []
    status_calls = []

    def fake_git_status(actual_plugin_dir, plugin_key=None, fetch_first=True):
        status_calls.append((Path(actual_plugin_dir), plugin_key, fetch_first))
        return "current"

    monkeypatch.setattr(plugin_core_module.subprocess, "run", lambda *args, **kwargs: FakeGitResult())
    monkeypatch.setattr(plugin, "refresh_single_plugin_update_time", lambda *args, **kwargs: False)
    monkeypatch.setattr(plugin, "installDependencies", lambda plugin_key: None)
    monkeypatch.setattr(plugin, "getGitUpdateStatus", fake_git_status)
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "update", "plugin_key": "OtherPlugin"})
    plugin.handleApiCommand({"action": "list_plugins"})

    assert responses[0] == {
        "status": "success",
        "action": "update",
        "plugin_key": "OtherPlugin",
    }
    assert responses[1]["update_status"]["OtherPlugin"] == "current"
    assert plugin.update_status["OtherPlugin"] == "current"
    assert status_calls == [(plugin_dir, "OtherPlugin", False)]


def test_update_command_uses_detected_repository_folder(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "Domoticz-deCONZ"
    (plugin_dir / ".git").mkdir(parents=True)
    write_plugin_py(plugin_dir, key="DECONZ", name="deCONZ")
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "deCONZ": ["Smanar", "Domoticz-deCONZ", "description", "master", ""],
    }
    responses = []
    git_calls = []
    status_calls = []

    def fake_run(command, cwd=None, **kwargs):
        git_calls.append((command, Path(cwd)))
        if command == ["git", "remote", "-v"]:
            class FakeRemoteResult:
                stdout = "origin\tgit@github.com:Smanar/Domoticz-deCONZ.git (fetch)\n"
                stderr = ""
                returncode = 0

            return FakeRemoteResult()
        return FakeGitResult()

    def fake_refresh_status(plugin_key, actual_plugin_dir, fetch_first=True):
        status_calls.append((plugin_key, Path(actual_plugin_dir), fetch_first))
        plugin.update_status[plugin_key] = "current"
        return "current"

    monkeypatch.setattr(plugin_core_module.subprocess, "run", fake_run)
    monkeypatch.setattr(plugin, "refresh_single_plugin_update_time", lambda *args, **kwargs: False)
    monkeypatch.setattr(plugin, "refresh_single_plugin_update_status", fake_refresh_status)
    monkeypatch.setattr(plugin, "installDependencies", lambda plugin_key: None)
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "update", "plugin_key": "deCONZ"})

    assert responses[0] == {
        "status": "success",
        "action": "update",
        "plugin_key": "deCONZ",
    }
    assert all(cwd == plugin_dir for _, cwd in git_calls)
    assert [command for command, _ in git_calls[-3:]] == [
        ["git", "reset", "--hard", "HEAD"],
        ["git", "checkout", "master"],
        ["git", "pull", "--force", "origin", "master"],
    ]
    assert status_calls == [("deCONZ", plugin_dir, False)]


def test_self_update_command_schedules_detached_helper(plugin_core_module, tmp_path, monkeypatch):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "00-PyPluginStore": ["adrighem", "PyPluginStore", "description", "master", ""],
    }
    responses = []
    popen_calls = []

    def fail_sync_git(*args, **kwargs):
        raise AssertionError("self update should not run git synchronously")

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))

        class FakeProcess:
            pass

        return FakeProcess()

    monkeypatch.setattr(
        plugin_core_module.HostRuntime,
        "preflight_self_update",
        lambda self, plugin_dir: (
            True,
            "Self update pre-flight checks passed.",
            {"already_current": False, "upstream_ref": "origin/master"},
        ),
    )
    monkeypatch.setattr(plugin_core_module.subprocess, "run", fail_sync_git)
    monkeypatch.setattr(plugin_core_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "update", "plugin_key": "00-PyPluginStore"})

    assert responses[0]["status"] == "success"
    assert responses[0]["action"] == "update"
    assert responses[0]["plugin_key"] == "00-PyPluginStore"
    assert responses[0]["message"].startswith("Self update started after pre-flight checks.")
    assert plugin.update_status["00-PyPluginStore"] == "unknown"
    assert len(popen_calls) == 1

    command = popen_calls[0][0][0]
    helper = command[2]
    assert command[:2] == [plugin_core_module.sys.executable, "-c"]
    assert '["git", "status", "--porcelain", "--untracked-files=no"]' in helper
    assert '["git", "merge", "--ff-only", upstream_ref]' in helper
    assert '["git", "reset", "--hard", "HEAD"]' not in helper
    assert '["git", "pull", "--force"]' not in helper


def test_self_update_command_reports_preflight_failure(plugin_core_module, tmp_path, monkeypatch):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "00-PyPluginStore": ["adrighem", "PyPluginStore", "description", "master", ""],
    }
    responses = []

    monkeypatch.setattr(
        plugin_core_module.HostRuntime,
        "preflight_self_update",
        lambda self, plugin_dir: (False, "PyPluginStore has local tracked file changes; self-update refused.", {}),
    )
    monkeypatch.setattr(
        plugin_core_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected helper launch")),
    )
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "update", "plugin_key": "00-PyPluginStore"})

    assert responses[0] == {
        "status": "error",
        "message": "PyPluginStore has local tracked file changes; self-update refused.",
    }


def test_self_update_preflight_rejects_dirty_tracked_files(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / ".git").mkdir()
    runtime = plugin_core_module.LinuxHostRuntime(plugin_core_module.Parameters)

    def fake_run_git(command, cwd, timeout=15):
        if command == ["git", "rev-parse", "--is-inside-work-tree"]:
            return FakeGitResult("true\n")
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return FakeGitResult(str(manager_dir) + "\n")
        if command == ["git", "status", "--porcelain", "--untracked-files=no"]:
            return FakeGitResult(" M plugin.py\n")
        raise AssertionError("unexpected command: " + repr(command))

    monkeypatch.setattr(runtime, "command_available", lambda command: command == "git")
    monkeypatch.setattr(runtime, "run_git", fake_run_git)

    success, message, plan = runtime.preflight_self_update(manager_dir)

    assert success is False
    assert message == "PyPluginStore has local tracked file changes; self-update refused."
    assert plan == {}


def test_self_update_preflight_reports_dubious_ownership(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / ".git").mkdir()
    runtime = plugin_core_module.LinuxHostRuntime(plugin_core_module.Parameters)

    monkeypatch.setattr(runtime, "command_available", lambda command: command == "git")
    monkeypatch.setattr(
        runtime,
        "_run_git_once",
        lambda command, cwd, timeout=15: FakeGitResult(stderr=DUBIOUS_OWNERSHIP_ERROR, returncode=128),
    )
    monkeypatch.setattr(runtime, "repair_git_repository_ownership", lambda cwd: False)

    success, message, plan = runtime.preflight_self_update(manager_dir)

    assert success is False
    assert "ownership does not match the Domoticz user" in message
    assert "fix the plugin folder ownership manually" in message
    assert "safe.directory" not in message
    assert plan == {}


def test_self_update_preflight_rejects_invalid_target_python(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / ".git").mkdir()
    runtime = plugin_core_module.LinuxHostRuntime(plugin_core_module.Parameters)

    def fake_run_git(command, cwd, timeout=15):
        if command == ["git", "rev-parse", "--is-inside-work-tree"]:
            return FakeGitResult("true\n")
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return FakeGitResult(str(manager_dir) + "\n")
        if command == ["git", "status", "--porcelain", "--untracked-files=no"]:
            return FakeGitResult("")
        if command == ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
            return FakeGitResult("origin/master\n")
        if command == ["git", "fetch", "--prune"]:
            return FakeGitResult("")
        if command == ["git", "rev-parse", "--verify", "origin/master"]:
            return FakeGitResult("abc123\n")
        if command == ["git", "merge-base", "--is-ancestor", "HEAD", "origin/master"]:
            return FakeGitResult("")
        if command == ["git", "rev-list", "--left-right", "--count", "HEAD...origin/master"]:
            return FakeGitResult("0\t1\n")
        if command[:3] == ["git", "cat-file", "-e"]:
            return FakeGitResult("")
        if command == ["git", "show", "origin/master:plugin.py"]:
            return FakeGitResult("def broken(:\n")
        raise AssertionError("unexpected command: " + repr(command))

    monkeypatch.setattr(runtime, "command_available", lambda command: command == "git")
    monkeypatch.setattr(runtime, "run_git", fake_run_git)

    success, message, plan = runtime.preflight_self_update(manager_dir)

    assert success is False
    assert "invalid Python syntax in plugin.py" in message
    assert plan == {}


def test_self_update_preflight_allows_fast_forward_candidate(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / ".git").mkdir()
    runtime = plugin_core_module.LinuxHostRuntime(plugin_core_module.Parameters)

    def fake_run_git(command, cwd, timeout=15):
        if command == ["git", "rev-parse", "--is-inside-work-tree"]:
            return FakeGitResult("true\n")
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return FakeGitResult(str(manager_dir) + "\n")
        if command == ["git", "status", "--porcelain", "--untracked-files=no"]:
            return FakeGitResult("")
        if command == ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
            return FakeGitResult("origin/master\n")
        if command == ["git", "fetch", "--prune"]:
            return FakeGitResult("")
        if command == ["git", "rev-parse", "--verify", "origin/master"]:
            return FakeGitResult("abc123\n")
        if command == ["git", "merge-base", "--is-ancestor", "HEAD", "origin/master"]:
            return FakeGitResult("")
        if command == ["git", "rev-list", "--left-right", "--count", "HEAD...origin/master"]:
            return FakeGitResult("0\t1\n")
        if command[:3] == ["git", "cat-file", "-e"]:
            return FakeGitResult("")
        if command == ["git", "show", "origin/master:plugin.py"]:
            return FakeGitResult("print('plugin')\n")
        if command == ["git", "show", "origin/master:plugin_core.py"]:
            return FakeGitResult("print('core')\n")
        raise AssertionError("unexpected command: " + repr(command))

    monkeypatch.setattr(runtime, "command_available", lambda command: command == "git")
    monkeypatch.setattr(runtime, "run_git", fake_run_git)

    success, message, plan = runtime.preflight_self_update(manager_dir)

    assert success is True
    assert message == "Self update pre-flight checks passed."
    assert plan == {"already_current": False, "upstream_ref": "origin/master"}


def test_self_update_preflight_reports_already_current(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / ".git").mkdir()
    runtime = plugin_core_module.LinuxHostRuntime(plugin_core_module.Parameters)

    def fake_run_git(command, cwd, timeout=15):
        if command == ["git", "rev-parse", "--is-inside-work-tree"]:
            return FakeGitResult("true\n")
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return FakeGitResult(str(manager_dir) + "\n")
        if command == ["git", "status", "--porcelain", "--untracked-files=no"]:
            return FakeGitResult("")
        if command == ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
            return FakeGitResult("origin/master\n")
        if command == ["git", "fetch", "--prune"]:
            return FakeGitResult("")
        if command == ["git", "rev-parse", "--verify", "origin/master"]:
            return FakeGitResult("abc123\n")
        if command == ["git", "merge-base", "--is-ancestor", "HEAD", "origin/master"]:
            return FakeGitResult("")
        if command == ["git", "rev-list", "--left-right", "--count", "HEAD...origin/master"]:
            return FakeGitResult("0\t0\n")
        raise AssertionError("unexpected command: " + repr(command))

    monkeypatch.setattr(runtime, "command_available", lambda command: command == "git")
    monkeypatch.setattr(runtime, "run_git", fake_run_git)

    success, message, plan = runtime.preflight_self_update(manager_dir)

    assert success is True
    assert message == "PyPluginStore is already up-to-date."
    assert plan == {"already_current": True, "upstream_ref": "origin/master"}


def test_refresh_update_status_command_runs_serial_refresh(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    write_plugin_py(plugins_dir / "OtherPlugin", key="OTHER", name="OtherPlugin")
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }
    responses = []
    calls = []

    def fake_fetch_registry():
        calls.append("fetch_registry")
        plugin.plugin_data["LocalPlugin"] = [
            "git@github.com:owner/private-plugin.git",
            "",
            "local description",
            "main",
            "",
        ]
        plugin.local_plugin_keys = ["LocalPlugin"]

    def fake_refresh(installed, actual_plugins_dir):
        calls.append("refresh_status")
        assert Path(actual_plugins_dir) == plugins_dir
        assert set(installed) == {"00-PyPluginStore", "OtherPlugin"}
        return {"00-PyPluginStore": "unknown", "OtherPlugin": "available"}

    monkeypatch.setattr(plugin, "fetch_registry", fake_fetch_registry)
    monkeypatch.setattr(plugin, "refreshInstalledUpdateStatuses", fake_refresh)
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "refresh_update_status"})

    response = responses[0]
    assert response["status"] == "success"
    assert response["action"] == "refresh_update_status"
    assert response["update_status"] == {
        "00-PyPluginStore": "unknown",
        "OtherPlugin": "available",
    }
    assert response["data"] == plugin.plugin_data
    assert response["local_plugins"] == ["LocalPlugin"]
    assert response["installed_match_details"]["OtherPlugin"]["source"] == "exact folder key"
    assert calls == ["fetch_registry", "refresh_status"]


def test_check_for_update_reports_unknown_without_error(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "OtherPlugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }

    monkeypatch.setattr(plugin, "fetch_git_repo", lambda actual_dir: False)

    plugin.CheckForUpdatePythonPlugin("owner", "repo", "OtherPlugin")

    assert plugin_core_module.Domoticz.calls["Error"] == []
    assert plugin_core_module.Domoticz.calls["SendNotification"] == []
    assert plugin.update_status["OtherPlugin"] == "unknown"


def test_check_for_update_notifies_when_update_available(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "OtherPlugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }

    monkeypatch.setattr(plugin, "fetch_git_repo", lambda actual_dir: True)
    monkeypatch.setattr(plugin, "get_git_remote_ref", lambda actual_dir: "origin/main")
    monkeypatch.setattr(plugin, "get_git_remote_commit_date", lambda actual_dir, ref: "")
    monkeypatch.setattr(plugin, "get_git_ahead_behind", lambda actual_dir, ref: (0, 1))

    plugin.CheckForUpdatePythonPlugin("owner", "repo", "OtherPlugin")

    assert plugin_core_module.Domoticz.calls["Error"] == []
    assert len(plugin_core_module.Domoticz.calls["SendNotification"]) == 1
    assert plugin.update_status["OtherPlugin"] == "available"


def test_check_for_update_caches_current_status(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "OtherPlugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }

    monkeypatch.setattr(plugin, "fetch_git_repo", lambda actual_dir: True)
    monkeypatch.setattr(plugin, "get_git_remote_ref", lambda actual_dir: "origin/main")
    monkeypatch.setattr(plugin, "get_git_remote_commit_date", lambda actual_dir, ref: "")
    monkeypatch.setattr(plugin, "get_git_ahead_behind", lambda actual_dir, ref: (0, 0))

    plugin.CheckForUpdatePythonPlugin("owner", "repo", "OtherPlugin")

    assert plugin_core_module.Domoticz.calls["Error"] == []
    assert plugin_core_module.Domoticz.calls["SendNotification"] == []
    assert plugin.update_status["OtherPlugin"] == "current"


def test_check_for_update_skips_missing_notification_api(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "OtherPlugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }

    monkeypatch.delattr(plugin_core_module.Domoticz, "SendNotification", raising=False)
    monkeypatch.setattr(plugin, "fetch_git_repo", lambda actual_dir: True)
    monkeypatch.setattr(plugin, "get_git_remote_ref", lambda actual_dir: "origin/main")
    monkeypatch.setattr(plugin, "get_git_remote_commit_date", lambda actual_dir, ref: "")
    monkeypatch.setattr(plugin, "get_git_ahead_behind", lambda actual_dir, ref: (0, 1))

    plugin.CheckForUpdatePythonPlugin("owner", "repo", "OtherPlugin")

    assert plugin_core_module.Domoticz.calls["Error"] == []
    assert plugin_core_module.Domoticz.calls["SendNotification"] == []
    assert any("Notification skipped" in args[0] for args, _ in plugin_core_module.Domoticz.calls["Log"])
    assert plugin.update_status["OtherPlugin"] == "available"


def test_install_command_reports_clone_failure(plugin_core_module, tmp_path, monkeypatch):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "PrivatePlugin": ["git@github.com:owner/private-plugin.git", "", "description", "main", ""],
    }
    responses = []

    class FakeGitResult:
        stdout = ""
        stderr = "fatal: repository not found"
        returncode = 128

    monkeypatch.setattr(plugin_core_module.subprocess, "run", lambda *args, **kwargs: FakeGitResult())
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "install", "plugin_key": "PrivatePlugin"})

    assert responses[0]["status"] == "error"
    assert "repository not found" in responses[0]["message"]


def test_daily_heartbeat_refreshes_update_status_once(plugin_core_module, tmp_path, monkeypatch):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    refresh_calls = []

    class FakeDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 6, 15, 8, 0, 0)

    monkeypatch.setattr(plugin_core_module, "datetime", FakeDateTime)
    monkeypatch.setattr(plugin, "refreshInstalledUpdateStatuses", lambda **kwargs: refresh_calls.append(kwargs) or {})

    plugin.onHeartbeat()
    plugin.onHeartbeat()

    assert len(refresh_calls) == 1
    assert Path(refresh_calls[0]["plugins_dir"]).name == "plugins"


def test_dependency_install_command_prefers_uv_with_active_python(plugin_core_module, tmp_path):
    runtime = plugin_core_module.LinuxHostRuntime({})
    runtime.command_available = lambda command: command == "uv"

    command = runtime.dependency_install_command(str(tmp_path / "requirements.txt"), str(tmp_path / "deps"))

    assert command[:5] == ["uv", "pip", "install", "--python", plugin_core_module.sys.executable]


def test_dependency_install_command_prefers_current_python_before_pip3(plugin_core_module, tmp_path):
    runtime = plugin_core_module.LinuxHostRuntime({})
    runtime.command_available = lambda command: command == "pip3"
    runtime.command_can_run = lambda command, timeout=10: command == [plugin_core_module.sys.executable, "-m", "pip", "--version"]

    command = runtime.dependency_install_command(str(tmp_path / "requirements.txt"), str(tmp_path / "deps"))

    assert command[:3] == [plugin_core_module.sys.executable, "-m", "pip"]
