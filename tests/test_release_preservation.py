import hashlib
import os
import stat
from pathlib import Path

import pytest


OLD_PLUGIN = b"print('old release')\n"
NEW_PLUGIN = b"print('new release')\n"
OLD_DEFAULT = b'{"source": "packaged-old"}\n'
NEW_DEFAULT = b'{"source": "packaged-new"}\n'
LOCAL_SETTINGS = b'{"source": "host-local"}\n'


def sha256(contents):
    return hashlib.sha256(contents).hexdigest()


def write_files(root, files):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for relative_path, contents in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, str):
            contents = contents.encode("utf-8")
        path.write_bytes(contents)
    return root


def file_manifest(files):
    return {
        relative_path: sha256(
            contents.encode("utf-8")
            if isinstance(contents, str)
            else contents
        )
        for relative_path, contents in files.items()
    }


def basic_install(tmp_path, *, source_extra=None, staged_extra=None):
    pristine = {
        "plugin.py": OLD_PLUGIN,
        "config/settings.json": OLD_DEFAULT,
        "README.md": b"Old release\n",
    }
    staged_files = {
        "plugin.py": NEW_PLUGIN,
        "config/settings.json": NEW_DEFAULT,
        "README.md": b"New release\n",
    }
    source_files = dict(pristine)
    source_files.update(source_extra or {})
    staged_files.update(staged_extra or {})
    source = write_files(tmp_path / "installed", source_files)
    staged = write_files(tmp_path / "staged", staged_files)
    return source, staged, file_manifest(pristine)


def make_service(plugin_core_module, **limits):
    return plugin_core_module.ReleasePreservationService(
        plugin_core_module.BasePlugin(),
        **limits,
    )


def inventory(
    service,
    source,
    artifact_files,
    *,
    mutable_paths=(),
    preserved_files=None,
    operation="release_update",
    tracked_changes=(),
    untracked_files=(),
):
    return service.inventory(
        installed_dir=str(source),
        artifact_files=dict(artifact_files),
        preserved_files=dict(preserved_files or {}),
        mutable_paths=list(mutable_paths),
        operation=operation,
        tracked_changes=list(tracked_changes),
        untracked_files=list(untracked_files),
    )


def apply_overlay(
    service,
    inventory_result,
    staged,
    *,
    trigger="automatic",
    approved_inventory_sha256=None,
):
    return service.apply_overlay(
        inventory_result,
        staged_dir=str(staged),
        trigger=trigger,
        approved_inventory_sha256=approved_inventory_sha256,
    )


def assert_blocked(
    plugin_core_module,
    reason,
    call,
    *,
    paths=None,
):
    with pytest.raises(plugin_core_module.ReleasePreservationError) as caught:
        call()

    assert caught.value.status == "preservation_blocked"
    assert caught.value.reason == reason
    if paths is not None:
        assert caught.value.paths == paths
    return caught.value


@pytest.mark.parametrize(
    "operation",
    ["release_update", "rollback", "channel_switch"],
)
def test_reviewed_mutable_overlay_is_reused_for_every_release_replacement(
    plugin_core_module, tmp_path, operation
):
    source, staged, artifact_files = basic_install(tmp_path)
    (source / "config/settings.json").write_bytes(LOCAL_SETTINGS)
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["config/settings.json"],
        operation=operation,
    )

    result = apply_overlay(service, scanned, staged)

    assert (staged / "config/settings.json").read_bytes() == LOCAL_SETTINGS
    assert (staged / "plugin.py").read_bytes() == NEW_PLUGIN
    assert result.operation == operation
    assert result.inventory_sha256 == scanned.sha256
    assert result.preserved_paths == ["config/settings.json"]
    assert result.preserved_files == {
        "config/settings.json": sha256(LOCAL_SETTINGS)
    }


