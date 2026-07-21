import hashlib
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from plugin_core_helpers import configure_home
from test_release_migration import initialize_repository


COMMIT = "1" * 40
TREE = "a" * 64
ARCHIVE = "b" * 64


def descriptor(
    plugin_core_module,
    commit=COMMIT,
    *,
    migration_mode="automatic",
    migration_evidence="commit_source_archive",
):
    return plugin_core_module.ReleaseDescriptor.from_document(
        {
            "revision": 2,
            "release_id": "github:owner/example-plugin:v2.0.0",
            "supersedes": ["github:owner/example-plugin:v1.0.0"],
            "provider": "github",
            "repository_identity": "github.com/owner/example-plugin",
            "version": "2.0.0",
            "tag": "v2.0.0",
            "released_at": "2026-07-18T07:00:00Z",
            "commit": commit,
            "artifact": {
                "kind": "source_zip",
                "provenance": "forge_source_archive",
                "migration": {
                    "mode": migration_mode,
                    "evidence": migration_evidence,
                },
                "url": (
                    "https://api.github.com/repos/owner/"
                    "example-plugin/zipball/"
                    + commit
                ),
                "sha256": ARCHIVE,
                "size": 3,
                "tree_sha256": TREE,
                "root_prefix": "example-plugin-" + commit,
                "source_path": ".",
            },
        }
    )


class RecordingTransactionManager:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.transaction = None

    def create_transaction(self, **arguments):
        self.calls.append(("create", arguments))
        operation_root = self.root / arguments["operation_id"]
        operation_root.mkdir(parents=True)
        paths = SimpleNamespace(
            staged_code=str(operation_root / "code"),
            staged_dependencies=str(operation_root / "dependencies"),
        )
        self.transaction = SimpleNamespace(paths=paths, phase="created")
        return self.transaction

    def mark_staged_verified(self, operation_id):
        self.calls.append(("verified", operation_id))

    def activate(self, operation_id):
        self.calls.append(("activate", operation_id))
        return SimpleNamespace(phase="restart_pending")

    def abort(self, operation_id, error):
        self.calls.append(("abort", operation_id, str(error)))


class RecordingHttpClient:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []

    def download_to_path(self, url, destination, **arguments):
        self.calls.append((url, destination, arguments))
        if self.failure is not None:
            raise self.failure
        with open(destination, "wb") as archive:
            archive.write(b"zip")


class StagingExtractor:
    def extract(self, archive_path, destination, *, expected_root_prefix):
        del archive_path
        source_root = os.path.join(destination, expected_root_prefix)
        os.makedirs(source_root)
        with open(os.path.join(source_root, "plugin.py"), "wb") as plugin_file:
            plugin_file.write(b"print('release')\n")


class StagingValidator:
    def __init__(self, plugin_core_module):
        self.plugin_core_module = plugin_core_module

    def validate(self, **arguments):
        source_root = os.path.join(
            arguments["extraction_dir"], arguments["root_prefix"]
        )
        contents = b"print('release')\n"
        return self.plugin_core_module.ReleaseArtifactValidation(
            source_root=source_root,
            plugin_key=arguments["plugin_key"],
            identity_source="test",
            tree_sha256=arguments["expected_tree_sha256"],
            artifact_files={
                "plugin.py": {
                    "sha256": hashlib.sha256(contents).hexdigest(),
                    "size": len(contents),
                }
            },
        )


class RecordingDependencies:
    def __init__(self):
        self.calls = []

    def stage(self, operation_id, **arguments):
        self.calls.append((operation_id, arguments))
        return SimpleNamespace(requires_confirmation=False)


def make_strategy(plugin_core_module, tmp_path, *, http_failure=None):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    plugin.plugin_data = {
        "ExamplePlugin": [
            "owner",
            "example-plugin",
            "Example plugin",
            "main",
        ]
    }
    plugin.release_metadata_selection = plugin_core_module.ReleaseMetadataSelection(
        sequence=42,
        registry_bytes=b"{}",
        release_index_bytes=b"{}",
        release_index=None,
        release_authorized=True,
    )
    manager = RecordingTransactionManager(tmp_path / "transactions")
    http = RecordingHttpClient(http_failure)
    dependencies = RecordingDependencies()
    strategy = plugin_core_module.ReleaseInstallUpdateStrategy(
        plugin,
        transaction_manager=manager,
        dependency_service=dependencies,
        http_client=http,
        extractor=StagingExtractor(),
        validator=StagingValidator(plugin_core_module),
    )
    return plugin, strategy, manager, http, dependencies


