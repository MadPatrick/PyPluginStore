import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest


NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
REGISTRY = {
    "ExamplePlugin": ["owner", "repo", "Example plugin", "main"],
    "RetiredPlugin": ["retired", "repo", "Retired plugin", "main"],
}
REGISTRY_BYTES = (json.dumps(REGISTRY, separators=(",", ":")) + "\n").encode(
    "utf-8"
)
REGISTRY_SHA256 = hashlib.sha256(REGISTRY_BYTES).hexdigest()


def release_entry(
    revision=7,
    release_id="github:owner/repo:v1.4.0",
    supersedes=None,
    version="1.4.0",
    tag="v1.4.0",
    commit="0123456789abcdef0123456789abcdef01234567",
    tree_sha256="1" * 64,
):
    return {
        "revision": revision,
        "release_id": release_id,
        "supersedes": list(supersedes or []),
        "provider": "github",
        "repository_identity": "github.com/owner/repo",
        "version": version,
        "tag": tag,
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
            "tree_sha256": tree_sha256,
            "root_prefix": "repo-" + commit,
            "source_path": ".",
        },
    }


def release_index_document(
    sequence=42,
    generated_at="2026-07-18T08:00:00Z",
    expires_at="2026-07-25T08:00:00Z",
    registry_sha256=REGISTRY_SHA256,
    entry=None,
    tombstones=None,
):
    return {
        "schema_version": 1,
        "sequence": sequence,
        "generated_at": generated_at,
        "expires_at": expires_at,
        "registry_sha256": registry_sha256,
        "plugins": {
            "ExamplePlugin": release_entry() if entry is None else entry
        },
        "tombstones": dict(tombstones or {}),
    }


def release_tombstone(
    repository_identity="github.com/retired/repo",
    release_id="github:retired/repo:v1.2.0",
):
    return {
        "repository_identity": repository_identity,
        "last_revision": 4,
        "release_id": release_id,
        "reason": "Release packaging is no longer maintained.",
        "removed_at": "2026-07-18T09:00:00Z",
    }


def parse_index(plugin_core_module, document, previous=None):
    return plugin_core_module.ReleaseIndex.from_document(
        document,
        registry_bytes=REGISTRY_BYTES,
        now=NOW,
        previous=previous,
    )


def test_legacy_registry_entry_keeps_git_shape_and_gets_implicit_delivery_policy(
    plugin_core_module,
):
    plugin = plugin_core_module.BasePlugin()

    registry, platforms = plugin.normalize_registry(REGISTRY)

    assert registry == REGISTRY
    assert platforms == {
        "ExamplePlugin": ["unknown"],
        "RetiredPlugin": ["unknown"],
    }
    entry = plugin.registry_entries["ExamplePlugin"]
    assert entry.to_legacy_list() == REGISTRY["ExamplePlugin"]
    assert entry.delivery.preferred == "release_if_indexed"
    assert entry.delivery.git_supported is True
    assert entry.delivery.release is None


def test_object_registry_entry_parses_delivery_without_changing_legacy_consumers(
    plugin_core_module,
):
    plugin = plugin_core_module.BasePlugin()
    registry_document = {
        "ExamplePlugin": {
            "owner": "gitlab.com/group",
            "repository": "example-plugin",
            "description": "Example plugin",
            "branch": "main",
            "delivery": {
                "schema_version": 1,
                "preferred": "release",
                "git_supported": False,
                "release": {
                    "provider": "gitlab",
                    "channel": "stable",
                    "tag_pattern": "^v[0-9]+\\.[0-9]+\\.[0-9]+$",
                    "artifact": "source_zip",
                    "source_path": "plugin",
                    "mutable_paths": ["config.json", "data"],
                    "allowed_origins": ["https://packages.example.org/"],
                },
            },
        }
    }

    registry, _ = plugin.normalize_registry(registry_document)

    assert registry["ExamplePlugin"] == [
        "gitlab.com/group",
        "example-plugin",
        "Example plugin",
        "main",
    ]
    delivery = plugin.registry_entries["ExamplePlugin"].delivery
    assert delivery.schema_version == 1
    assert delivery.preferred == "release"
    assert delivery.git_supported is False
    assert delivery.release.provider == "gitlab"
    assert delivery.release.channel == "stable"
    assert delivery.release.tag_pattern == "^v[0-9]+\\.[0-9]+\\.[0-9]+$"
    assert delivery.release.artifact == "source_zip"
    assert delivery.release.source_path == "plugin"
    assert delivery.release.mutable_paths == ["config.json", "data"]
    assert delivery.release.allowed_origins == ["https://packages.example.org"]


