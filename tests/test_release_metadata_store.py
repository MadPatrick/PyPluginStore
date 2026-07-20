import hashlib
import json
import shutil
from datetime import datetime, timezone

import pytest


NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)
REGISTRY_DOCUMENT = {
    "ExamplePlugin": ["owner", "repo", "Example plugin", "main"],
}
REGISTRY_BYTES = (
    json.dumps(REGISTRY_DOCUMENT, indent=2, sort_keys=True) + "\n"
).encode("utf-8")
REGISTRY_SHA256 = hashlib.sha256(REGISTRY_BYTES).hexdigest()


class InjectedCrash(RuntimeError):
    pass


def release_index_document(
    sequence,
    generated_at="2026-07-18T08:00:00Z",
    expires_at="2026-07-25T08:00:00Z",
):
    commit = "0123456789abcdef0123456789abcdef01234567"
    return {
        "schema_version": 1,
        "sequence": sequence,
        "generated_at": generated_at,
        "expires_at": expires_at,
        "registry_sha256": REGISTRY_SHA256,
        "plugins": {
            "ExamplePlugin": {
                "revision": 7,
                "release_id": "github:owner/repo:v1.4.0",
                "supersedes": [],
                "provider": "github",
                "repository_identity": "github.com/owner/repo",
                "version": "1.4.0",
                "tag": "v1.4.0",
                "released_at": "2026-07-18T07:00:00Z",
                "commit": commit,
                "artifact": {
                    "kind": "source_zip",
                    "provenance": "forge_source_archive",
                    "migration_eligible": True,
                    "url": (
                        "https://github.com/owner/repo/archive/"
                        + commit
                        + ".zip"
                    ),
                    "sha256": "0" * 64,
                    "size": 123456,
                    "tree_sha256": "1" * 64,
                    "root_prefix": "repo-" + commit,
                    "source_path": ".",
                },
            }
        },
        "tombstones": {},
    }


def release_index_bytes(sequence, **overrides):
    document = release_index_document(sequence, **overrides)
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def write_bundle(tmp_path, sequence, **overrides):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir(exist_ok=True)
    registry_path = bundle_dir / "registry.json"
    index_path = bundle_dir / "release_index.json"
    registry_path.write_bytes(REGISTRY_BYTES)
    index_path.write_bytes(release_index_bytes(sequence, **overrides))
    return registry_path, index_path


def make_store(
    plugin_core_module,
    tmp_path,
    *,
    now=NOW,
    bundle=None,
    fault_injector=None,
):
    metadata_root = tmp_path / ".pypluginstore" / "metadata"
    bundle = bundle or (None, None)
    store = plugin_core_module.ReleaseMetadataStore(
        str(metadata_root),
        bundled_registry_path=(str(bundle[0]) if bundle[0] else None),
        bundled_index_path=(str(bundle[1]) if bundle[1] else None),
        clock=lambda: now,
        fault_injector=fault_injector,
    )
    return store, metadata_root


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_accept_remote_caches_exact_pair_hashes_watermark_and_pointer(
    plugin_core_module, tmp_path
):
    store, metadata_root = make_store(plugin_core_module, tmp_path)
    index_bytes = release_index_bytes(42)

    accepted = store.accept_remote(REGISTRY_BYTES, index_bytes)

    generation = metadata_root / "generations" / "42"
    assert accepted.sequence == 42
    assert accepted.release_authorized is True
    assert generation.joinpath("registry.json").read_bytes() == REGISTRY_BYTES
    assert generation.joinpath("release_index.json").read_bytes() == index_bytes
    hashes = load_json(generation / "hashes.json")
    assert hashes["registry_sha256"] == hashlib.sha256(
        REGISTRY_BYTES
    ).hexdigest()
    assert hashes["release_index_sha256"] == hashlib.sha256(
        index_bytes
    ).hexdigest()
    assert load_json(metadata_root / "trust-state.json")[
        "highest_sequence"
    ] == 42
    assert load_json(metadata_root / "current.json")["sequence"] == 42
    assert not list((metadata_root / "generations").glob("*.tmp-*"))

    loaded = make_store(plugin_core_module, tmp_path)[0].load()
    assert loaded.sequence == 42
    assert loaded.release_authorized is True
    assert loaded.registry_bytes == REGISTRY_BYTES
    assert loaded.release_index_bytes == index_bytes


