import copy
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import REPO_ROOT, load_module_from_path


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "releases"
NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)
TAG_PATTERN = r"^v[0-9]+\.[0-9]+\.[0-9]+$"
EXPECTED_CANDIDATE_FIELDS = {
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


class FixtureTransport:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.requests = []

    def get_json(self, url, **kwargs):
        self.requests.append(url)
        if url not in self.responses:
            raise AssertionError("Unexpected fixture request: " + url)
        return copy.deepcopy(self.responses[url])


@pytest.fixture
def release_providers_module():
    module_path = REPO_ROOT / ".github" / "scripts" / "release_providers.py"
    if not module_path.is_file():
        class MissingReleaseProviders:
            def __getattr__(self, name):
                raise AssertionError(
                    "Missing scanner release-provider contract: " + name
                )

        return MissingReleaseProviders()
    return load_module_from_path(
        "release_providers_under_test",
        module_path,
    )


def load_fixture(name):
    return json.loads(
        (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    )


def stable_policy(artifact="source_zip"):
    policy = {
        "channel": "stable",
        "tag_pattern": TAG_PATTERN,
        "artifact": "asset_zip" if artifact.startswith("asset:") else artifact,
        "source_path": ".",
    }
    if artifact.startswith("asset:"):
        policy["asset_name"] = artifact.split(":", 1)[1]
    return policy


def github_case(module, artifact="source_zip"):
    releases_url = (
        "https://api.github.com/repos/octo/example/releases?per_page=100"
    )
    ref_url = (
        "https://api.github.com/repos/octo/example/git/ref/tags/v1.4.0"
    )
    tag_url = (
        "https://api.github.com/repos/octo/example/git/tags/"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    transport = FixtureTransport(
        {
            releases_url: load_fixture("github_releases.json"),
            ref_url: load_fixture("github_tag_ref.json"),
            tag_url: load_fixture("github_annotated_tag.json"),
        }
    )
    repository = {
        "repository_identity": "github.com/octo/example",
        "owner": "octo",
        "repository": "example",
        "api_base": "https://api.github.com",
        "web_base": "https://github.com",
    }
    expected = {
        "provider": "github",
        "release_id": "github:octo/example:v1.4.0",
        "commit": "1111111111111111111111111111111111111111",
        "source_url": (
            "https://api.github.com/repos/octo/example/zipball/"
            "1111111111111111111111111111111111111111"
        ),
        "asset_url": (
            "https://github.com/octo/example/releases/download/v1.4.0/"
            "domoticz-plugin.zip"
        ),
        "asset_size": 45678,
        "provider_sha256": "a" * 64,
        "requests": [releases_url, ref_url, tag_url],
    }
    return (
        module.GitHubReleaseAdapter(),
        repository,
        stable_policy(artifact),
        transport,
        expected,
    )


def gitlab_case(module, artifact="source_zip"):
    project = "group%2Fsubgroup%2Fexample"
    releases_url = (
        "https://gitlab.com/api/v4/projects/"
        + project
        + "/releases?order_by=released_at&sort=desc&per_page=100"
    )
    tag_url = (
        "https://gitlab.com/api/v4/projects/"
        + project
        + "/repository/tags/v1.4.0"
    )
    transport = FixtureTransport(
        {
            releases_url: load_fixture("gitlab_releases.json"),
            tag_url: load_fixture("gitlab_tag.json"),
        }
    )
    repository = {
        "repository_identity": "gitlab.com/group/subgroup/example",
        "project_path": "group/subgroup/example",
        "api_base": "https://gitlab.com/api/v4",
        "web_base": "https://gitlab.com",
    }
    expected = {
        "provider": "gitlab",
        "release_id": "gitlab:group/subgroup/example:v1.4.0",
        "commit": "2222222222222222222222222222222222222222",
        "source_url": (
            "https://gitlab.com/api/v4/projects/"
            + project
            + "/repository/archive.zip?sha="
            + "2222222222222222222222222222222222222222"
        ),
        "asset_url": (
            "https://gitlab.com/group/subgroup/example/-/releases/v1.4.0/"
            "downloads/domoticz-plugin.zip"
        ),
        "asset_size": None,
        "provider_sha256": "",
        "requests": [releases_url, tag_url],
    }
    return (
        module.GitLabReleaseAdapter(),
        repository,
        stable_policy(artifact),
        transport,
        expected,
    )


def forgejo_case(module, artifact="source_zip"):
    releases_url = (
        "https://codeberg.org/api/v1/repos/team/example/releases?"
        "page=1&limit=50"
    )
    ref_url = (
        "https://codeberg.org/api/v1/repos/team/example/git/refs/"
        "tags%2Fv1.4.0"
    )
    transport = FixtureTransport(
        {
            releases_url: load_fixture("forgejo_releases.json"),
            ref_url: load_fixture("forgejo_tag_ref.json"),
        }
    )
    repository = {
        "repository_identity": "codeberg.org/team/example",
        "owner": "team",
        "repository": "example",
        "api_base": "https://codeberg.org/api/v1",
        "web_base": "https://codeberg.org",
    }
    expected = {
        "provider": "forgejo",
        "release_id": "forgejo:codeberg.org/team/example:v1.4.0",
        "commit": "3333333333333333333333333333333333333333",
        "source_url": (
            "https://codeberg.org/team/example/archive/"
            "3333333333333333333333333333333333333333.zip"
        ),
        "asset_url": (
            "https://codeberg.org/team/example/releases/download/v1.4.0/"
            "domoticz-plugin.zip"
        ),
        "asset_size": 34567,
        "provider_sha256": "",
        "requests": [releases_url, ref_url],
    }
    return (
        module.ForgejoReleaseAdapter(),
        repository,
        stable_policy(artifact),
        transport,
        expected,
    )


def gitea_case(module, artifact="source_zip"):
    releases_url = (
        "https://gitea.example/api/v1/repos/team/example/releases?"
        "page=1&limit=50"
    )
    ref_url = (
        "https://gitea.example/api/v1/repos/team/example/git/refs/"
        "tags%2Fv1.4.0"
    )
    transport = FixtureTransport(
        {
            releases_url: load_fixture("gitea_releases.json"),
            ref_url: load_fixture("gitea_tag_ref.json"),
        }
    )
    repository = {
        "repository_identity": "gitea.example/team/example",
        "owner": "team",
        "repository": "example",
        "api_base": "https://gitea.example/api/v1",
        "web_base": "https://gitea.example",
    }
    expected = {
        "provider": "gitea",
        "release_id": "gitea:gitea.example/team/example:v1.4.0",
        "commit": "4444444444444444444444444444444444444444",
        "source_url": (
            "https://gitea.example/team/example/archive/"
            "4444444444444444444444444444444444444444.zip"
        ),
        "asset_url": (
            "https://gitea.example/team/example/releases/download/v1.4.0/"
            "domoticz-plugin.zip"
        ),
        "asset_size": 23456,
        "provider_sha256": "",
        "requests": [releases_url, ref_url],
    }
    return (
        module.GiteaReleaseAdapter(),
        repository,
        stable_policy(artifact),
        transport,
        expected,
    )


PROVIDER_CASE_BUILDERS = {
    "github": github_case,
    "gitlab": gitlab_case,
    "forgejo": forgejo_case,
    "gitea": gitea_case,
}


def resolve_case(module, provider, artifact="source_zip"):
    adapter, repository, policy, transport, expected = (
        PROVIDER_CASE_BUILDERS[provider](module, artifact=artifact)
    )
    candidate = adapter.resolve(
        repository,
        policy,
        transport,
        now=NOW,
    )
    return candidate, transport, expected


def test_all_forge_adapters_return_the_same_provider_neutral_candidate_shape(
    release_providers_module,
):
    candidates = [
        resolve_case(release_providers_module, provider)[0]
        for provider in PROVIDER_CASE_BUILDERS
    ]

    for candidate in candidates:
        assert candidate.__class__ is release_providers_module.ReleaseCandidate
        assert is_dataclass(candidate)
        assert set(asdict(candidate)) == EXPECTED_CANDIDATE_FIELDS
        assert candidate.repository_identity
        assert candidate.release_id
        assert candidate.source_revision == candidate.commit


@pytest.mark.parametrize("provider", PROVIDER_CASE_BUILDERS)
def test_forge_adapter_filters_stable_release_and_resolves_exact_commit(
    release_providers_module, provider
):
    candidate, transport, expected = resolve_case(
        release_providers_module, provider
    )

    assert candidate.provider == expected["provider"]
    assert candidate.release_id == expected["release_id"]
    assert candidate.version == "1.4.0"
    assert candidate.tag == "v1.4.0"
    assert candidate.released_at == "2026-07-17T09:00:00Z"
    assert candidate.commit == expected["commit"]
    assert candidate.source_revision == expected["commit"]
    assert candidate.artifact_kind == "source_zip"
    assert candidate.artifact_provenance == "forge_source_archive"
    assert candidate.artifact_url == expected["source_url"]
    assert "v1.4.0" not in candidate.artifact_url
    assert candidate.artifact_size is None
    assert candidate.provider_sha256 == ""
    assert candidate.source_path == "."
    assert candidate.migration_eligible is True
    assert transport.requests == expected["requests"]


@pytest.mark.parametrize("provider", PROVIDER_CASE_BUILDERS)
def test_forge_adapter_accepts_sha256_git_object_ids(
    release_providers_module, provider
):
    adapter, repository, policy, transport, expected = (
        PROVIDER_CASE_BUILDERS[provider](release_providers_module)
    )
    sha256_commit = "c" * 64
    if provider == "github":
        ref_response = transport.responses[expected["requests"][1]]
        ref_response["object"] = {
            "type": "commit",
            "sha": sha256_commit,
        }
    elif provider == "gitlab":
        tag_response = transport.responses[expected["requests"][-1]]
        tag_response["target"] = sha256_commit
        tag_response["commit"]["id"] = sha256_commit
    else:
        ref_response = transport.responses[expected["requests"][-1]][0]
        ref_response["object"]["sha"] = sha256_commit

    candidate = adapter.resolve(
        repository,
        policy,
        transport,
        now=NOW,
    )

    assert candidate.commit == sha256_commit
    assert candidate.source_revision == sha256_commit
    assert sha256_commit in candidate.artifact_url


def test_gitlab_nested_project_path_is_encoded_in_every_api_request(
    release_providers_module,
):
    _, transport, _ = resolve_case(release_providers_module, "gitlab")

    assert len(transport.requests) == 2
    assert all(
        "/projects/group%2Fsubgroup%2Fexample/" in request
        for request in transport.requests
    )
    assert all(
        "/projects/group/subgroup/example/" not in request
        for request in transport.requests
    )


def test_forgejo_and_gitea_use_distinct_adapter_classes(
    release_providers_module,
):
    forgejo = release_providers_module.ForgejoReleaseAdapter()
    gitea = release_providers_module.GiteaReleaseAdapter()

    assert type(forgejo) is release_providers_module.ForgejoReleaseAdapter
    assert type(gitea) is release_providers_module.GiteaReleaseAdapter
    assert type(forgejo) is not type(gitea)


@pytest.mark.parametrize("provider", PROVIDER_CASE_BUILDERS)
def test_configured_attached_zip_is_selected_by_exact_name(
    release_providers_module, provider
):
    candidate, _, expected = resolve_case(
        release_providers_module,
        provider,
        artifact="asset:domoticz-plugin.zip",
    )

    assert candidate.artifact_url == expected["asset_url"]
    assert candidate.artifact_kind == "asset_zip"
    assert candidate.artifact_provenance == "attached_asset"
    assert candidate.artifact_size == expected["asset_size"]
    assert candidate.provider_sha256 == expected["provider_sha256"]
    assert candidate.migration_eligible is False
    assert candidate.commit == expected["commit"]


def test_missing_configured_asset_is_rejected(release_providers_module):
    adapter, repository, policy, transport, _ = github_case(
        release_providers_module,
        artifact="asset:not-published.zip",
    )

    with pytest.raises(ValueError):
        adapter.resolve(repository, policy, transport, now=NOW)


def generic_case(module, manifest=None, manifest_url=None):
    manifest_url = manifest_url or (
        "https://downloads.example.test/example/release-manifest.json"
    )
    transport = FixtureTransport(
        {
            manifest_url: (
                load_fixture("generic_manifest.json")
                if manifest is None
                else manifest
            )
        }
    )
    repository = {
        "repository_identity": "downloads.example.test/example",
    }
    policy = {
        "channel": "stable",
        "manifest_url": manifest_url,
    }
    return (
        module.GenericManifestAdapter(),
        repository,
        policy,
        transport,
    )


def test_generic_https_manifest_normalizes_without_forge_api_calls(
    release_providers_module,
):
    adapter, repository, policy, transport = generic_case(
        release_providers_module
    )

    candidate = adapter.resolve(
        repository, policy, transport, now=NOW
    )

    assert candidate.__class__ is release_providers_module.ReleaseCandidate
    assert set(asdict(candidate)) == EXPECTED_CANDIDATE_FIELDS
    assert candidate.provider == "generic"
    assert candidate.repository_identity == "downloads.example.test/example"
    assert (
        candidate.release_id
        == "generic:downloads.example.test/example:v1.4.0"
    )
    assert candidate.version == "1.4.0"
    assert candidate.tag == ""
    assert candidate.released_at == "2026-07-17T09:00:00Z"
    assert candidate.source_revision == "release-2026-07-17-v1.4.0"
    assert candidate.commit == ""
    assert candidate.artifact_kind == "asset_zip"
    assert candidate.artifact_provenance == "generic_manifest"
    assert candidate.artifact_url.endswith("/domoticz-plugin.zip")
    assert candidate.artifact_size == 56789
    assert candidate.provider_sha256 == "b" * 64
    assert candidate.source_path == "plugin"
    assert candidate.migration_eligible is False
    assert transport.requests == [policy["manifest_url"]]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("release_id", ""),
        ("released_at", "not-a-timestamp"),
        ("url", "http://downloads.example.test/plugin.zip"),
        ("sha256", "A" * 64),
        ("size", 0),
        ("source_revision", ""),
    ],
    ids=(
        "schema",
        "release-id",
        "timestamp",
        "artifact-https",
        "digest",
        "size",
        "source-revision",
    ),
)
def test_generic_manifest_rejects_invalid_or_mutable_artifact_metadata(
    release_providers_module, field, value
):
    manifest = load_fixture("generic_manifest.json")
    manifest[field] = value
    adapter, repository, policy, transport = generic_case(
        release_providers_module, manifest=manifest
    )

    with pytest.raises(ValueError):
        adapter.resolve(repository, policy, transport, now=NOW)


def test_generic_manifest_location_must_use_https(release_providers_module):
    insecure_url = "http://downloads.example.test/release-manifest.json"
    adapter, repository, policy, transport = generic_case(
        release_providers_module,
        manifest_url=insecure_url,
    )

    with pytest.raises(ValueError):
        adapter.resolve(repository, policy, transport, now=NOW)

    assert transport.requests == []
