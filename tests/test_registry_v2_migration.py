import json

import pytest

from conftest import REPO_ROOT, load_module_from_path


PLUGIN_DIGEST = "a" * 64


@pytest.fixture
def migration_module():
    return load_module_from_path(
        "migrate_registry_v2_under_test",
        REPO_ROOT / ".github" / "scripts" / "migrate_registry_v2.py",
    )


def json_bytes(document):
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def certification(
    legacy_package_id,
    repository_identity,
    domoticz_key,
    branch="main",
):
    return {
        "legacy_package_id": legacy_package_id,
        "repository_identity": repository_identity,
        "branch": branch,
        "domoticz_key": domoticz_key,
        "plugin_py_sha256": PLUGIN_DIGEST,
    }


def certifications(*records):
    return json_bytes(
        {
            "schema_version": 1,
            "certifications": list(records),
        }
    )


def discovery_output(*records, failures=None):
    return json_bytes(
        {
            "schema_version": 1,
            "certifications": list(records),
            "failures": list(failures or []),
        }
    )


def platform_metadata(entries):
    return json_bytes({"version": 1, "entries": entries})


def migrate(module, registry, update_times, platforms, *identity_records):
    return module.migrate_public_data(
        json_bytes(registry),
        json_bytes(update_times),
        platform_metadata(platforms),
        certifications(*identity_records),
    )


def test_migration_converts_public_files_to_sorted_explicit_records(
    migration_module,
):
    registry = {
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "Zulu": ["owner", "zulu-plugin", "Zulu", "main", "", ["linux"]],
        "Alpha": ["gitlab.com/group/subgroup", "alpha", "Alpha", "main"],
    }
    result = migrate(
        migration_module,
        registry,
        {
            "Zulu": "2026-07-21T11:00:00+02:00",
            "Alpha": "2026-07-20T09:00:00.958Z",
        },
        {
            "Zulu": {"source": "reviewed", "reviewed": True},
            "Alpha": {"source": "unknown", "reviewed": False},
        },
        certification("Zulu", "github.com/owner/zulu-plugin", "ZULU"),
        certification("Alpha", "gitlab.com/group/subgroup/alpha", "ALPHA"),
    )

    assert result.ready is True
    registry_v2 = json.loads(result.registry_bytes)
    assert registry_v2["schema_version"] == 2
    assert [item["package_id"] for item in registry_v2["packages"]] == [
        "Alpha",
        "Zulu",
    ]
    assert registry_v2["packages"][0]["domoticz_key"] == "ALPHA"
    assert registry_v2["packages"][0]["repository"] == {
        "url": "https://gitlab.com/group/subgroup/alpha",
        "branch": "main",
    }
    assert registry_v2["packages"][0]["platforms"] == []
    assert registry_v2["packages"][0]["delivery"] == {
        "preferred": "release_if_indexed",
        "git_supported": True,
        "release": {
            "provider": "gitlab",
            "channel": "stable",
            "tag_pattern": r"^v?[0-9]+(?:\.[0-9]+){1,3}$",
            "artifact": "source_zip",
            "source_path": ".",
            "mutable_paths": [],
        },
    }

    updates = json.loads(result.update_times_bytes)
    assert updates == {
        "schema_version": 2,
        "updates": [
            {"package_id": "Alpha", "updated_at": "2026-07-20T09:00:00Z"},
            {"package_id": "Zulu", "updated_at": "2026-07-21T09:00:00Z"},
        ],
    }
    detections = json.loads(result.platform_metadata_bytes)
    assert [item["package_id"] for item in detections["detections"]] == [
        "Alpha",
        "Zulu",
    ]
    assert "Idle" not in result.registry_bytes.decode("utf-8")


