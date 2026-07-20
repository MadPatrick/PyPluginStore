import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from plugin_core_helpers import configure_home
from test_release_migration import GIT, head_commit, initialize_repository


OLD_COMMIT = "1" * 40
OLD_TREE = "2" * 64
NEW_COMMIT = "3" * 40
NEW_TREE = "4" * 64


class SimulatedCrash(BaseException):
    pass


def install_metadata_document(
    commit,
    tree_sha256,
    revision,
    release_id,
    artifact_files=None,
):
    if artifact_files is None:
        artifact_files = {
            "plugin.py": {"sha256": "4" * 64, "size": 4096},
        }
    return {
        "schema": 1,
        "plugin_key": "ExamplePlugin",
        "management_mode": "release",
        "repository_identity": "github.com/owner/example-plugin",
        "version": "1.0.0" if revision == 1 else "2.0.0",
        "tag": "v1.0.0" if revision == 1 else "v2.0.0",
        "release_id": release_id,
        "release_revision": revision,
        "released_at": "2026-07-18T07:00:00Z",
        "commit": commit,
        "artifact_sha256": "5" * 64,
        "artifact_tree_sha256": tree_sha256,
        "artifact_provenance": "forge_source_archive",
        "artifact_files": artifact_files,
        "preserved_files": {},
        "index_sequence": revision,
        "installed_at": "2026-07-18T08:00:00Z",
    }


def expected_current():
    return {
        "management_mode": "release",
        "commit": OLD_COMMIT,
        "artifact_tree_sha256": OLD_TREE,
    }


def migration_snapshot():
    return {
        "repository_identity": "github.com/owner/example-plugin",
        "release_commit": OLD_COMMIT,
        "relationship": "equal",
        "inventory_sha256": "6" * 64,
        "tracked_changes": [],
        "untracked_files": [],
        "mutable_paths": [],
        "shallow": False,
    }


def migration_expected_current():
    return {
        "management_mode": "git",
        "commit": OLD_COMMIT,
        "migration_snapshot": migration_snapshot(),
    }


def target_release():
    return {
        "management_mode": "release",
        "release_id": "github:owner/example-plugin:v2.0.0",
        "release_revision": 2,
        "commit": NEW_COMMIT,
        "artifact_tree_sha256": NEW_TREE,
    }


def dependency_snapshot():
    return {
        "installer": "none",
        "command": [],
        "compatibility_warnings": [],
        "compatibility_conflicts": [],
        "compatibility_confirmed": False,
    }


def new_manager(plugin_core_module, windows=False):
    plugin = plugin_core_module.BasePlugin()
    if windows:
        plugin.host = plugin_core_module.WindowsHostRuntime(
            plugin_core_module.Parameters
        )
    return plugin_core_module.ReleaseTransactionManager(plugin)


def make_manager(plugin_core_module, tmp_path, windows=False):
    plugins_dir, manager_dir = configure_home(plugin_core_module, tmp_path)
    return (
        new_manager(plugin_core_module, windows=windows),
        plugins_dir,
        manager_dir,
    )


def write_marker(directory, value, extra_name=""):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "marker.txt").write_text(value, encoding="utf-8")
    if extra_name:
        (directory / extra_name).write_text(value, encoding="utf-8")


def read_marker(directory):
    return (Path(directory) / "marker.txt").read_text(encoding="utf-8")


def artifact_inventory(directory):
    directory = Path(directory)
    inventory = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name == ".pypluginstore.json":
            continue
        contents = path.read_bytes()
        inventory[path.relative_to(directory).as_posix()] = {
            "sha256": hashlib.sha256(contents).hexdigest(),
            "size": len(contents),
        }
    return inventory


def install_current_release(plugins_dir, manager_dir):
    live_code = plugins_dir / "ExamplePlugin"
    live_dependencies = manager_dir / ".shared_deps"
    write_marker(live_code, "old-code", "old-only.py")
    write_marker(live_dependencies, "old-dependencies", "old-only.py")
    (live_code / "plugin.py").write_text(
        "# old plugin\n",
        encoding="utf-8",
    )
    (live_code / ".pypluginstore.json").write_text(
        json.dumps(
            install_metadata_document(
                OLD_COMMIT,
                OLD_TREE,
                1,
                "github:owner/example-plugin:v1.0.0",
                artifact_inventory(live_code),
            )
        ),
        encoding="utf-8",
    )
    return live_code, live_dependencies


