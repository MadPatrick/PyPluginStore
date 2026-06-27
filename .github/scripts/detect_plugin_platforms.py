#!/usr/bin/env python3
import argparse
import ast
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
REGISTRY_FILE = os.path.join(REPO_ROOT, "registry.json")

PLATFORM_ORDER = ["linux", "windows"]
DEFAULT_PLATFORMS = ["linux", "windows"]
MAX_ANALYSIS_FILES = 40
MAX_TEXT_FILE_BYTES = 160_000

API_USER_AGENT = "Domoticz-Plugin-Platform-Scanner"

LINUX_ONLY_PATTERNS = [
    (r"\blinux\s+only\b", 10, "states Linux only"),
    (r"\bonly\s+(?:runs?|works?|supported)\s+(?:on|with|under)\s+linux\b", 10, "states Linux-only support"),
    (r"\brequires?\s+(?:a\s+)?(?:linux|raspbian|raspberry\s+pi)\b", 8, "states Linux/Raspberry Pi requirement"),
    (r"\bnot\s+(?:supported|working|compatible)\s+(?:on|with|under)\s+windows\b", 10, "states Windows is unsupported"),
    (r"\bdoes\s+not\s+(?:run|work)\s+(?:on|under)\s+windows\b", 10, "states Windows does not work"),
]

WINDOWS_ONLY_PATTERNS = [
    (r"\bwindows\s+only\b", 10, "states Windows only"),
    (r"\bonly\s+(?:runs?|works?|supported)\s+(?:on|with|under)\s+windows\b", 10, "states Windows-only support"),
    (r"\brequires?\s+(?:microsoft\s+)?windows\b", 8, "states Windows requirement"),
    (r"\bnot\s+(?:supported|working|compatible)\s+(?:on|with|under)\s+linux\b", 10, "states Linux is unsupported"),
    (r"\bdoes\s+not\s+(?:run|work)\s+(?:on|under)\s+linux\b", 10, "states Linux does not work"),
]

BOTH_PLATFORM_PATTERNS = [
    (r"\b(?:linux|raspbian|raspberry\s+pi)\b.{0,100}\bwindows\b", 8, "mentions Linux and Windows support"),
    (r"\bwindows\b.{0,100}\b(?:linux|raspbian|raspberry\s+pi)\b", 8, "mentions Windows and Linux support"),
    (r"\bcross[-\s]?platform\b", 8, "states cross-platform support"),
    (r"\bplatform[-\s]?independent\b", 8, "states platform-independent support"),
    (r"\b(?:works|runs|supported)\s+(?:on|under)\s+(?:both\s+)?(?:linux|windows)\s+and\s+(?:linux|windows)\b", 8, "states both-platform support"),
]

LINUX_TEXT_PATTERNS = [
    (r"\braspberry\s+pi\b|\braspbian\b|\brpi\b", 3, "mentions Raspberry Pi/Raspbian"),
    (r"\bapt(?:-get)?\s+install\b", 4, "uses apt package installation"),
    (r"\bsudo\b", 2, "uses sudo"),
    (r"\bsystemctl\b|\bsystemd\b", 4, "uses systemd"),
    (r"\bchmod\s+\+x\b", 3, "uses chmod"),
    (r"(?<!\w)/(?:dev|etc|proc|sys|var)/(?:[\w.\-/]+)?", 4, "uses Unix system paths"),
    (r"/dev/(?:tty|serial|gpio|i2c|spi)", 6, "uses Linux device paths"),
    (r"\b(?:bash|sh)\s+", 2, "uses shell commands"),
    (r"\b(?:rpi\.gpio|gpiozero|pigpio|spidev|smbus2?|wiringpi|adafruit_dht|bluepy)\b", 7, "uses Linux/Raspberry Pi Python dependency"),
]

WINDOWS_TEXT_PATTERNS = [
    (r"\bpowershell(?:\.exe)?\b", 5, "uses PowerShell"),
    (r"\bcmd\.exe\b", 5, "uses cmd.exe"),
    (r"\b(?:\.bat|\.cmd|\.ps1)\b", 4, "uses Windows script files"),
    (r"\bCOM\d+\b", 5, "uses Windows serial port names"),
    (r"\b[A-Z]:\\", 5, "uses Windows drive paths"),
    (r"\bwindows\s+service\b", 4, "mentions Windows service"),
    (r"\b(?:pywin32|pypiwin32|win32api|win32com|win32service|winreg|winsound|msvcrt|wmi)\b", 8, "uses Windows Python dependency"),
]