def test_reviewed_mutable_directory_carries_packaged_and_local_only_files(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"config/runtime.json": b'{"counter": 3}\n'},
    )
    (source / "config/settings.json").write_bytes(LOCAL_SETTINGS)
    service = make_service(plugin_core_module)

    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["config"],
    )
    result = apply_overlay(service, scanned, staged)

    assert result.preserved_paths == [
        "config/runtime.json",
        "config/settings.json",
    ]
    assert (staged / "config/runtime.json").read_bytes() == b'{"counter": 3}\n'
    assert (staged / "config/settings.json").read_bytes() == LOCAL_SETTINGS


def test_prior_preserved_file_is_carried_only_when_its_audit_hash_matches(
    plugin_core_module, tmp_path
):
    state = b'{"counter": 7}\n'
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.json": state},
    )
    service = make_service(plugin_core_module)

    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["runtime"],
        preserved_files={"runtime/state.json": sha256(state)},
    )
    result = apply_overlay(service, scanned, staged)

    assert result.preserved_files == {"runtime/state.json": sha256(state)}
    assert (staged / "runtime/state.json").read_bytes() == state


def test_changed_prior_preserved_file_requires_a_new_exact_manual_inventory(
    plugin_core_module, tmp_path
):
    state = b'{"counter": 8}\n'
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.json": state},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["runtime"],
        preserved_files={"runtime/state.json": sha256(b'{"counter": 7}\n')},
    )

    assert scanned.unknown_paths == ["runtime/state.json"]
    assert_blocked(
        plugin_core_module,
        "inventory_approval_required",
        lambda: apply_overlay(service, scanned, staged),
        paths=["runtime/state.json"],
    )

    result = apply_overlay(
        service,
        scanned,
        staged,
        trigger="manual",
        approved_inventory_sha256=scanned.sha256,
    )
    assert result.preserved_files == {"runtime/state.json": sha256(state)}