def prepare_transaction(
    manager,
    plugins_dir,
    manager_dir,
    operation_id="operation-001",
    *,
    stage_dependencies=True,
):
    live_code, live_dependencies = install_current_release(
        plugins_dir,
        manager_dir,
    )

    transaction = manager.create_transaction(
        plugin_key="ExamplePlugin",
        operation_id=operation_id,
        operation="release_update",
        expected_current=expected_current(),
        target=target_release(),
    )
    write_marker(transaction.paths.staged_code, "new-code", "new-only.py")
    (Path(transaction.paths.staged_code) / "plugin.py").write_text(
        "# new plugin\n",
        encoding="utf-8",
    )
    shutil.copytree(
        live_dependencies,
        transaction.paths.staged_dependencies,
        dirs_exist_ok=True,
    )
    (
        Path(transaction.paths.staged_code) / ".pypluginstore.json"
    ).write_text(
        json.dumps(
            install_metadata_document(
                NEW_COMMIT,
                NEW_TREE,
                2,
                "github:owner/example-plugin:v2.0.0",
                artifact_inventory(transaction.paths.staged_code),
            )
        ),
        encoding="utf-8",
    )
    verified = manager.mark_staged_verified(operation_id)
    if not stage_dependencies:
        return verified
    return manager.mark_dependencies_staged(
        operation_id,
        dependency_snapshot(),
    )


def migration_expected_from_preflight(preflight):
    return {
        "management_mode": "git",
        "commit": preflight.installed_commit,
        "migration_snapshot": {
            "repository_identity": preflight.installed_repository_identity,
            "release_commit": preflight.release_commit,
            "relationship": preflight.relationship,
            "inventory_sha256": preflight.inventory_sha256,
            "tracked_changes": list(preflight.tracked_changes),
            "untracked_files": list(preflight.untracked_files),
            "mutable_paths": list(
                preflight.preservation_inventory.mutable_paths
            ),
            "shallow": preflight.shallow,
        },
    }


def prepare_migration_transaction(
    plugin_core_module,
    manager,
    plugins_dir,
    manager_dir,
    operation_id="operation-001",
):
    live_code, installed_commit = initialize_repository(
        plugins_dir / "ExamplePlugin"
    )
    live_dependencies = manager_dir / ".shared_deps"
    write_marker(live_dependencies, "old-dependencies", "old-only.py")
    preflight = plugin_core_module.GitMigrationPreflight(
        manager.plugin
    ).evaluate(
        plugin_key="ExamplePlugin",
        plugin_dir=str(live_code),
        repository_identity="github.com/owner/example-plugin",
        release_commit=installed_commit,
        trigger="manual",
        mutable_paths=[],
    )
    assert preflight.allowed is True
    assert preflight.preservation_inventory is not None
    target = target_release()
    target["commit"] = installed_commit
    transaction = manager.create_transaction(
        plugin_key="ExamplePlugin",
        operation_id=operation_id,
        operation="release_migration",
        expected_current=migration_expected_from_preflight(preflight),
        target=target,
    )
    write_marker(transaction.paths.staged_code, "new-code", "new-only.py")
    staged_code = Path(transaction.paths.staged_code)
    (staged_code / "plugin.py").write_text(
        "# release plugin\n",
        encoding="utf-8",
    )
    (staged_code / ".pypluginstore.json").write_text(
        json.dumps(
            install_metadata_document(
                installed_commit,
                NEW_TREE,
                2,
                "github:owner/example-plugin:v2.0.0",
                artifact_inventory(staged_code),
            )
        ),
        encoding="utf-8",
    )
    shutil.copytree(
        live_dependencies,
        transaction.paths.staged_dependencies,
    )
    manager.mark_staged_verified(operation_id)
    transaction = manager.mark_dependencies_staged(
        operation_id,
        dependency_snapshot(),
    )
    return transaction, live_code, installed_commit, preflight


