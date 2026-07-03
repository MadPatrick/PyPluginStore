#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
REGISTRY_FILE = os.path.join(REPO_ROOT, "registry.json")
UPDATE_TIMES_FILE = os.path.join(REPO_ROOT, "update_times.json")
PLATFORM_METADATA_FILE = os.path.join(REPO_ROOT, ".github", "platform_detection.json")

DEFAULT_GIT_HOST = "github.com"
SUPPORTED_GIT_HOSTS = ("github.com", "gitlab.com", "codeberg.org")
API_USER_AGENT = "Domoticz-Plugin-Registry-Cleanup"

REMOVABLE_STATUSES = {"missing", "empty"}


class CheckResult:
    def __init__(self, key, status, url="", reason=""):
        self.key = key
        self.status = status
        self.url = url
        self.reason = reason

    @property
    def removable(self):
        return self.status in REMOVABLE_STATUSES


def split_registry_owner(author):
    author = str(author or "").strip().strip("/")
    for host in SUPPORTED_GIT_HOSTS:
        if author.lower() == host:
            return host, ""
        if author.lower().startswith(host + "/"):
            return host, author[len(host) + 1:]
    return DEFAULT_GIT_HOST, author


def quote_path_part(value):
    return urllib.parse.quote(str(value), safe="")


def quote_repo_path(path):
    return urllib.parse.quote(str(path), safe="/")


def raw_plugin_url(author, repository, branch):
    host, owner_path = split_registry_owner(author)
    repo_path = "/".join(part for part in (owner_path + "/" + repository).split("/") if part)
    repo_path = quote_repo_path(repo_path)
    branch = quote_path_part(branch)

    if host == "gitlab.com":
        return f"https://gitlab.com/{repo_path}/-/raw/{branch}/plugin.py"
    if host == "codeberg.org":
        return f"https://codeberg.org/{repo_path}/raw/branch/{branch}/plugin.py"
    return f"https://raw.githubusercontent.com/{repo_path}/{branch}/plugin.py"


def headers_for_url(url):
    host = urllib.parse.urlparse(url).hostname or ""
    headers = {
        "Accept": "text/plain,*/*",
        "User-Agent": API_USER_AGENT,
    }

    if host == "raw.githubusercontent.com":
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"token {token}"
    elif host == "gitlab.com":
        token = os.environ.get("GITLAB_TOKEN")
        if token:
            headers["PRIVATE-TOKEN"] = token

    return headers


def load_json_file(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path, data):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.write("\n")


