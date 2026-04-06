import json
import os
import urllib.request
import urllib.parse
from urllib.error import HTTPError

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(SCRIPT_DIR, '../../registry.json')

def get_existing_repos(registry):
    existing = set()
    for key, data in registry.items():
        if key == "Idle":
            continue
        owner = data[0].lower()
        repo = data[1].lower()
        existing.add(f"{owner}/{repo}")
    return existing

def search_github():
    query = urllib.parse.quote('domoticz plugin language:python')
    url = f'https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=100'
    headers = {'User-Agent': 'Domoticz-Plugin-Scanner', 'Accept': 'application/vnd.github.v3+json'}
    
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = f'token {token}'
        
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data.get('items', [])
    except HTTPError as e:
        print(f"Error fetching from GitHub API: {e}")
        return []

def main():
    with open(REGISTRY_FILE, 'r') as f:
        registry = json.load(f)
        
    existing_repos = get_existing_repos(registry)
    new_plugins = 0
    
    items = search_github()
    for repo in items:
        full_name = repo['full_name'].lower()
        if full_name not in existing_repos:
            owner = repo['owner']['login']
            repo_name = repo['name']
            description = repo['description'] or f"{repo_name} plugin for Domoticz"
            default_branch = repo['default_branch']
            
            key = repo_name
            if key in registry:
                key = f"{owner}-{repo_name}"
                
            registry[key] = [
                owner,
                repo_name,
                description,
                default_branch
            ]
            existing_repos.add(full_name)
            new_plugins += 1
            print(f"Added new plugin: {full_name}")

    if new_plugins > 0:
        with open(REGISTRY_FILE, 'w') as f:
            json.dump(registry, f, indent=4)
            f.write('\n') # add trailing newline to match conventional json format
        print(f"Updated registry.json with {new_plugins} new plugins.")
    else:
        print("No new plugins found.")

if __name__ == '__main__':
    main()