def test_fresh_bundle_bootstraps_only_when_no_newer_sequence_was_accepted(
    plugin_core_module, tmp_path
):
    bundle = write_bundle(tmp_path, 40)
    store, metadata_root = make_store(
        plugin_core_module, tmp_path, bundle=bundle
    )

    selected = store.load()

    assert selected.sequence == 40
    assert selected.release_authorized is True
    assert selected.registry_bytes == REGISTRY_BYTES
    assert selected.release_index_bytes == bundle[1].read_bytes()
    assert (
        metadata_root / "generations" / "40" / "registry.json"
    ).read_bytes() == REGISTRY_BYTES
    assert load_json(metadata_root / "trust-state.json")[
        "highest_sequence"
    ] == 40


def test_expired_bundle_keeps_registry_available_but_cannot_authorize_releases(
    plugin_core_module, tmp_path
):
    bundle = write_bundle(
        tmp_path,
        40,
        generated_at="2026-07-01T08:00:00Z",
        expires_at="2026-07-10T08:00:00Z",
    )
    store, metadata_root = make_store(
        plugin_core_module, tmp_path, bundle=bundle
    )

    selected = store.load()

    assert selected.registry_bytes == REGISTRY_BYTES
    assert selected.release_authorized is False
    assert selected.release_index is None
    assert selected.reason
    assert not (metadata_root / "trust-state.json").exists()
    assert not (metadata_root / "generations" / "40").exists()


def test_expired_cached_pair_pauses_release_changes_without_losing_registry(
    plugin_core_module, tmp_path
):
    accepting_store, _ = make_store(plugin_core_module, tmp_path)
    index_bytes = release_index_bytes(42)
    accepting_store.accept_remote(REGISTRY_BYTES, index_bytes)

    expired_store, _ = make_store(plugin_core_module, tmp_path, now=LATER)
    selected = expired_store.load()

    assert selected.sequence == 42
    assert selected.registry_bytes == REGISTRY_BYTES
    assert selected.release_authorized is False
    assert selected.release_index is None
    assert selected.reason


def test_authorized_in_memory_selection_is_revoked_after_expiry(
    plugin_core_module, tmp_path
):
    current_time = [NOW]
    store = plugin_core_module.ReleaseMetadataStore(
        str(tmp_path / ".pypluginstore" / "metadata"),
        clock=lambda: current_time[0],
    )
    index_bytes = release_index_bytes(42)
    selected = store.accept_remote(REGISTRY_BYTES, index_bytes)

    assert store.revalidate_selection(selected) is selected

    current_time[0] = LATER
    revoked = store.revalidate_selection(selected)

    assert revoked.sequence == selected.sequence
    assert revoked.registry_bytes == REGISTRY_BYTES
    assert revoked.release_index_bytes == index_bytes
    assert revoked.release_authorized is False
    assert revoked.release_index is None
    assert "expired" in revoked.reason.lower()


def test_bundle_cannot_seed_below_durable_watermark_after_cache_loss(
    plugin_core_module, tmp_path
):
    initial_store, metadata_root = make_store(plugin_core_module, tmp_path)
    initial_store.accept_remote(REGISTRY_BYTES, release_index_bytes(42))
    shutil.rmtree(metadata_root / "generations" / "42")
    (metadata_root / "current.json").unlink()
    bundle = write_bundle(tmp_path, 41)

    recovering_store, _ = make_store(
        plugin_core_module, tmp_path, bundle=bundle
    )
    selected = recovering_store.load()

    assert load_json(metadata_root / "trust-state.json")[
        "highest_sequence"
    ] == 42
    assert selected.registry_bytes == REGISTRY_BYTES
    assert selected.release_authorized is False
    assert selected.release_index is None
    assert selected.reason
    assert not (metadata_root / "generations" / "41").exists()


