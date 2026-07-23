import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugin_core_helpers import configure_home
from test_release_migration import commit_files, git, initialize_repository
from test_release_runtime_strategy import (
    RecordingHttpClient,
    descriptor,
    make_strategy,
)


PLUGIN_KEY = "ExamplePlugin"
REPOSITORY_IDENTITY = "github.com/owner/example-plugin"


def configure_release_entry(plugin_core_module, plugin, *, mutable_paths=()):
    delivery = plugin_core_module.DeliveryPolicy.from_document(
        {
            "schema_version": 1,
            "preferred": "release_if_indexed",
            "git_supported": True,
            "release": {
                "provider": "github",
                "channel": "stable",
                "tag_pattern": r"^v[0-9]+\.[0-9]+\.[0-9]+$",
                "artifact": "source_zip",
                "source_path": ".",
                "mutable_paths": list(mutable_paths),
            },
        }
    )
    entry = plugin_core_module.RegistryEntry(
        PLUGIN_KEY,
        "owner",
        "example-plugin",
        "Example plugin",
        "main",
        delivery=delivery,
    )
    plugin.registry_entries[PLUGIN_KEY] = entry
    plugin.plugin_data[PLUGIN_KEY] = entry.to_legacy_list()
    return entry


def write_local_data(repository, relative_path, contents):
    path = Path(repository, *relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def test_release_switch_planner_shares_manual_actionability_with_the_ui(
    plugin_core_module,
    tmp_path,
    monkeypatch,
):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    repository, release_commit = initialize_repository(
        os.path.join(plugin.get_host().plugins_dir(), PLUGIN_KEY)
    )
    plugin.installed_plugin_folders[PLUGIN_KEY] = PLUGIN_KEY
    entry = configure_release_entry(plugin_core_module, plugin)
    release = descriptor(plugin_core_module, release_commit)
    context = {
        "installed_mode": "git",
        "release": release,
        "tombstone": None,
        "metadata_authorized": True,
        "metadata_reason": "",
        "installed_release": None,
        "channel_preference": "keep_git",
        "downgrade_confirmed": False,
        "release_was_activated": False,
        "git_status": "current",
        "index_sequence": 42,
    }

    available = plugin._plan_release_switch(entry, context)

    assert available.action_state == "available"
    assert available.preflight.allowed is True

    commit_files(
        repository,
        {"newer.py": "newer than the release\n"},
        "advance installed checkout",
    )
    confirmation = plugin._plan_release_switch(entry, context)

    assert confirmation.action_state == "confirmation_required"
    assert confirmation.preflight.requires_confirmation is True

    blocked_preflight = plugin_core_module.GitMigrationPreflightResult(
        status="migration_waiting_for_release",
        reason="ancestry_unavailable",
        message="Release ancestry could not be verified.",
    )
    monkeypatch.setattr(
        plugin.install_update_strategy.release_strategy,
        "preflight_migration",
        lambda requested_entry, requested_release, trigger: blocked_preflight,
    )

    blocked = plugin._plan_release_switch(entry, context)

    assert blocked.action_state == "blocked"
    assert blocked.message == "Release ancestry could not be verified."


def test_management_map_exposes_confirmable_release_switch_not_artifact_only(
    plugin_core_module,
    tmp_path,
    monkeypatch,
):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    repository, release_commit = initialize_repository(
        os.path.join(plugin.get_host().plugins_dir(), PLUGIN_KEY)
    )
    plugin.installed_plugin_folders[PLUGIN_KEY] = PLUGIN_KEY
    entry = configure_release_entry(plugin_core_module, plugin)
    release = descriptor(plugin_core_module, release_commit)
    commit_files(
        repository,
        {"newer.py": "newer than the release\n"},
        "advance installed checkout",
    )
    selection = SimpleNamespace(
        release_authorized=True,
        release_index=SimpleNamespace(
            plugins={PLUGIN_KEY: release},
            tombstones={},
        ),
        reason="",
        sequence=42,
    )
    monkeypatch.setattr(
        plugin,
        "getCurrentReleaseMetadataSelection",
        lambda: selection,
    )

    management = plugin.getPluginManagementMap(
        [PLUGIN_KEY],
        {PLUGIN_KEY: "current"},
        {},
        plugin.get_host().plugins_dir(),
    )[PLUGIN_KEY]

    assert management["status"] == "migration_confirmation_required"
    assert management["migration_action_state"] == "confirmation_required"
    assert management["release_available"] is True
    assert management["updateable"] is False
    assert management["migration_message"] == (
        "The installed Git checkout contains commits newer than the available "
        "Release."
    )


@pytest.mark.parametrize(
    ("relative_path", "contents", "mutable_paths"),
    [
        pytest.param(
            "config/settings.json",
            b'{"host": "local"}\n',
            ["config/settings.json"],
            id="reviewed-mutable-tracked-data",
        ),
        pytest.param(
            "runtime/state.json",
            b'{"counter": 7}\n',
            [],
            id="unknown-untracked-data",
        ),
    ],
)
def test_manual_migration_preserves_only_exactly_approved_local_inventory(
    plugin_core_module,
    tmp_path,
    relative_path,
    contents,
    mutable_paths,
):
    plugin, strategy, manager, http, dependencies = make_strategy(
        plugin_core_module, tmp_path
    )
    repository, installed_commit = initialize_repository(
        os.path.join(plugin.get_host().plugins_dir(), PLUGIN_KEY)
    )
    local_path = write_local_data(repository, relative_path, contents)
    plugin.installed_plugin_folders[PLUGIN_KEY] = PLUGIN_KEY
    entry = configure_release_entry(
        plugin_core_module,
        plugin,
        mutable_paths=mutable_paths,
    )
    release = descriptor(plugin_core_module, installed_commit)
    preflight = strategy.preflight_migration(entry, release, "manual")

    assert preflight.allowed is False
    assert preflight.requires_approval is True
    assert relative_path in preflight.approval_required_paths

    refused = strategy.migrate(
        entry,
        release,
        "manual",
        index_sequence=42,
    )

    assert refused[0] is False
    assert "exact approval" in refused[1].lower()
    assert manager.calls == []
    assert http.calls == []
    assert dependencies.calls == []

    result = strategy.migrate(
        entry,
        release,
        "manual",
        index_sequence=42,
        approved_inventory_sha256=preflight.inventory_sha256,
    )

    assert result == (
        True,
        "Release 2.0.0 staged successfully; restart required.",
    )
    assert [call[0] for call in manager.calls] == [
        "create",
        "verified",
        "activate",
    ]
    assert len(http.calls) == 1
    assert len(dependencies.calls) == 1
    staged_path = Path(
        manager.transaction.paths.staged_code,
        *relative_path.split("/"),
    )
    assert staged_path.read_bytes() == contents
    metadata = plugin.install_metadata_service.read(
        manager.transaction.paths.staged_code
    )
    assert metadata.migration_inventory_sha256 == preflight.inventory_sha256
    assert metadata.preserved_files == {
        relative_path: hashlib.sha256(contents).hexdigest(),
    }
    assert local_path.read_bytes() == contents
    assert (repository / ".git").is_dir()


@pytest.mark.parametrize(
    ("relationship", "expected_relationship"),
    [
        pytest.param("ahead", "installed_ahead", id="installed-ahead"),
        pytest.param("diverged", "diverged", id="diverged-history"),
    ],
)
def test_manual_ahead_or_diverged_migration_requires_explicit_downgrade_consent(
    plugin_core_module,
    tmp_path,
    relationship,
    expected_relationship,
):
    plugin, strategy, manager, http, dependencies = make_strategy(
        plugin_core_module, tmp_path
    )
    repository, base_commit = initialize_repository(
        os.path.join(plugin.get_host().plugins_dir(), PLUGIN_KEY)
    )
    if relationship == "ahead":
        release_commit = base_commit
        installed_commit = commit_files(
            repository,
            {"plugin.py": "print('installed ahead')\n"},
            "installed ahead",
        )
    else:
        release_commit = commit_files(
            repository,
            {"README.md": "Reviewed release\n"},
            "reviewed release",
        )
        git(repository, "checkout", "--quiet", "--detach", base_commit)
        installed_commit = commit_files(
            repository,
            {"plugin.py": "print('local branch')\n"},
            "local branch",
        )
    plugin.installed_plugin_folders[PLUGIN_KEY] = PLUGIN_KEY
    entry = configure_release_entry(plugin_core_module, plugin)
    release = descriptor(plugin_core_module, release_commit)
    preflight = strategy.preflight_migration(entry, release, "manual")

    assert preflight.relationship == expected_relationship
    assert preflight.installed_commit == installed_commit
    assert preflight.requires_confirmation is True

    refused = strategy.migrate(
        entry,
        release,
        "manual",
        index_sequence=42,
    )

    assert refused[0] is False
    assert manager.calls == []
    assert http.calls == []
    assert dependencies.calls == []

    result = strategy.migrate(
        entry,
        release,
        "manual",
        index_sequence=42,
        downgrade_confirmed=True,
    )

    assert result[0] is True
    assert manager.calls[0][1]["expected_current"] == {
        "management_mode": "git",
        "commit": installed_commit,
        "migration_snapshot": {
            "repository_identity": preflight.installed_repository_identity,
            "release_commit": preflight.release_commit,
            "relationship": preflight.relationship,
            "inventory_sha256": preflight.inventory_sha256,
            "tracked_changes": preflight.tracked_changes,
            "untracked_files": preflight.untracked_files,
            "mutable_paths": (
                preflight.preservation_inventory.mutable_paths
            ),
            "shallow": preflight.shallow,
        },
    }
    assert [call[0] for call in manager.calls] == [
        "create",
        "verified",
        "activate",
    ]


class InventoryMutatingHttpClient(RecordingHttpClient):
    def __init__(self, local_path, replacement):
        super().__init__()
        self.local_path = Path(local_path)
        self.replacement = replacement

    def download_to_path(self, url, destination, **arguments):
        super().download_to_path(url, destination, **arguments)
        self.local_path.write_bytes(self.replacement)


def test_inventory_change_after_preflight_aborts_before_activation(
    plugin_core_module, tmp_path
):
    plugin, strategy, manager, _http, dependencies = make_strategy(
        plugin_core_module, tmp_path
    )
    repository, installed_commit = initialize_repository(
        os.path.join(plugin.get_host().plugins_dir(), PLUGIN_KEY)
    )
    state_path = write_local_data(
        repository,
        "runtime/state.json",
        b'{"counter": 1}\n',
    )
    plugin.installed_plugin_folders[PLUGIN_KEY] = PLUGIN_KEY
    entry = configure_release_entry(plugin_core_module, plugin)
    release = descriptor(plugin_core_module, installed_commit)
    preflight = strategy.preflight_migration(entry, release, "manual")
    strategy.http_client = InventoryMutatingHttpClient(
        state_path,
        b'{"counter": 2}\n',
    )

    success, message = strategy.migrate(
        entry,
        release,
        "manual",
        index_sequence=42,
        approved_inventory_sha256=preflight.inventory_sha256,
    )

    assert success is False
    assert "changed after it was inventoried" in message.lower()
    assert [call[0] for call in manager.calls] == ["create", "abort"]
    assert all(call[0] != "activate" for call in manager.calls)
    assert dependencies.calls == []
    assert state_path.read_bytes() == b'{"counter": 2}\n'
    assert (repository / ".git").is_dir()


def call_use_release(plugin, monkeypatch, token=""):
    responses = []
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)
    payload = {"action": "use_release", "plugin_key": PLUGIN_KEY}
    if token:
        payload["confirmation_token"] = token
    plugin.handleApiCommand(payload)
    assert len(responses) == 1
    return responses[0]


