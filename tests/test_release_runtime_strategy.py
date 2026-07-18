import hashlib
import os
from types import SimpleNamespace

from plugin_core_helpers import configure_home


COMMIT = "1" * 40
TREE = "a" * 64
ARCHIVE = "b" * 64


def descriptor(plugin_core_module):
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
            "commit": COMMIT,
            "artifact": {
                "kind": "source_zip",
                "provenance": "forge_source_archive",
                "migration_eligible": True,
                "url": "https://github.com/owner/example-plugin/archive/"
                + COMMIT
                + ".zip",
                "sha256": ARCHIVE,
                "size": 3,
                "tree_sha256": TREE,
                "root_prefix": "example-plugin-" + COMMIT,
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
    assert len(dependencies.calls) == 1
    metadata = plugin.install_metadata_service.read(
        manager.transaction.paths.staged_code
    )
    assert metadata.release_id == "github:owner/example-plugin:v2.0.0"
    assert metadata.index_sequence == 42
    assert metadata.artifact_tree_sha256 == TREE


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