LINUX_IMPORTS = {
    "adafruit_dht",
    "bluepy",
    "dbus",
    "fcntl",
    "gpiozero",
    "grp",
    "pigpio",
    "pwd",
    "rpi",
    "rpi.gpio",
    "smbus",
    "smbus2",
    "spidev",
    "syslog",
    "termios",
    "wiringpi",
}

WINDOWS_IMPORTS = {
    "msvcrt",
    "pywintypes",
    "pythoncom",
    "win32api",
    "win32com",
    "win32con",
    "win32event",
    "win32service",
    "win32serviceutil",
    "winreg",
    "winsound",
    "wmi",
}

SKIP_PATH_PARTS = {
    ".git",
    ".github",
    "__pycache__",
    "node_modules",
    "vendor",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
}

ANALYSIS_EXTENSIONS = {
    ".bat",
    ".cfg",
    ".cmd",
    ".ini",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".service",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

IMPORTANT_FILENAMES = {
    "dockerfile",
    "install",
    "install.sh",
    "install.ps1",
    "plugin.py",
    "pyproject.toml",
    "readme",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
}


class PlatformDecision:
    def __init__(self, platforms, linux_score=0, windows_score=0, both_score=0, confidence="low", reasons=None):
        self.platforms = list(platforms)
        self.linux_score = linux_score
        self.windows_score = windows_score
        self.both_score = both_score
        self.confidence = confidence
        self.reasons = list(reasons or [])

    def to_dict(self):
        return {
            "platforms": self.platforms,
            "confidence": self.confidence,
            "scores": {
                "linux": self.linux_score,
                "windows": self.windows_score,
                "both": self.both_score,
            },
            "reasons": self.reasons,
        }


def github_headers():
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": API_USER_AGENT,
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers=github_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"Error fetching {url}: HTTP {e.code}")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None


def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers=github_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read(MAX_TEXT_FILE_BYTES + 1)
            return content[:MAX_TEXT_FILE_BYTES].decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return None
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


def quote_path_part(value):
    return urllib.parse.quote(str(value), safe="")


def quote_repo_path(path):
    return urllib.parse.quote(str(path), safe="/")


def get_repo_tree(owner, repo, branch):
    url = (
        "https://api.github.com/repos/"
        f"{quote_path_part(owner)}/{quote_path_part(repo)}/git/trees/"
        f"{quote_path_part(branch)}?recursive=1"
    )
    data = fetch_json(url)
    if not isinstance(data, dict):
        return None
    tree = data.get("tree")
    if not isinstance(tree, list):
        return None
    return tree


def get_raw_file(owner, repo, branch, path):
    url = (
        "https://raw.githubusercontent.com/"
        f"{quote_path_part(owner)}/{quote_path_part(repo)}/"
        f"{quote_path_part(branch)}/{quote_repo_path(path)}"
    )
    return fetch_text(url)


def normalize_platforms(platforms):
    if isinstance(platforms, str):
        platforms = [platforms]
    if not isinstance(platforms, list):
        return []

    normalized = []
    for platform in platforms:
        platform_name = str(platform or "").strip().lower()
        if platform_name in PLATFORM_ORDER and platform_name not in normalized:
            normalized.append(platform_name)
    return [platform for platform in PLATFORM_ORDER if platform in normalized]


def get_registry_entry_platforms(data):
    if isinstance(data, dict):
        return normalize_platforms(data.get("platforms", data.get("platform")))
    if isinstance(data, list) and len(data) > 5:
        return normalize_platforms(data[5])
    return []


def set_registry_entry_platforms(data, platforms):
    platforms = normalize_platforms(platforms)
    if not platforms:
        return data

    if isinstance(data, dict):
        updated = dict(data)
        updated["platforms"] = platforms
        return updated

    updated = list(data)
    while len(updated) < 5:
        updated.append("")
    if len(updated) == 5:
        updated.append(platforms)
    else:
        updated[5] = platforms
    return updated


def registry_entry_identity(data):
    if isinstance(data, dict):
        owner = data.get("owner", data.get("author", ""))
        repo = data.get("repository", data.get("repo", ""))
        branch = data.get("branch", "master")
        return owner, repo, branch
    if isinstance(data, list) and len(data) >= 4:
        return data[0], data[1], data[3]
    return "", "", ""


def is_skipped_path(path):
    parts = str(path).lower().split("/")
    return any(part in SKIP_PATH_PARTS for part in parts)