def assert_old_live(transaction):
    assert read_marker(transaction.paths.live_code) == "old-code"
    assert read_marker(transaction.paths.live_dependencies) == "old-dependencies"
    assert (Path(transaction.paths.live_code) / "old-only.py").is_file()
    assert not (Path(transaction.paths.live_code) / "new-only.py").exists()
    assert (Path(transaction.paths.live_dependencies) / "old-only.py").is_file()
    assert not (
        Path(transaction.paths.live_dependencies) / "new-only.py"
    ).exists()


def assert_new_live(transaction):
    assert read_marker(transaction.paths.live_code) == "new-code"
    assert read_marker(transaction.paths.live_dependencies) == "old-dependencies"
    assert (Path(transaction.paths.live_code) / "new-only.py").is_file()
    assert not (Path(transaction.paths.live_code) / "old-only.py").exists()
    assert (Path(transaction.paths.live_dependencies) / "old-only.py").is_file()
    assert not (Path(transaction.paths.live_dependencies) / "new-only.py").exists()


def test_release_transaction_paths_are_manager_owned_and_same_filesystem(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    state_root = manager_dir / ".pypluginstore"

    assert Path(transaction.paths.journal) == (
        state_root / "transactions" / "operation-001.json"
    )
    assert Path(transaction.paths.staged_code) == (
        state_root / "staging" / "ExamplePlugin" / "operation-001" / "code"
    )
    assert Path(transaction.paths.staged_dependencies) == (
        state_root
        / "staging"
        / "ExamplePlugin"
        / "operation-001"
        / "dependencies"
    )
    assert Path(transaction.paths.backup_code) == (
        state_root / "backups" / "ExamplePlugin" / "operation-001" / "code"
    )
    assert Path(transaction.paths.backup_dependencies) == (
        state_root
        / "backups"
        / "ExamplePlugin"
        / "operation-001"
        / "dependencies"
    )
    assert Path(transaction.paths.live_code) == plugins_dir / "ExamplePlugin"
    assert Path(transaction.paths.live_dependencies) == manager_dir / ".shared_deps"

    manager_device = os.stat(manager_dir).st_dev
    assert os.stat(transaction.paths.live_code).st_dev == manager_device
    assert os.stat(transaction.paths.live_dependencies).st_dev == manager_device
    assert os.stat(Path(transaction.paths.staged_code).parent).st_dev == (
        manager_device
    )
    assert os.stat(Path(transaction.paths.backup_code).parent).st_dev == (
        manager_device
    )


@pytest.mark.parametrize(
    "plugin_key,operation_id",
    [
        ("../Plugin", "operation-001"),
        (".hidden", "operation-001"),
        ("ExamplePlugin", "../operation"),
        ("ExamplePlugin", "/absolute"),
        ("ExamplePlugin", ""),
    ],
)
def test_release_transaction_rejects_unsafe_path_identifiers(
    plugin_core_module, tmp_path, plugin_key, operation_id
):
    manager, _, manager_dir = make_manager(plugin_core_module, tmp_path)

    with pytest.raises(ValueError):
        manager.create_transaction(
            plugin_key=plugin_key,
            operation_id=operation_id,
            operation="release_update",
            expected_current=expected_current(),
            target=target_release(),
        )

    state_root = manager_dir / ".pypluginstore"
    assert not (tmp_path / "operation").exists()
    if state_root.exists():
        assert not any(path.name == "operation" for path in state_root.rglob("*"))


def test_release_transaction_never_reuses_an_orphan_operation_directory(
    plugin_core_module, tmp_path
):
    manager, _, manager_dir = make_manager(plugin_core_module, tmp_path)
    with manager.operation_lock():
        pass
    state_root = manager_dir / ".pypluginstore"
    orphan = (
        state_root / "staging" / "ExamplePlugin" / "operation-001"
    )
    orphan.mkdir(parents=True)
    (orphan / "untrusted.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ValueError, match="operation path already exists"):
        manager.create_transaction(
            plugin_key="ExamplePlugin",
            operation_id="operation-001",
            operation="release_update",
            expected_current=expected_current(),
            target=target_release(),
        )

    assert not (
        state_root / "transactions" / "operation-001.json"
    ).exists()


def test_release_transaction_journal_contains_complete_recovery_descriptor(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)

    document = json.loads(
        Path(transaction.paths.journal).read_text(encoding="utf-8")
    )

    assert document["schema_version"] == 1
    assert document["operation_id"] == "operation-001"
    assert document["plugin_key"] == "ExamplePlugin"
    assert document["operation"] == "release_update"
    assert document["phase"] == "dependencies_staged"
    assert document["expected_current"] == expected_current()
    assert document["target"] == target_release()
    assert document["dependency_snapshot"] == dependency_snapshot()
    assert document["dependency_state"]["expected"]["present"] is True
    assert document["dependency_state"]["target"]["present"] is True
    assert document["staged_snapshot"]["artifact_files"] == (
        install_metadata_document(
            NEW_COMMIT,
            NEW_TREE,
            2,
            "github:owner/example-plugin:v2.0.0",
            artifact_inventory(transaction.paths.staged_code),
        )["artifact_files"]
    )
    assert document["rollback_from"] == ""
    assert document["paths"] == transaction.paths.to_document()
    assert document["created_at"].endswith("Z")
    assert document["updated_at"].endswith("Z")


def test_release_transaction_refuses_activation_before_dependencies_are_staged(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(
        manager,
        plugins_dir,
        manager_dir,
        stage_dependencies=False,
    )

    with pytest.raises(RuntimeError, match="dependencies_staged"):
        manager.activate(transaction.operation_id)

    unchanged = manager.load_transaction(transaction.operation_id)
    assert unchanged.phase == "staged_verified"
    assert unchanged.dependency_snapshot is None
    assert_old_live(unchanged)


def test_startup_recovery_before_activation_preserves_current_install(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    install_current_release(plugins_dir, manager_dir)
    transaction = manager.create_transaction(
        plugin_key="ExamplePlugin",
        operation_id="operation-001",
        operation="release_update",
        expected_current=expected_current(),
        target=target_release(),
    )

    new_manager(plugin_core_module).recover_pending()

    recovered = manager.load_transaction(transaction.operation_id)
    assert recovered.phase == "rolled_back"
    assert_old_live(recovered)


def test_activation_rejects_staged_metadata_outside_pinned_target(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    metadata_path = Path(transaction.paths.staged_code) / ".pypluginstore.json"
    document = json.loads(metadata_path.read_text(encoding="utf-8"))
    document["release_id"] = "github:owner/example-plugin:v2.0.0-repacked"
    metadata_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="pinned target"):
        manager.activate(transaction.operation_id)

    rejected = manager.load_transaction(transaction.operation_id)
    assert rejected.phase == "rolled_back"
    assert_old_live(rejected)


def test_activation_rejects_staged_code_changed_after_verification(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    (Path(transaction.paths.staged_code) / "plugin.py").write_text(
        "# changed after verification\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pinned target"):
        manager.activate(transaction.operation_id)

    rejected = manager.load_transaction(transaction.operation_id)
    assert rejected.phase == "rolled_back"
    assert_old_live(rejected)


def test_activation_rejects_code_and_self_reported_inventory_changed_together(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    staged_code = Path(transaction.paths.staged_code)
    (staged_code / "plugin.py").write_text(
        "# changed with matching self-reported hash\n",
        encoding="utf-8",
    )
    metadata_path = staged_code / ".pypluginstore.json"
    document = json.loads(metadata_path.read_text(encoding="utf-8"))
    document["artifact_files"] = artifact_inventory(staged_code)
    metadata_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="pinned target"):
        manager.activate(transaction.operation_id)

    rejected = manager.load_transaction(transaction.operation_id)
    assert rejected.phase == "rolled_back"
    assert_old_live(rejected)


def test_activation_rejects_dependencies_changed_after_staging(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    (Path(transaction.paths.staged_dependencies) / "marker.txt").write_text(
        "changed dependencies",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pinned snapshot"):
        manager.activate(transaction.operation_id)

    rejected = manager.load_transaction(transaction.operation_id)
    assert rejected.phase == "rolled_back"
    assert_old_live(rejected)


def test_activation_refuses_changed_live_dependencies(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    (Path(transaction.paths.live_dependencies) / "marker.txt").write_text(
        "newer live dependency state",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="expected_current"):
        manager.activate(transaction.operation_id)

    stale = manager.load_transaction(transaction.operation_id)
    assert stale.phase == "stale_target"
    assert read_marker(stale.paths.live_code) == "old-code"
    assert read_marker(stale.paths.live_dependencies) == (
        "newer live dependency state"
    )


def test_activation_never_trusts_a_preseeded_backup_leaf(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    write_marker(transaction.paths.backup_code, "untrusted-backup")

    with pytest.raises(ValueError, match="backup destination"):
        manager.activate(transaction.operation_id)

    unchanged = manager.load_transaction(transaction.operation_id)
    assert unchanged.phase == "dependencies_staged"
    assert_old_live(unchanged)


@pytest.mark.parametrize(
    ("operation", "operation_expected_current"),
    [
        pytest.param(
            "release_install",
            {"management_mode": "absent"},
            id="new-install-binds-absence",
        ),
        pytest.param(
            "release_update",
            expected_current(),
            id="release-update-binds-installed-release",
        ),
        pytest.param(
            "release_migration",
            migration_expected_current(),
            id="git-migration-binds-content-snapshot",
        ),
    ],
)
def test_release_transaction_records_operation_specific_expected_current_state(
    plugin_core_module,
    tmp_path,
    operation,
    operation_expected_current,
):
    manager, _, _ = make_manager(plugin_core_module, tmp_path)

    transaction = manager.create_transaction(
        plugin_key="ExamplePlugin",
        operation_id="operation-001",
        operation=operation,
        expected_current=operation_expected_current,
        target=target_release(),
    )
    document = json.loads(
        Path(transaction.paths.journal).read_text(encoding="utf-8")
    )

    assert transaction.operation == operation
    assert transaction.expected_current == operation_expected_current
    assert document["operation"] == operation
    assert document["expected_current"] == operation_expected_current


@pytest.mark.skipif(GIT is None, reason="Git is required")
@pytest.mark.parametrize(
    "change_kind",
    [
        pytest.param("tracked", id="same-head-tracked-change"),
        pytest.param("untracked", id="same-head-untracked-file"),
    ],
)
def test_git_migration_activation_rejects_same_head_content_changes(
    plugin_core_module,
    tmp_path,
    change_kind,
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction, live_code, installed_commit, _preflight = (
        prepare_migration_transaction(
            plugin_core_module,
            manager,
            plugins_dir,
            manager_dir,
        )
    )
    if change_kind == "tracked":
        (live_code / "README.md").write_text(
            "changed after approval\n",
            encoding="utf-8",
        )
    else:
        runtime_file = live_code / "runtime" / "state.json"
        runtime_file.parent.mkdir()
        runtime_file.write_text('{"counter": 1}\n', encoding="utf-8")

    assert head_commit(live_code) == installed_commit

    with pytest.raises(RuntimeError, match="expected_current"):
        manager.activate(transaction.operation_id)

    stale = manager.load_transaction(transaction.operation_id)
    assert stale.phase == "stale_target"
    assert Path(stale.paths.live_code) == live_code
    assert (live_code / ".git").is_dir()
    assert head_commit(live_code) == installed_commit
    assert not Path(stale.paths.backup_code).exists()


@pytest.mark.skipif(GIT is None, reason="Git is required")
def test_migration_backup_revalidation_restores_checkout_changed_during_rename(
    plugin_core_module,
    tmp_path,
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction, live_code, installed_commit, _preflight = (
        prepare_migration_transaction(
            plugin_core_module,
            manager,
            plugins_dir,
            manager_dir,
        )
    )
    changed_contents = "changed inside rename window\n"

    def change_moved_checkout(phase, current_transaction):
        if phase == "code_backed_up":
            Path(
                current_transaction.paths.backup_code,
                "README.md",
            ).write_text(changed_contents, encoding="utf-8")

    manager.fault_injector = change_moved_checkout

    with pytest.raises(
        RuntimeError,
        match="changed after migration approval",
    ):
        manager.activate(transaction.operation_id)

    stale = manager.load_transaction(transaction.operation_id)
    assert stale.phase == "stale_target"
    assert Path(stale.paths.live_code) == live_code
    assert live_code.is_dir()
    assert (live_code / ".git").is_dir()
    assert (live_code / "README.md").read_text(encoding="utf-8") == (
        changed_contents
    )
    assert head_commit(live_code) == installed_commit
    assert not Path(stale.paths.backup_code).exists()
    assert read_marker(stale.paths.live_dependencies) == "old-dependencies"
    assert not Path(stale.paths.backup_dependencies).exists()


@pytest.mark.parametrize(
    ("field", "invalid_value", "error"),
    [
        ("phase", "invented_phase", "phase is unsupported"),
        ("schema_version", True, "schema is unsupported"),
        ("target.release_revision", 0, "release_revision"),
    ],
)
def test_release_transaction_revalidates_loaded_journal_descriptors(
    plugin_core_module,
    tmp_path,
    field,
    invalid_value,
    error,
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    journal_path = Path(transaction.paths.journal)
    document = json.loads(journal_path.read_text(encoding="utf-8"))
    if field == "target.release_revision":
        document["target"]["release_revision"] = invalid_value
    else:
        document[field] = invalid_value
    journal_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        manager.load_transaction(transaction.operation_id)


def test_release_transaction_fsyncs_journal_before_each_directory_rename(
    plugin_core_module, tmp_path, monkeypatch
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    events = []
    rename_phases = []
    real_replace = plugin_core_module.os.replace

    def record_fsync(file_descriptor):
        events.append("fsync")

    def record_replace(source, destination):
        source_path = Path(source)
        if source_path.is_dir():
            journal = json.loads(
                Path(transaction.paths.journal).read_text(encoding="utf-8")
            )
            events.append("directory_rename")
            rename_phases.append(journal["phase"])
        return real_replace(source, destination)

    monkeypatch.setattr(plugin_core_module.os, "fsync", record_fsync)
    monkeypatch.setattr(plugin_core_module.os, "replace", record_replace)

    manager.activate(transaction.operation_id)

    assert rename_phases == [
        "code_backup_pending",
        "dependencies_backup_pending",
        "dependencies_activation_pending",
        "code_activation_pending",
    ]
    previous_rename = -1
    for index, event in enumerate(events):
        if event != "directory_rename":
            continue
        assert "fsync" in events[previous_rename + 1 : index]
        previous_rename = index


def test_release_transaction_activates_code_and_dependency_snapshots(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)

    activated = manager.activate(transaction.operation_id)

    assert activated.phase == "restart_pending"
    assert_new_live(activated)
    assert read_marker(activated.paths.backup_code) == "old-code"
    assert read_marker(activated.paths.backup_dependencies) == "old-dependencies"
    assert (Path(activated.paths.backup_code) / "old-only.py").is_file()
    assert (
        Path(activated.paths.backup_dependencies) / "old-only.py"
    ).is_file()
    assert not Path(activated.paths.staged_code).exists()
    assert not Path(activated.paths.staged_dependencies).exists()


@pytest.mark.parametrize("failure_rename", [1, 2, 3, 4])
def test_release_transaction_immediately_rolls_back_every_rename_failure(
    plugin_core_module, tmp_path, monkeypatch, failure_rename
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    real_replace = plugin_core_module.os.replace
    directory_rename_count = 0

    def fail_one_directory_rename(source, destination):
        nonlocal directory_rename_count
        if Path(source).is_dir():
            directory_rename_count += 1
            if directory_rename_count == failure_rename:
                raise OSError("injected rename failure {}".format(failure_rename))
        return real_replace(source, destination)

    monkeypatch.setattr(
        plugin_core_module.os, "replace", fail_one_directory_rename
    )

    with pytest.raises(OSError, match="injected rename failure"):
        manager.activate(transaction.operation_id)

    rolled_back = manager.load_transaction(transaction.operation_id)
    assert rolled_back.phase == "rolled_back"
    assert "injected rename failure" in rolled_back.error
    assert_old_live(rolled_back)


@pytest.mark.parametrize(
    "crash_phase,expected_recovery_phase,expected_marker",
    [
        ("code_backed_up", "rolled_back", "old-code"),
        ("dependencies_backed_up", "rolled_back", "old-code"),
        ("dependencies_activated", "rolled_back", "old-code"),
        ("release_activated", "restart_pending", "new-code"),
    ],
)
def test_release_transaction_startup_recovery_is_idempotent_at_each_boundary(
    plugin_core_module,
    tmp_path,
    crash_phase,
    expected_recovery_phase,
    expected_marker,
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)

    def crash_after_phase(phase, current_transaction):
        if phase == crash_phase:
            raise SimulatedCrash(phase)

    manager.fault_injector = crash_after_phase

    with pytest.raises(SimulatedCrash):
        manager.activate(transaction.operation_id)

    recovered_manager = new_manager(plugin_core_module)
    recovered_manager.recover_pending()
    recovered = recovered_manager.load_transaction(transaction.operation_id)
    first_journal = Path(recovered.paths.journal).read_bytes()
    first_code = read_marker(recovered.paths.live_code)
    first_dependencies = read_marker(recovered.paths.live_dependencies)

    assert recovered.phase == expected_recovery_phase
    assert first_code == expected_marker
    assert first_dependencies == "old-dependencies"

    recovered_manager.recover_pending()

    assert Path(recovered.paths.journal).read_bytes() == first_journal
    assert read_marker(recovered.paths.live_code) == first_code
    assert read_marker(recovered.paths.live_dependencies) == first_dependencies


def test_recovery_never_claims_rollback_when_required_backup_is_missing(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)

    def crash_after_code_backup(phase, _transaction):
        if phase == "code_backed_up":
            raise SimulatedCrash(phase)

    manager.fault_injector = crash_after_code_backup
    with pytest.raises(SimulatedCrash):
        manager.activate(transaction.operation_id)
    shutil.rmtree(transaction.paths.backup_code)

    with pytest.raises(RuntimeError, match="could not restore"):
        new_manager(plugin_core_module).recover_pending()

    blocked = manager.load_transaction(transaction.operation_id)
    assert blocked.phase == "rollback_pending"
    assert "could not restore" in blocked.error


def test_forward_recovery_requires_the_activated_dependency_snapshot(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)

    def crash_after_release_activation(phase, _transaction):
        if phase == "release_activated":
            raise SimulatedCrash(phase)

    manager.fault_injector = crash_after_release_activation
    with pytest.raises(SimulatedCrash):
        manager.activate(transaction.operation_id)
    shutil.rmtree(transaction.paths.live_dependencies)

    recovered_manager = new_manager(plugin_core_module)
    recovered_manager.recover_pending()
    recovered = recovered_manager.load_transaction(transaction.operation_id)

    assert recovered.phase == "rolled_back"
    assert_old_live(recovered)


def test_release_transaction_retains_known_good_backup_until_completion(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    manager.activate(transaction.operation_id)

    completed = manager.mark_release_managed(transaction.operation_id)
    reloaded = new_manager(plugin_core_module).load_transaction(
        transaction.operation_id
    )

    assert completed.phase == "release_managed"
    assert reloaded.phase == "release_managed"
    assert read_marker(reloaded.paths.backup_code) == "old-code"
    assert read_marker(reloaded.paths.backup_dependencies) == "old-dependencies"


def test_release_transaction_can_roll_back_from_retained_backup(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    manager.activate(transaction.operation_id)

    rolled_back = manager.rollback(transaction.operation_id)

    assert rolled_back.phase == "rolled_back"
    assert_old_live(rolled_back)


@pytest.mark.parametrize("corrupt_component", ["code", "dependencies"])
def test_explicit_rollback_never_overwrites_live_with_a_corrupt_backup(
    plugin_core_module, tmp_path, corrupt_component
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    manager.activate(transaction.operation_id)
    if corrupt_component == "code":
        corrupt_path = Path(transaction.paths.backup_code) / "plugin.py"
    else:
        corrupt_path = (
            Path(transaction.paths.backup_dependencies) / "marker.txt"
        )
    corrupt_path.write_text("corrupt retained backup", encoding="utf-8")

    with pytest.raises(RuntimeError, match="snapshots"):
        manager.rollback(transaction.operation_id)

    unchanged = manager.load_transaction(transaction.operation_id)
    assert unchanged.phase == "restart_pending"
    assert_new_live(unchanged)


def test_rollback_origin_survives_a_crash_without_preexisting_live_trees(
    plugin_core_module, tmp_path
):
    manager, _, _ = make_manager(plugin_core_module, tmp_path)
    transaction = manager.create_transaction(
        plugin_key="ExamplePlugin",
        operation_id="operation-001",
        operation="release_install",
        expected_current={"management_mode": "absent"},
        target=target_release(),
    )
    write_marker(transaction.paths.staged_code, "new-code", "new-only.py")
    staged_code = Path(transaction.paths.staged_code)
    (staged_code / "plugin.py").write_text("# new plugin\n", encoding="utf-8")
    (staged_code / ".pypluginstore.json").write_text(
        json.dumps(
            install_metadata_document(
                NEW_COMMIT,
                NEW_TREE,
                2,
                "github:owner/example-plugin:v2.0.0",
                artifact_inventory(staged_code),
            )
        ),
        encoding="utf-8",
    )
    Path(transaction.paths.staged_dependencies).mkdir()
    manager.mark_staged_verified(transaction.operation_id)
    manager.mark_dependencies_staged(
        transaction.operation_id,
        dependency_snapshot(),
    )
    manager.activate(transaction.operation_id)

    def crash_before_restore(*_args, **_kwargs):
        raise SimulatedCrash("rollback_pending")

    manager._restore_component = crash_before_restore
    with pytest.raises(SimulatedCrash):
        manager.rollback(transaction.operation_id)

    interrupted = manager.load_transaction(transaction.operation_id)
    assert interrupted.phase == "rollback_pending"
    assert interrupted.rollback_from == "restart_pending"

    recovered_manager = new_manager(plugin_core_module)
    recovered_manager.recover_pending()
    recovered = recovered_manager.load_transaction(transaction.operation_id)
    assert recovered.phase == "rolled_back"
    assert not Path(recovered.paths.live_code).exists()
    assert not Path(recovered.paths.live_dependencies).exists()


def test_recovery_resumes_after_one_rollback_component_was_restored(
    plugin_core_module, tmp_path
):
    manager, plugins_dir, manager_dir = make_manager(
        plugin_core_module, tmp_path
    )
    transaction = prepare_transaction(manager, plugins_dir, manager_dir)
    manager.activate(transaction.operation_id)
    real_restore = manager._restore_component
    restore_calls = 0

    def crash_after_first_restore(*args, **kwargs):
        nonlocal restore_calls
        real_restore(*args, **kwargs)
        restore_calls += 1
        if restore_calls == 1:
            raise SimulatedCrash("code restored")

    manager._restore_component = crash_after_first_restore
    with pytest.raises(SimulatedCrash):
        manager.rollback(transaction.operation_id)

    recovered_manager = new_manager(plugin_core_module)
    recovered_manager.recover_pending()
    recovered = recovered_manager.load_transaction(transaction.operation_id)

    assert recovered.phase == "rolled_back"
    assert_old_live(recovered)


def test_release_transactions_are_globally_serialized(
    plugin_core_module, tmp_path
):
    first_manager, _, _ = make_manager(plugin_core_module, tmp_path)
    second_manager = new_manager(plugin_core_module)

    with first_manager.operation_lock(blocking=False):
        with pytest.raises(RuntimeError):
            second_manager.recover_pending(blocking=False)

    second_manager.recover_pending(blocking=False)


def test_release_transaction_rejects_a_symlink_lock_file(
    plugin_core_module, tmp_path
):
    manager, _, manager_dir = make_manager(plugin_core_module, tmp_path)
    with manager.operation_lock():
        pass
    lock_path = manager_dir / ".pypluginstore" / "transactions.lock"
    external_file = tmp_path / "external-lock-target"
    external_file.write_text("do-not-touch", encoding="utf-8")
    lock_path.unlink()
    lock_path.symlink_to(external_file)

    with pytest.raises(ValueError, match="regular file"):
        with manager.operation_lock():
            pass

    assert external_file.read_text(encoding="utf-8") == "do-not-touch"
