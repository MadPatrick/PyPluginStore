from pathlib import Path
from types import SimpleNamespace


def configure_home(plugin_core_module, tmp_path):
    plugins_dir = tmp_path / "domoticz" / "plugins"
    manager_dir = plugins_dir / "00-PyPluginStore"
    manager_dir.mkdir(parents=True)
    plugin_core_module.Parameters = {"HomeFolder": str(manager_dir) + "/"}
    return plugins_dir, manager_dir


def test_add_self_to_registry_uses_installed_folder(plugin_core_module, tmp_path):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()

    plugin.add_self_to_registry()

    assert plugin.plugin_data["00-PyPluginStore"] == [
        "adrighem",
        "PyPluginStore",
        "PyPluginStore plugin manager",
        "master",
        "",
    ]


def test_get_git_update_status_reports_available(plugin_core_module, tmp_path, monkeypatch):
    plugin_dir = tmp_path / "Plugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()
    responses = iter([
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(returncode=0, stdout="0\t2\n", stderr=""),
    ])
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return next(responses)

    monkeypatch.setattr(plugin_core_module.subprocess, "run", fake_run)

    assert plugin.getGitUpdateStatus(plugin_dir) == "available"
    assert calls[0][0] == ["git", "fetch", "--quiet"]
    assert calls[1][0] == ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"]


def test_get_git_update_status_reports_current(plugin_core_module, tmp_path, monkeypatch):
    plugin_dir = tmp_path / "Plugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()
    responses = iter([
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(returncode=0, stdout="0 0\n", stderr=""),
    ])

    monkeypatch.setattr(plugin_core_module.subprocess, "run", lambda *args, **kwargs: next(responses))

    assert plugin.getGitUpdateStatus(plugin_dir) == "current"


def test_get_git_update_status_reports_unknown_without_git(plugin_core_module, tmp_path):
    plugin = plugin_core_module.BasePlugin()

    assert plugin.getGitUpdateStatus(tmp_path / "Plugin") == "unknown"


def test_list_plugins_response_includes_manager_and_update_status(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    (plugins_dir / "OtherPlugin").mkdir()
    (plugins_dir / ".hidden").mkdir()
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "00-PyPluginStore": ["adrighem", "PyPluginStore", "PyPluginStore plugin manager", "master", ""],
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }
    responses = []

    def fake_status(installed, actual_plugins_dir):
        assert Path(actual_plugins_dir) == plugins_dir
        return {key: "current" for key in installed}

    monkeypatch.setattr(plugin, "getInstalledUpdateStatuses", fake_status)
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "list_plugins"})

    response = responses[0]
    assert response["status"] == "success"
    assert response["manager_key"] == "00-PyPluginStore"
    assert set(response["installed"]) == {"00-PyPluginStore", "OtherPlugin"}
    assert response["update_status"] == {
        "00-PyPluginStore": "current",
        "OtherPlugin": "current",
    }


def test_restart_command_responds_before_scheduling_restart(plugin_core_module, tmp_path, monkeypatch):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    events = []

    monkeypatch.setattr(plugin, "sendApiResponse", lambda response: events.append(("response", response)))
    monkeypatch.setattr(plugin, "restartDomoticz", lambda: events.append(("restart", None)))

    plugin.handleApiCommand({"action": "restart_domoticz"})

    assert events[0][0] == "response"
    assert events[0][1]["status"] == "success"
    assert events[0][1]["action"] == "restart_domoticz"
    assert events[1] == ("restart", None)
