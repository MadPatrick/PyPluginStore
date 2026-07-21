import json

import pytest

from conftest import REPO_ROOT, load_module_from_path


def repository(url="https://github.com/Owner/Example-Plugin", branch="main"):
    return {
        "url": url,
        "branch": branch,
    }


def package(package_id="ExamplePlugin", **overrides):
    document = {
        "package_id": package_id,
        "domoticz_key": "EXAMPLE",
        "description": "Example Domoticz plugin",
        "repository": repository(),
        "platforms": ["linux", "windows"],
        "delivery": {
            "preferred": "git",
            "git_supported": True,
        },
    }
    document.update(overrides)
    return document


def registry_bytes(packages, **overrides):
    document = {
        "schema_version": 2,
        "packages": packages,
    }
    document.update(overrides)
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


@pytest.fixture
def registry_records_module():
    return load_module_from_path(
        "registry_records_v2_under_test",
        REPO_ROOT / ".github" / "scripts" / "registry_records.py",
    )


def parse_registry(module, packages):
    return module.RegistryDocument.from_bytes(registry_bytes(packages))


def test_v2_registry_parses_explicit_package_identity(registry_records_module):
    document = parse_registry(
        registry_records_module,
        [package("Domoticz-SMA-Inverter", domoticz_key="SMA")],
    )

    assert document.schema_version == 2
    assert [record.package_id for record in document.packages] == [
        "Domoticz-SMA-Inverter"
    ]
    assert document.by_package_id["Domoticz-SMA-Inverter"].domoticz_key == "SMA"


def test_v2_registry_serialization_is_deterministic_and_sorted_by_package_id(
    registry_records_module,
):
    first = registry_records_module.RegistryDocument.from_bytes(
        registry_bytes(
            [
                package(
                    "z-plugin",
                    domoticz_key="Z",
                    repository=repository(
                        "https://github.com/Owner/z-plugin"
                    ),
                ),
                package(
                    "A-plugin",
                    domoticz_key="A",
                    repository=repository(
                        "https://github.com/Owner/A-plugin"
                    ),
                ),
                package(
                    "middle-plugin",
                    domoticz_key="M",
                    repository=repository(
                        "https://github.com/Owner/middle-plugin"
                    ),
                ),
            ]
        )
    )
    second = registry_records_module.RegistryDocument.from_bytes(
        registry_bytes(
            [
                package(
                    "middle-plugin",
                    domoticz_key="M",
                    repository=repository(
                        "https://github.com/Owner/middle-plugin"
                    ),
                ),
                package(
                    "z-plugin",
                    domoticz_key="Z",
                    repository=repository(
                        "https://github.com/Owner/z-plugin"
                    ),
                ),
                package(
                    "A-plugin",
                    domoticz_key="A",
                    repository=repository(
                        "https://github.com/Owner/A-plugin"
                    ),
                ),
            ]
        )
    )

    first_bytes = first.to_bytes()
    second_bytes = second.to_bytes()

    assert first_bytes == second_bytes
    assert first_bytes.endswith(b"\n")
    assert [
        item["package_id"]
        for item in json.loads(first_bytes.decode("utf-8"))["packages"]
    ] == ["A-plugin", "middle-plugin", "z-plugin"]
    assert registry_records_module.RegistryDocument.from_bytes(
        first_bytes
    ).to_bytes() == first_bytes


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            {
                "ExamplePlugin": {
                    "owner": "owner",
                    "repository": "example-plugin",
                    "description": "Legacy keyed entry",
                    "branch": "main",
                }
            },
            id="legacy-top-level-package-key",
        ),
        pytest.param(
            {
                "schema_version": 2,
                "packages": {"ExamplePlugin": package()},
            },
            id="keyed-package-collection",
        ),
        pytest.param(
            {
                "schema_version": 2,
                "packages": [
                    ["owner", "example-plugin", "Description", "main"]
                ],
            },
            id="positional-package-entry",
        ),
        pytest.param(
            {
                "schema_version": 2,
                "packages": [package("Idle", domoticz_key="Idle")],
            },
            id="idle-sentinel",
        ),
    ],
)
def test_v2_registry_rejects_legacy_identity_shapes(
    registry_records_module,
    document,
):
    contents = (json.dumps(document) + "\n").encode("utf-8")

    with pytest.raises(ValueError):
        registry_records_module.RegistryDocument.from_bytes(contents)