def test_release_install_uses_pinned_pipeline_and_writes_audit_metadata(
    plugin_core_module, tmp_path
):
    plugin, strategy, manager, http, dependencies = make_strategy(
        plugin_core_module, tmp_path
    )
    entry = plugin.get_registry_entry("ExamplePlugin")

    result = strategy.install(entry, descriptor(plugin_core_module), "automatic")

    assert result == (
        True,
        "Release 2.0.0 staged successfully; restart required.",
    )
    assert [call[0] for call in manager.calls] == [
        "create",
        "verified",
        "activate",
    ]
    assert http.calls[0][2]["expected_sha256"] == ARCHIVE
    assert http.calls[0][2]["expected_size"] == 3
    assert http.calls[0][2]["headers"] == {
        "User-Agent": "PyPluginStore-Release-Runtime",
    }
    assert http.calls[0][2]["allowed_origins"] == [
        "https://codeload.github.com",
    ]
    assert len(dependencies.calls) == 1
    metadata = plugin.install_metadata_service.read(
        manager.transaction.paths.staged_code
    )
    assert metadata.release_id == "github:owner/example-plugin:v2.0.0"
    assert metadata.index_sequence == 42
    assert metadata.artifact_tree_sha256 == TREE


@pytest.mark.parametrize(
    "artifact_url",
    [
        "https://api.github.com/repos/owner/example-plugin/zipball/"
        + ("2" * 40),
        "https://api.github.com/repos/owner/example-plugin/zipball/"
        + COMMIT
        + "?download=1",
        "https://github.example.test/api/v3/repos/owner/"
        "example-plugin/zipball/"
        + COMMIT,
    ],
)
def test_runtime_does_not_infer_codeload_for_noncanonical_github_urls(
    plugin_core_module, tmp_path, artifact_url
):
    plugin, strategy, _manager, _http, _dependencies = make_strategy(
        plugin_core_module, tmp_path
    )
    entry = plugin.get_registry_entry("ExamplePlugin")
    release = descriptor(plugin_core_module)
    release = replace(
        release,
        artifact=replace(release.artifact, url=artifact_url),
    )

    assert strategy._allowed_origins(entry, release) == []


def test_self_hosted_web_base_does_not_allow_runtime_redirects(
    plugin_core_module,
    tmp_path,
):
    _plugin, strategy, _manager, _http, _dependencies = make_strategy(
        plugin_core_module,
        tmp_path,
    )
    identity = "gitea.example.test/owner/example-plugin"
    policy = plugin_core_module.DeliveryPolicy.from_document(
        {
            "schema_version": 1,
            "preferred": "release_if_indexed",
            "git_supported": True,
            "release": {
                "provider": "gitea",
                "tag_pattern": r"^v[0-9]+\.[0-9]+\.[0-9]+$",
                "api_base": "https://gitea.example.test/api/v1",
                "web_base": "https://gitea.example.test",
                "release_page_size": 50,
            },
        },
        identity,
    )
    entry = plugin_core_module.RegistryEntry(
        "ExamplePlugin",
        "https://gitea.example.test/owner",
        "example-plugin",
        "Example plugin",
        "main",
        delivery=policy,
    )
    release = replace(
        descriptor(plugin_core_module),
        provider="gitea",
        repository_identity=identity,
        artifact=replace(
            descriptor(plugin_core_module).artifact,
            url="https://gitea.example.test/api/v1/archive.zip",
        ),
    )

    assert strategy._allowed_origins(entry, release) == []


def test_release_failure_aborts_without_falling_back_to_git(
    plugin_core_module, tmp_path
):
    plugin, strategy, manager, _http, dependencies = make_strategy(
        plugin_core_module,
        tmp_path,
        http_failure=ValueError("artifact digest mismatch"),
    )
    entry = plugin.get_registry_entry("ExamplePlugin")

    result = strategy.install(entry, descriptor(plugin_core_module), "manual")

    assert result == (False, "artifact digest mismatch")
    assert [call[0] for call in manager.calls] == ["create", "abort"]
    assert dependencies.calls == []


