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
        "LocalPlugin": ["git@github.com:owner/private-plugin.git", "", "local description", "main"],
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
        "RemoteOnly": "2026-06-14T15:10:03Z",
    })

    plugin.fetch_registry()

    assert plugin.plugin_data["PublicPlugin"] == [
        "local-owner",
        "public-plugin",
        "local override",
        "main",
        "",
    ]
    assert plugin.plugin_data["LocalPlugin"] == [
        "git@github.com:owner/private-plugin.git",
        "",
        "local description",
        "main",
        "2026-06-16T18:42:59Z",
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


def test_build_git_clone_url_accepts_owner_repo_and_full_urls(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()

    assert plugin.build_git_clone_url("owner", "repo") == "https://github.com/owner/repo.git"
    assert plugin.build_git_clone_url("github.com/owner/repo", "") == "https://github.com/owner/repo.git"
    assert plugin.build_git_clone_url("https://github.com/owner/repo/tree/main", "") == "https://github.com/owner/repo.git"
    assert plugin.build_git_clone_url("git@github.com:owner/private-repo.git", "") == "git@github.com:owner/private-repo.git"
    assert plugin.build_git_clone_url("file:///srv/git/local-plugin", "") == "file:///srv/git/local-plugin"


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


def test_list_plugins_response_includes_manager_and_update_status(plugin_core_module, tmp_path, monkeypatch):
    plugins_dir, _ = configure_home(plugin_core_module, tmp_path)
    write_plugin_py(plugins_dir / "OtherPlugin", key="OTHER", name="OtherPlugin")
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
    assert response["installed_match_details"]["OtherPlugin"]["source"] == "exact folder key"
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