def test_automatic_replacement_blocks_unknown_local_file(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.json": b"local state\n"},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(service, source, artifact_files)

    assert scanned.unknown_paths == ["runtime/state.json"]
    assert_blocked(
        plugin_core_module,
        "unknown_local_paths",
        lambda: apply_overlay(service, scanned, staged),
        paths=["runtime/state.json"],
    )
    assert not (staged / "runtime/state.json").exists()


def test_manual_replacement_shows_exact_inventory_before_approval(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.json": b"local state\n"},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(service, source, artifact_files)

    assert len(scanned.sha256) == 64
    assert scanned.entries["runtime/state.json"].sha256 == sha256(
        b"local state\n"
    )
    assert scanned.entries["runtime/state.json"].size == len(b"local state\n")
    assert scanned.entries["runtime/state.json"].classification == "unknown"
    assert_blocked(
        plugin_core_module,
        "inventory_approval_required",
        lambda: apply_overlay(
            service,
            scanned,
            staged,
            trigger="manual",
        ),
        paths=["runtime/state.json"],
    )


def test_manual_approval_must_match_the_exact_inventory_digest(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.json": b"local state\n"},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(service, source, artifact_files)

    assert_blocked(
        plugin_core_module,
        "inventory_approval_required",
        lambda: apply_overlay(
            service,
            scanned,
            staged,
            trigger="manual",
            approved_inventory_sha256="0" * 64,
        ),
        paths=["runtime/state.json"],
    )
    assert not (staged / "runtime/state.json").exists()


def test_exact_manual_approval_carries_unknown_noncode_path(
    plugin_core_module, tmp_path
):
    contents = b"operator notes\n"
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/notes.txt": contents},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(service, source, artifact_files)

    result = apply_overlay(
        service,
        scanned,
        staged,
        trigger="manual",
        approved_inventory_sha256=scanned.sha256,
    )

    assert result.preserved_files == {"runtime/notes.txt": sha256(contents)}
    assert (staged / "runtime/notes.txt").read_bytes() == contents


@pytest.mark.parametrize("mutation", ["modify", "add", "replace-with-link"])
def test_approved_inventory_is_revalidated_immediately_before_copy(
    plugin_core_module, tmp_path, mutation
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.json": b"first\n"},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(service, source, artifact_files)
    if mutation == "modify":
        (source / "runtime/state.json").write_bytes(b"second\n")
    elif mutation == "add":
        (source / "runtime/extra.json").write_bytes(b"new path\n")
    else:
        (source / "runtime/state.json").unlink()
        (source / "runtime/state.json").symlink_to(tmp_path / "outside")

    assert_blocked(
        plugin_core_module,
        "inventory_changed",
        lambda: apply_overlay(
            service,
            scanned,
            staged,
            trigger="manual",
            approved_inventory_sha256=scanned.sha256,
        ),
    )
    assert not (staged / "runtime/state.json").exists()
    assert not (staged / "runtime/extra.json").exists()


def test_inventory_digest_is_stable_and_content_bound(
    plugin_core_module, tmp_path
):
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.json": b"first\n"},
    )
    service = make_service(plugin_core_module)

    first = inventory(service, source, artifact_files)
    unchanged = inventory(service, source, artifact_files)
    (source / "runtime/state.json").write_bytes(b"second\n")
    changed = inventory(service, source, artifact_files)

    assert first.sha256 == unchanged.sha256
    assert changed.sha256 != first.sha256


def test_git_migration_automatic_trigger_rejects_dirty_tracked_mutable_path(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(tmp_path)
    (source / "config/settings.json").write_bytes(LOCAL_SETTINGS)
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        operation="git_migration",
        mutable_paths=["config/settings.json"],
        tracked_changes=["config/settings.json"],
    )

    assert scanned.tracked_changes == ["config/settings.json"]
    assert_blocked(
        plugin_core_module,
        "tracked_changes",
        lambda: apply_overlay(service, scanned, staged),
        paths=["config/settings.json"],
    )


def test_git_migration_manual_trigger_requires_hash_bound_tracked_approval(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(tmp_path)
    (source / "config/settings.json").write_bytes(LOCAL_SETTINGS)
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        operation="git_migration",
        mutable_paths=["config/settings.json"],
        tracked_changes=["config/settings.json"],
    )

    assert_blocked(
        plugin_core_module,
        "inventory_approval_required",
        lambda: apply_overlay(
            service,
            scanned,
            staged,
            trigger="manual",
        ),
        paths=["config/settings.json"],
    )
    result = apply_overlay(
        service,
        scanned,
        staged,
        trigger="manual",
        approved_inventory_sha256=scanned.sha256,
    )
    assert result.preserved_files == {
        "config/settings.json": sha256(LOCAL_SETTINGS)
    }


def test_git_migration_never_preserves_dirty_tracked_path_outside_policy(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(tmp_path)
    (source / "README.md").write_bytes(b"Local rewrite\n")
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        operation="git_migration",
        tracked_changes=["README.md"],
    )

    assert_blocked(
        plugin_core_module,
        "tracked_path_not_mutable",
        lambda: apply_overlay(
            service,
            scanned,
            staged,
            trigger="manual",
            approved_inventory_sha256=scanned.sha256,
        ),
        paths=["README.md"],
    )
    assert (staged / "README.md").read_bytes() == b"New release\n"


def test_git_migration_automatically_carries_reviewed_untracked_mutable_path(
    plugin_core_module, tmp_path
):
    state = b'{"counter": 11}\n'
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.json": state},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        operation="git_migration",
        mutable_paths=["runtime"],
        untracked_files=["runtime/state.json"],
    )

    result = apply_overlay(service, scanned, staged)

    assert scanned.untracked_files == ["runtime/state.json"]
    assert result.preserved_files == {"runtime/state.json": sha256(state)}


def test_git_migration_unknown_untracked_path_blocks_automatic_but_manual_can_approve(
    plugin_core_module, tmp_path
):
    notes = b"keep after migration\n"
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={"notes/operator.txt": notes},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        operation="git_migration",
        untracked_files=["notes/operator.txt"],
    )

    assert_blocked(
        plugin_core_module,
        "unknown_local_paths",
        lambda: apply_overlay(service, scanned, staged),
        paths=["notes/operator.txt"],
    )
    result = apply_overlay(
        service,
        scanned,
        staged,
        trigger="manual",
        approved_inventory_sha256=scanned.sha256,
    )
    assert result.preserved_files == {"notes/operator.txt": sha256(notes)}


def test_declared_mutable_path_may_replace_packaged_default(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(tmp_path)
    (source / "config/settings.json").write_bytes(LOCAL_SETTINGS)
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["config/settings.json"],
    )

    apply_overlay(service, scanned, staged)

    assert (staged / "config/settings.json").read_bytes() == LOCAL_SETTINGS


def test_unknown_path_may_not_replace_packaged_default_even_with_manual_approval(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(tmp_path)
    (source / "README.md").write_bytes(b"Local rewrite\n")
    service = make_service(plugin_core_module)
    scanned = inventory(service, source, artifact_files)

    assert_blocked(
        plugin_core_module,
        "packaged_path_collision",
        lambda: apply_overlay(
            service,
            scanned,
            staged,
            trigger="manual",
            approved_inventory_sha256=scanned.sha256,
        ),
        paths=["README.md"],
    )
    assert (staged / "README.md").read_bytes() == b"New release\n"


@pytest.mark.parametrize(
    ("source_path", "staged_path"),
    [
        ("runtime/state", "runtime/state/value.json"),
        ("runtime/state/value.json", "runtime/state"),
    ],
)
def test_preserved_file_directory_type_collision_is_blocked(
    plugin_core_module, tmp_path, source_path, staged_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={source_path: b"local\n"},
        staged_extra={staged_path: b"packaged\n"},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["runtime"],
    )

    assert_blocked(
        plugin_core_module,
        "packaged_path_collision",
        lambda: apply_overlay(service, scanned, staged),
    )


def test_escaping_source_symlink_is_never_a_preservation_overlay(
    plugin_core_module, tmp_path
):
    source, _, artifact_files = basic_install(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside\n")
    runtime = source / "runtime"
    runtime.mkdir()
    (runtime / "state.json").symlink_to(outside)
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "unsafe_preserved_path",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=["runtime"],
        ),
        paths=["runtime/state.json"],
    )


def test_staged_symlink_is_not_followed_when_overlaying_packaged_default(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(tmp_path)
    (source / "config/settings.json").write_bytes(LOCAL_SETTINGS)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside\n")
    (staged / "config/settings.json").unlink()
    (staged / "config/settings.json").symlink_to(outside)
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["config/settings.json"],
    )

    assert_blocked(
        plugin_core_module,
        "unsafe_staged_path",
        lambda: apply_overlay(service, scanned, staged),
        paths=["config/settings.json"],
    )
    assert outside.read_bytes() == b"outside\n"


def test_known_disposable_caches_are_ignored_and_never_copied(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={
            "__pycache__/helper.cpython-313.pyc": b"bytecode",
            ".pytest_cache/v/cache/nodeids": b"[]",
            ".mypy_cache/3.13/cache.json": b"{}",
            ".ruff_cache/content": b"cache",
        },
    )
    service = make_service(plugin_core_module)
    scanned = inventory(service, source, artifact_files)
    result = apply_overlay(service, scanned, staged)

    assert scanned.unknown_paths == []
    assert scanned.ignored_paths == [
        ".mypy_cache/3.13/cache.json",
        ".pytest_cache/v/cache/nodeids",
        ".ruff_cache/content",
        "__pycache__/helper.cpython-313.pyc",
    ]
    assert result.preserved_files == {}
    for relative_path in scanned.ignored_paths:
        assert not (staged / relative_path).exists()


def test_cache_churn_does_not_invalidate_exact_inventory_approval(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={
            "runtime/notes.txt": b"keep\n",
            "__pycache__/helper.pyc": b"old cache",
        },
    )
    service = make_service(plugin_core_module)
    scanned = inventory(service, source, artifact_files)
    (source / "__pycache__/helper.pyc").write_bytes(b"new cache")

    result = apply_overlay(
        service,
        scanned,
        staged,
        trigger="manual",
        approved_inventory_sha256=scanned.sha256,
    )

    assert result.preserved_files == {
        "runtime/notes.txt": sha256(b"keep\n")
    }


def test_git_and_manager_metadata_are_ignored_not_overlaid(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={
            ".git/config": b"[remote \"origin\"]\n",
            ".pypluginstore.json": b'{"old": true}\n',
        },
        staged_extra={".pypluginstore.json": b'{"new": true}\n'},
    )
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        operation="git_migration",
    )
    result = apply_overlay(service, scanned, staged)

    assert scanned.unknown_paths == []
    assert ".git/config" in scanned.ignored_paths
    assert ".pypluginstore.json" in scanned.ignored_paths
    assert result.preserved_files == {}
    assert (staged / ".pypluginstore.json").read_bytes() == b'{"new": true}\n'
    assert not (staged / ".git").exists()


