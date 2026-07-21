import json
import os

import pytest

from plugin_core_helpers import configure_home, write_plugin_py


def make_service(plugin_core_module, tmp_path):
    plugins_dir, manager_dir = configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    return (
        plugin.local_registry_service,
        plugins_dir,
        manager_dir / "registry_local.json",
    )


def package_by_id(document):
    return {
        package["package_id"]: package for package in document["packages"]
    }


def test_first_legacy_read_backs_up_exact_bytes_and_rewrites_v2(
    plugin_core_module, tmp_path
):
    service, plugins_dir, registry_file = make_service(
        plugin_core_module, tmp_path
    )
    write_plugin_py(
        plugins_dir / "PrivatePlugin",
        key="PRIVATE-RUNTIME",
        name="Private plugin",
    )
    write_plugin_py(
        plugins_dir / "DifferentFolder",
        key="UNRELATED-RUNTIME",
        name="Unrelated plugin",
    )
    legacy_bytes = (
        b'{\n  "PrivatePlugin": {'
        b'"owner": "gitlab.com/example-group", '
        b'"repository": "private-plugin", '
        b'"description": "Private plugin", '
        b'"branch": "main", "platform": "linux"},\n'
        b'  "UninstalledPlugin": ['
        b'"git@codeberg.org:example/uninstalled.git", "", '
        b'"Uninstalled", "stable"]\n}\n'
    )
    registry_file.write_bytes(legacy_bytes)

    document = service.read_document()

    assert document.writable is True
    assert document.migrated is True
    assert document.schema_version == 2
    assert (registry_file.parent / service.BACKUP_FILE_NAME).read_bytes() == (
        legacy_bytes
    )
    persisted = json.loads(registry_file.read_text(encoding="utf-8"))
    assert set(persisted) == {"schema_version", "packages"}
    assert persisted["schema_version"] == 2
    packages = package_by_id(persisted)
    assert packages["PrivatePlugin"] == {
        "package_id": "PrivatePlugin",
        "domoticz_key": "PRIVATE-RUNTIME",
        "description": "Private plugin",
        "repository": {
            "url": (
                "https://gitlab.com/example-group/private-plugin.git"
            ),
            "branch": "main",
        },
        "platforms": ["linux"],
    }
    assert packages["UninstalledPlugin"]["domoticz_key"] == ""
    assert packages["UninstalledPlugin"]["repository"] == {
        "url": "git@codeberg.org:example/uninstalled.git",
        "branch": "stable",
    }
    for package in persisted["packages"]:
        assert set(package) == {
            "package_id",
            "domoticz_key",
            "description",
            "repository",
            "platforms",
        }
        assert not ({"owner", "author", "repo", "plugin_key"} & set(package))
        assert set(package["repository"]) == {"url", "branch"}


def test_v2_read_is_idempotent_and_does_not_touch_the_backup(
    plugin_core_module, tmp_path, monkeypatch
):
    service, _, registry_file = make_service(plugin_core_module, tmp_path)
    legacy_bytes = b'{"Plugin":["owner","repo","Plugin","main"]}\n'
    registry_file.write_bytes(legacy_bytes)
    first = service.read_document()
    v2_bytes = registry_file.read_bytes()
    backup_file = registry_file.parent / service.BACKUP_FILE_NAME
    backup_bytes = backup_file.read_bytes()

    monkeypatch.setattr(
        service,
        "atomic_write_bytes",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("v2 read attempted a write")
        ),
    )
    monkeypatch.setattr(
        service,
        "preserve_legacy_backup",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("v2 read attempted a backup")
        ),
    )

    second = service.read_document()

    assert first.migrated is True
    assert second.migrated is False
    assert second.writable is True
    assert second.revision == first.revision
    assert registry_file.read_bytes() == v2_bytes
    assert backup_file.read_bytes() == backup_bytes == legacy_bytes


@pytest.mark.parametrize(
    "contents",
    [
        b"{broken",
        b'{"schema_version":2,"packages":[],"owner":"legacy"}',
        (
            b'{"schema_version":2,"packages":[{'
            b'"package_id":"Plugin","domoticz_key":"",'
            b'"description":"Plugin",'
            b'"repository":{"url":"https://example.org/team/plugin",'
            b'"branch":"main"},"platforms":[],"owner":"legacy"}]}'
        ),
    ],
)
def test_malformed_or_mixed_registry_stays_read_only_without_backup(
    plugin_core_module, tmp_path, contents
):
    service, _, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_bytes(contents)

    document = service.read_document()

    assert document.writable is False
    assert document.error_code == "invalid_local_registry"
    assert registry_file.read_bytes() == contents
    assert not (registry_file.parent / service.BACKUP_FILE_NAME).exists()


