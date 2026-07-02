import json
import os
import sys
import urllib.request
import urllib.parse
from urllib.error import HTTPError
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from detect_plugin_platforms import (
    choose_platforms_for_registry,
    detect_platforms_for_repo,
    decision_confidence,
    decision_platforms,
    ensure_platform_metadata_for_registry,
    get_registry_entry_platforms,
    load_platform_metadata,
    normalize_platforms,
    platform_metadata_identity,
    save_platform_metadata,
    set_registry_entry_platforms,
    update_platform_metadata_entry,
)

REGISTRY_FILE = os.path.join(SCRIPT_DIR, '../../registry.json')
UPDATE_TIMES_FILE = os.path.join(SCRIPT_DIR, '../../update_times.json')
PLATFORM_METADATA_FILE = os.path.join(SCRIPT_DIR, '../../.github/platform_detection.json')
DEFAULT_GIT_HOST = "github.com"
SUPPORTED_GIT_HOSTS = ("github.com", "gitlab.com", "codeberg.org")

# Repositories that should never be added to or kept in the registry.
REPO_BLOCKLIST = {
    "ycahome/pp-manager",
    "adrighem/pp-manager",
    "adrighem/pypluginstore",
    "domoticz/domoticz",
}

def is_valid_plugin_repo(repo_name):
    return bool(repo_name) and not repo_name.startswith('.') and '/' not in repo_name and '\\' not in repo_name

def split_registry_owner(author):
    author = str(author or "").strip().strip("/")
    for host in SUPPORTED_GIT_HOSTS:
        if author.lower() == host:
            return host, ""
        if author.lower().startswith(host + "/"):
            return host, author[len(host) + 1:]
    return DEFAULT_GIT_HOST, author


def get_registry_owner(host, owner_path):
    host = str(host or DEFAULT_GIT_HOST).strip().lower()
    owner_path = str(owner_path or "").strip().strip("/")
    if host == DEFAULT_GIT_HOST:
        return owner_path
    return host + "/" + owner_path


def get_repository_identity(owner, repo):
    host, owner_path = split_registry_owner(owner)
    return f"{host}/{owner_path}/{repo}".lower()


def normalize_full_name(owner, repo):
    return f"{owner}/{repo}".lower()

def get_repo_block_reason(owner, repo):
    if normalize_full_name(owner, repo) in REPO_BLOCKLIST:
        return "Repo blocklisted"
    return None

def get_repo_skip_reason(repo):
    if repo.get('archived'):
        return "Repo archived"
    if repo.get('disabled'):
        return "Repo disabled"
    if repo.get('empty') or repo.get('empty_repo'):
        return "Repo empty"

    size = repo.get('size')
    if size is not None:
        try:
            if int(size) <= 0:
                return "Repo empty"
        except (TypeError, ValueError):
            pass

    return None

def remove_registry_entry(registry, update_times, platform_metadata, key, reason):
    print(f"[-] Removing {key} ({reason})")
    del registry[key]
    if key in update_times:
        del update_times[key]
    platform_metadata.get("entries", {}).pop(key, None)

def build_registry_entry(owner, repo_name, description, branch, platforms=None):
    entry = [owner, repo_name, description, branch]
    normalized_platforms = normalize_platforms(platforms)
    if normalized_platforms:
        entry = set_registry_entry_platforms(entry, normalized_platforms)
    return entry


def github_headers():
    headers = {'User-Agent': 'Domoticz-Plugin-Scanner', 'Accept': 'application/vnd.github.v3+json'}
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = f'token {token}'
    return headers


def gitlab_headers():
    headers = {'User-Agent': 'Domoticz-Plugin-Scanner', 'Accept': 'application/json'}
    token = os.environ.get('GITLAB_TOKEN')
    if token:
        headers['PRIVATE-TOKEN'] = token
    return headers


def generic_headers():
    return {'User-Agent': 'Domoticz-Plugin-Scanner', 'Accept': 'application/json'}


def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or generic_headers())
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except HTTPError as e:
        if e.code == 404:
            return "DELETED"
        print(f"Error fetching {url}: {e}")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None