@pytest.mark.parametrize(
    "mutable_path",
    [
        "plugin.py",
        ".pypluginstore.json",
        ".pypluginstore/journal.json",
        ".git/config",
        "CON.txt",
        "runtime/trailing. ",
    ],
)
def test_mutable_policy_rejects_manager_and_cross_platform_reserved_paths(
    plugin_core_module, tmp_path, mutable_path
):
    source, _, artifact_files = basic_install(tmp_path)
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "unsafe_preserved_path",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=[mutable_path],
        ),
        paths=[mutable_path],
    )


def test_locally_modified_plugin_entrypoint_is_never_preserved(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(tmp_path)
    (source / "plugin.py").write_bytes(b"print('locally changed')\n")
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "unsafe_preserved_path",
        lambda: inventory(service, source, artifact_files),
        paths=["plugin.py"],
    )
    assert (staged / "plugin.py").read_bytes() == NEW_PLUGIN


@pytest.mark.parametrize(
    "relative_path",
    [
        "runtime/helper.py",
        "runtime/helper.pyc",
        "runtime/native.so",
        "runtime/native.dll",
        "runtime/program.exe",
    ],
)
def test_manual_inventory_can_never_approve_executable_code_extension(
    plugin_core_module, tmp_path, relative_path
):
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={relative_path: b"executable code"},
    )
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "unsafe_preserved_path",
        lambda: inventory(service, source, artifact_files),
        paths=[relative_path],
    )