def test_legacy_casefold_collision_is_not_migrated(
    plugin_core_module, tmp_path
):
    service, _, registry_file = make_service(plugin_core_module, tmp_path)
    contents = (
        b'{"Plugin":["owner","one","One","main"],'
        b'"plugin":["owner","two","Two","main"]}\n'
    )
    registry_file.write_bytes(contents)

    document = service.read_document()

    assert document.writable is False
    assert "colliding package IDs" in document.message
    assert registry_file.read_bytes() == contents
    assert not (registry_file.parent / service.BACKUP_FILE_NAME).exists()


def test_api_rejects_casefold_collision_without_changing_v2(
    plugin_core_module, tmp_path
):
    service, _, registry_file = make_service(plugin_core_module, tmp_path)
    registry_file.write_bytes(
        b'{"Plugin":["owner","repo","Plugin","main"]}\n'
    )
    document = service.read_document()
    before = registry_file.read_bytes()

    with pytest.raises(plugin_core_module.LocalRegistryError) as error:
        service.upsert(
            document.revision,
            "",
            {
                "key": "plugin",
                "repository_source": "https://example.org/team/plugin",
                "description": "Duplicate",
                "branch": "main",
            },
        )

    assert error.value.code == "local_registry_entry_exists"
    assert registry_file.read_bytes() == before


def test_conflicting_backup_keeps_legacy_registry_read_only(
    plugin_core_module, tmp_path
):
    service, _, registry_file = make_service(plugin_core_module, tmp_path)
    contents = b'{"Plugin":["owner","repo","Plugin","main"]}\n'
    registry_file.write_bytes(contents)
    backup_file = registry_file.parent / service.BACKUP_FILE_NAME
    backup_file.write_bytes(b"different deployment state\n")

    document = service.read_document()

    assert document.writable is False
    assert "different bytes" in document.message
    assert registry_file.read_bytes() == contents
    assert backup_file.read_bytes() == b"different deployment state\n"


def test_failed_atomic_migration_preserves_legacy_and_can_retry(
    plugin_core_module, tmp_path, monkeypatch
):
    service, _, registry_file = make_service(plugin_core_module, tmp_path)
    contents = b'{"Plugin":["owner","repo","Plugin","main"]}\n'
    registry_file.write_bytes(contents)
    backup_file = registry_file.parent / service.BACKUP_FILE_NAME
    real_replace = os.replace

    def fail_registry_replace(source, destination):
        if os.path.abspath(destination) == os.path.abspath(registry_file):
            raise PermissionError("registry is read only")
        return real_replace(source, destination)

    monkeypatch.setattr(plugin_core_module.os, "replace", fail_registry_replace)

    failed = service.read_document()

    assert failed.writable is False
    assert registry_file.read_bytes() == contents
    assert backup_file.read_bytes() == contents
    assert list(registry_file.parent.glob(".registry_local.json.*.tmp")) == []

    monkeypatch.setattr(plugin_core_module.os, "replace", real_replace)
    retried = service.read_document()

    assert retried.writable is True
    assert retried.migrated is True
    assert json.loads(registry_file.read_text(encoding="utf-8"))[
        "schema_version"
    ] == 2
    assert backup_file.read_bytes() == contents


def test_new_api_entry_writes_only_v2_without_creating_legacy_backup(
    plugin_core_module, tmp_path
):
    service, plugins_dir, registry_file = make_service(
        plugin_core_module, tmp_path
    )
    write_plugin_py(
        plugins_dir / "LanPlugin",
        key="LAN/RUNTIME",
        name="LAN plugin",
    )

    document = service.upsert(
        service.read_document().revision,
        "",
        {
            "key": "LanPlugin",
            "repository_source": "file:///srv/git/lan-plugin.git",
            "description": "LAN plugin",
            "branch": "main",
        },
    )

    persisted = json.loads(registry_file.read_text(encoding="utf-8"))
    assert document.writable is True
    assert persisted == {
        "schema_version": 2,
        "packages": [
            {
                "package_id": "LanPlugin",
                "domoticz_key": "LAN/RUNTIME",
                "description": "LAN plugin",
                "repository": {
                    "url": "file:///srv/git/lan-plugin.git",
                    "branch": "main",
                },
                "platforms": [],
            }
        ],
    }
    assert not (registry_file.parent / service.BACKUP_FILE_NAME).exists()
