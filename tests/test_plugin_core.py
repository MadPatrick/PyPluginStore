import json
from datetime import datetime
from pathlib import Path


def configure_home(plugin_core_module, tmp_path):
    plugins_dir = tmp_path / "domoticz" / "plugins"
    manager_dir = plugins_dir / "00-PyPluginStore"
    manager_dir.mkdir(parents=True)
    plugin_core_module.Parameters = {
        "HomeFolder": str(manager_dir) + "/",
        "Mode4": "None",
    }
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


def test_load_update_times_falls_back_to_bundled_file(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    bundled_file = manager_dir / "update_times.json"
    bundled_file.write_text(json.dumps({"Plugin": "2026-06-14T15:10:03Z"}))
    plugin = plugin_core_module.BasePlugin()

    def fake_urlopen(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(plugin_core_module.urllib.request, "urlopen", fake_urlopen)

    assert plugin.load_update_times() == {"Plugin": "2026-06-14T15:10:03Z"}
    assert json.loads(bundled_file.read_text()) == {"Plugin": "2026-06-14T15:10:03Z"}
    assert json.loads((manager_dir / "update_times.cache.json").read_text()) == {
        "Plugin": "2026-06-14T15:10:03Z",
    }


def test_load_update_times_uses_bundled_when_cache_write_fails(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / "update_times.json").write_text(json.dumps({"Plugin": "2026-06-14T15:10:03Z"}))
    plugin = plugin_core_module.BasePlugin()

    def fake_urlopen(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(plugin_core_module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(plugin, "save_update_times_cache", lambda update_times: False)

    assert plugin.load_update_times() == {"Plugin": "2026-06-14T15:10:03Z"}


def test_load_update_times_keeps_newer_cached_timestamp(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / "update_times.cache.json").write_text(json.dumps({"Plugin": "2026-06-14T15:10:03Z"}))
    plugin = plugin_core_module.BasePlugin()
    saved_update_times = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return json.dumps({"Plugin": "2026-01-01T00:00:00Z"}).encode("utf-8")

    monkeypatch.setattr(plugin_core_module.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(plugin, "save_update_times_cache", lambda update_times: saved_update_times.append(dict(update_times)) or True)

    assert plugin.load_update_times() == {"Plugin": "2026-06-14T15:10:03Z"}
    assert saved_update_times == [{"Plugin": "2026-06-14T15:10:03Z"}]


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


def test_list_plugins_response_includes_manager_and_update_status(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    (plugins_dir / "OtherPlugin").mkdir()
    (plugins_dir / ".hidden").mkdir()
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "00-PyPluginStore": ["adrighem", "PyPluginStore", "PyPluginStore plugin manager", "master", ""],
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }
    plugin.update_status = {
        "00-PyPluginStore": "current",
        "OtherPlugin": "available",
    }
    responses = []

    monkeypatch.setattr(plugin, "getGitUpdateStatus", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected git check")))
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "list_plugins"})

    response = responses[0]
    assert response["status"] == "success"
    assert response["manager_key"] == "00-PyPluginStore"
    assert set(response["installed"]) == {"00-PyPluginStore", "OtherPlugin"}
    assert response["update_status"] == {
        "00-PyPluginStore": "current",
        "OtherPlugin": "available",
    }


def test_update_command_refreshes_cached_status_for_next_list(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "OtherPlugin"
    (plugin_dir / ".git").mkdir(parents=True)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }
    plugin.update_status = {"OtherPlugin": "available"}
    responses = []
    status_calls = []

    class FakeGitResult:
        stdout = "Already up to date."
        stderr = ""
        returncode = 0

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


def test_refresh_update_status_command_runs_serial_refresh(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    (plugins_dir / "OtherPlugin").mkdir()
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "OtherPlugin": ["owner", "repo", "description", "main", ""],
    }
    responses = []

    def fake_refresh(installed, actual_plugins_dir):
        assert Path(actual_plugins_dir) == plugins_dir
        assert set(installed) == {"00-PyPluginStore", "OtherPlugin"}
        return {"00-PyPluginStore": "unknown", "OtherPlugin": "available"}

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
