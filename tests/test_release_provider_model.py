from abc import ABC
from dataclasses import FrozenInstanceError, asdict, is_dataclass
from datetime import datetime, timezone

import pytest

from conftest import REPO_ROOT, load_module_from_path


EXPECTED_FIELDS = {
    "provider",
    "repository_identity",
    "release_id",
    "version",
    "tag",
    "released_at",
    "source_revision",
    "commit",
    "artifact_kind",
    "artifact_provenance",
    "artifact_url",
    "artifact_size",
    "provider_sha256",
    "source_path",
    "migration_eligible",
}


@pytest.fixture
def providers_module():
    return load_module_from_path(
        "release_provider_model_under_test",
        REPO_ROOT / ".github" / "scripts" / "release_providers.py",
    )


def candidate_values(**overrides):
    values = {
        "provider": "gitlab",
        "repository_identity": "gitlab.com/group/example",
        "release_id": "gitlab:group/example:v1.4.0",
        "version": "1.4.0",
        "tag": "v1.4.0",
        "released_at": "2026-07-17T09:00:00Z",
        "source_revision": "1" * 40,
        "commit": "1" * 40,
        "artifact_kind": "source_zip",
        "artifact_provenance": "forge_source_archive",
        "artifact_url": (
            "https://gitlab.com/api/v4/projects/group%2Fexample/"
            "repository/archive.zip?sha=" + "1" * 40
        ),
        "artifact_size": None,
        "provider_sha256": "",
        "source_path": ".",
        "migration_eligible": True,
    }
    values.update(overrides)
    return values


def test_release_candidate_is_immutable_and_provider_neutral(providers_module):
    candidate = providers_module.ReleaseCandidate(**candidate_values())

    assert is_dataclass(candidate)
    assert set(asdict(candidate)) == EXPECTED_FIELDS
    with pytest.raises(FrozenInstanceError):
        candidate.version = "2.0.0"


def test_release_candidate_allows_generic_non_git_revision(providers_module):
    candidate = providers_module.ReleaseCandidate(
        **candidate_values(
            provider="generic",
            repository_identity="downloads.example.test/example",
            release_id="generic:downloads.example.test/example:v1.4.0",
            tag="",
            source_revision="release-2026-07-17-v1.4.0",
            commit="",
            artifact_kind="asset_zip",
            artifact_provenance="generic_manifest",
            artifact_url="https://downloads.example.test/example/plugin.zip",
            artifact_size=1234,
            provider_sha256="a" * 64,
            source_path="plugin",
            migration_eligible=False,
        )
    )

    assert candidate.commit == ""
    assert candidate.tag == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository_identity", "https://gitlab.com/group/example"),
        ("released_at", "2026-07-17"),
        ("commit", "1" * 39),
        ("artifact_url", "http://downloads.example.test/plugin.zip"),
        ("artifact_size", 0),
        ("artifact_size", True),
        ("provider_sha256", "A" * 64),
        ("source_path", "../plugin"),
        ("migration_eligible", "yes"),
    ],
)
def test_release_candidate_rejects_invalid_fields(
    providers_module, field, value
):
    values = candidate_values(**{field: value})
    if field == "commit":
        values["source_revision"] = value

    with pytest.raises(ValueError):
        providers_module.ReleaseCandidate(**values)


def test_migration_eligibility_requires_full_commit(providers_module):
    with pytest.raises(ValueError):
        providers_module.ReleaseCandidate(
            **candidate_values(
                provider="generic",
                tag="",
                source_revision="immutable-release-1",
                commit="",
            )
        )


def test_release_provider_adapter_defines_abstract_resolve_contract(
    providers_module,
):
    assert issubclass(providers_module.ReleaseProviderAdapter, ABC)

    class MissingResolve(providers_module.ReleaseProviderAdapter):
        pass

    with pytest.raises(TypeError):
        MissingResolve()


def test_stable_release_selection_full_matches_and_sorts_timestamps(
    providers_module,
):
    releases = [
        {
            "tag_name": "v1.3.0",
            "published_at": "2026-07-16T09:00:00Z",
            "draft": False,
            "prerelease": False,
        },
        {
            "tag_name": "v1.5.0-rc.1",
            "published_at": "2026-07-18T09:00:00Z",
            "draft": False,
            "prerelease": False,
        },
        {
            "tag_name": "v2.0.0",
            "published_at": "2026-07-18T10:00:00Z",
            "draft": True,
            "prerelease": False,
        },
        {
            "tag_name": "v1.4.0",
            "published_at": "2026-07-17T09:00:00Z",
            "draft": False,
            "prerelease": False,
        },
    ]

    selected = providers_module.select_latest_stable_release(
        releases,
        r"^v[0-9]+\.[0-9]+\.[0-9]+$",
        now=datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert selected["tag_name"] == "v1.4.0"
    assert not providers_module.tag_matches_pattern(
        "prefix-v1.4.0", r"v[0-9]+\.[0-9]+\.[0-9]+"
    )


def test_exact_asset_selection_rejects_missing_or_duplicate_names(
    providers_module,
):
    assets = [
        {"name": "checksums.txt"},
        {"name": "domoticz-plugin.zip", "size": 1234},
    ]

    selected = providers_module.select_exact_asset(
        assets, "domoticz-plugin.zip"
    )
    assert selected["size"] == 1234

    with pytest.raises(ValueError):
        providers_module.select_exact_asset(assets, "plugin.zip")
    with pytest.raises(ValueError):
        providers_module.select_exact_asset(
            assets + [{"name": "domoticz-plugin.zip"}],
            "domoticz-plugin.zip",
        )


def test_asset_pattern_is_full_match_and_must_select_exactly_one(
    providers_module,
):
    assets = [
        {"name": "plugin-v1.4.0.zip"},
        {"name": "plugin-v1.4.0.zip.sha256"},
    ]

    selected = providers_module.select_asset(
        assets,
        asset_pattern=r"plugin-v[0-9]+\.[0-9]+\.[0-9]+\.zip",
    )

    assert selected["name"] == "plugin-v1.4.0.zip"
    with pytest.raises(ValueError):
        providers_module.select_asset(assets, asset_pattern=r"plugin-.*")
    with pytest.raises(ValueError):
        providers_module.select_asset(
            assets,
            asset_name="plugin-v1.4.0.zip",
            asset_pattern=r".*\.zip",
        )
