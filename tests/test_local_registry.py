import json

import pytest

from plugin_core_helpers import configure_home, write_plugin_py


def make_service(plugin_core_module, tmp_path):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    return plugin, plugin.local_registry_service, manager_dir / "registry_local.json"


def test_missing_and_empty_local_registries_have_distinct_revisions(
    plugin_core_module, tmp_path
):
    _, service, registry_file = make_service(plugin_core_module, tmp_path)

    missing = service.read_document()
    registry_file.write_text("{}\n", encoding="utf-8")
    empty = service.read_document()

    assert missing.entries == {}
    assert missing.exists is False
    assert missing.writable is True
    assert empty.entries == {}
    assert empty.exists is True
    assert missing.revision != empty.revision


@pytest.mark.parametrize("contents", ["{broken", "[]"])
def test_malformed_local_registry_is_read_only(
    plugin_core_module, tmp_path, contents
):
    _, service, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_text(contents, encoding="utf-8")

    document = service.read_document()

    assert document.writable is False
    assert document.error_code == "invalid_local_registry"
    assert document.message


def test_create_writes_canonical_entry_and_preserves_legacy_entries(
    plugin_core_module, tmp_path
):
    _, service, registry_file = make_service(plugin_core_module, tmp_path)
    legacy_entry = ["owner", "legacy-repo", "Legacy", "main", "old timestamp"]
    registry_file.write_text(
        json.dumps({"Legacy": legacy_entry}), encoding="utf-8"
    )
    document = service.read_document()

    updated = service.upsert(
        document.revision,
        "",
        {
            "key": "PrivatePlugin",
            "repository_source": "git@example.org:team/private-plugin.git",
            "description": "Private plugin",
            "branch": "main",
        },
    )

    saved = json.loads(registry_file.read_text(encoding="utf-8"))
    assert saved["Legacy"] == legacy_entry
    assert saved["PrivatePlugin"] == {
        "owner": "git@example.org:team/private-plugin.git",
        "description": "Private plugin",
        "branch": "main",
    }
    assert "platform" not in saved["PrivatePlugin"]
    assert "platforms" not in saved["PrivatePlugin"]
    assert updated.revision == service.read_document().revision


def test_update_cannot_rename_local_registry_key(plugin_core_module, tmp_path):
    _, service, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_text(
        json.dumps({"Original": ["owner", "repo", "", "main"]}),
        encoding="utf-8",
    )
    document = service.read_document()

    with pytest.raises(plugin_core_module.LocalRegistryError) as error:
        service.upsert(
            document.revision,
            "Original",
            {
                "key": "Renamed",
                "repository_source": "https://example.org/team/repo",
                "description": "",
                "branch": "main",
            },
        )

    assert error.value.code == "invalid_local_registry_entry"
    assert error.value.field_errors == {"key": "Plugin key cannot be renamed."}


def test_stale_revision_does_not_write(plugin_core_module, tmp_path):
    _, service, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_text("{}\n", encoding="utf-8")

    with pytest.raises(plugin_core_module.LocalRegistryError) as error:
        service.upsert(
            "sha256:stale",
            "",
            {
                "key": "Plugin",
                "repository_source": "https://example.org/team/plugin",
                "description": "",
                "branch": "main",
            },
        )

    assert error.value.code == "registry_conflict"
    assert error.value.reload_required is True
    assert registry_file.read_text(encoding="utf-8") == "{}\n"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("key", "../Plugin"),
        ("repository_source", "https://user:secret@example.org/team/plugin"),
        ("repository_source", "not a repository"),
        ("description", "bad\x00description"),
        ("branch", "bad\nbranch"),
    ],
)
def test_invalid_local_registry_fields_do_not_write(
    plugin_core_module, tmp_path, field, value
):
    _, service, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_text("{}\n", encoding="utf-8")
    entry = {
        "key": "Plugin",
        "repository_source": "https://example.org/team/plugin",
        "description": "Description",
        "branch": "main",
    }
    entry[field] = value

    with pytest.raises(plugin_core_module.LocalRegistryError) as error:
        service.upsert(service.read_document().revision, "", entry)

    assert error.value.code == "invalid_local_registry_entry"
    assert field in error.value.field_errors
    assert registry_file.read_text(encoding="utf-8") == "{}\n"


def test_delete_last_entry_writes_empty_object(plugin_core_module, tmp_path):
    _, service, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_text(
        json.dumps({"Plugin": ["owner", "repo", "", "main"]}),
        encoding="utf-8",
    )

    service.delete(service.read_document().revision, "Plugin")

    assert json.loads(registry_file.read_text(encoding="utf-8")) == {}


def test_atomic_replace_failure_preserves_registry(
    plugin_core_module, tmp_path, monkeypatch
):
    _, service, registry_file = make_service(plugin_core_module, tmp_path)
    original = '{"Plugin": ["owner", "repo", "", "main"]}\n'
    registry_file.write_text(original, encoding="utf-8")

    def fail_replace(*args, **kwargs):
        raise PermissionError("read only")

    monkeypatch.setattr(plugin_core_module.os, "replace", fail_replace)

    with pytest.raises(plugin_core_module.LocalRegistryError) as error:
        service.delete(service.read_document().revision, "Plugin")

    assert error.value.code == "registry_write_failed"
    assert registry_file.read_text(encoding="utf-8") == original
    assert not (registry_file.parent / "registry_local.json.tmp").exists()