@pytest.mark.parametrize(
    "index_bytes",
    [
        release_index_bytes(41),
        release_index_bytes(
            43,
            generated_at="2026-07-01T08:00:00Z",
            expires_at="2026-07-10T08:00:00Z",
        ),
    ],
    ids=("lower-sequence", "expired"),
)
def test_rejected_remote_pair_does_not_replace_current_or_watermark(
    plugin_core_module, tmp_path, index_bytes
):
    store, metadata_root = make_store(plugin_core_module, tmp_path)
    current_index = release_index_bytes(42)
    store.accept_remote(REGISTRY_BYTES, current_index)

    with pytest.raises(ValueError):
        store.accept_remote(REGISTRY_BYTES, index_bytes)

    assert load_json(metadata_root / "current.json")["sequence"] == 42
    assert load_json(metadata_root / "trust-state.json")[
        "highest_sequence"
    ] == 42
    assert (
        metadata_root / "generations" / "42" / "release_index.json"
    ).read_bytes() == current_index


@pytest.mark.parametrize(
    "pointer_contents",
    ["{broken", '{"sequence": 41}\n', '{"sequence": 99}\n'],
    ids=("malformed", "below-watermark", "missing-generation"),
)
def test_startup_recovers_highest_complete_generation_and_repairs_pointer(
    plugin_core_module, tmp_path, pointer_contents
):
    store, metadata_root = make_store(plugin_core_module, tmp_path)
    store.accept_remote(REGISTRY_BYTES, release_index_bytes(41))
    store.accept_remote(REGISTRY_BYTES, release_index_bytes(42))
    (metadata_root / "current.json").write_text(
        pointer_contents, encoding="utf-8"
    )

    selected = make_store(plugin_core_module, tmp_path)[0].load()

    assert selected.sequence == 42
    assert selected.release_authorized is True
    assert load_json(metadata_root / "current.json")["sequence"] == 42
    assert load_json(metadata_root / "trust-state.json")[
        "highest_sequence"
    ] == 42


def test_startup_ignores_corrupt_complete_generation_above_watermark(
    plugin_core_module, tmp_path
):
    store, metadata_root = make_store(plugin_core_module, tmp_path)
    store.accept_remote(REGISTRY_BYTES, release_index_bytes(41))
    generation_41 = metadata_root / "generations" / "41"
    generation_42 = metadata_root / "generations" / "42"
    shutil.copytree(generation_41, generation_42)
    (generation_42 / "release_index.json").write_bytes(b"{corrupt")

    selected = make_store(plugin_core_module, tmp_path)[0].load()

    assert selected.sequence == 41
    assert selected.release_authorized is True
    assert load_json(metadata_root / "current.json")["sequence"] == 41


def test_startup_never_falls_back_below_watermark_when_trusted_generation_is_lost(
    plugin_core_module, tmp_path
):
    bundle = write_bundle(tmp_path, 40)
    store, metadata_root = make_store(
        plugin_core_module, tmp_path, bundle=bundle
    )
    store.accept_remote(REGISTRY_BYTES, release_index_bytes(41))
    store.accept_remote(REGISTRY_BYTES, release_index_bytes(42))
    shutil.rmtree(metadata_root / "generations" / "42")
    (metadata_root / "current.json").write_text("{broken", encoding="utf-8")

    selected = make_store(
        plugin_core_module, tmp_path, bundle=bundle
    )[0].load()

    assert load_json(metadata_root / "trust-state.json")[
        "highest_sequence"
    ] == 42
    assert selected.registry_bytes == REGISTRY_BYTES
    assert selected.release_authorized is False
    assert selected.release_index is None
    assert selected.reason


def test_malformed_watermark_fails_closed_instead_of_resetting_trust(
    plugin_core_module, tmp_path
):
    bundle = write_bundle(tmp_path, 40)
    store, metadata_root = make_store(
        plugin_core_module, tmp_path, bundle=bundle
    )
    store.accept_remote(REGISTRY_BYTES, release_index_bytes(42))
    (metadata_root / "trust-state.json").write_text(
        "{broken", encoding="utf-8"
    )

    selected = make_store(
        plugin_core_module, tmp_path, bundle=bundle
    )[0].load()

    assert selected.registry_bytes == REGISTRY_BYTES
    assert selected.release_authorized is False
    assert selected.release_index is None
    assert selected.reason
    assert (metadata_root / "trust-state.json").read_text(
        encoding="utf-8"
    ) == "{broken"