@pytest.mark.parametrize(
    "contents",
    [
        pytest.param(
            b'{"schema_version":2,"schema_version":2,"packages":[]}\n',
            id="duplicate-json-key",
        ),
        pytest.param(
            registry_bytes([], unexpected=True),
            id="unknown-top-level-field",
        ),
        pytest.param(
            (json.dumps({"schema_version": 2}) + "\n").encode("utf-8"),
            id="missing-packages",
        ),
        pytest.param(
            (json.dumps({"schema_version": 1, "packages": []}) + "\n").encode(
                "utf-8"
            ),
            id="unsupported-schema",
        ),
        pytest.param(
            registry_bytes([package(unexpected=True)]),
            id="unknown-package-field",
        ),
        pytest.param(
            registry_bytes(
                [package(repository={**repository(), "owner": "legacy-owner"})]
            ),
            id="unknown-repository-field",
        ),
    ],
)
def test_v2_registry_parsing_is_strict(registry_records_module, contents):
    with pytest.raises(ValueError):
        registry_records_module.RegistryDocument.from_bytes(contents)


@pytest.mark.parametrize(
    "package_ids",
    [
        pytest.param(["ExamplePlugin", "ExamplePlugin"], id="exact-duplicate"),
        pytest.param(
            ["Domoticz-Shelly-Plugin", "Domoticz-Shelly-plugin"],
            id="case-folded-duplicate",
        ),
    ],
)
def test_v2_registry_rejects_duplicate_portable_package_ids(
    registry_records_module,
    package_ids,
):
    packages = [
        package(package_id, domoticz_key="KEY" + str(index))
        for index, package_id in enumerate(package_ids)
    ]

    with pytest.raises(ValueError, match="(?i)package.*id"):
        parse_registry(registry_records_module, packages)


@pytest.mark.parametrize(
    ("url", "identity", "clone_url"),
    [
        pytest.param(
            "https://github.com/Owner/Example-Plugin",
            "github.com/owner/example-plugin",
            "https://github.com/Owner/Example-Plugin.git",
            id="github",
        ),
        pytest.param(
            "https://gitlab.com/Group/Subgroup/Example-Plugin",
            "gitlab.com/group/subgroup/example-plugin",
            "https://gitlab.com/Group/Subgroup/Example-Plugin.git",
            id="gitlab-nested-group",
        ),
        pytest.param(
            "https://codeberg.org/Team/Example-Plugin",
            "codeberg.org/team/example-plugin",
            "https://codeberg.org/Team/Example-Plugin.git",
            id="codeberg-forgejo",
        ),
        pytest.param(
            "https://forge.example.test/Team/Example-Plugin",
            "forge.example.test/team/example-plugin",
            "https://forge.example.test/Team/Example-Plugin.git",
            id="custom-forge",
        ),
    ],
)
def test_v2_repository_url_is_provider_neutral(
    registry_records_module,
    url,
    identity,
    clone_url,
):
    document = parse_registry(
        registry_records_module,
        [package(repository=repository(url))],
    )
    record = document.packages[0]

    assert record.repository_url == url
    assert record.repository_identity == identity
    assert record.clone_url == clone_url


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/example-plugin",
        "https://user:secret@github.com/owner/example-plugin",
        "https://github.com/owner/example-plugin?ref=main",
        "https://github.com/owner/example-plugin#readme",
        "https://github.com/example-plugin",
        "https://github.com/owner/example-plugin.git",
    ],
)
def test_v2_repository_url_requires_a_canonical_public_https_web_url(
    registry_records_module,
    url,
):
    with pytest.raises(ValueError, match="(?i)repository.*url"):
        parse_registry(
            registry_records_module,
            [package(repository=repository(url))],
        )
