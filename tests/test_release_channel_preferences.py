import json
import os

import pytest


def channel_document(channels=None, **overrides):
    document = {
        "schema_version": 1,
        "channels": dict(channels or {}),
    }
    document.update(overrides)
    return document


def make_service(plugin_core_module, monkeypatch, manager_dir):
    manager_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        plugin_core_module,
        "Parameters",
        {"HomeFolder": str(manager_dir) + os.sep},
        raising=False,
    )
    return plugin_core_module.ChannelPreferenceService(
        plugin_core_module.BasePlugin()
    )


def test_channel_preference_document_parses_explicit_choices(
    plugin_core_module,
):
    document = channel_document(
        {
            "github.com/owner/example-plugin": "keep_git",
            "gitlab.com/group/other-plugin": "release",
        }
    )

    preferences = plugin_core_module.ChannelPreferenceDocument.from_document(
        document
    )

    assert preferences.schema_version == 1
    assert preferences.channels == {
        "github.com/owner/example-plugin": "keep_git",
        "gitlab.com/group/other-plugin": "release",
    }
    assert preferences.to_document() == document


@pytest.mark.parametrize(
    "document",
    [
        pytest.param([], id="not-an-object"),
        pytest.param(
            channel_document(schema_version=2),
            id="unsupported-schema",
        ),
        pytest.param(
            {"schema_version": 1},
            id="missing-channels",
        ),
        pytest.param(
            {"schema_version": 1, "channels": []},
            id="channels-not-an-object",
        ),
        pytest.param(
            channel_document(
                {"GitHub.com/Owner/Example-Plugin": "keep_git"}
            ),
            id="identity-not-normalized",
        ),
        pytest.param(
            channel_document({"github.com/owner/../plugin": "keep_git"}),
            id="unsafe-identity",
        ),
        pytest.param(
            channel_document(
                {"github.com/owner/example-plugin": "automatic"}
            ),
            id="unsupported-choice",
        ),
        pytest.param(
            channel_document(
                {"github.com/owner/example-plugin": True}
            ),
            id="non-string-choice",
        ),
        pytest.param(
            channel_document(
                {
                    "github.com/owner/example-plugin": "keep_git",
                    "GitHub.com/Owner/Example-Plugin.git": "release",
                }
            ),
            id="normalized-identity-collision",
        ),
    ],
)
def test_channel_preference_document_rejects_invalid_schema_identity_or_value(
    plugin_core_module, document
):
    with pytest.raises(ValueError):
        plugin_core_module.ChannelPreferenceDocument.from_document(document)