def test_local_registry_entries_are_explicitly_git_only(plugin_core_module):
    plugin = plugin_core_module.BasePlugin()
    local_registry = {
        "ExamplePlugin": {
            "owner": "owner",
            "repository": "repo",
            "description": "Local override",
            "branch": "main",
            "delivery": {
                "schema_version": 1,
                "preferred": "release",
                "git_supported": False,
                "release": {"provider": "github"},
            },
        }
    }

    _, _, entries = plugin.registry_service.normalize_registry(
        local_registry,
        local_keys={"ExamplePlugin"},
    )

    assert entries["ExamplePlugin"].delivery.preferred == "git"
    assert entries["ExamplePlugin"].delivery.git_supported is True
    assert entries["ExamplePlugin"].delivery.release is None


def test_normalized_release_index_exposes_provider_neutral_descriptor(
    plugin_core_module,
):
    index = parse_index(plugin_core_module, release_index_document())

    assert index.schema_version == 1
    assert index.sequence == 42
    assert index.generated_at == "2026-07-18T08:00:00Z"
    assert index.expires_at == "2026-07-25T08:00:00Z"
    assert index.registry_sha256 == REGISTRY_SHA256
    descriptor = index.plugins["ExamplePlugin"]
    assert descriptor.revision == 7
    assert descriptor.release_id == "github:owner/repo:v1.4.0"
    assert descriptor.provider == "github"
    assert descriptor.repository_identity == "github.com/owner/repo"
    assert descriptor.commit == "0123456789abcdef0123456789abcdef01234567"
    assert descriptor.artifact.kind == "source_zip"
    assert descriptor.artifact.provenance == "forge_source_archive"
    assert descriptor.artifact.migration_eligible is True
    assert descriptor.artifact.sha256 == "0" * 64
    assert descriptor.artifact.tree_sha256 == "1" * 64
    assert descriptor.artifact.size == 123456
    assert descriptor.artifact.source_path == "."


def test_normalized_release_index_preserves_decertification_tombstone(
    plugin_core_module,
):
    index = parse_index(
        plugin_core_module,
        release_index_document(
            tombstones={"RetiredPlugin": release_tombstone()}
        ),
    )

    tombstone = index.tombstones["RetiredPlugin"]
    assert tombstone.repository_identity == "github.com/retired/repo"
    assert tombstone.last_revision == 4
    assert tombstone.release_id == "github:retired/repo:v1.2.0"
    assert tombstone.reason == "Release packaging is no longer maintained."
    assert tombstone.removed_at == "2026-07-18T09:00:00Z"


def test_higher_revision_accepts_complete_supersedes_lineage(plugin_core_module):
    previous_entry = release_entry(
        revision=6,
        release_id="github:owner/repo:v1.3.0",
        supersedes=["github:owner/repo:v1.2.0"],
        version="1.3.0",
        tag="v1.3.0",
        commit="1" * 40,
        tree_sha256="2" * 64,
    )
    previous = parse_index(
        plugin_core_module,
        release_index_document(sequence=41, entry=previous_entry),
    )
    current_entry = release_entry(
        supersedes=[
            "github:owner/repo:v1.2.0",
            "github:owner/repo:v1.3.0",
        ]
    )

    current = parse_index(
        plugin_core_module,
        release_index_document(entry=current_entry),
        previous=previous,
    )

    assert current.plugins["ExamplePlugin"].revision == 7
    assert current.plugins["ExamplePlugin"].supersedes == [
        "github:owner/repo:v1.2.0",
        "github:owner/repo:v1.3.0",
    ]


@pytest.mark.parametrize(
    "current_entry",
    [
        release_entry(
            revision=5,
            release_id="github:owner/repo:v1.4.0",
            supersedes=["github:owner/repo:v1.3.0"],
        ),
        release_entry(revision=7, supersedes=[]),
        release_entry(
            revision=6,
            release_id="github:owner/repo:v1.4.0",
            supersedes=["github:owner/repo:v1.3.0"],
        ),
        release_entry(
            revision=6,
            release_id="github:owner/repo:v1.3.0",
            supersedes=["github:owner/repo:v1.2.0"],
            version="1.3.0",
            tag="v1.3.0",
            commit="2" * 40,
        ),
        release_entry(
            revision=7,
            release_id="github:owner/repo:v1.3.0",
            supersedes=[
                "github:owner/repo:v1.2.0",
                "github:owner/repo:v1.3.0",
            ],
        ),
    ],
    ids=(
        "revision-regression",
        "missing-predecessor",
        "same-revision-new-release",
        "same-revision-mutated-commit",
        "higher-revision-same-release",
    ),
)
def test_release_ordering_rejects_regressions_gaps_and_mutations(
    plugin_core_module, current_entry
):
    previous_entry = release_entry(
        revision=6,
        release_id="github:owner/repo:v1.3.0",
        supersedes=["github:owner/repo:v1.2.0"],
        version="1.3.0",
        tag="v1.3.0",
        commit="1" * 40,
        tree_sha256="2" * 64,
    )
    previous = parse_index(
        plugin_core_module,
        release_index_document(sequence=41, entry=previous_entry),
    )

    with pytest.raises(ValueError):
        parse_index(
            plugin_core_module,
            release_index_document(entry=current_entry),
            previous=previous,
        )