def test_use_release_api_challenge_is_opaque_and_rejects_stale_inventory(
    plugin_core_module, tmp_path, monkeypatch
):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    repository, installed_commit = initialize_repository(
        os.path.join(plugin.get_host().plugins_dir(), PLUGIN_KEY)
    )
    state_path = write_local_data(
        repository,
        "runtime/state.json",
        b'{"counter": 1}\n',
    )
    plugin.installed_plugin_folders[PLUGIN_KEY] = PLUGIN_KEY
    entry = configure_release_entry(plugin_core_module, plugin)
    release = descriptor(plugin_core_module, installed_commit)
    plugin.release_metadata_selection = (
        plugin_core_module.ReleaseMetadataSelection(
            sequence=42,
            registry_bytes=b"{}",
            release_index_bytes=b"{}",
            release_index=None,
            release_authorized=True,
        )
    )
    context = {
        "installed_mode": "git",
        "release": release,
        "tombstone": None,
        "metadata_authorized": True,
        "metadata_reason": "",
        "installed_release": None,
        "channel_preference": None,
        "downgrade_confirmed": False,
        "release_was_activated": False,
        "git_status": "unknown",
        "index_sequence": 42,
    }
    monkeypatch.setattr(
        plugin,
        "_release_action_context",
        lambda requested_entry, trigger: dict(context),
    )
    release_strategy = plugin.install_update_strategy.release_strategy
    migration_calls = []
    monkeypatch.setattr(
        release_strategy,
        "migrate",
        lambda *arguments, **keywords: migration_calls.append(
            (arguments, keywords)
        ),
    )
    initial_preflight = release_strategy.preflight_migration(
        entry,
        release,
        "manual",
    )

    response = call_use_release(plugin, monkeypatch)

    assert response["status"] == "confirmation_required"
    assert response["challenge"]["kind"] == "git_migration"
    assert set(response["challenge"]) == {"kind", "token", "message"}
    token = response["challenge"]["token"]
    assert token
    assert token != initial_preflight.inventory_sha256
    assert "runtime/state.json" not in str(response)
    assert initial_preflight.inventory_sha256 not in str(response)
    assert migration_calls == []

    state_path.write_bytes(b'{"counter": 2}\n')
    stale_response = call_use_release(plugin, monkeypatch, token)

    assert stale_response["status"] == "error"
    assert "does not match" in stale_response["message"].lower()
    assert migration_calls == []
    assert plugin.channel_preference_service.get(REPOSITORY_IDENTITY) is None
    assert state_path.read_bytes() == b'{"counter": 2}\n'
    assert (repository / ".git").is_dir()


