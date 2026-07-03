import json
import urllib.error
from types import SimpleNamespace

import pytest

from conftest import REPO_ROOT, load_module_from_path


VALID_ENTRY = ["owner", "repo", "description", "main"]


def patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file):
    monkeypatch.setattr(scan_plugins_module, "REGISTRY_FILE", str(registry_file))
    monkeypatch.setattr(scan_plugins_module, "UPDATE_TIMES_FILE", str(update_times_file))
    monkeypatch.setattr(scan_plugins_module, "PLATFORM_METADATA_FILE", str(metadata_file))


def platform_decision(platforms, confidence="medium", evidence_class="test"):
    return SimpleNamespace(
        platforms=platforms,
        confidence=confidence,
        evidence_class=evidence_class,
        linux_score=0,
        windows_score=0,
        both_score=0,
        reasons=[],
    )


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
def cleanup_registry_module():
    return load_module_from_path(
        "cleanup_registry_under_test",
        REPO_ROOT / ".github" / "scripts" / "cleanup_registry.py",
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


def test_validate_platform_metadata_accepts_matching_sidecar(validate_plugins_module, tmp_path, monkeypatch):
    metadata_file = tmp_path / "platform_detection.json"
    metadata_file.write_text(json.dumps({
        "version": 1,
        "entries": {
            "PlatformPlugin": {
                "identity": "github.com/owner/repo@main",
                "owner": "owner",
                "repository": "repo",
                "branch": "main",
                "registry_platforms": ["linux", "windows"],
                "source": "legacy_detected",
                "confidence": "unknown",
                "evidence_class": "legacy",
                "reviewed": False,
            },
        },
    }))
    monkeypatch.setattr(validate_plugins_module, "PLATFORM_METADATA_FILE_PATH", str(metadata_file))

    validate_plugins_module.validate_platform_metadata({
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "PlatformPlugin": ["owner", "repo", "description", "main", "", ["linux", "windows"]],
    })


def test_validate_platform_metadata_rejects_stale_or_mismatched_sidecar(validate_plugins_module, tmp_path, monkeypatch):
    metadata_file = tmp_path / "platform_detection.json"
    metadata_file.write_text(json.dumps({
        "version": 1,
        "entries": {
            "PlatformPlugin": {
                "registry_platforms": ["windows"],
                "source": "legacy_detected",
                "confidence": "unknown",
                "reviewed": False,
            },
            "MissingPlugin": {
                "registry_platforms": [],
                "source": "unknown",
                "confidence": "unknown",
                "reviewed": False,
            },
        },
    }))
    monkeypatch.setattr(validate_plugins_module, "PLATFORM_METADATA_FILE_PATH", str(metadata_file))

    with pytest.raises(ValueError):
        validate_plugins_module.validate_platform_metadata({
            "PlatformPlugin": ["owner", "repo", "description", "main", "", ["linux", "windows"]],
        })


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


def test_validate_repository_uses_supported_host_urls(validate_plugins_module, monkeypatch):
    calls = []

    def fake_run(cmd, env, capture_output, text):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="abc123\trefs/heads/main\n", stderr="")

    monkeypatch.setattr(validate_plugins_module.subprocess, "run", fake_run)

    assert validate_plugins_module.validate_repository(
        "codeberg.org/Hoog",
        "Domoticz-Stromer-plugin",
        "main",
    ) is True
    assert validate_plugins_module.validate_repository(
        "gitlab.com/r.boeters",
        "DomoticzSabNZBDPlugin",
        "master",
    ) is True
    assert calls == [
        [
            "git",
            "ls-remote",
            "--heads",
            "https://codeberg.org/Hoog/Domoticz-Stromer-plugin",
            "main",
        ],
        [
            "git",
            "ls-remote",
            "--heads",
            "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin",
            "master",
        ],
    ]


def test_validate_repository_requires_matching_branch_output(validate_plugins_module, monkeypatch):
    def fake_run(cmd, env, capture_output, text):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(validate_plugins_module.subprocess, "run", fake_run)

    assert validate_plugins_module.validate_repository("owner", "empty-repo", "main") is False


