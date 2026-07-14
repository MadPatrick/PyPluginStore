import os
import sys
import json
import subprocess

# Adjust path relative to the current script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
REGISTRY_FILE_PATH = os.path.join(SCRIPT_DIR, '../../registry.json')
UPDATE_TIMES_FILE_PATH = os.path.join(SCRIPT_DIR, '../../update_times.json')
PLATFORM_METADATA_FILE_PATH = os.path.join(SCRIPT_DIR, '../../.github/platform_detection.json')
DEFAULT_GIT_HOST = "github.com"
SUPPORTED_GIT_HOSTS = ("github.com", "gitlab.com", "codeberg.org")
VALID_PLATFORM_METADATA_SOURCES = {"unknown", "legacy_detected", "detected", "reviewed"}
VALID_PLATFORM_METADATA_CONFIDENCE = {"unknown", "low", "medium", "high"}
GIT_REMOTE_TIMEOUT_SECONDS = 30

try:
    from detect_plugin_platforms import get_registry_entry_platforms
except ImportError:
    get_registry_entry_platforms = None

try:
    from cleanup_registry import check_root_plugin_py
except ImportError:
    check_root_plugin_py = None

def load_registry():
    print(f"Checking if registry file exists at: {REGISTRY_FILE_PATH}")
    if not os.path.isfile(REGISTRY_FILE_PATH):
        print(f"Registry file not found at: {REGISTRY_FILE_PATH}")
        sys.exit(1)

    with open(REGISTRY_FILE_PATH, 'r') as f:
        registry_data = json.load(f)

    validate_platform_metadata(registry_data)
    validate_update_times(registry_data)
        
    plugin_data = {}
    for key, data in registry_data.items():
        if key == "Idle":
            continue
        validate_registry_entry(key, data)
        plugin_data[key] = {
            "key": key,
            "author": data[0],
            "repository": data[1],
            "description": data[2],
            "branch": data[3]
        }
    return plugin_data


def normalize_platforms(platforms):
    if get_registry_entry_platforms is not None:
        return get_registry_entry_platforms(["", "", "", "", "", platforms])

    if isinstance(platforms, str):
        platforms = [platforms]
    if not isinstance(platforms, list):
        return []

    normalized = []
    for platform in platforms:
        platform_name = str(platform or "").strip().lower()
        if platform_name in {"linux", "windows"} and platform_name not in normalized:
            normalized.append(platform_name)
    return [platform for platform in ("linux", "windows") if platform in normalized]


def validate_platform_metadata(registry_data):
    if not os.path.isfile(PLATFORM_METADATA_FILE_PATH):
        return

    with open(PLATFORM_METADATA_FILE_PATH, 'r') as f:
        metadata = json.load(f)

    if not isinstance(metadata, dict):
        raise ValueError("Platform metadata must be a JSON object.")
    if metadata.get("version") != 1:
        raise ValueError("Platform metadata has an unsupported version.")

    entries = metadata.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("Platform metadata must contain an entries object.")

    registry_keys = {key for key in registry_data if key != "Idle"}
    for key, entry in entries.items():
        if key not in registry_keys:
            raise ValueError(f"Platform metadata contains stale entry '{key}'.")
        if not isinstance(entry, dict):
            raise ValueError(f"Platform metadata entry '{key}' must be an object.")

        registry_platforms = normalize_platforms(registry_data[key][5] if len(registry_data[key]) > 5 else [])
        metadata_platforms = normalize_platforms(entry.get("registry_platforms", []))
        if metadata_platforms != registry_platforms:
            raise ValueError(f"Platform metadata entry '{key}' does not match registry platforms.")

        if entry.get("source") not in VALID_PLATFORM_METADATA_SOURCES:
            raise ValueError(f"Platform metadata entry '{key}' has invalid source.")
        if entry.get("confidence") not in VALID_PLATFORM_METADATA_CONFIDENCE:
            raise ValueError(f"Platform metadata entry '{key}' has invalid confidence.")
        if not isinstance(entry.get("reviewed", False), bool):
            raise ValueError(f"Platform metadata entry '{key}' has invalid reviewed flag.")