def test_manual_inventory_rejects_executable_permission_even_without_code_extension(
    plugin_core_module, tmp_path
):
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/helper": b"#!/bin/sh\n"},
    )
    helper = source / "runtime/helper"
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
    if not helper.stat().st_mode & stat.S_IXUSR:
        pytest.skip("the test filesystem does not support executable bits")
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "unsafe_preserved_path",
        lambda: inventory(service, source, artifact_files),
        paths=["runtime/helper"],
    )


def test_preservation_enforces_per_file_size_limit(
    plugin_core_module, tmp_path
):
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={"runtime/state.bin": b"12345"},
    )
    service = make_service(plugin_core_module, max_file_size=4)

    assert_blocked(
        plugin_core_module,
        "preservation_limit_exceeded",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=["runtime"],
        ),
        paths=["runtime/state.bin"],
    )


def test_preservation_enforces_total_size_limit(plugin_core_module, tmp_path):
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={
            "runtime/one.bin": b"1234",
            "runtime/two.bin": b"5678",
        },
    )
    service = make_service(
        plugin_core_module,
        max_file_size=4,
        max_total_size=7,
    )

    assert_blocked(
        plugin_core_module,
        "preservation_limit_exceeded",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=["runtime"],
        ),
        paths=["runtime/one.bin", "runtime/two.bin"],
    )


def test_preservation_enforces_file_count_limit(plugin_core_module, tmp_path):
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={
            "runtime/one.json": b"1",
            "runtime/two.json": b"2",
        },
    )
    service = make_service(plugin_core_module, max_files=1)

    assert_blocked(
        plugin_core_module,
        "preservation_limit_exceeded",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=["runtime"],
        ),
        paths=["runtime/one.json", "runtime/two.json"],
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_preservation_rejects_non_regular_file_type(plugin_core_module, tmp_path):
    source, _, artifact_files = basic_install(tmp_path)
    runtime = source / "runtime"
    runtime.mkdir()
    os.mkfifo(runtime / "state.pipe")
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "unsupported_file_type",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=["runtime"],
        ),
        paths=["runtime/state.pipe"],
    )