def normalize_gitlab_project(project):
    full_name = project.get('path_with_namespace') or project.get('full_name') or ""
    if "/" not in full_name:
        return None
    owner_path, repo_name = full_name.rsplit("/", 1)
    return {
        "host": "gitlab.com",
        "archived": bool(project.get('archived')),
        "disabled": False,
        "empty_repo": bool(project.get('empty_repo', False)),
        "size": project.get('repository_size', project.get('size', 1)),
        "full_name": full_name,
        "owner": {"login": owner_path},
        "name": repo_name,
        "description": project.get('description') or "",
        "default_branch": project.get('default_branch') or "master",
        "pushed_at": project.get('last_activity_at') or project.get('updated_at'),
    }


def normalize_codeberg_repo(repo):
    full_name = repo.get('full_name') or ""
    if "/" not in full_name:
        return None
    owner_path, repo_name = full_name.rsplit("/", 1)
    return {
        "host": "codeberg.org",
        "archived": bool(repo.get('archived')),
        "disabled": False,
        "empty": bool(repo.get('empty')),
        "size": repo.get('size', 1),
        "full_name": full_name,
        "owner": {"login": owner_path},
        "name": repo_name,
        "description": repo.get('description') or "",
        "default_branch": repo.get('default_branch') or "master",
        "pushed_at": repo.get('updated_at') or repo.get('pushed_at'),
    }


def raw_plugin_url_for_repo(repo):
    host = repo.get('host', DEFAULT_GIT_HOST)
    owner = repo.get('owner', {}).get('login', '')
    repo_name = repo.get('name', '')
    branch = repo.get('default_branch') or 'master'
    path = "/".join(urllib.parse.quote(part, safe="") for part in (owner + "/" + repo_name).split("/") if part)
    branch = urllib.parse.quote(branch, safe="")
    if host == "gitlab.com":
        return f"https://gitlab.com/{path}/-/raw/{branch}/plugin.py"
    if host == "codeberg.org":
        return f"https://codeberg.org/{path}/raw/branch/{branch}/plugin.py"
    return f"https://raw.githubusercontent.com/{path}/{branch}/plugin.py"


def has_root_plugin_py(repo):
    url = raw_plugin_url_for_repo(repo)
    headers = gitlab_headers() if repo.get('host') == "gitlab.com" else generic_headers()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read(4096).strip() != b""
    except Exception:
        return False


def get_github_repo_info(owner, repo):
    url = f'https://api.github.com/repos/{owner}/{repo}'
    return fetch_json(url, github_headers())


def get_gitlab_repo_info(owner_path, repo):
    project_path = urllib.parse.quote(owner_path + "/" + repo, safe="")
    data = fetch_json(f'https://gitlab.com/api/v4/projects/{project_path}', gitlab_headers())
    if data == "DELETED" or data is None:
        return data
    return normalize_gitlab_project(data)


def get_codeberg_repo_info(owner_path, repo):
    path = "/".join(urllib.parse.quote(part, safe="") for part in (owner_path + "/" + repo).split("/"))
    data = fetch_json(f'https://codeberg.org/api/v1/repos/{path}', generic_headers())
    if data == "DELETED" or data is None:
        return data
    return normalize_codeberg_repo(data)


def get_repo_info(owner, repo):
    host, owner_path = split_registry_owner(owner)
    if host == "gitlab.com":
        return get_gitlab_repo_info(owner_path, repo)
    if host == "codeberg.org":
        return get_codeberg_repo_info(owner_path, repo)
    return get_github_repo_info(owner_path, repo)

def search_github():
    # Multiple queries to be more comprehensive
    queries = [
        'domoticz plugin',
        'domoticz integration',
        'domoticz python',
        'topic:domoticz-plugin'
    ]

    all_items = []
    seen_full_names = set()

    headers = github_headers()

    for query in queries:
        print(f"Searching for: {query}")
        encoded_query = urllib.parse.quote(query)
        url = f'https://api.github.com/search/repositories?q={encoded_query}&sort=updated&order=desc&per_page=100'

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                items = data.get('items', [])
                for item in items:
                    if item['full_name'] not in seen_full_names:
                        all_items.append(item)
                        seen_full_names.add(item['full_name'])
        except HTTPError as e:
            print(f"Error searching GitHub for '{query}': {e}")

    return all_items


def search_gitlab():
    queries = [
        'domoticz plugin',
        'domoticz python plugin',
    ]
    all_items = []
    seen_full_names = set()

    for query in queries:
        print(f"Searching GitLab for: {query}")
        encoded_query = urllib.parse.quote(query)
        url = (
            'https://gitlab.com/api/v4/projects?'
            f'search={encoded_query}&simple=true&per_page=100&order_by=last_activity_at&sort=desc'
        )
        data = fetch_json(url, gitlab_headers())
        if not isinstance(data, list):
            continue
        for item in data:
            repo = normalize_gitlab_project(item)
            if repo and repo['full_name'] not in seen_full_names and has_root_plugin_py(repo):
                all_items.append(repo)
                seen_full_names.add(repo['full_name'])

    return all_items


