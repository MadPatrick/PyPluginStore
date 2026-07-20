import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILE = os.path.join(SCRIPT_DIR, 'registry.json')
SCRIPTS_DIR = os.path.join(SCRIPT_DIR, ".github", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from registry_records import RegistryRecord
from scan_github_plugins import get_repo_info

def main():
    with open(REGISTRY_FILE, 'r') as f:
        registry = json.load(f)

    print(f"Auditing {len(registry)} plugins...")

    for key, data in list(registry.items()):
        if key == "Idle": continue

        record = RegistryRecord.from_entry(key, data)
        owner = record.owner
        repo_name = record.repository
        desc = record.description

        print(f"Checking {owner}/{repo_name}...", end=' ', flush=True)

        info = get_repo_info(owner, repo_name)

        if info == "DELETED":
            print("❌ DELETED (Should be removed)")
        elif info:
            if info.get('archived'):
                print("⚠️ ARCHIVED (Should we remove?)")
            else:
                current_desc = info.get('description', '')
                if current_desc and current_desc != desc:
                    print("📝 Description out of date")
                else:
                    print("✅ OK")
        else:
            print("❓ Unknown Error")

        # Avoid hitting rate limits
        time.sleep(0.5)

if __name__ == '__main__':
    main()