def file_priority(path):
    path_lower = str(path).lower()
    base = os.path.basename(path_lower)
    _, ext = os.path.splitext(base)

    if is_skipped_path(path_lower):
        return None
    if base.startswith("readme"):
        return 0
    if base in {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"}:
        return 1
    if base == "plugin.py" or base.startswith("plugin_"):
        return 2
    if ext == ".py":
        return 3
    if base in IMPORTANT_FILENAMES or ext in ANALYSIS_EXTENSIONS:
        return 4
    return None


def select_analysis_files(tree, limit=MAX_ANALYSIS_FILES):
    candidates = []
    for item in tree or []:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        priority = file_priority(path)
        if priority is None:
            continue
        size = item.get("size")
        if size is not None:
            try:
                if int(size) > MAX_TEXT_FILE_BYTES:
                    continue
            except (TypeError, ValueError):
                pass
        candidates.append((priority, str(path).count("/"), int(size or 0), str(path)))

    candidates.sort()
    return [path for _, _, _, path in candidates[:limit]]


def add_reason(scores, target, weight, source, reason):
    scores[target] += weight
    tagged_reason = f"{source}: {reason}"
    if tagged_reason not in scores["reasons"]:
        scores["reasons"].append(tagged_reason)


def score_patterns(text, source, scores, patterns, target):
    if not text:
        return
    for pattern, weight, reason in patterns:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            add_reason(scores, target, weight, source, reason)


def score_path(path, scores):
    path_lower = str(path).lower()
    base = os.path.basename(path_lower)
    _, ext = os.path.splitext(base)

    if ext in {".sh", ".service"} or "/systemd/" in path_lower:
        add_reason(scores, "linux", 3, path, "Linux-oriented file name")
    if ext in {".bat", ".cmd", ".ps1"} or "windows" in path_lower:
        add_reason(scores, "windows", 3, path, "Windows-oriented file name")


def collect_python_imports(tree):
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.lower())
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.lower())
    return imports


def score_python_ast(text, source, scores):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(text)
    except SyntaxError:
        return

    for module_name in collect_python_imports(tree):
        module_root = module_name.split(".", 1)[0]
        if module_name in LINUX_IMPORTS or module_root in LINUX_IMPORTS:
            add_reason(scores, "linux", 8, source, f"imports Linux-specific module {module_name}")
        if module_name in WINDOWS_IMPORTS or module_root in WINDOWS_IMPORTS:
            add_reason(scores, "windows", 8, source, f"imports Windows-specific module {module_name}")


def score_text(text, source, scores):
    score_patterns(text, source, scores, BOTH_PLATFORM_PATTERNS, "both")
    score_patterns(text, source, scores, LINUX_ONLY_PATTERNS, "linux_only")
    score_patterns(text, source, scores, WINDOWS_ONLY_PATTERNS, "windows_only")
    score_patterns(text, source, scores, LINUX_TEXT_PATTERNS, "linux")
    score_patterns(text, source, scores, WINDOWS_TEXT_PATTERNS, "windows")

    if source.lower().endswith(".py"):
        score_python_ast(text, source, scores)


def new_scores():
    return {
        "linux": 0,
        "windows": 0,
        "both": 0,
        "linux_only": 0,
        "windows_only": 0,
        "reasons": [],
    }


def decide_platforms(scores, assume_generic_python_is_cross_platform=True):
    linux_score = scores["linux"] + scores["linux_only"]
    windows_score = scores["windows"] + scores["windows_only"]
    both_score = scores["both"]

    if scores["linux_only"] >= 8 and windows_score < 6:
        return PlatformDecision(["linux"], linux_score, windows_score, both_score, "high", scores["reasons"])

    if scores["windows_only"] >= 8 and linux_score < 6:
        return PlatformDecision(["windows"], linux_score, windows_score, both_score, "high", scores["reasons"])

    if both_score >= 8:
        return PlatformDecision(DEFAULT_PLATFORMS, linux_score, windows_score, both_score, "high", scores["reasons"])

    if linux_score >= 8 and windows_score >= 8:
        return PlatformDecision(DEFAULT_PLATFORMS, linux_score, windows_score, both_score, "medium", scores["reasons"])

    if linux_score >= 8 and windows_score < 6:
        return PlatformDecision(["linux"], linux_score, windows_score, both_score, "medium", scores["reasons"])

    if windows_score >= 8 and linux_score < 6:
        return PlatformDecision(["windows"], linux_score, windows_score, both_score, "medium", scores["reasons"])

    if assume_generic_python_is_cross_platform:
        reasons = list(scores["reasons"])
        if not reasons:
            reasons.append("generic: no Linux-only or Windows-only evidence found")
        return PlatformDecision(DEFAULT_PLATFORMS, linux_score, windows_score, both_score, "low", reasons)

    return PlatformDecision([], linux_score, windows_score, both_score, "unknown", scores["reasons"])


