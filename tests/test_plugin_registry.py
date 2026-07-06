import json

from plugin_core_helpers import configure_home, write_plugin_py

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


def test_on_start_installs_custom_ui_and_icon_image(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / "pypluginstore.html").write_text("<div>Plugin Store</div>")
    (manager_dir / "pypluginstore-icon.png").write_bytes(b"icon")
    plugin_core_module.Devices = {}

    class FakeDevice:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def Create(self):
            return None

    monkeypatch.setattr(plugin_core_module.Domoticz, "Device", FakeDevice, raising=False)
    monkeypatch.setattr(plugin_core_module.BasePlugin, "fetch_registry", lambda self: None)

    plugin_core_module.BasePlugin().onStart()

    domoticz_dir = tmp_path / "domoticz"
    assert (domoticz_dir / "www" / "templates" / "pypluginstore.html").read_text() == "<div>Plugin Store</div>"
    assert (domoticz_dir / "www" / "images" / "pypluginstore-icon.png").read_bytes() == b"icon"
    assert not (domoticz_dir / "www" / "templates" / "pypluginstore-icon.png").exists()


def test_on_start_setup_warning_skips_missing_notification_api(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir = tmp_path / "domoticz" / "plugins"
    manager_dir = plugins_dir / "PyPluginStore"
    manager_dir.mkdir(parents=True)
    plugin_core_module.Parameters = {
        "HomeFolder": str(manager_dir) + "/",
        "Mode4": "None",
        "Mode6": "Normal",
    }
    plugin_core_module.Devices = {}

    class FakeDevice:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def Create(self):
            return None

    monkeypatch.setattr(plugin_core_module.Domoticz, "Device", FakeDevice, raising=False)
    monkeypatch.delattr(plugin_core_module.Domoticz, "SendNotification", raising=False)
    monkeypatch.setattr(plugin_core_module.BasePlugin, "fetch_registry", lambda self: None)

    plugin_core_module.BasePlugin().onStart()

    assert any("strongly advised" in args[0] for args, _ in plugin_core_module.Domoticz.calls["Error"])
    assert any("Notification skipped" in args[0] for args, _ in plugin_core_module.Domoticz.calls["Log"])


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


def test_fetch_registry_merges_remote_registry_with_local_overlay(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / "registry_local.json").write_text(json.dumps({
        "LocalPlugin": ["git@github.com:owner/private-plugin.git", "", "local description", "main", "2030-01-01T00:00:00Z"],
        "PublicPlugin": ["local-owner", "public-plugin", "local override", "main"],
    }))
    plugin = plugin_core_module.BasePlugin()

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return json.dumps({
                "PublicPlugin": ["remote-owner", "public-plugin", "remote description", "main"],
                "RemoteOnly": ["remote-owner", "remote-only", "remote only", "master"],
            }).encode("utf-8")

    monkeypatch.setattr(plugin_core_module.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(plugin, "load_update_times", lambda: {
        "LocalPlugin": "2026-06-16T18:42:59Z",
        "PublicPlugin": "2026-06-17T18:42:59Z",
        "RemoteOnly": "2026-06-14T15:10:03Z",
    })

    plugin.fetch_registry()

    assert plugin.plugin_data["PublicPlugin"] == [
        "local-owner",
        "public-plugin",
        "local override",
        "main",
    ]
    assert plugin.plugin_data["LocalPlugin"] == [
        "git@github.com:owner/private-plugin.git",
        "",
        "local description",
        "main",
    ]
    assert plugin.plugin_data["RemoteOnly"] == [
        "remote-owner",
        "remote-only",
        "remote only",
        "master",
        "2026-06-14T15:10:03Z",
    ]
    assert plugin.local_plugin_keys == ["LocalPlugin", "PublicPlugin"]


def test_fetch_registry_falls_back_to_bundled_registry(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    (manager_dir / "registry.json").write_text(json.dumps({
        "BundledPlugin": ["owner", "repo", "description", "main"],
    }))
    plugin = plugin_core_module.BasePlugin()

    monkeypatch.setattr(plugin_core_module.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(plugin, "load_update_times", lambda: {})

    plugin.fetch_registry()

    assert plugin.plugin_data["BundledPlugin"] == ["owner", "repo", "description", "main", ""]
    assert plugin.local_plugin_keys == []


def test_registry_normalizer_accepts_object_entries_with_platforms(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()

    registry, platforms = plugin.normalize_registry({
        "ObjectPlugin": {
            "owner": "owner",
            "repository": "repo",
            "description": "description",
            "branch": "main",
            "platforms": ["Linux", "Windows", "other"],
        },
        "ListPlugin": ["owner", "repo", "description", "main", "", ["windows"]],
    })

    assert registry["ObjectPlugin"] == ["owner", "repo", "description", "main"]
    assert platforms["ObjectPlugin"] == ["linux", "windows"]
    assert registry["ListPlugin"] == ["owner", "repo", "description", "main", ""]
    assert platforms["ListPlugin"] == ["windows"]


def test_registry_entry_model_preserves_legacy_shape(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()

    registry, platforms = plugin.normalize_registry({
        "ObjectPlugin": {
            "owner": "owner",
            "repository": "repo",
            "description": "description",
            "branch": "main",
            "platforms": ["linux"],
        },
        "ListPlugin": ["owner", "repo", "description", "main", "", ["windows"]],
    })

    assert registry == {
        "ObjectPlugin": ["owner", "repo", "description", "main"],
        "ListPlugin": ["owner", "repo", "description", "main", ""],
    }
    assert platforms == {
        "ObjectPlugin": ["linux"],
        "ListPlugin": ["windows"],
    }
    assert plugin.registry_entries["ObjectPlugin"].to_legacy_list() == registry["ObjectPlugin"]
    assert plugin.registry_entries["ListPlugin"].to_legacy_list() == registry["ListPlugin"]


def test_get_registry_entry_rebuilds_from_legacy_plugin_data(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "ManualPlugin": ["owner", "repo", "description", "develop", "2026-06-14T15:10:03Z"],
    }
    plugin.plugin_platforms = {"ManualPlugin": ["windows"]}

    entry = plugin.get_registry_entry("ManualPlugin")

    assert entry.key == "ManualPlugin"
    assert entry.author == "owner"
    assert entry.repository == "repo"
    assert entry.description == "description"
    assert entry.branch == "develop"
    assert entry.updated_at == "2026-06-14T15:10:03Z"
    assert entry.platforms == ["windows"]


def test_build_git_clone_url_accepts_owner_repo_and_full_urls(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()

    assert plugin.build_git_clone_url("owner", "repo") == "https://github.com/owner/repo.git"
    assert plugin.build_git_clone_url("github.com/owner/repo", "") == "https://github.com/owner/repo.git"
    assert plugin.build_git_clone_url("https://github.com/owner/repo/tree/main", "") == "https://github.com/owner/repo.git"
    assert plugin.build_git_clone_url("git@github.com:owner/private-repo.git", "") == "git@github.com:owner/private-repo.git"
    assert plugin.build_git_clone_url("file:///srv/git/local-plugin", "") == "file:///srv/git/local-plugin"


def test_build_git_clone_url_accepts_codeberg_and_gitlab_hosts(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()

    assert plugin.build_git_clone_url(
        "codeberg.org/Hoog",
        "Domoticz-Stromer-plugin",
    ) == "https://codeberg.org/Hoog/Domoticz-Stromer-plugin.git"
    assert plugin.build_git_clone_url(
        "gitlab.com/r.boeters",
        "DomoticzSabNZBDPlugin",
    ) == "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin.git"
    assert plugin.build_git_clone_url(
        "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin/-/tree/master",
        "",
    ) == "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin.git"
    assert plugin.build_git_clone_url(
        "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/src/branch/main",
        "",
    ) == "https://codeberg.org/Hoog/Domoticz-Stromer-plugin.git"


def test_build_git_clone_url_only_normalizes_real_github_hosts(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()

    assert plugin.build_git_clone_url(
        "https://github.com.evil/owner/repo/tree/main",
        "",
    ) == "https://github.com.evil/owner/repo/tree/main"
    assert plugin.build_git_clone_url(
        "https://example.com/github.com/owner/repo/tree/main",
        "",
    ) == "https://example.com/github.com/owner/repo/tree/main"


def test_normalize_git_repo_identity_supports_codeberg_and_gitlab(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()

    assert plugin.normalize_git_repo_identity(
        "git@gitlab.com:r.boeters/DomoticzSabNZBDPlugin.git",
    ) == "gitlab.com/r.boeters/domoticzsabnzbdplugin"
    assert plugin.normalize_git_repo_identity(
        "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/src/branch/main",
    ) == "codeberg.org/hoog/domoticz-stromer-plugin"
    assert plugin.normalize_github_repo_identity(
        "https://codeberg.org/Hoog/Domoticz-Stromer-plugin",
    ) == "codeberg.org/hoog/domoticz-stromer-plugin"


def test_get_plugin_versions_fetches_raw_plugin_py_for_supported_hosts(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    (plugins_dir / "Stromer").mkdir()
    (plugins_dir / "Stromer" / "plugin.py").write_text(
        '"""\n<plugin key="Stromer" name="Stromer" version="1.0.0">\n</plugin>\n"""\n'
    )
    (plugins_dir / "SabNZBD").mkdir()
    (plugins_dir / "SabNZBD" / "plugin.py").write_text(
        '"""\n<plugin key="SabNZBD" name="SabNZBD" version="0.0.1">\n</plugin>\n"""\n'
    )
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "Stromer": ["codeberg.org/Hoog", "Domoticz-Stromer-plugin", "description", "main", ""],
        "SabNZBD": ["gitlab.com/r.boeters", "DomoticzSabNZBDPlugin", "description", "master", ""],
    }
    fetched_urls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return b'"""\n<plugin key="Remote" name="Remote" version="2.0.0">\n</plugin>\n"""\n'

    def fake_urlopen(request, timeout=0):
        fetched_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(plugin_core_module.urllib.request, "urlopen", fake_urlopen)

    versions = plugin.get_plugin_versions(
        ["Stromer", "SabNZBD"],
        {"Stromer": "available", "SabNZBD": "available"},
        str(plugins_dir),
    )

    assert fetched_urls == [
        "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/raw/branch/main/plugin.py",
        "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin/-/raw/master/plugin.py",
    ]
    assert versions == {
        "Stromer": {"installed": "1.0.0", "available": "2.0.0"},
        "SabNZBD": {"installed": "0.0.1", "available": "2.0.0"},
    }


def test_get_plugin_versions_uses_local_override_branch(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    plugin_dir = plugins_dir / "SolarEdge"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(
        '"""\n<plugin key="SolarEdge_ModbusTCP" name="SolarEdge ModbusTCP" version="2.0.5.5">\n</plugin>\n"""\n'
    )
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "domoticz-solaredge-modbustcp-plugin": [
            "addiejanssen",
            "domoticz-solaredge-modbustcp-plugin",
            "description",
            "meters",
            "",
        ],
    }
    plugin.installed_plugin_folders = {
        "domoticz-solaredge-modbustcp-plugin": "SolarEdge",
    }
    fetched_urls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return b'"""\n<plugin key="SolarEdge_ModbusTCP" name="SolarEdge ModbusTCP" version="2.0.4">\n</plugin>\n"""\n'

    def fake_urlopen(request, timeout=0):
        fetched_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(plugin_core_module.urllib.request, "urlopen", fake_urlopen)

    versions = plugin.get_plugin_versions(
        ["domoticz-solaredge-modbustcp-plugin"],
        {"domoticz-solaredge-modbustcp-plugin": "available"},
        str(plugins_dir),
    )

    assert fetched_urls == [
        "https://raw.githubusercontent.com/addiejanssen/domoticz-solaredge-modbustcp-plugin/meters/plugin.py",
    ]
    assert versions == {
        "domoticz-solaredge-modbustcp-plugin": {
            "installed": "2.0.5.5",
            "available": "2.0.4",
        },
    }


def test_list_plugins_response_includes_manager_and_update_status(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    write_plugin_py(plugins_dir / "OtherPlugin", key="OTHER", name="OtherPlugin")
    (plugins_dir / "OtherPlugin" / ".git").mkdir()
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
    assert response["local_plugins"] == []
    assert response["installed_match_details"]["00-PyPluginStore"]["source"] == "plugin.py externallink"
    assert response["installed_match_details"]["00-PyPluginStore"]["is_git"] is False
    assert response["installed_match_details"]["OtherPlugin"]["source"] == "exact folder key"
    assert response["installed_match_details"]["OtherPlugin"]["is_git"] is True
    assert response["platforms"] == {}


def test_list_plugins_response_includes_local_plugin_keys(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    write_plugin_py(plugins_dir / "LocalPlugin", key="PRIVATE", name="LocalPlugin")
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "LocalPlugin": ["git@github.com:owner/private-plugin.git", "", "description", "main", ""],
    }
    plugin.local_plugin_keys = ["LocalPlugin"]
    responses = []

    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "list_plugins"})

    assert responses[0]["local_plugins"] == ["LocalPlugin"]
    assert set(responses[0]["installed"]) == {"00-PyPluginStore", "LocalPlugin"}


def test_on_command_ignores_empty_api_payload(plugin_core_module, monkeypatch):
    plugin = plugin_core_module.BasePlugin()
    handled_payloads = []
    plugin_core_module.Devices = {1: FakeTextDevice("")}

    monkeypatch.setattr(plugin, "handleApiCommand", handled_payloads.append)

    plugin.onCommand(2, "On", 0, 0)

    assert handled_payloads == []
    assert plugin_core_module.Domoticz.calls["Error"] == []


def test_on_command_clears_stale_large_api_response_without_error(plugin_core_module, monkeypatch):
    plugin = plugin_core_module.BasePlugin()
    handled_payloads = []
    stale_response = json.dumps({
        "status": "success",
        "action": "list_plugins",
        "tx_id": "123",
        "data": {"Plugin": "x" * 2500},
    })
    plugin_core_module.Devices = {1: FakeTextDevice(stale_response)}

    monkeypatch.setattr(plugin, "handleApiCommand", handled_payloads.append)

    plugin.onCommand(2, "On", 0, 0)

    assert handled_payloads == []
    assert plugin_core_module.Devices[1].sValue == ""
    assert plugin_core_module.Domoticz.calls["Error"] == []


def test_on_command_clears_truncated_stale_api_response_without_error(plugin_core_module, monkeypatch):
    plugin = plugin_core_module.BasePlugin()
    handled_payloads = []
    stale_response = '{"status":"success","action":"list_plugins","tx_id":"123","data":"' + ("x" * 2500)
    plugin_core_module.Devices = {1: FakeTextDevice(stale_response)}

    monkeypatch.setattr(plugin, "handleApiCommand", handled_payloads.append)

    plugin.onCommand(2, "On", 0, 0)

    assert handled_payloads == []
    assert plugin_core_module.Devices[1].sValue == ""
    assert plugin_core_module.Domoticz.calls["Error"] == []


def test_on_command_rejects_large_api_request(plugin_core_module, monkeypatch):
    plugin = plugin_core_module.BasePlugin()
    handled_payloads = []
    large_request = json.dumps({
        "action": "install",
        "tx_id": "123",
        "plugin_key": "x" * 2500,
    })
    plugin_core_module.Devices = {1: FakeTextDevice(large_request)}

    monkeypatch.setattr(plugin, "handleApiCommand", handled_payloads.append)

    plugin.onCommand(2, "On", 0, 0)

    assert handled_payloads == []
    assert plugin_core_module.Devices[1].sValue == ""
    assert any("API Payload exceeds length limit." in args[0] for args, _ in plugin_core_module.Domoticz.calls["Error"])


def test_send_api_response_logs_error_payload_with_context(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()
    plugin_core_module.Devices = {1: FakeTextDevice("")}

    plugin.sendApiResponse({
        "status": "error",
        "action": "update",
        "plugin_key": "00-PP-MANAGER",
        "message": "preflight failed",
    })

    assert plugin_core_module.Devices[1].sValue == json.dumps({
        "status": "error",
        "action": "update",
        "plugin_key": "00-PP-MANAGER",
        "message": "preflight failed",
    })
    assert any(
        "API update for 00-PP-MANAGER failed: preflight failed" in args[0]
        for args, _ in plugin_core_module.Domoticz.calls["Error"]
    )


def test_send_api_response_logs_error_even_without_payload_device(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()
    plugin_core_module.Devices = {}

    plugin.sendApiResponse({
        "status": "error",
        "action": "restart_domoticz",
        "message": "restart not configured",
    })

    assert any(
        "API restart_domoticz failed: restart not configured" in args[0]
        for args, _ in plugin_core_module.Domoticz.calls["Error"]
    )


class FakeTextDevice:
    def __init__(self, s_value):
        self.sValue = s_value
        self.updates = []

    def Update(self, nValue, sValue):
        self.sValue = sValue
        self.updates.append((nValue, sValue))