def test_migration_normalizes_explicit_codeberg_delivery_policy(
    migration_module,
):
    delivery = {
        "schema_version": 1,
        "preferred": "release_if_indexed",
        "git_supported": True,
        "release": {
            "provider": "forgejo",
            "channel": "stable",
            "tag_pattern": "^v[0-9]+\\.[0-9]+\\.[0-9]+$",
            "artifact": "source_zip",
            "source_path": ".",
            "mutable_paths": ["data"],
        },
    }
    result = migrate(
        migration_module,
        {
            "Stromer": {
                "owner": "codeberg.org/Hoog",
                "repository": "Domoticz-Stromer-plugin",
                "description": "Stromer",
                "branch": "main",
                "platforms": ["linux", "windows"],
                "delivery": delivery,
            }
        },
        {},
        {},
        certification(
            "Stromer",
            "codeberg.org/hoog/domoticz-stromer-plugin",
            "STROMER",
        ),
    )

    migrated_delivery = json.loads(result.registry_bytes)["packages"][0][
        "delivery"
    ]
    expected = dict(delivery)
    expected.pop("schema_version")
    expected["release"] = dict(expected["release"])
    expected["release"]["provider"] = "codeberg"
    assert migrated_delivery == expected


def test_migration_enables_future_release_discovery_on_supported_forges(
    migration_module,
):
    registry = {
        "GitHubPlugin": ["owner", "github-plugin", "GitHub", "main"],
        "GitLabPlugin": [
            "gitlab.com/group/subgroup",
            "gitlab-plugin",
            "GitLab",
            "main",
        ],
        "CodebergPlugin": [
            "codeberg.org/team",
            "codeberg-plugin",
            "Codeberg",
            "main",
        ],
    }
    identities = [
        certification(
            "GitHubPlugin",
            "github.com/owner/github-plugin",
            "GITHUB",
        ),
        certification(
            "GitLabPlugin",
            "gitlab.com/group/subgroup/gitlab-plugin",
            "GITLAB",
        ),
        certification(
            "CodebergPlugin",
            "codeberg.org/team/codeberg-plugin",
            "CODEBERG",
        ),
    ]

    result = migrate(
        migration_module,
        registry,
        {},
        {},
        *identities,
    )
    packages = {
        item["package_id"]: item
        for item in json.loads(result.registry_bytes)["packages"]
    }

    assert {
        package_id: package["delivery"]["release"]["provider"]
        for package_id, package in packages.items()
    } == {
        "CodebergPlugin": "codeberg",
        "GitHubPlugin": "github",
        "GitLabPlugin": "gitlab",
    }
    assert all(
        package["delivery"]["preferred"] == "release_if_indexed"
        and package["delivery"]["git_supported"] is True
        for package in packages.values()
    )


def test_migration_resolves_shelly_casefold_collision_across_all_files(
    migration_module,
):
    registry = {
        "Domoticz-Shelly-Plugin": [
            "lemassykoi",
            "Domoticz-Shelly-Plugin",
            "GitHub Shelly",
            "main",
            "",
            ["linux"],
        ],
        "Domoticz-Shelly-plugin": [
            "codeberg.org/Hoog",
            "Domoticz-Shelly-plugin",
            "Codeberg Shelly",
            "main",
        ],
    }
    result = migrate(
        migration_module,
        registry,
        {
            "Domoticz-Shelly-Plugin": "2026-07-20T13:00:15Z",
            "Domoticz-Shelly-plugin": "2026-07-02T19:18:35+02:00",
        },
        {
            "Domoticz-Shelly-Plugin": {"source": "reviewed"},
            "Domoticz-Shelly-plugin": {"source": "unknown"},
        },
        certification(
            "Domoticz-Shelly-Plugin",
            "github.com/lemassykoi/domoticz-shelly-plugin",
            "SHELLY_GEN2",
        ),
        certification(
            "Domoticz-Shelly-plugin",
            "codeberg.org/hoog/domoticz-shelly-plugin",
            "SHELLY_COMPONENTS",
        ),
    )

    package_ids = [
        item["package_id"] for item in json.loads(result.registry_bytes)["packages"]
    ]
    assert package_ids == ["Domoticz-Shelly-Plugin", "hoog-domoticz-shelly-plugin"]
    assert len({value.casefold() for value in package_ids}) == 2
    assert {
        item["package_id"] for item in json.loads(result.update_times_bytes)["updates"]
    } == set(package_ids)
    report = json.loads(result.report_bytes)
    assert report["renamed_packages"] == [
        {
            "legacy_package_id": "Domoticz-Shelly-plugin",
            "package_id": "hoog-domoticz-shelly-plugin",
        }
    ]