def validate_update_times(registry_data):
    if not os.path.isfile(UPDATE_TIMES_FILE_PATH):
        return

    with open(UPDATE_TIMES_FILE_PATH, 'r') as f:
        update_times = json.load(f)

    if not isinstance(update_times, dict):
        raise ValueError("Update-times file must be a JSON object.")

    registry_keys = {key for key in registry_data if key != "Idle"}
    stale_keys = sorted(key for key in update_times if key not in registry_keys)
    if stale_keys:
        joined_keys = ", ".join(stale_keys)
        raise ValueError(f"Update-times file contains stale entries: {joined_keys}")


def validate_registry_entry(key, data):
    if not isinstance(data, list) or len(data) < 4:
        raise ValueError(f"Plugin '{key}' must be a list with owner, repository, description and branch.")

    if not key or key.startswith(".") or "/" in key or "\\" in key:
        raise ValueError(f"Plugin key '{key}' is invalid. Keys must be visible folder names without path separators.")

    for index, field_name in enumerate(("author", "repository", "description", "branch")):
        if not isinstance(data[index], str) or not data[index].strip():
            raise ValueError(f"Plugin '{key}' has an invalid {field_name}.")

    repository = data[1]
    if repository.startswith(".") or "/" in repository or "\\" in repository:
        raise ValueError(f"Plugin '{key}' has an invalid repository name '{repository}'.")

    if len(data) > 5:
        platforms = data[5]
        if isinstance(platforms, str):
            platforms = [platforms]
        if not isinstance(platforms, list) or not platforms:
            raise ValueError(f"Plugin '{key}' has invalid platform metadata.")
        for platform_name in platforms:
            if str(platform_name).strip().lower() not in {"linux", "windows"}:
                raise ValueError(f"Plugin '{key}' has unsupported platform '{platform_name}'.")


def split_registry_owner(author):
    author = str(author or "").strip().strip("/")
    for host in SUPPORTED_GIT_HOSTS:
        if author.lower() == host:
            return host, ""
        if author.lower().startswith(host + "/"):
            return host, author[len(host) + 1:]
    return DEFAULT_GIT_HOST, author


def build_repository_url(author, repository):
    host, owner_path = split_registry_owner(author)
    path_parts = [part for part in (owner_path + "/" + repository).split("/") if part]
    return "https://" + host + "/" + "/".join(path_parts)


def validate_repository(author, repository, branch):
    repo_url = build_repository_url(author, repository)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    repo_clone_cmd = ["git", "ls-remote", "--heads", repo_url, branch]
    try:
        result = subprocess.run(
            repo_clone_cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=GIT_REMOTE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(f"Timed out executing command after {GIT_REMOTE_TIMEOUT_SECONDS}s: {' '.join(repo_clone_cmd)}")
        return False
    if result.returncode != 0:
        print(f"Error executing command: {' '.join(repo_clone_cmd)}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
    return result.returncode == 0 and bool(result.stdout.strip())


def validate_root_plugin_py(key, author, repository, branch, opener=None):
    if check_root_plugin_py is None:
        print("Root plugin.py validation is unavailable because cleanup_registry.py could not be imported.")
        return False

    result = check_root_plugin_py(
        key,
        [author, repository, "", branch],
        opener=opener,
    )
    if result.status == "present":
        return True

    detail = f" ({result.reason})" if result.reason else ""
    print(f"Root plugin.py check failed for {key}: {result.status}{detail}")
    if result.url:
        print(f"Checked URL: {result.url}")
    return False


def main():
    print("Loading registry file...")
    plugin_data = load_registry()
    print(f"Loaded {len(plugin_data)} plugins.")

    if not plugin_data:
        print("No plugin data found, exiting.")
        sys.exit(1)

    all_valid = True
    for key, data in plugin_data.items():
        print(f"Validating repository for plugin: {key}")
        repository_is_valid = validate_repository(data["author"], data["repository"], data["branch"])
        plugin_file_is_valid = False
        if repository_is_valid:
            plugin_file_is_valid = validate_root_plugin_py(
                key,
                data["author"],
                data["repository"],
                data["branch"],
            )

        if repository_is_valid and plugin_file_is_valid:
            print(f"✅ Repository {data['author']}/{data['repository']} on branch {data['branch']} is valid.")
        else:
            print(f"❌ Repository {data['author']}/{data['repository']} on branch {data['branch']} is invalid.")
            all_valid = False

    if not all_valid:
        print("One or more plugins are invalid.")
        sys.exit(1)  # Exit with a non-zero code to indicate failure

if __name__ == "__main__":
    main()