def search_codeberg():
    queries = [
        'domoticz',
        'domoticz plugin',
    ]
    all_items = []
    seen_full_names = set()

    for query in queries:
        print(f"Searching Codeberg for: {query}")
        encoded_query = urllib.parse.quote(query)
        url = f'https://codeberg.org/api/v1/repos/search?q={encoded_query}&limit=50'
        data = fetch_json(url, generic_headers())
        items = data.get('data', []) if isinstance(data, dict) else []
        for item in items:
            repo = normalize_codeberg_repo(item)
            if repo and repo['full_name'] not in seen_full_names and has_root_plugin_py(repo):
                all_items.append(repo)
                seen_full_names.add(repo['full_name'])

    return all_items


def search_repositories():
    return search_github() + search_gitlab() + search_codeberg()

def main():
    if not os.path.exists(REGISTRY_FILE):
        print(f"Registry file not found at {REGISTRY_FILE}")
        return

    with open(REGISTRY_FILE, 'r') as f:
        registry = json.load(f)
        
    update_times = {}
    if os.path.exists(UPDATE_TIMES_FILE):
        with open(UPDATE_TIMES_FILE, 'r') as f:
            update_times = json.load(f)

    platform_metadata_exists = os.path.exists(PLATFORM_METADATA_FILE)
    platform_metadata = ensure_platform_metadata_for_registry(
        load_platform_metadata(PLATFORM_METADATA_FILE),
        registry,
        manual_changes_are_reviewed=platform_metadata_exists,
    )

    stats = {"updated": 0, "removed": 0, "added": 0, "metadata_updated": 0}

    # 1. Sync Existing Plugins
    print("Syncing existing plugins...")
    for key in list(registry.keys()):
        if key == "Idle": continue

        data = registry[key]
        owner, repo_name = data[0], data[1]

        block_reason = get_repo_block_reason(owner, repo_name)
        if block_reason:
            remove_registry_entry(registry, update_times, platform_metadata, key, block_reason)
            stats["removed"] += 1
            continue

        # Determine if we need to fetch info (for existing plugins, we check 1 in 4 to stay under rate limits if no token)
        # In GitHub Actions, GITHUB_TOKEN is present, so we can check all.
        info = get_repo_info(owner, repo_name)

        if info == "DELETED":
            remove_registry_entry(registry, update_times, platform_metadata, key, "Repo deleted")
            stats["removed"] += 1
        elif info:
            skip_reason = get_repo_skip_reason(info)
            if skip_reason:
                remove_registry_entry(registry, update_times, platform_metadata, key, skip_reason)
                stats["removed"] += 1
            else:
                # Update metadata. Registry branches are curated and must not
                # follow repository default-branch changes automatically.
                updated_desc = info.get('description') or data[2]
                registry_branch = data[3]
                updated_at = info.get('pushed_at') or info.get('updated_at')
                current_platforms = get_registry_entry_platforms(data)
                platform_decision = detect_platforms_for_repo(owner, repo_name, registry_branch, info)
                detected_platforms = decision_platforms(platform_decision)
                metadata_entry = platform_metadata["entries"].get(key, {})
                if metadata_entry.get("identity") != platform_metadata_identity(owner, repo_name, registry_branch):
                    metadata_entry = {}
                next_platforms, platform_policy = choose_platforms_for_registry(
                    current_platforms,
                    platform_decision,
                    metadata_entry=metadata_entry,
                    is_new=False,
                )

                # Check if changed
                if (updated_desc != data[2] or
                    update_times.get(key) != updated_at or
                    next_platforms != current_platforms):

                    print(f"[*] Updating {key}")
                    if detected_platforms and next_platforms == current_platforms:
                        print(
                            f"    keeping platforms {current_platforms or ['unknown']}; "
                            f"detected {detected_platforms} "
                            f"({decision_confidence(platform_decision)}, {platform_policy})"
                        )
                    elif next_platforms != current_platforms:
                        print(
                            f"    platforms {current_platforms or ['unknown']} -> {next_platforms} "
                            f"({decision_confidence(platform_decision)}, {platform_policy})"
                        )
                    registry[key] = build_registry_entry(
                        owner,
                        repo_name,
                        updated_desc,
                        registry_branch,
                        next_platforms
                    )
                    if updated_at:
                        update_times[key] = updated_at
                    stats["updated"] += 1

                if platform_decision is not None and platform_policy != "unchanged":
                    before = json.dumps(platform_metadata["entries"].get(key, {}), sort_keys=True)
                    platform_metadata = update_platform_metadata_entry(
                        platform_metadata,
                        key,
                        owner,
                        repo_name,
                        registry_branch,
                        next_platforms,
                        decision=platform_decision,
                        policy_action=platform_policy,
                    )
                    after = json.dumps(platform_metadata["entries"].get(key, {}), sort_keys=True)
                    if after != before:
                        stats["metadata_updated"] += 1

        # Throttle to respect rate limits
        if not os.environ.get('GITHUB_TOKEN'):
            time.sleep(1)

    # 2. Discover New Plugins
    print("Searching for new plugins...")
    new_items = search_repositories()
    existing_full_names = {
        get_repository_identity(v[0], v[1])
        for k, v in registry.items()
        if k != "Idle" and isinstance(v, list) and len(v) >= 2
    }

    for repo in new_items:
        repo_host = repo.get('host', DEFAULT_GIT_HOST)
        owner = repo['owner']['login']
        repo_name = repo['name']
        registry_owner = get_registry_owner(repo_host, owner)
        full_name = get_repository_identity(registry_owner, repo_name)
        if full_name not in existing_full_names:
            block_reason = get_repo_block_reason(owner, repo_name)
            if block_reason:
                print(f"[-] Skipping {repo['full_name']} ({block_reason})")
                continue

            skip_reason = get_repo_skip_reason(repo)
            if skip_reason:
                print(f"[-] Skipping {repo['full_name']} ({skip_reason})")
                continue

            if not is_valid_plugin_repo(repo_name):
                print(f"[-] Skipping {repo['full_name']} (Invalid plugin repository name)")
                continue

            description = repo['description'] or f"{repo_name} plugin for Domoticz"
            default_branch = repo['default_branch']
            pushed_at = repo.get('pushed_at') or repo.get('updated_at')
            platform_decision = detect_platforms_for_repo(registry_owner, repo_name, default_branch, repo)
            platforms, platform_policy = choose_platforms_for_registry(
                [],
                platform_decision,
                metadata_entry=None,
                is_new=True,
            )

            key = repo_name
            if key in registry:
                key = f"{owner}-{repo_name}"

            print(f"[+] Adding {key}")
            detected_platforms = decision_platforms(platform_decision)
            if detected_platforms and not platforms:
                print(
                    f"    leaving platforms unknown; detected {detected_platforms} "
                    f"({decision_confidence(platform_decision)}, {platform_policy})"
                )
            elif platforms:
                print(f"    platforms {platforms} ({decision_confidence(platform_decision)}, {platform_policy})")
            registry[key] = build_registry_entry(
                registry_owner,
                repo_name,
                description,
                default_branch,
                platforms
            )
            if pushed_at:
                update_times[key] = pushed_at
            before = json.dumps(platform_metadata["entries"].get(key, {}), sort_keys=True)
            platform_metadata = update_platform_metadata_entry(
                platform_metadata,
                key,
                registry_owner,
                repo_name,
                default_branch,
                platforms,
                decision=platform_decision,
                policy_action=platform_policy,
            )
            after = json.dumps(platform_metadata["entries"].get(key, {}), sort_keys=True)
            if after != before:
                stats["metadata_updated"] += 1
            stats["added"] += 1

    # 3. Save Results
    if stats["updated"] > 0 or stats["removed"] > 0 or stats["added"] > 0 or stats["metadata_updated"] > 0:
        platform_metadata = ensure_platform_metadata_for_registry(platform_metadata, registry)
        with open(REGISTRY_FILE, 'w') as f:
            json.dump(registry, f, indent=4)
            f.write('\n')
        with open(UPDATE_TIMES_FILE, 'w') as f:
            json.dump(update_times, f, indent=4)
            f.write('\n')
        save_platform_metadata(platform_metadata, PLATFORM_METADATA_FILE)
        print(
            "Registry updated: "
            f"{stats['added']} added, {stats['updated']} updated, "
            f"{stats['removed']} removed, {stats['metadata_updated']} metadata updated."
        )
    else:
        print("No changes needed.")

if __name__ == '__main__':
    main()