CRASH_BOUNDARIES = (
    "registry_written",
    "registry_fsynced",
    "index_written",
    "index_fsynced",
    "hashes_written",
    "hashes_fsynced",
    "generation_fsynced",
    "generation_renamed",
    "generations_fsynced",
    "watermark_written",
    "watermark_fsynced",
    "watermark_replaced",
    "metadata_fsynced_after_watermark",
    "pointer_written",
    "pointer_fsynced",
    "pointer_replaced",
    "metadata_fsynced_after_pointer",
)

RECOVERY_CRASH_BOUNDARIES = (
    "recovery_selected",
    "watermark_written",
    "watermark_fsynced",
    "watermark_replaced",
    "metadata_fsynced_after_watermark",
    "pointer_written",
    "pointer_fsynced",
    "pointer_replaced",
    "metadata_fsynced_after_pointer",
)


@pytest.mark.parametrize("boundary", CRASH_BOUNDARIES)
def test_crash_at_each_durability_boundary_recovers_a_complete_trusted_pair(
    plugin_core_module, tmp_path, boundary
):
    initial_store, metadata_root = make_store(plugin_core_module, tmp_path)
    index_41 = release_index_bytes(41)
    index_42 = release_index_bytes(42)
    initial_store.accept_remote(REGISTRY_BYTES, index_41)
    events = []

    def crash_after_event(event):
        events.append(event)
        if event == boundary:
            raise InjectedCrash(event)

    crashing_store, _ = make_store(
        plugin_core_module,
        tmp_path,
        fault_injector=crash_after_event,
    )

    with pytest.raises(InjectedCrash, match=boundary):
        crashing_store.accept_remote(REGISTRY_BYTES, index_42)

    assert boundary in events
    for state_name in ("trust-state.json", "current.json"):
        state_path = metadata_root / state_name
        if state_path.exists():
            load_json(state_path)

    recovered = make_store(plugin_core_module, tmp_path)[0].load()
    generation_was_renamed = CRASH_BOUNDARIES.index(boundary) >= (
        CRASH_BOUNDARIES.index("generation_renamed")
    )
    expected_sequence = 42 if generation_was_renamed else 41
    expected_index = index_42 if generation_was_renamed else index_41
    assert recovered.sequence == expected_sequence
    assert recovered.release_authorized is True
    assert recovered.registry_bytes == REGISTRY_BYTES
    assert recovered.release_index_bytes == expected_index
    assert load_json(metadata_root / "current.json")[
        "sequence"
    ] == expected_sequence
    assert load_json(metadata_root / "trust-state.json")[
        "highest_sequence"
    ] == expected_sequence


@pytest.mark.parametrize("boundary", RECOVERY_CRASH_BOUNDARIES)
def test_crash_while_repairing_pointer_is_idempotently_recoverable(
    plugin_core_module, tmp_path, boundary
):
    initial_store, metadata_root = make_store(plugin_core_module, tmp_path)
    initial_store.accept_remote(REGISTRY_BYTES, release_index_bytes(41))

    def crash_after_generation_rename(event):
        if event == "generation_renamed":
            raise InjectedCrash(event)

    interrupted_store, _ = make_store(
        plugin_core_module,
        tmp_path,
        fault_injector=crash_after_generation_rename,
    )
    with pytest.raises(InjectedCrash, match="generation_renamed"):
        interrupted_store.accept_remote(
            REGISTRY_BYTES, release_index_bytes(42)
        )

    recovery_events = []

    def crash_during_recovery(event):
        recovery_events.append(event)
        if event == boundary:
            raise InjectedCrash(event)

    recovery_store, _ = make_store(
        plugin_core_module,
        tmp_path,
        fault_injector=crash_during_recovery,
    )
    with pytest.raises(InjectedCrash, match=boundary):
        recovery_store.load()

    assert boundary in recovery_events
    selected = make_store(plugin_core_module, tmp_path)[0].load()
    assert selected.sequence == 42
    assert selected.release_authorized is True
    assert load_json(metadata_root / "current.json")["sequence"] == 42
    assert load_json(metadata_root / "trust-state.json")[
        "highest_sequence"
    ] == 42