def test_validate_root_plugin_py_accepts_present_file_on_supported_hosts(validate_plugins_module):
    fetched_urls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size=-1):
            return b"import Domoticz\n"

    def fake_urlopen(request, timeout=0):
        fetched_urls.append(request.full_url)
        return FakeResponse()

    assert validate_plugins_module.validate_root_plugin_py(
        "Domoticz-Stromer-plugin",
        "codeberg.org/Hoog",
        "Domoticz-Stromer-plugin",
        "main",
        opener=fake_urlopen,
    ) is True

    assert fetched_urls == [
        "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/raw/branch/main/plugin.py",
    ]


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (b"", None),
        (None, urllib.error.HTTPError("https://example.invalid/plugin.py", 404, "Not Found", {}, None)),
    ],
)
def test_validate_root_plugin_py_rejects_missing_or_empty_file(validate_plugins_module, content, error):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size=-1):
            return content

    def fake_urlopen(request, timeout=0):
        if error is not None:
            raise error
        return FakeResponse()

    assert validate_plugins_module.validate_root_plugin_py(
        "BrokenPlugin",
        "owner",
        "repo",
        "main",
        opener=fake_urlopen,
    ) is False


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


def test_scanner_normalizes_supported_host_registry_entries(scan_plugins_module):
    assert scan_plugins_module.get_registry_owner("github.com", "owner") == "owner"
    assert scan_plugins_module.get_registry_owner("codeberg.org", "Hoog") == "codeberg.org/Hoog"
    assert scan_plugins_module.get_repository_identity("gitlab.com/r.boeters", "DomoticzSabNZBDPlugin") == (
        "gitlab.com/r.boeters/domoticzsabnzbdplugin"
    )


def test_scanner_checks_root_plugin_py_on_supported_hosts(scan_plugins_module, monkeypatch):
    fetched_urls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size=-1):
            return b'"""<plugin key="Test" name="Test"></plugin>"""'

    def fake_urlopen(request, timeout=0):
        fetched_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(scan_plugins_module.urllib.request, "urlopen", fake_urlopen)

    assert scan_plugins_module.has_root_plugin_py({
        "host": "codeberg.org",
        "owner": {"login": "Hoog"},
        "name": "Domoticz-Stromer-plugin",
        "default_branch": "main",
    }) is True
    assert scan_plugins_module.has_root_plugin_py({
        "host": "gitlab.com",
        "owner": {"login": "r.boeters"},
        "name": "DomoticzSabNZBDPlugin",
        "default_branch": "master",
    }) is True
    assert fetched_urls == [
        "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/raw/branch/main/plugin.py",
        "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin/-/raw/master/plugin.py",
    ]


def test_cleanup_registry_builds_raw_plugin_urls_for_supported_hosts(cleanup_registry_module):
    assert cleanup_registry_module.raw_plugin_url("owner", "repo", "main") == (
        "https://raw.githubusercontent.com/owner/repo/main/plugin.py"
    )
    assert cleanup_registry_module.raw_plugin_url(
        "codeberg.org/Hoog",
        "Domoticz-Stromer-plugin",
        "main",
    ) == "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/raw/branch/main/plugin.py"
    assert cleanup_registry_module.raw_plugin_url(
        "gitlab.com/r.boeters",
        "DomoticzSabNZBDPlugin",
        "master",
    ) == "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin/-/raw/master/plugin.py"


def test_cleanup_registry_dry_run_does_not_remove_entries(cleanup_registry_module, tmp_path):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
    registry = {
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "Good": ["owner", "present", "description", "main"],
        "Missing": ["owner", "missing", "description", "main"],
        "Empty": ["owner", "empty", "description", "main"],
        "ServerError": ["owner", "server-error", "description", "main"],
    }
    update_times = {
        "Good": "2026-06-14T15:10:03Z",
        "Missing": "2026-06-14T15:10:03Z",
        "Empty": "2026-06-14T15:10:03Z",
        "ServerError": "2026-06-14T15:10:03Z",
    }
    metadata = {
        "version": 1,
        "entries": {
            key: {"registry_platforms": ["linux"]}
            for key in ("Good", "Missing", "Empty", "ServerError")
        },
    }
    registry_file.write_text(json.dumps(registry))
    update_times_file.write_text(json.dumps(update_times))
    metadata_file.write_text(json.dumps(metadata))

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size=-1):
            return self.content

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        if "/present/" in url:
            return FakeResponse(b"import Domoticz\n")
        if "/missing/" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if "/empty/" in url:
            return FakeResponse(b"")
        if "/server-error/" in url:
            raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
        raise AssertionError(f"Unexpected URL: {url}")

    stats = cleanup_registry_module.cleanup_registry_files(
        str(registry_file),
        str(update_times_file),
        str(metadata_file),
        apply_changes=False,
        sleep_seconds=0,
        opener=fake_urlopen,
    )

    assert stats == {
        "checked": 4,
        "present": 1,
        "would_remove": 2,
        "removed": 0,
        "errors": 1,
    }
    assert json.loads(registry_file.read_text()) == registry
    assert json.loads(update_times_file.read_text()) == update_times
    assert json.loads(metadata_file.read_text()) == metadata


