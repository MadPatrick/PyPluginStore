import json

import pytest

from plugin_core_helpers import configure_home


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