def test_missing_identity_certification_blocks_all_public_outputs(
    migration_module,
):
    result = migrate(
        migration_module,
        {"Example": ["owner", "example", "Example", "main"]},
        {"Example": "2026-07-21T09:00:00Z"},
        {"Example": {"source": "unknown"}},
    )

    assert result.ready is False
    assert result.registry_bytes is None
    assert result.update_times_bytes is None
    assert result.platform_metadata_bytes is None
    assert json.loads(result.report_bytes)["missing_certifications"] == [
        "Example"
    ]


def test_certification_is_bound_to_repository_and_branch(migration_module):
    with pytest.raises(ValueError, match="repository does not match"):
        migrate(
            migration_module,
            {"Example": ["owner", "example", "Example", "main"]},
            {},
            {},
            certification(
                "Example",
                "github.com/other/example",
                "EXAMPLE",
            ),
        )


def test_identity_discovery_output_feeds_migration_without_manual_editing(
    migration_module,
):
    registry = {"Example": ["owner", "example", "Example", "main"]}
    result = migration_module.migrate_public_data(
        json_bytes(registry),
        json_bytes({}),
        platform_metadata({}),
        discovery_output(
            certification(
                "Example",
                "github.com/owner/example",
                "EXAMPLE",
            )
        ),
    )

    assert result.ready is True
    assert json.loads(result.registry_bytes)["packages"][0][
        "domoticz_key"
    ] == "EXAMPLE"


def test_failed_identity_discovery_keeps_public_outputs_blocked(
    migration_module,
):
    registry = {"Example": ["owner", "example", "Example", "main"]}
    result = migration_module.migrate_public_data(
        json_bytes(registry),
        json_bytes({}),
        platform_metadata({}),
        discovery_output(
            failures=[
                {
                    "legacy_package_id": "Example",
                    "reason": "plugin.py did not declare a key",
                }
            ]
        ),
    )

    assert result.ready is False
    assert result.registry_bytes is None
    assert json.loads(result.report_bytes)["missing_certifications"] == [
        "Example"
    ]


def test_migration_outputs_are_deterministic_across_legacy_object_order(
    migration_module,
):
    entries = {
        "Zulu": ["owner", "zulu", "Zulu", "main"],
        "Alpha": ["gitlab.com/group", "alpha", "Alpha", "main"],
    }
    updates = {
        "Zulu": "2026-07-21T11:00:00Z",
        "Alpha": "2026-07-20T09:00:00Z",
    }
    platforms = {
        "Zulu": {"source": "unknown"},
        "Alpha": {"source": "reviewed"},
    }
    identities = certifications(
        certification("Zulu", "github.com/owner/zulu", "ZULU"),
        certification("Alpha", "gitlab.com/group/alpha", "ALPHA"),
    )

    first = migration_module.migrate_public_data(
        json_bytes(entries),
        json_bytes(updates),
        platform_metadata(platforms),
        identities,
    )
    second = migration_module.migrate_public_data(
        json_bytes(dict(reversed(list(entries.items())))),
        json_bytes(dict(reversed(list(updates.items())))),
        platform_metadata(dict(reversed(list(platforms.items())))),
        identities,
    )

    assert first.registry_bytes == second.registry_bytes
    assert first.update_times_bytes == second.update_times_bytes
    assert first.platform_metadata_bytes == second.platform_metadata_bytes
    assert first.report_bytes == second.report_bytes