def test_cleanup_registry_apply_removes_missing_entries_from_sidecars(cleanup_registry_module, tmp_path):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "Good": ["owner", "present", "description", "main"],
        "Missing": ["owner", "missing", "description", "main"],
        "ServerError": ["owner", "server-error", "description", "main"],
    }))
    update_times_file.write_text(json.dumps({
        "Good": "2026-06-14T15:10:03Z",
        "Missing": "2026-06-14T15:10:03Z",
        "ServerError": "2026-06-14T15:10:03Z",
    }))
    metadata_file.write_text(json.dumps({
        "version": 1,
        "entries": {
            "Good": {"registry_platforms": ["linux"]},
            "Missing": {"registry_platforms": ["linux"]},
            "ServerError": {"registry_platforms": ["linux"]},
        },
    }))

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self, size=-1):
            return b"import Domoticz\n"

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        if "/present/" in url:
            return FakeResponse()
        if "/missing/" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if "/server-error/" in url:
            raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
        raise AssertionError(f"Unexpected URL: {url}")

    stats = cleanup_registry_module.cleanup_registry_files(
        str(registry_file),
        str(update_times_file),
        str(metadata_file),
        apply_changes=True,
        sleep_seconds=0,
        opener=fake_urlopen,
    )

    registry = json.loads(registry_file.read_text())
    update_times = json.loads(update_times_file.read_text())
    metadata = json.loads(metadata_file.read_text())

    assert stats["removed"] == 1
    assert "Good" in registry
    assert "Missing" not in registry
    assert "ServerError" in registry
    assert "Missing" not in update_times
    assert "Missing" not in metadata["entries"]


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
    assert decision.evidence_class == "generic_python"


def test_platform_detector_respects_explicit_both_support(platform_detector_module):
    decision = platform_detector_module.detect_platforms_from_repository_data(
        file_texts={
            "README.md": "Supported on Linux and Windows Domoticz installations.",
        }
    )

    assert decision.platforms == ["linux", "windows"]
    assert decision.confidence == "high"
    assert decision.evidence_class == "explicit_both"


def test_platform_policy_requires_high_confidence_for_existing_changes(platform_detector_module):
    current, action = platform_detector_module.choose_platforms_for_registry(
        ["linux", "windows"],
        platform_decision(["linux"], confidence="medium", evidence_class="linux_evidence"),
    )

    assert current == ["linux", "windows"]
    assert action == "kept_existing_requires_high_confidence"

    current, action = platform_detector_module.choose_platforms_for_registry(
        ["linux", "windows"],
        platform_decision(["linux"], confidence="high", evidence_class="explicit_linux_only"),
    )

    assert current == ["linux"]
    assert action == "accepted_high_confidence_change"


def test_platform_policy_keeps_reviewed_entries(platform_detector_module):
    current, action = platform_detector_module.choose_platforms_for_registry(
        ["linux", "windows"],
        platform_decision(["linux"], confidence="high", evidence_class="explicit_linux_only"),
        metadata_entry={"reviewed": True},
    )

    assert current == ["linux", "windows"]
    assert action == "kept_reviewed"


def test_platform_policy_leaves_low_confidence_new_entries_unknown(platform_detector_module):
    current, action = platform_detector_module.choose_platforms_for_registry(
        [],
        platform_decision(["linux", "windows"], confidence="low", evidence_class="generic_python"),
        is_new=True,
    )

    assert current == []
    assert action == "kept_low_confidence_new"


def test_platform_metadata_marks_missing_entries_reviewed_when_sidecar_exists(platform_detector_module):
    registry = {
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "ManualPlugin": ["owner", "repo", "description", "main", "", ["linux"]],
    }

    metadata = platform_detector_module.ensure_platform_metadata_for_registry(
        {"version": 1, "entries": {}},
        registry,
        manual_changes_are_reviewed=True,
    )

    entry = metadata["entries"]["ManualPlugin"]
    assert entry["registry_platforms"] == ["linux"]
    assert entry["source"] == "reviewed"
    assert entry["evidence_class"] == "manual_registry_edit"
    assert entry["reviewed"] is True


