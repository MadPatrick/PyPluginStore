import hashlib
import json

import pytest

from conftest import REPO_ROOT, load_module_from_path


package_identity_module = load_module_from_path(
    "package_identity_under_test",
    REPO_ROOT / "package_identity.py",
)
certify_plugin_py = package_identity_module.certify_plugin_py


def test_certifier_extracts_exact_domoticz_key_and_digest_without_execution():
    contents = b'''"""<plugin key="SMA" name="SMA Inverter"></plugin>"""\nraise RuntimeError("must not execute")\n'''

    identity = certify_plugin_py(contents)

    assert identity.domoticz_key == "SMA"
    assert identity.plugin_py_sha256 == hashlib.sha256(contents).hexdigest()


@pytest.mark.parametrize(
    "contents",
    [
        b"print('no metadata')\n",
        b'''"""<plugin name="Missing key"></plugin>"""\n''',
        b'''"""<plugin key="One"></plugin><plugin key="Two"></plugin>"""\n''',
        b'''"""<plugin key="One" key="Two"></plugin>"""\n''',
        b'''"""<plugin key=" ../unsafe "></plugin>"""\n''',
    ],
)
def test_certifier_rejects_ambiguous_or_invalid_identity(contents):
    with pytest.raises(ValueError):
        certify_plugin_py(contents)


class Response:
    status = 200

    def __init__(self, contents):
        self.contents = contents

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self.contents


def test_discovery_is_provider_neutral_and_binds_repository_branch_and_digest():
    module = load_module_from_path(
        "certify_package_identities_under_test",
        REPO_ROOT / ".github" / "scripts" / "certify_package_identities.py",
    )
    registry = {
        "GitHub": ["owner", "github-plugin", "GitHub", "main"],
        "GitLab": ["gitlab.com/group/subgroup", "gitlab-plugin", "GitLab", "stable"],
        "Codeberg": ["codeberg.org/team", "codeberg-plugin", "Codeberg", "main"],
    }
    requested_urls = []

    def opener(request, timeout):
        assert timeout == 20
        requested_urls.append(request.full_url)
        key = {
            "raw.githubusercontent.com": "GITHUB",
            "gitlab.com": "GITLAB",
            "codeberg.org": "CODEBERG",
        }[request.host]
        return Response(
            ('"""<plugin key="' + key + '" name="Example"></plugin>"""\n').encode()
        )

    result = module.discover_identities(
        (json.dumps(registry) + "\n").encode(),
        opener=opener,
        workers=3,
    )

    assert result["failures"] == []
    assert [item["legacy_package_id"] for item in result["certifications"]] == [
        "Codeberg",
        "GitHub",
        "GitLab",
    ]
    assert {
        item["repository_identity"] for item in result["certifications"]
    } == {
        "codeberg.org/team/codeberg-plugin",
        "github.com/owner/github-plugin",
        "gitlab.com/group/subgroup/gitlab-plugin",
    }
    assert any("/-/raw/stable/plugin.py" in url for url in requested_urls)
    assert any("/raw/branch/main/plugin.py" in url for url in requested_urls)


def test_discovery_reports_failures_without_guessing_a_key():
    module = load_module_from_path(
        "certify_package_identities_failure_under_test",
        REPO_ROOT / ".github" / "scripts" / "certify_package_identities.py",
    )

    result = module.discover_identities(
        json.dumps({"Example": ["owner", "repo", "Example", "main"]}).encode(),
        opener=lambda *_args, **_kwargs: Response(b"print('no tag')\n"),
        workers=1,
    )

    assert result["certifications"] == []
    assert result["failures"][0]["legacy_package_id"] == "Example"