def test_clean_git_checkout_migrates_through_the_same_pinned_pipeline(
    plugin_core_module, tmp_path
):
    plugin, strategy, manager, http, dependencies = make_strategy(
        plugin_core_module, tmp_path
    )
    plugins_dir = plugin.get_host().plugins_dir()
    repository, installed_commit = initialize_repository(
        os.path.join(plugins_dir, "ExamplePlugin")
    )
    plugin.installed_plugin_folders["ExamplePlugin"] = "ExamplePlugin"
    entry = plugin.get_registry_entry("ExamplePlugin")
    release = descriptor(plugin_core_module, installed_commit)
    preflight = strategy.preflight_migration(
        entry,
        release,
        "automatic",
    )

    result = strategy.migrate(
        entry,
        release,
        "automatic",
        index_sequence=42,
    )

    assert result == (
        True,
        "Release 2.0.0 staged successfully; restart required.",
    )
    create = manager.calls[0]
    assert create[0] == "create"
    assert create[1]["operation"] == "release_migration"
    expected_current = create[1]["expected_current"]
    assert expected_current == {
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
    assert len(http.calls) == 1
    assert len(dependencies.calls) == 1
    metadata = plugin.install_metadata_service.read(
        manager.transaction.paths.staged_code
    )
    assert metadata.migration_source_commit == installed_commit
    assert len(metadata.migration_inventory_sha256) == 64
    assert metadata.preserved_files == {}
    assert repository.is_dir()


@pytest.mark.parametrize(
    ("migration_mode", "trigger", "allowed", "message"),
    [
        ("automatic", "automatic", True, ""),
        ("automatic", "manual", True, ""),
        ("manual", "manual", True, ""),
        ("manual", "automatic", False, "requires manual migration"),
        ("blocked", "manual", False, "not migration eligible"),
        ("blocked", "automatic", False, "not migration eligible"),
    ],
)
def test_runtime_preflight_enforces_migration_mode_and_trigger(
    plugin_core_module,
    tmp_path,
    monkeypatch,
    migration_mode,
    trigger,
    allowed,
    message,
):
    plugin, strategy, _manager, _http, _dependencies = make_strategy(
        plugin_core_module,
        tmp_path,
    )
    repository, installed_commit = initialize_repository(
        os.path.join(plugin.get_host().plugins_dir(), "ExamplePlugin")
    )
    plugin.installed_plugin_folders["ExamplePlugin"] = "ExamplePlugin"
    entry = plugin.get_registry_entry("ExamplePlugin")
    sentinel = object()
    evaluate_calls = []

    def evaluate(**arguments):
        evaluate_calls.append(arguments)
        return sentinel

    monkeypatch.setattr(
        strategy,
        "_preflight",
        lambda: SimpleNamespace(evaluate=evaluate),
    )
    release = descriptor(
        plugin_core_module,
        installed_commit,
        migration_mode=migration_mode,
        migration_evidence=(
            "commit_source_archive"
            if migration_mode == "automatic"
            else "unverified_asset"
        ),
    )

    if allowed:
        assert strategy.preflight_migration(entry, release, trigger) is sentinel
        assert len(evaluate_calls) == 1
        assert evaluate_calls[0]["plugin_dir"] == str(repository)
        assert evaluate_calls[0]["trigger"] == trigger
    else:
        with pytest.raises(ValueError, match=message):
            strategy.preflight_migration(entry, release, trigger)
        assert evaluate_calls == []


def test_dirty_git_checkout_is_blocked_before_download_or_transaction(
    plugin_core_module, tmp_path
):
    plugin, strategy, manager, http, dependencies = make_strategy(
        plugin_core_module, tmp_path
    )
    plugins_dir = plugin.get_host().plugins_dir()
    repository, installed_commit = initialize_repository(
        os.path.join(plugins_dir, "ExamplePlugin")
    )
    (repository / "README.md").write_text(
        "local change\n", encoding="utf-8"
    )
    plugin.installed_plugin_folders["ExamplePlugin"] = "ExamplePlugin"
    entry = plugin.get_registry_entry("ExamplePlugin")

    success, message = strategy.migrate(
        entry,
        descriptor(plugin_core_module, installed_commit),
        "automatic",
        index_sequence=42,
    )

    assert success is False
    assert "tracked" in message.lower() or "local" in message.lower()
    assert manager.calls == []
    assert http.calls == []
    assert dependencies.calls == []
    assert (repository / ".git").is_dir()