def test_platform_metadata_marks_platform_edits_reviewed_when_sidecar_exists(platform_detector_module):
    registry = {
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "ManualPlugin": ["owner", "repo", "description", "main", "", ["linux"]],
    }
    metadata = {
        "version": 1,
        "entries": {
            "ManualPlugin": {
                "identity": "github.com/owner/repo@main",
                "owner": "owner",
                "repository": "repo",
                "branch": "main",
                "registry_platforms": ["linux", "windows"],
                "source": "detected",
                "confidence": "low",
                "evidence_class": "generic_python",
                "reviewed": False,
                "last_detection": {"platforms": ["linux", "windows"]},
                "policy_action": "unchanged",
            },
        },
    }

    metadata = platform_detector_module.ensure_platform_metadata_for_registry(
        metadata,
        registry,
        manual_changes_are_reviewed=True,
    )

    entry = metadata["entries"]["ManualPlugin"]
    assert entry["registry_platforms"] == ["linux"]
    assert entry["source"] == "reviewed"
    assert entry["confidence"] == "unknown"
    assert entry["evidence_class"] == "manual_registry_edit"
    assert entry["reviewed"] is True
    assert "last_detection" not in entry
    assert "policy_action" not in entry


def test_platform_detector_fetches_codeberg_tree_and_raw_urls(platform_detector_module, monkeypatch):
    fetched_json_urls = []
    fetched_text_urls = []

    def fake_fetch_json(url, timeout=20):
        fetched_json_urls.append(url)
        return {
            "tree": [
                {"type": "blob", "path": "README.md", "size": 40},
                {"type": "blob", "path": "plugin.py", "size": 40},
            ],
        }

    def fake_fetch_text(url, timeout=20):
        fetched_text_urls.append(url)
        return "Domoticz plugin\nimport Domoticz\n"

    monkeypatch.setattr(platform_detector_module, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(platform_detector_module, "fetch_text", fake_fetch_text)

    decision = platform_detector_module.detect_platforms_for_repo(
        "codeberg.org/Hoog",
        "Domoticz-Stromer-plugin",
        "main",
        repo_info={"description": "Domoticz plugin"},
    )

    assert fetched_json_urls == [
        "https://codeberg.org/api/v1/repos/Hoog/Domoticz-Stromer-plugin/git/trees/main?recursive=1",
    ]
    assert fetched_text_urls == [
        "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/raw/branch/main/README.md",
        "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/raw/branch/main/plugin.py",
    ]
    assert decision.platforms == ["linux", "windows"]


def test_platform_detector_fetches_gitlab_tree_and_raw_urls(platform_detector_module, monkeypatch):
    fetched_json_urls = []
    fetched_text_urls = []

    def fake_fetch_json(url, timeout=20):
        fetched_json_urls.append(url)
        return [
            {"type": "blob", "path": "README.md", "size": 40},
            {"type": "blob", "path": "plugin.py", "size": 40},
        ]

    def fake_fetch_text(url, timeout=20):
        fetched_text_urls.append(url)
        return "Domoticz plugin\nimport Domoticz\n"

    monkeypatch.setattr(platform_detector_module, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(platform_detector_module, "fetch_text", fake_fetch_text)

    decision = platform_detector_module.detect_platforms_for_repo(
        "gitlab.com/r.boeters",
        "DomoticzSabNZBDPlugin",
        "master",
        repo_info={"description": "Domoticz plugin"},
    )

    assert fetched_json_urls == [
        "https://gitlab.com/api/v4/projects/r.boeters%2FDomoticzSabNZBDPlugin/repository/tree?recursive=true&per_page=100&ref=master",
    ]
    assert fetched_text_urls == [
        "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin/-/raw/master/README.md",
        "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin/-/raw/master/plugin.py",
    ]
    assert decision.platforms == ["linux", "windows"]


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
    metadata_file = tmp_path / "platform_detection.json"
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

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", lambda owner, repo: repo_info)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [])
    monkeypatch.setattr(
        scan_plugins_module,
        "detect_platforms_for_repo",
        lambda owner, repo, branch, repo_info=None: platform_decision(["linux"], confidence="medium"),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())

    assert registry["Plugin"] == ["owner", "repo", "description", "main", "", ["linux"]]
    metadata = json.loads(metadata_file.read_text())
    assert metadata["entries"]["Plugin"]["registry_platforms"] == ["linux"]
    assert metadata["entries"]["Plugin"]["source"] == "detected"


def test_scanner_never_updates_existing_registry_branch(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "luxtronikex": [
            "Rouzax",
            "luxtronik-domoticz-plugin-v2",
            "description",
            "dist",
            "",
            ["linux", "windows"],
        ],
    }))
    update_times_file.write_text(json.dumps({
        "luxtronikex": "2026-03-14T14:52:18Z",
    }))

    repo_info = {
        "archived": False,
        "disabled": False,
        "size": 100,
        "full_name": "Rouzax/luxtronik-domoticz-plugin-v2",
        "owner": {"login": "Rouzax"},
        "name": "luxtronik-domoticz-plugin-v2",
        "description": "updated description",
        "default_branch": "main",
        "pushed_at": "2026-07-02T11:45:18Z",
    }

    seen_branches = []

    def detect_platforms(owner, repo, branch, repo_info=None):
        seen_branches.append(branch)
        return platform_decision(["linux", "windows"], confidence="high")

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", lambda owner, repo: repo_info)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "detect_platforms_for_repo", detect_platforms)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    metadata = json.loads(metadata_file.read_text())

    assert seen_branches == ["dist"]
    assert registry["luxtronikex"] == [
        "Rouzax",
        "luxtronik-domoticz-plugin-v2",
        "updated description",
        "dist",
        "",
        ["linux", "windows"],
    ]
    assert metadata["entries"]["luxtronikex"]["branch"] == "dist"
    assert metadata["entries"]["luxtronikex"]["identity"] == (
        "github.com/rouzax/luxtronik-domoticz-plugin-v2@dist"
    )


