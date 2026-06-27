import json
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


@pytest.fixture
def platform_detector_module():
    return load_module_from_path(
        "detect_plugin_platforms_under_test",
        REPO_ROOT / ".github" / "scripts" / "detect_plugin_platforms.py",
    )


def test_validate_registry_entry_accepts_normal_entry(validate_plugins_module):
    validate_plugins_module.validate_registry_entry("NormalPlugin", VALID_ENTRY)


def test_validate_registry_entry_accepts_platform_metadata(validate_plugins_module):
    validate_plugins_module.validate_registry_entry(
        "PlatformPlugin",
        ["owner", "repo", "description", "main", "", ["linux", "windows"]],
    )


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
        ("Plugin", ["owner", "repo", "description", "main", "", []]),
        ("Plugin", ["owner", "repo", "description", "main", "", ["macos"]]),
        ("Plugin", ["owner", "repo", "description", "main", "", {"platform": "linux"}]),
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
        return SimpleNamespace(returncode=0, stdout="abc123\trefs/heads/main\n", stderr="")

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


def test_validate_repository_requires_matching_branch_output(validate_plugins_module, monkeypatch):
    def fake_run(cmd, env, capture_output, text):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(validate_plugins_module.subprocess, "run", fake_run)

    assert validate_plugins_module.validate_repository("owner", "empty-repo", "main") is False


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


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        ({"archived": True, "size": 10}, "Repo archived"),
        ({"disabled": True, "size": 10}, "Repo disabled"),
        ({"size": 0}, "Repo empty"),
        ({"size": "0"}, "Repo empty"),
        ({"size": 1}, None),
        ({}, None),
    ],
)
def test_scanner_explains_unscannable_repositories(scan_plugins_module, repo, expected):
    assert scan_plugins_module.get_repo_skip_reason(repo) == expected


def test_scanner_blocks_explicit_repositories(scan_plugins_module):
    assert scan_plugins_module.get_repo_block_reason("domoticz", "domoticz") == "Repo blocklisted"
    assert scan_plugins_module.get_repo_block_reason("owner", "repo") is None


def test_platform_detector_flags_linux_only_dependencies(platform_detector_module):
    decision = platform_detector_module.detect_platforms_from_repository_data(
        file_texts={
            "README.md": "Requires Linux on a Raspberry Pi. Install with sudo apt install i2c-tools.",
            "plugin.py": "import RPi.GPIO as GPIO\nDEVICE = '/dev/gpiochip0'\n",
        }
    )

    assert decision.platforms == ["linux"]
    assert decision.linux_score > decision.windows_score


def test_platform_detector_prefers_explicit_linux_only_over_both_mentions(platform_detector_module):
    decision = platform_detector_module.detect_platforms_from_repository_data(
        file_texts={
            "README.md": "Linux only. Windows is not supported.",
        }
    )

    assert decision.platforms == ["linux"]


def test_platform_detector_flags_windows_only_dependencies(platform_detector_module):
    decision = platform_detector_module.detect_platforms_from_repository_data(
        file_texts={
            "README.md": "Windows only plugin. Use COM3 for the serial connection.",
            "plugin.py": "import winreg\n",
        }
    )

    assert decision.platforms == ["windows"]
    assert decision.windows_score > decision.linux_score


def test_platform_detector_defaults_generic_python_plugins_to_both(platform_detector_module):
    decision = platform_detector_module.detect_platforms_from_repository_data(
        file_texts={
            "README.md": "Domoticz plugin using the HTTP API.",
            "plugin.py": "import Domoticz\nimport requests\n",
        }
    )

    assert decision.platforms == ["linux", "windows"]
    assert decision.confidence == "low"


def test_platform_detector_respects_explicit_both_support(platform_detector_module):
    decision = platform_detector_module.detect_platforms_from_repository_data(
        file_texts={
            "README.md": "Supported on Linux and Windows Domoticz installations.",
        }
    )

    assert decision.platforms == ["linux", "windows"]
    assert decision.confidence == "high"


def test_platform_detector_writes_platforms_in_sixth_registry_slot(platform_detector_module):
    assert platform_detector_module.set_registry_entry_platforms(
        ["owner", "repo", "description", "main"],
        ["windows"],
    ) == ["owner", "repo", "description", "main", "", ["windows"]]

    assert platform_detector_module.set_registry_entry_platforms(
        ["owner", "repo", "description", "main", "2026-06-14T15:10:03Z"],
        ["linux"],
    ) == ["owner", "repo", "description", "main", "2026-06-14T15:10:03Z", ["linux"]]


