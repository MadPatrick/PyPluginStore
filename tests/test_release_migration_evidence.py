import copy

import pytest


def artifact_document(*, mode="automatic", evidence="commit_source_archive"):
    return {
        "kind": "source_zip",
        "provenance": "forge_source_archive",
        "migration": {
            "mode": mode,
            "evidence": evidence,
        },
        "url": "https://github.com/owner/plugin/archive/" + "1" * 40 + ".zip",
        "sha256": "2" * 64,
        "size": 123,
        "tree_sha256": "3" * 64,
        "root_prefix": "plugin-" + "1" * 40,
        "source_path": ".",
    }


def test_v2_artifact_requires_explicit_migration_evidence(plugin_core_module):
    document = artifact_document()

    artifact = plugin_core_module.ReleaseArtifact.from_document(document)

    assert artifact.migration_mode == "automatic"
    assert artifact.migration_evidence == "commit_source_archive"
    assert artifact.migration == {
        "mode": "automatic",
        "evidence": "commit_source_archive",
    }
    assert artifact.migration_eligible is True

    legacy = copy.deepcopy(document)
    legacy["migration_eligible"] = True
    legacy.pop("migration")
    with pytest.raises(ValueError):
        plugin_core_module.ReleaseArtifact.from_document(legacy)

    mixed = copy.deepcopy(document)
    mixed["migration_eligible"] = True
    with pytest.raises(ValueError):
        plugin_core_module.ReleaseArtifact.from_document(mixed)


@pytest.mark.parametrize(
    ("mode", "evidence", "valid"),
    [
        ("automatic", "commit_source_archive", True),
        ("automatic", "source_equivalent_asset", True),
        ("automatic", "generic_manifest", False),
        ("manual", "generic_manifest", True),
        ("manual", "unverified_asset", True),
        ("manual", "commit_source_archive", False),
        ("blocked", "unverified_asset", True),
        ("blocked", "commit_source_archive", True),
    ],
)
def test_v2_artifact_validates_migration_mode_and_evidence(
    plugin_core_module,
    mode,
    evidence,
    valid,
):
    document = artifact_document(mode=mode, evidence=evidence)
    if evidence == "source_equivalent_asset":
        document["kind"] = "asset_zip"
        document["provenance"] = "release_asset"
        document["root_prefix"] = "."
    elif evidence != "commit_source_archive":
        document["kind"] = "asset_zip"
        document["provenance"] = "generic_manifest"
        document["root_prefix"] = "."

    if valid:
        artifact = plugin_core_module.ReleaseArtifact.from_document(document)
        assert artifact.migration_mode == mode
        assert artifact.migration_evidence == evidence
    else:
        with pytest.raises(ValueError):
            plugin_core_module.ReleaseArtifact.from_document(document)


@pytest.mark.parametrize(
    ("eligible", "provenance", "expected_mode", "expected_evidence"),
    [
        (True, "forge_source_archive", "automatic", "commit_source_archive"),
        (False, "generic_manifest", "manual", "generic_manifest"),
        (False, "release_asset", "manual", "unverified_asset"),
    ],
)
def test_legacy_artifact_adapter_maps_boolean_to_explicit_evidence(
    plugin_core_module,
    eligible,
    provenance,
    expected_mode,
    expected_evidence,
):
    document = artifact_document()
    document.pop("migration")
    document["migration_eligible"] = eligible
    document["provenance"] = provenance
    if provenance != "forge_source_archive":
        document["kind"] = "asset_zip"
        document["root_prefix"] = "."

    artifact = plugin_core_module.ReleaseArtifact.from_legacy_document(document)

    assert artifact.migration_mode == expected_mode
    assert artifact.migration_evidence == expected_evidence