def test_scanner_adds_platforms_for_new_plugins(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
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

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [repo_info])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [])
    monkeypatch.setattr(
        scan_plugins_module,
        "detect_platforms_for_repo",
        lambda owner, repo, branch, repo_info=None: platform_decision(["windows"], confidence="medium"),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())

    assert registry["repo"] == ["owner", "repo", "description", "main", "", ["windows"]]


def test_scanner_keeps_low_confidence_new_plugin_platforms_unknown(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
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

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [repo_info])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [])
    monkeypatch.setattr(
        scan_plugins_module,
        "detect_platforms_for_repo",
        lambda owner, repo, branch, repo_info=None: platform_decision(
            ["linux", "windows"],
            confidence="low",
            evidence_class="generic_python",
        ),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    metadata = json.loads(metadata_file.read_text())

    assert registry["repo"] == ["owner", "repo", "description", "main"]
    assert metadata["entries"]["repo"]["registry_platforms"] == []
    assert metadata["entries"]["repo"]["last_detection"]["platforms"] == ["linux", "windows"]
    assert metadata["entries"]["repo"]["policy_action"] == "kept_low_confidence_new"


def test_scanner_blocks_medium_confidence_existing_platform_downgrade(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "Plugin": ["owner", "repo", "description", "main", "", ["linux", "windows"]],
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

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", lambda owner, repo: repo_info)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [])
    monkeypatch.setattr(
        scan_plugins_module,
        "detect_platforms_for_repo",
        lambda owner, repo, branch, repo_info=None: platform_decision(
            ["linux"],
            confidence="medium",
            evidence_class="linux_evidence",
        ),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    metadata = json.loads(metadata_file.read_text())

    assert registry["Plugin"] == ["owner", "repo", "description", "main", "", ["linux", "windows"]]
    assert metadata["entries"]["Plugin"]["registry_platforms"] == ["linux", "windows"]
    assert metadata["entries"]["Plugin"]["last_detection"]["platforms"] == ["linux"]
    assert metadata["entries"]["Plugin"]["policy_action"] == "kept_existing_requires_high_confidence"


def test_scanner_treats_existing_registry_entries_missing_from_sidecar_as_reviewed(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
        "ManualPlugin": ["owner", "repo", "description", "main"],
    }))
    update_times_file.write_text(json.dumps({
        "ManualPlugin": "2026-06-14T15:10:03Z",
    }))
    metadata_file.write_text(json.dumps({
        "version": 1,
        "entries": {},
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

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", lambda owner, repo: repo_info)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [])
    monkeypatch.setattr(
        scan_plugins_module,
        "detect_platforms_for_repo",
        lambda owner, repo, branch, repo_info=None: platform_decision(
            ["linux"],
            confidence="medium",
            evidence_class="linux_evidence",
        ),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    metadata = json.loads(metadata_file.read_text())

    assert registry["ManualPlugin"] == ["owner", "repo", "description", "main"]
    assert metadata["entries"]["ManualPlugin"]["source"] == "reviewed"
    assert metadata["entries"]["ManualPlugin"]["reviewed"] is True
    assert metadata["entries"]["ManualPlugin"]["policy_action"] == "kept_reviewed"
    assert metadata["entries"]["ManualPlugin"]["last_detection"]["platforms"] == ["linux"]


def test_scanner_adds_codeberg_and_gitlab_plugins(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
    registry_file.write_text(json.dumps({
        "Idle": ["Idle", "Idle", "Idle", "master"],
    }))
    update_times_file.write_text(json.dumps({}))

    codeberg_repo = {
        "archived": False,
        "disabled": False,
        "size": 100,
        "host": "codeberg.org",
        "full_name": "Hoog/Domoticz-Stromer-plugin",
        "owner": {"login": "Hoog"},
        "name": "Domoticz-Stromer-plugin",
        "description": "Domoticz plugin for integrating Stromer portal data.",
        "default_branch": "main",
        "pushed_at": "2026-06-30T19:36:29Z",
    }
    gitlab_repo = {
        "archived": False,
        "disabled": False,
        "size": 100,
        "host": "gitlab.com",
        "full_name": "r.boeters/DomoticzSabNZBDPlugin",
        "owner": {"login": "r.boeters"},
        "name": "DomoticzSabNZBDPlugin",
        "description": "SabNZBD Python plugin for Domoticz Home Automation",
        "default_branch": "master",
        "pushed_at": "2019-08-16T18:29:37.958Z",
    }

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [codeberg_repo])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [gitlab_repo])
    monkeypatch.setattr(
        scan_plugins_module,
        "detect_platforms_for_repo",
        lambda owner, repo, branch, repo_info=None: platform_decision(["linux", "windows"], confidence="medium"),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    update_times = json.loads(update_times_file.read_text())

    assert registry["Domoticz-Stromer-plugin"] == [
        "codeberg.org/Hoog",
        "Domoticz-Stromer-plugin",
        "Domoticz plugin for integrating Stromer portal data.",
        "main",
        "",
        ["linux", "windows"],
    ]
    assert registry["DomoticzSabNZBDPlugin"] == [
        "gitlab.com/r.boeters",
        "DomoticzSabNZBDPlugin",
        "SabNZBD Python plugin for Domoticz Home Automation",
        "master",
        "",
        ["linux", "windows"],
    ]
    assert update_times["Domoticz-Stromer-plugin"] == "2026-06-30T19:36:29Z"
    assert update_times["DomoticzSabNZBDPlugin"] == "2019-08-16T18:29:37.958Z"


def test_scanner_removes_empty_existing_repo_and_does_not_readd(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
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

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", lambda owner, repo: empty_repo)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [empty_repo])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [])
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    update_times = json.loads(update_times_file.read_text())

    assert "Domoticz_integration" not in registry
    assert "Domoticz_integration" not in update_times


def test_scanner_removes_blocklisted_existing_repo_and_does_not_readd(scan_plugins_module, tmp_path, monkeypatch):
    registry_file = tmp_path / "registry.json"
    update_times_file = tmp_path / "update_times.json"
    metadata_file = tmp_path / "platform_detection.json"
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

    patch_scanner_paths(scan_plugins_module, monkeypatch, registry_file, update_times_file, metadata_file)
    monkeypatch.setattr(scan_plugins_module, "get_repo_info", fail_get_repo_info)
    monkeypatch.setattr(scan_plugins_module, "search_github", lambda: [domoticz_repo])
    monkeypatch.setattr(scan_plugins_module, "search_gitlab", lambda: [])
    monkeypatch.setattr(scan_plugins_module, "search_codeberg", lambda: [])
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    scan_plugins_module.main()

    registry = json.loads(registry_file.read_text())
    update_times = json.loads(update_times_file.read_text())

    assert "domoticz" not in registry
    assert "domoticz" not in update_times