def test_manual_update_routes_git_migration_through_opaque_confirmation(
    plugin_core_module, tmp_path, monkeypatch
):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    repository, installed_commit = initialize_repository(
        os.path.join(plugin.get_host().plugins_dir(), PLUGIN_KEY)
    )
    plugin.installed_plugin_folders[PLUGIN_KEY] = PLUGIN_KEY
    entry = configure_release_entry(plugin_core_module, plugin)
    release = descriptor(plugin_core_module, installed_commit)
    plugin.release_metadata_selection = (
        plugin_core_module.ReleaseMetadataSelection(
            sequence=42,
            registry_bytes=b"{}",
            release_index_bytes=b"{}",
            release_index=None,
            release_authorized=True,
        )
    )
    context = {
        "installed_mode": "git",
        "release": release,
        "tombstone": None,
        "metadata_authorized": True,
        "metadata_reason": "",
        "installed_release": None,
        "channel_preference": None,
        "downgrade_confirmed": False,
        "release_was_activated": False,
        "git_status": "unknown",
        "index_sequence": 42,
    }
    monkeypatch.setattr(
        plugin,
        "_release_action_context",
        lambda requested_entry, trigger: dict(context),
    )
    release_strategy = plugin.install_update_strategy.release_strategy
    migration_calls = []

    def migrate(*arguments, **keywords):
        migration_calls.append((arguments, keywords))
        return True, "Release migration staged; restart required."

    monkeypatch.setattr(release_strategy, "migrate", migrate)
    monkeypatch.setattr(
        plugin.install_metadata_service,
        "read",
        lambda plugin_dir: SimpleNamespace(
            release_id=release.release_id,
            release_revision=release.revision,
            artifact_tree_sha256=release.artifact.tree_sha256,
        ),
    )
    responses = []
    monkeypatch.setattr(plugin, "sendApiResponse", responses.append)

    plugin.handleApiCommand(
        {"action": "update", "plugin_key": PLUGIN_KEY}
    )

    challenge = responses.pop()
    assert challenge["status"] == "confirmation_required"
    assert challenge["action"] == "update"
    assert challenge["challenge"]["kind"] == "git_migration"
    assert migration_calls == []

    plugin.handleApiCommand(
        {
            "action": "update",
            "plugin_key": PLUGIN_KEY,
            "confirmation_token": challenge["challenge"]["token"],
        }
    )

    completed = responses.pop()
    assert completed["status"] == "success"
    assert completed["action"] == "update"
    assert completed["restart_pending"] is True
    assert len(migration_calls) == 1
    assert migration_calls[0][0][:3] == (entry, release, "manual")
    assert len(
        migration_calls[0][1]["approved_inventory_sha256"]
    ) == 64
    assert migration_calls[0][1]["downgrade_confirmed"] is False
    assert plugin.channel_preference_service.get(
        REPOSITORY_IDENTITY
    ) == "release"
    assert (repository / ".git").is_dir()