def detect_platforms_from_repository_data(repo_info=None, file_texts=None, assume_generic_python_is_cross_platform=True):
    scores = new_scores()
    repo_info = repo_info or {}
    file_texts = file_texts or {}

    metadata_parts = [
        repo_info.get("name", ""),
        repo_info.get("description", ""),
        " ".join(repo_info.get("topics") or []),
    ]
    score_text("\n".join(str(part) for part in metadata_parts if part), "github metadata", scores)

    for path, text in file_texts.items():
        score_path(path, scores)
        score_text(text, path, scores)

    return decide_platforms(scores, assume_generic_python_is_cross_platform)


def detect_platforms_for_repo(owner, repo, branch, repo_info=None):
    tree = get_repo_tree(owner, repo, branch)
    if tree is None:
        decision = detect_platforms_from_repository_data(
            repo_info=repo_info,
            file_texts={},
            assume_generic_python_is_cross_platform=False,
        )
        return decision if decision.platforms else None

    file_texts = {}
    for path in select_analysis_files(tree):
        text = get_raw_file(owner, repo, branch, path)
        if text is not None:
            file_texts[path] = text

    decision = detect_platforms_from_repository_data(
        repo_info=repo_info,
        file_texts=file_texts,
        assume_generic_python_is_cross_platform=bool(file_texts),
    )
    return decision if decision.platforms else None


def update_registry_platforms(registry_file=REGISTRY_FILE, missing_only=False, dry_run=False, limit=None, sleep_seconds=None):
    with open(registry_file, "r", encoding="utf-8") as f:
        registry = json.load(f)

    stats = {
        "scanned": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
        "skipped": 0,
    }

    if sleep_seconds is None:
        sleep_seconds = 0 if os.environ.get("GITHUB_TOKEN") else 1

    for key, data in list(registry.items()):
        if key == "Idle":
            continue
        if limit is not None and stats["scanned"] >= limit:
            break

        current_platforms = get_registry_entry_platforms(data)
        if missing_only and current_platforms:
            stats["skipped"] += 1
            continue

        owner, repo, branch = registry_entry_identity(data)
        if not owner or not repo or not branch:
            print(f"[-] Skipping {key} (invalid registry entry)")
            stats["skipped"] += 1
            continue

        stats["scanned"] += 1
        print(f"Checking {key} ({owner}/{repo})...", end=" ", flush=True)
        decision = detect_platforms_for_repo(owner, repo, branch)
        if decision is None:
            print("no decision")
            stats["failed"] += 1
        elif decision.platforms != current_platforms:
            registry[key] = set_registry_entry_platforms(data, decision.platforms)
            print(f"{current_platforms or ['unknown']} -> {decision.platforms} ({decision.confidence})")
            stats["updated"] += 1
        else:
            print(f"{current_platforms} unchanged")
            stats["unchanged"] += 1

        if sleep_seconds:
            time.sleep(sleep_seconds)

    if stats["updated"] and not dry_run:
        with open(registry_file, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=4)
            f.write("\n")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Detect likely Domoticz plugin platform support and update registry metadata.")
    parser.add_argument("--registry", default=REGISTRY_FILE, help="Path to registry.json")
    parser.add_argument("--missing-only", action="store_true", help="Only classify entries without platform metadata")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing registry.json")
    parser.add_argument("--limit", type=int, help="Limit the number of registry entries scanned")
    parser.add_argument("--sleep", type=float, help="Seconds to sleep between repositories")
    args = parser.parse_args()

    stats = update_registry_platforms(
        registry_file=args.registry,
        missing_only=args.missing_only,
        dry_run=args.dry_run,
        limit=args.limit,
        sleep_seconds=args.sleep,
    )
    print(
        "Platform scan complete: "
        f"{stats['scanned']} scanned, {stats['updated']} updated, "
        f"{stats['unchanged']} unchanged, {stats['failed']} failed, {stats['skipped']} skipped."
    )


if __name__ == "__main__":
    main()