def test_scanner_updates_existing_registry_platforms(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "Plugin": ["owner", "repo", "description", "main"],
    }))
    update_times_file.write_text(json.dumps({
        "Plugin": "2026-06-14T15:10:03Z",
    }))

    repo_info = {
        "archived": False,
        "disabled": False,
        "size": 100,
        "full_name": "owner/repo",
        "owner": {"login": "owner"},
        "name": "repo",
        "description": "description",
        "default_branch": "main",
        "pushed_at": "2026-06-14T15:10:03Z",
    }

    monkeypatch.setattr(scan_plugins_module, "REGISTRY_FILE", str(registry_file))
    monkeypatch.setattr(scan_plugins_module, "UPDATE_TIMES_FILE", str(update_times_file))
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", lambda owner, repo: repo_info)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [])
    monkeypatch.setattr(
        scan_plugins_module,
        "detect_platforms_for_repo",
        lambda owner, repo, branch, repo_info=None: SimpleNamespace(platforms=["linux"]),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())

    assert registry["Plugin"] == ["owner", "repo", "description", "main", "", ["linux"]]


def test_scanner_adds_platforms_for_new_plugins(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
    }))
    update_times_file.write_text(json.dumps({}))

    repo_info = {
        "archived": False,
        "disabled": False,
        "size": 100,
        "full_name": "owner/repo",
        "owner": {"login": "owner"},
        "name": "repo",
        "description": "description",
        "default_branch": "main",
        "pushed_at": "2026-06-14T15:10:03Z",
    }

    monkeypatch.setattr(scan_plugins_module, "REGISTRY_FILE", str(registry_file))
    monkeypatch.setattr(scan_plugins_module, "UPDATE_TIMES_FILE", str(update_times_file))
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [repo_info])
    monkeypatch.setattr(
        scan_plugins_module,
        "detect_platforms_for_repo",
        lambda owner, repo, branch, repo_info=None: SimpleNamespace(platforms=["windows"]),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())

    assert registry["repo"] == ["owner", "repo", "description", "main", "", ["windows"]]


def test_scanner_removes_empty_existing_repo_and_does_not_readd(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "Domoticz_integration": [
            "cipesokram",
            "Domoticz_integration",
            "Arduino to domoticz integration",
            "master",
        ],
    }))
    update_times_file.write_text(json.dumps({
        "Domoticz_integration": "2018-03-02T13:38:59Z",
    }))

    empty_repo = {
        "archived": False,
        "disabled": False,
        "size": 0,
        "full_name": "cipesokram/Domoticz_integration",
        "owner": {"login": "cipesokram"},
        "name": "Domoticz_integration",
        "description": "Arduino to domoticz integration",
        "default_branch": "master",
        "pushed_at": "2018-03-02T13:38:59Z",
    }

    monkeypatch.setattr(scan_plugins_module, "REGISTRY_FILE", str(registry_file))
    monkeypatch.setattr(scan_plugins_module, "UPDATE_TIMES_FILE", str(update_times_file))
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", lambda owner, repo: empty_repo)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [empty_repo])
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    update_times = json.loads(update_times_file.read_text())

    assert "Domoticz_integration" not in registry
    assert "Domoticz_integration" not in update_times


def test_scanner_removes_blocklisted_existing_repo_and_does_not_readd(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "domoticz": [
            "domoticz",
            "domoticz",
            "Free open source home automation system",
            "development",
        ],
    }))
    update_times_file.write_text(json.dumps({
        "domoticz": "2026-06-13T09:52:48Z",
    }))

    domoticz_repo = {
        "archived": False,
        "disabled": False,
        "size": 100,
        "full_name": "domoticz/domoticz",
        "owner": {"login": "domoticz"},
        "name": "domoticz",
        "description": "Free open source home automation system",
        "default_branch": "development",
        "pushed_at": "2026-06-13T09:52:48Z",
    }

    def fail_get_repo_info(owner, repo):
        raise AssertionError("blocklisted repositories should not be fetched")

    monkeypatch.setattr(scan_plugins_module, "REGISTRY_FILE", str(registry_file))
    monkeypatch.setattr(scan_plugins_module, "UPDATE_TIMES_FILE", str(update_times_file))
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", fail_get_repo_info)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [domoticz_repo])
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    update_times = json.loads(update_times_file.read_text())

    assert "domoticz" not in registry
    assert "domoticz" not in update_times