@pytest.mark.parametrize(
    "identity,expected",
    [
        (
            "HTTPS://GitHub.COM/Owner/Example-Plugin.git/",
            "github.com/owner/example-plugin",
        ),
        (
            "https://gitlab.com/Group/SubGroup/Plugin.git",
            "gitlab.com/group/subgroup/plugin",
        ),
        (
            "forge.example/Team/Plugin",
            "forge.example/team/plugin",
        ),
    ],
)
def test_channel_service_normalizes_repository_identity_keys(
    plugin_core_module, monkeypatch, tmp_path, identity, expected
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    service.set(identity, "keep_git")

    saved = json.loads(
        (manager_dir / ".pypluginstore" / "channels.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved == channel_document({expected: "keep_git"})
    assert service.get(identity) == "keep_git"
    assert service.get(expected) == "keep_git"


@pytest.mark.parametrize(
    "identity",
    [
        "../owner/plugin",
        "http://github.com/owner/plugin",
        "https://user:secret@example.org/owner/plugin",
        "github.com/owner/plugin?channel=release",
        "file:///srv/plugins/example",
    ],
)
def test_channel_service_rejects_unsafe_repository_identities(
    plugin_core_module, monkeypatch, tmp_path, identity
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    with pytest.raises(ValueError):
        service.set(identity, "keep_git")

    assert not (manager_dir / ".pypluginstore" / "channels.json").exists()


@pytest.mark.parametrize("choice", ["", "git", "auto", "KEEP_GIT", None, True])
def test_channel_service_accepts_only_explicit_keep_git_or_release_choices(
    plugin_core_module, monkeypatch, tmp_path, choice
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    with pytest.raises(ValueError):
        service.set("github.com/owner/example-plugin", choice)


def test_channel_preferences_survive_plugin_checkout_replacement(
    plugin_core_module, monkeypatch, tmp_path
):
    plugins_dir = tmp_path / "plugins"
    manager_dir = plugins_dir / "00-PyPluginStore"
    plugin_dir = plugins_dir / "ExamplePlugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / ".git").mkdir()
    (plugin_dir / "plugin.py").write_text("# old checkout\n", encoding="utf-8")
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    service.set("github.com/owner/example-plugin", "keep_git")
    old_plugin_dir = plugins_dir / "ExamplePlugin.old"
    plugin_dir.rename(old_plugin_dir)
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text("# updated checkout\n", encoding="utf-8")

    reloaded = make_service(plugin_core_module, monkeypatch, manager_dir)
    assert reloaded.get("github.com/owner/example-plugin") == "keep_git"
    assert not (plugin_dir / ".pypluginstore").exists()
    assert not (old_plugin_dir / ".pypluginstore").exists()


def test_channel_service_writes_only_to_manager_owned_state(
    plugin_core_module, monkeypatch, tmp_path
):
    plugins_dir = tmp_path / "plugins"
    manager_dir = plugins_dir / "00-PyPluginStore"
    plugin_dir = plugins_dir / "ExamplePlugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / ".git").mkdir()
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    service.set("github.com/owner/example-plugin", "release")

    expected_file = manager_dir / ".pypluginstore" / "channels.json"
    assert expected_file.is_file()
    assert not (plugin_dir / ".pypluginstore").exists()
    assert not (plugin_dir / "channels.json").exists()
    assert not (plugins_dir / ".pypluginstore").exists()


def test_channel_service_preserves_other_choices_and_can_clear_one(
    plugin_core_module, monkeypatch, tmp_path
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    service.set("github.com/owner/one", "keep_git")
    service.set("gitlab.com/group/two", "release")
    service.clear("github.com/owner/one")

    assert service.get("github.com/owner/one") is None
    assert service.get("gitlab.com/group/two") == "release"
    assert service.read().channels == {
        "gitlab.com/group/two": "release",
    }


def test_channel_service_fsyncs_before_atomic_replace(
    plugin_core_module, monkeypatch, tmp_path
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    service = make_service(plugin_core_module, monkeypatch, manager_dir)
    events = []
    real_replace = plugin_core_module.os.replace

    def record_fsync(file_descriptor):
        events.append("fsync")

    def record_replace(source, destination):
        events.append("replace")
        return real_replace(source, destination)

    monkeypatch.setattr(plugin_core_module.os, "fsync", record_fsync)
    monkeypatch.setattr(plugin_core_module.os, "replace", record_replace)

    service.set("github.com/owner/example-plugin", "keep_git")

    assert "fsync" in events
    assert "replace" in events
    assert events.index("fsync") < events.index("replace")
    preferences_file = manager_dir / ".pypluginstore" / "channels.json"
    assert preferences_file.read_bytes().endswith(b"\n")
    assert not (manager_dir / ".pypluginstore" / "channels.json.tmp").exists()


def test_channel_service_failed_replace_preserves_previous_preferences(
    plugin_core_module, monkeypatch, tmp_path
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    service = make_service(plugin_core_module, monkeypatch, manager_dir)
    service.set("github.com/owner/example-plugin", "keep_git")
    preferences_file = manager_dir / ".pypluginstore" / "channels.json"
    previous_bytes = preferences_file.read_bytes()

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(plugin_core_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        service.set("github.com/owner/example-plugin", "release")

    assert preferences_file.read_bytes() == previous_bytes
    assert not (manager_dir / ".pypluginstore" / "channels.json.tmp").exists()


def test_channel_service_discards_uncommitted_temp_and_keeps_current_file(
    plugin_core_module, monkeypatch, tmp_path
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    state_dir = manager_dir / ".pypluginstore"
    state_dir.mkdir(parents=True)
    preferences_file = state_dir / "channels.json"
    temp_file = state_dir / "channels.json.tmp"
    preferences_file.write_text(
        json.dumps(
            channel_document(
                {"github.com/owner/example-plugin": "keep_git"}
            )
        ),
        encoding="utf-8",
    )
    temp_file.write_text(
        json.dumps(
            channel_document(
                {"github.com/owner/example-plugin": "release"}
            )
        ),
        encoding="utf-8",
    )
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    assert service.get("github.com/owner/example-plugin") == "keep_git"
    assert not temp_file.exists()


def test_channel_service_does_not_promote_orphan_temp_file(
    plugin_core_module, monkeypatch, tmp_path
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    state_dir = manager_dir / ".pypluginstore"
    state_dir.mkdir(parents=True)
    temp_file = state_dir / "channels.json.tmp"
    temp_file.write_text(
        json.dumps(
            channel_document(
                {"github.com/owner/example-plugin": "release"}
            )
        ),
        encoding="utf-8",
    )
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    assert service.read().channels == {}
    assert not (state_dir / "channels.json").exists()
    assert not temp_file.exists()


def test_channel_service_rejects_invalid_file_without_using_valid_temp(
    plugin_core_module, monkeypatch, tmp_path
):
    manager_dir = tmp_path / "plugins" / "00-PyPluginStore"
    state_dir = manager_dir / ".pypluginstore"
    state_dir.mkdir(parents=True)
    preferences_file = state_dir / "channels.json"
    temp_file = state_dir / "channels.json.tmp"
    preferences_file.write_text("{not-json", encoding="utf-8")
    temp_file.write_text(
        json.dumps(
            channel_document(
                {"github.com/owner/example-plugin": "release"}
            )
        ),
        encoding="utf-8",
    )
    service = make_service(plugin_core_module, monkeypatch, manager_dir)

    with pytest.raises(ValueError):
        service.read()

    assert preferences_file.read_text(encoding="utf-8") == "{not-json"
    assert not temp_file.exists()