def check_root_plugin_py(key, data, opener=None):
    if not isinstance(data, list) or len(data) < 4:
        return CheckResult(key, "invalid-entry", reason="registry entry is not a four-field list")

    author, repository, branch = data[0], data[1], data[3]
    if not all(isinstance(value, str) and value.strip() for value in (author, repository, branch)):
        return CheckResult(key, "invalid-entry", reason="registry entry has blank author, repository, or branch")

    url = raw_plugin_url(author, repository, branch)
    request = urllib.request.Request(url, headers=headers_for_url(url))
    opener = opener or urllib.request.urlopen

    try:
        with opener(request, timeout=15) as response:
            content = response.read(4096)
            if content.strip():
                return CheckResult(key, "present", url=url)
            return CheckResult(key, "empty", url=url, reason="root plugin.py is empty")
    except urllib.error.HTTPError as e:
        if e.code in {404, 410}:
            return CheckResult(key, "missing", url=url, reason=f"HTTP {e.code}")
        return CheckResult(key, "error", url=url, reason=f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        return CheckResult(key, "error", url=url, reason=str(e.reason))
    except Exception as e:
        return CheckResult(key, "error", url=url, reason=str(e))


def remove_registry_entries(registry, update_times, platform_metadata, keys):
    for key in keys:
        registry.pop(key, None)
        update_times.pop(key, None)
        platform_metadata.get("entries", {}).pop(key, None)


def print_result(result, apply_changes):
    if result.status == "present":
        print(f"[OK] {result.key}")
    elif result.removable:
        action = "Removing" if apply_changes else "Would remove"
        print(f"[-] {action} {result.key}: {result.status} plugin.py ({result.reason})")
    else:
        detail = f": {result.reason}" if result.reason else ""
        print(f"[!] Keeping {result.key}: {result.status}{detail}")


def cleanup_registry_files(
    registry_file=REGISTRY_FILE,
    update_times_file=UPDATE_TIMES_FILE,
    platform_metadata_file=PLATFORM_METADATA_FILE,
    apply_changes=False,
    sleep_seconds=0.2,
    keys=None,
    opener=None,
):
    registry = load_json_file(registry_file)
    if not isinstance(registry, dict):
        raise ValueError(f"Registry file {registry_file} does not contain a JSON object.")

    update_times_exists = os.path.exists(update_times_file)
    update_times = load_json_file(update_times_file, {}) if update_times_exists else {}
    if not isinstance(update_times, dict):
        raise ValueError(f"Update-times file {update_times_file} does not contain a JSON object.")

    platform_metadata_exists = os.path.exists(platform_metadata_file)
    platform_metadata = load_json_file(platform_metadata_file, {"version": 1, "entries": {}})
    if not isinstance(platform_metadata, dict):
        raise ValueError(f"Platform metadata file {platform_metadata_file} does not contain a JSON object.")
    if not isinstance(platform_metadata.get("entries", {}), dict):
        platform_metadata["entries"] = {}

    selected_keys = set(keys or [])
    results = []
    for key in registry:
        if key == "Idle":
            continue
        if selected_keys and key not in selected_keys:
            continue

        result = check_root_plugin_py(key, registry[key], opener=opener)
        results.append(result)
        print_result(result, apply_changes)

        if sleep_seconds:
            time.sleep(sleep_seconds)

    removable_keys = [result.key for result in results if result.removable]
    if apply_changes and removable_keys:
        remove_registry_entries(registry, update_times, platform_metadata, removable_keys)
        save_json_file(registry_file, registry)
        if update_times_exists:
            save_json_file(update_times_file, update_times)
        if platform_metadata_exists:
            save_json_file(platform_metadata_file, platform_metadata)

    stats = {
        "checked": len(results),
        "present": sum(1 for result in results if result.status == "present"),
        "would_remove": 0 if apply_changes else len(removable_keys),
        "removed": len(removable_keys) if apply_changes else 0,
        "errors": sum(1 for result in results if result.status in {"error", "invalid-entry"}),
    }
    return stats


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Remove public registry entries whose configured branch does not contain a root plugin.py.",
    )
    parser.add_argument("--registry", default=REGISTRY_FILE, help="Path to registry.json.")
    parser.add_argument("--update-times", default=UPDATE_TIMES_FILE, help="Path to update_times.json.")
    parser.add_argument(
        "--platform-metadata",
        default=PLATFORM_METADATA_FILE,
        help="Path to .github/platform_detection.json.",
    )
    parser.add_argument("--apply", action="store_true", help="Write removals to registry files.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between remote checks, in seconds.")
    parser.add_argument("--only", action="append", default=[], help="Only check this registry key. Can be repeated.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        stats = cleanup_registry_files(
            registry_file=args.registry,
            update_times_file=args.update_times,
            platform_metadata_file=args.platform_metadata,
            apply_changes=args.apply,
            sleep_seconds=args.sleep,
            keys=args.only,
        )
    except Exception as e:
        print(f"Registry cleanup failed: {e}", file=sys.stderr)
        return 1

    if args.apply:
        print(
            "Registry cleanup complete: "
            f"{stats['checked']} checked, {stats['removed']} removed, {stats['errors']} kept with errors."
        )
    else:
        print(
            "Dry run complete: "
            f"{stats['checked']} checked, {stats['would_remove']} removable, "
            f"{stats['errors']} kept with errors. Re-run with --apply to update files."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