def test_get_local_registry_api_returns_derived_entry_metadata(
    plugin_core_module, tmp_path, monkeypatch
):
    plugin, _, registry_file = make_service(plugin_core_module, tmp_path)
    plugins_dir = registry_file.parents[1]
    write_plugin_py(
        plugins_dir / "PublicPlugin",
        key="PUBLIC",
        name="PublicPlugin",
    )
    registry_file.write_text(
        json.dumps(
            {
                "PublicPlugin": [
                    "local-owner",
                    "public-plugin",
                    "Local override",
                    "main",
                ]
            }
        ),
        encoding="utf-8",
    )
    plugin.public_registry_data = {
        "PublicPlugin": [
            "public-owner",
            "public-plugin",
            "Public description",
            "master",
        ]
    }
    plugin.apply_registry_sources(
        plugin.public_registry_data,
        plugin.local_registry_service.read_document().entries,
    )
    responses = []
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "get_local_registry"})

    response = responses[0]
    assert response["status"] == "success"
    assert response["action"] == "get_local_registry"
    assert response["path"] == str(registry_file)
    assert response["read_only"] is False
    assert response["entries"] == [
        {
            "key": "PublicPlugin",
            "repository_source": (
                "https://github.com/local-owner/public-plugin.git"
            ),
            "description": "Local override",
            "branch": "main",
            "overrides_public": True,
            "installed": True,
            "valid": True,
            "errors": {},
        }
    ]


def test_get_local_registry_api_keeps_malformed_file_read_only(
    plugin_core_module, tmp_path, monkeypatch
):
    plugin, _, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_text("{broken", encoding="utf-8")
    responses = []
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand({"action": "get_local_registry"})

    response = responses[0]
    assert response["status"] == "error"
    assert response["code"] == "invalid_local_registry"
    assert response["read_only"] is True
    assert response["path"] == str(registry_file)


def test_upsert_api_reapplies_cached_public_registry_without_network(
    plugin_core_module, tmp_path, monkeypatch
):
    plugin, service, registry_file = make_service(plugin_core_module, tmp_path)
    plugin.public_registry_data = {
        "PublicPlugin": [
            "public-owner",
            "public-plugin",
            "Public description",
            "master",
        ],
        "RemoteOnly": ["owner", "remote-only", "Remote", "main"],
    }
    plugin.apply_registry_sources(plugin.public_registry_data, {})
    monkeypatch.setattr(
        plugin,
        "fetch_remote_registry",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected network fetch")),
    )
    responses = []
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand(
        {
            "action": "upsert_local_registry_entry",
            "expected_revision": service.read_document().revision,
            "original_key": "",
            "entry": {
                "key": "PublicPlugin",
                "repository_source": "https://example.org/team/private-plugin",
                "description": "Local override",
                "branch": "main",
            },
        }
    )

    assert responses[0]["status"] == "success"
    assert responses[0]["plugin_key"] == "PublicPlugin"
    assert responses[0]["revision"].startswith("sha256:")
    assert plugin.local_plugin_keys == ["PublicPlugin"]
    assert plugin.plugin_data["PublicPlugin"][:4] == [
        "https://example.org/team/private-plugin",
        "",
        "Local override",
        "main",
    ]
    assert "RemoteOnly" in plugin.plugin_data
    assert json.loads(registry_file.read_text(encoding="utf-8"))[
        "PublicPlugin"
    ]["owner"] == "https://example.org/team/private-plugin"


def test_delete_api_restores_cached_public_override(
    plugin_core_module, tmp_path, monkeypatch
):
    plugin, service, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_text(
        json.dumps(
            {
                "PublicPlugin": {
                    "owner": "https://example.org/team/private-plugin",
                    "description": "Local override",
                    "branch": "main",
                }
            }
        ),
        encoding="utf-8",
    )
    plugin.public_registry_data = {
        "PublicPlugin": [
            "public-owner",
            "public-plugin",
            "Public description",
            "master",
        ]
    }
    plugin.apply_registry_sources(
        plugin.public_registry_data,
        service.read_document().entries,
    )
    responses = []
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand(
        {
            "action": "delete_local_registry_entry",
            "expected_revision": service.read_document().revision,
            "plugin_key": "PublicPlugin",
        }
    )

    assert responses[0]["status"] == "success"
    assert plugin.local_plugin_keys == []
    assert plugin.plugin_data["PublicPlugin"][:4] == [
        "public-owner",
        "public-plugin",
        "Public description",
        "master",
    ]


def test_local_registry_api_returns_structured_validation_errors(
    plugin_core_module, tmp_path, monkeypatch
):
    plugin, service, _ = make_service(plugin_core_module, tmp_path)
    responses = []
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand(
        {
            "action": "upsert_local_registry_entry",
            "expected_revision": service.read_document().revision,
            "original_key": "",
            "entry": {
                "key": "Plugin",
                "repository_source": "not a repository",
                "description": "",
                "branch": "main",
            },
        }
    )

    assert responses[0] == {
        "status": "error",
        "action": "upsert_local_registry_entry",
        "code": "invalid_local_registry_entry",
        "message": "Check the highlighted local registry fields.",
        "field_errors": {
            "repository_source": "Enter a valid repository source."
        },
        "reload_required": False,
        "read_only": False,
    }