def test_candidate_paths_colliding_under_windows_casefold_are_rejected(
    plugin_core_module, tmp_path
):
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={
            "runtime/State.json": b"upper\n",
            "runtime/state.json": b"lower\n",
        },
    )
    spellings = {path.name for path in (source / "runtime").iterdir()}
    if not {"State.json", "state.json"}.issubset(spellings):
        pytest.skip("the test filesystem is case-insensitive")
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "path_collision",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=["runtime"],
        ),
        paths=["runtime/State.json", "runtime/state.json"],
    )


def test_overlay_path_colliding_with_packaged_path_under_windows_casefold_is_rejected(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(tmp_path)
    temporary_config = source / "config-renamed"
    (source / "config").rename(temporary_config)
    config = source / "Config"
    temporary_config.rename(config)
    temporary_settings = config / "settings-renamed.json"
    (config / "settings.json").rename(temporary_settings)
    settings = config / "Settings.json"
    temporary_settings.rename(settings)
    settings.write_bytes(LOCAL_SETTINGS)
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["Config"],
    )

    assert_blocked(
        plugin_core_module,
        "packaged_path_collision",
        lambda: apply_overlay(service, scanned, staged),
        paths=["Config/Settings.json", "config/settings.json"],
    )


def test_candidate_paths_colliding_after_unicode_normalization_are_rejected(
    plugin_core_module, tmp_path
):
    composed = "runtime/caf\N{LATIN SMALL LETTER E WITH ACUTE}.json"
    decomposed = "runtime/cafe\N{COMBINING ACUTE ACCENT}.json"
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={composed: b"composed\n", decomposed: b"decomposed\n"},
    )
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "path_collision",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=["runtime"],
        ),
        paths=sorted([composed, decomposed]),
    )


def test_single_non_nfc_overlay_path_is_rejected_as_nonportable(
    plugin_core_module, tmp_path
):
    decomposed = "runtime/cafe\N{COMBINING ACUTE ACCENT}.json"
    source, _, artifact_files = basic_install(
        tmp_path,
        source_extra={decomposed: b"decomposed\n"},
    )
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "unsafe_preserved_path",
        lambda: inventory(
            service,
            source,
            artifact_files,
            mutable_paths=["runtime"],
        ),
        paths=[decomposed],
    )


def test_preserved_audit_hashes_are_sorted_and_match_final_overlay_bytes(
    plugin_core_module, tmp_path
):
    files = {
        "runtime/z-last.json": b"z\n",
        "runtime/a-first.json": b"a\n",
    }
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra=files,
    )
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["runtime"],
    )
    result = apply_overlay(service, scanned, staged)

    assert list(result.preserved_files) == sorted(files)
    for relative_path, contents in files.items():
        expected = sha256(contents)
        assert result.preserved_files[relative_path] == expected
        assert sha256((staged / relative_path).read_bytes()) == expected


def test_apply_is_all_or_nothing_when_late_inventory_revalidation_fails(
    plugin_core_module, tmp_path
):
    source, staged, artifact_files = basic_install(
        tmp_path,
        source_extra={
            "runtime/a.json": b"first\n",
            "runtime/z.json": b"last\n",
        },
    )
    service = make_service(plugin_core_module)
    scanned = inventory(
        service,
        source,
        artifact_files,
        mutable_paths=["runtime"],
    )
    (source / "runtime/z.json").write_bytes(b"changed\n")

    assert_blocked(
        plugin_core_module,
        "inventory_changed",
        lambda: apply_overlay(service, scanned, staged),
    )
    assert not (staged / "runtime/a.json").exists()
    assert not (staged / "runtime/z.json").exists()


def test_preservation_rejects_unknown_operation(plugin_core_module, tmp_path):
    source, _, artifact_files = basic_install(tmp_path)
    service = make_service(plugin_core_module)

    assert_blocked(
        plugin_core_module,
        "invalid_operation",
        lambda: inventory(
            service,
            source,
            artifact_files,
            operation="in_place_patch",
        ),
    )