@pytest.mark.parametrize(
    "document",
    [
        release_index_document(sequence=41),
        release_index_document(
            generated_at="2026-07-25T08:00:00Z",
            expires_at="2026-07-18T08:00:00Z",
        ),
        release_index_document(expires_at="2026-07-18T11:59:59Z"),
        release_index_document(registry_sha256="f" * 64),
    ],
    ids=(
        "non-increasing-sequence",
        "invalid-validity-window",
        "expired",
        "registry-byte-mismatch",
    ),
)
def test_index_rejects_sequence_freshness_and_registry_binding_failures(
    plugin_core_module, document
):
    previous = None
    if document["sequence"] == 41:
        previous = parse_index(
            plugin_core_module,
            release_index_document(sequence=41),
        )

    with pytest.raises(ValueError):
        parse_index(plugin_core_module, document, previous=previous)


def invalid_documents():
    cases = []

    wrong_schema = release_index_document()
    wrong_schema["schema_version"] = 2
    cases.append(pytest.param(wrong_schema, id="unsupported-schema"))

    unknown_plugin = release_index_document()
    unknown_plugin["plugins"] = {"UnknownPlugin": release_entry()}
    cases.append(pytest.param(unknown_plugin, id="unknown-plugin"))

    wrong_identity = release_index_document()
    wrong_identity["plugins"]["ExamplePlugin"][
        "repository_identity"
    ] = "github.com/other/repo"
    cases.append(pytest.param(wrong_identity, id="repository-mismatch"))

    insecure_url = release_index_document()
    insecure_url["plugins"]["ExamplePlugin"]["artifact"][
        "url"
    ] = "http://github.com/owner/repo/archive/main.zip"
    cases.append(pytest.param(insecure_url, id="non-https-artifact"))

    invalid_digest = release_index_document()
    invalid_digest["plugins"]["ExamplePlugin"]["artifact"]["sha256"] = "A" * 64
    cases.append(pytest.param(invalid_digest, id="invalid-digest"))

    empty_artifact = release_index_document()
    empty_artifact["plugins"]["ExamplePlugin"]["artifact"]["size"] = 0
    cases.append(pytest.param(empty_artifact, id="empty-artifact"))

    mutable_revision = release_index_document()
    mutable_revision["plugins"]["ExamplePlugin"]["commit"] = "main"
    cases.append(pytest.param(mutable_revision, id="mutable-revision"))

    unsafe_source_path = release_index_document()
    unsafe_source_path["plugins"]["ExamplePlugin"]["artifact"][
        "source_path"
    ] = "../plugin"
    cases.append(pytest.param(unsafe_source_path, id="unsafe-source-path"))

    overlapping_tombstone = release_index_document(
        tombstones={
            "ExamplePlugin": release_tombstone(
                repository_identity="github.com/owner/repo",
                release_id="github:owner/repo:v1.3.0",
            )
        }
    )
    cases.append(pytest.param(overlapping_tombstone, id="active-tombstone-overlap"))

    malformed_tombstones = {
        "unknown-plugin": {
            "UnknownPlugin": release_tombstone(),
        },
        "repository-mismatch-tombstone": {
            "RetiredPlugin": {
                **release_tombstone(),
                "repository_identity": "github.com/other/repo",
            },
        },
        "invalid-last-revision": {
            "RetiredPlugin": {
                **release_tombstone(),
                "last_revision": 0,
            },
        },
        "missing-release-identity": {
            "RetiredPlugin": {
                **release_tombstone(),
                "release_id": "",
            },
        },
        "missing-reason": {
            "RetiredPlugin": {
                **release_tombstone(),
                "reason": "",
            },
        },
        "invalid-removal-time": {
            "RetiredPlugin": {
                **release_tombstone(),
                "removed_at": "not-a-timestamp",
            },
        },
    }
    for case_id, tombstones in malformed_tombstones.items():
        cases.append(
            pytest.param(
                release_index_document(tombstones=tombstones),
                id=case_id,
            )
        )

    return cases


@pytest.mark.parametrize("document", invalid_documents())
def test_invalid_release_index_is_rejected(plugin_core_module, document):
    with pytest.raises(ValueError):
        parse_index(plugin_core_module, copy.deepcopy(document))
