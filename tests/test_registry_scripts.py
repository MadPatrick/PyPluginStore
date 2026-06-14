from types import SimpleNamespace

import pytest

from conftest import REPO_ROOT, load_module_from_path


VALID_ENTRY = ["owner", "repo", "description", "main"]


@pytest.fixture
def validate_plugins_module():
    return load_module_from_path(
        "validate_plugins_under_test",
        REPO_ROOT / ".github" / "scripts" / "validate_plugins.py",
    )


@pytest.fixture
def scan_plugins_module():
    return load_module_from_path(
        "scan_github_plugins_under_test",
        REPO_ROOT / ".github" / "scripts" / "scan_github_plugins.py",
    )


def test_validate_registry_entry_accepts_normal_entry(validate_plugins_module):
    validate_plugins_module.validate_registry_entry("NormalPlugin", VALID_ENTRY)


@pytest.mark.parametrize(
    ("key", "entry"),
    [
        ("", VALID_ENTRY),
        (".github", VALID_ENTRY),
        ("nested/plugin", VALID_ENTRY),
        ("nested\\plugin", VALID_ENTRY),
        ("Plugin", ["owner", ".github", "description", "main"]),
        ("Plugin", ["owner", "nested/repo", "description", "main"]),
        ("Plugin", ["owner", "repo", "", "main"]),
        ("Plugin", ["owner", "repo", "description"]),
        ("Plugin", {"owner": "owner", "repo": "repo"}),
    ],
)
def test_validate_registry_entry_rejects_invalid_entry(validate_plugins_module, key, entry):
    with pytest.raises(ValueError):
        validate_plugins_module.validate_registry_entry(key, entry)


def test_validate_repository_uses_argument_list_and_disables_prompts(validate_plugins_module, monkeypatch):
    calls = []

    def fake_run(cmd, env, capture_output, text):
        calls.append({
            "cmd": cmd,
            "env": env,
            "capture_output": capture_output,
            "text": text,
        })
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(validate_plugins_module.subprocess, "run", fake_run)

    assert validate_plugins_module.validate_repository("owner", "repo", "main") is True
    assert calls[0]["cmd"] == [
        "git",
        "ls-remote",
        "--heads",
        "https://github.com/owner/repo",
        "main",
    ]
    assert calls[0]["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert calls[0]["capture_output"] is True
    assert calls[0]["text"] is True


@pytest.mark.parametrize(
    ("repo_name", "expected"),
    [
        ("domoticz-plugin", True),
        ("", False),
        (None, False),
        (".github", False),
        ("nested/repo", False),
        ("nested\\repo", False),
    ],
)
def test_scanner_validates_plugin_repository_names(scan_plugins_module, repo_name, expected):
    assert scan_plugins_module.is_valid_plugin_repo(repo_name) is expected
