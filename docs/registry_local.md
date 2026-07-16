# registry_local.json How-To

Use `registry_local.json` for plugins that should only appear in your own PyPluginStore installation: private repositories, local forks, test branches, or plugins that are not ready for the public registry.

## Manage Entries in the UI

Open the Plugin Store custom page and select **Local registry** in the header. The manager lets you:

- Add a blank entry for a private, local, or unpublished plugin.
- Select a public plugin and prefill a new local override.
- Edit the repository source, description, or branch of an existing local entry.
- Delete an override without deleting the installed plugin directory.

The plugin key cannot be renamed while editing. To use a different key, create a new entry and delete the old one.

Saving validates the values locally; it does not contact the repository or install the plugin. Use SSH keys or the Git credential configuration of the Domoticz OS user for private access. Repository URLs containing HTTP usernames or passwords are rejected so credentials are not persisted through the UI.

Every save and delete includes a revision of the file that was loaded. If another browser tab or process changes `registry_local.json`, PyPluginStore keeps your form values and asks you to reload instead of overwriting the newer file.

If the file contains malformed JSON, the dialog shows the file path and parse error and stays read-only. Correct the file manually, then select **Reload entries**.

UI-created and UI-edited entries use one complete **Repository source** and do not write platform metadata. Existing entries that are not edited keep their current representation and platform values.

## Advanced Manual Editing

The UI is the recommended workflow. You can still create or edit the file directly in the installed PyPluginStore folder:

- Linux: `/path/to/domoticz/plugins/00-PyPluginStore/registry_local.json`
- Windows: `C:\path\to\domoticz\plugins\00-PyPluginStore\registry_local.json`

PyPluginStore loads the public `registry.json` first, then overlays `registry_local.json`. Local entries show a **Local** badge in the Plugin Store UI. If a local entry uses the same key as a public entry, the local entry wins.

After editing the file, click **Refresh status** in the Plugin Store UI or restart Domoticz.

## Manual File Format

Use object-style entries. The file itself must be valid JSON: double-quoted strings, no comments, and no trailing commas. Manual entries may keep separate `owner` and `repository` fields and optional platform metadata for backward compatibility.

```json
{
    "MyPlugin": {
        "owner": "my-github-user",
        "repository": "domoticz-my-plugin",
        "description": "Description shown in PyPluginStore.",
        "branch": "main",
        "platforms": ["linux", "windows"]
    }
}
```

The top-level key, `MyPlugin` in this example, is the plugin key and install folder name. Keep it simple: no slashes, backslashes, empty names, or names starting with `.`.

## Fields

| Field | Use |
| --- | --- |
| `owner` | GitHub owner, hosted path such as `gitlab.com/group`, or a full clone URL. |
| `repository` | Repository name. Omit it when `owner` is already a full clone URL. |
| `description` | Text shown in the Plugin Store UI. |
| `branch` | Branch to clone or update, usually `main` or `master`. Defaults to `master` if omitted. |
| `platforms` | Optional list: `["linux"]`, `["windows"]`, or `["linux", "windows"]`. Omitted means unknown, not blocked. |

`author` and `repo` are accepted aliases for older files. The UI stores a complete clone source in `owner` and omits `repository`; both representations are supported.

## Common Use Cases

### Private GitHub Repository Over SSH

Use this when the Domoticz host has an SSH key that can read the private repository.

```json
{
    "HeatingLab": {
        "owner": "git@github.com:my-org/domoticz-heating-lab.git",
        "description": "Private heating automation plugin.",
        "branch": "main",
        "platforms": ["linux"]
    }
}
```

### Private Repository Over HTTPS

Use this when your Git credential helper or URL configuration already gives the Domoticz user access.

```json
{
    "WeatherLab": {
        "owner": "https://github.com/my-org/domoticz-weather-lab.git",
        "description": "Private weather station plugin.",
        "branch": "main",
        "platforms": ["linux", "windows"]
    }
}
```

### GitLab or Codeberg Plugin

Include the host name in `owner`.

```json
{
    "SabnzbdLab": {
        "owner": "gitlab.com/my-group",
        "repository": "domoticz-sabnzbd-lab",
        "description": "Local GitLab plugin entry.",
        "branch": "main",
        "platforms": ["linux"]
    },
    "StromerLab": {
        "owner": "codeberg.org/my-user",
        "repository": "domoticz-stromer-lab",
        "description": "Local Codeberg plugin entry.",
        "branch": "main",
        "platforms": ["linux", "windows"]
    }
}
```

### Local or LAN Git Repository

Use a full clone URL in `owner`. This also works for local bare repositories.

```json
{
    "GarageController": {
        "owner": "file:///srv/git/domoticz-garage-controller.git",
        "description": "Garage controller plugin from a local Git repository.",
        "branch": "main",
        "platforms": ["linux"]
    }
}
```

### Override a Public Registry Entry

Use the same key as the public entry. PyPluginStore keeps the public registry available, but this one local entry replaces the public definition on your installation.

```json
{
    "deCONZ": {
        "owner": "my-github-user",
        "repository": "domoticz-deconz-fork",
        "description": "Local deCONZ fork with custom patches.",
        "branch": "my-domoticz-branch",
        "platforms": ["linux"]
    }
}
```

### Repo Mismatch Warning

**Repo mismatch** means an installed plugin's Git checkout does not match the configured registry entry for that plugin key. PyPluginStore does not update it automatically, because it may be a fork or branch you chose on purpose.

You have two good options:

- If the installed repo is the one you want, open **Local registry** and add a matching repository source and branch.
- If you want the managed registry repo instead, remove the mismatched plugin folder, install the registry entry, and restart Domoticz. This works as long as the `plugin.py` metadata keeps the same `<plugin key="...">`, because Domoticz uses that key to match the existing hardware entry.

Deleting a local override never removes the installed plugin. If a public entry becomes active again and points elsewhere, the installed checkout may show **Repo mismatch** until the registry and checkout agree.

### Test a Feature Branch

Point a local entry at a branch before you publish or submit it to the public registry.

```json
{
    "MyPluginBeta": {
        "owner": "my-github-user",
        "repository": "domoticz-my-plugin",
        "description": "Beta branch of my Domoticz plugin.",
        "branch": "feature/new-hardware-support",
        "platforms": ["linux", "windows"]
    }
}
```

## Complete Example

```json
{
    "HeatingLab": {
        "owner": "git@github.com:my-org/domoticz-heating-lab.git",
        "description": "Private heating automation plugin.",
        "branch": "main",
        "platforms": ["linux"]
    },
    "SabnzbdLab": {
        "owner": "gitlab.com/my-group",
        "repository": "domoticz-sabnzbd-lab",
        "description": "Local GitLab plugin entry.",
        "branch": "main",
        "platforms": ["linux"]
    },
    "deCONZ": {
        "owner": "my-github-user",
        "repository": "domoticz-deconz-fork",
        "description": "Local deCONZ fork with custom patches.",
        "branch": "my-domoticz-branch",
        "platforms": ["linux"]
    }
}
```

## Troubleshooting

For manually edited files, validate the JSON before reloading:

```bash
python -m json.tool /path/to/domoticz/plugins/00-PyPluginStore/registry_local.json
```

Then open **Local registry** and select **Reload entries**, or click **Refresh status** on the main page.

If a private plugin appears but install fails, check that the Domoticz OS user can run `git ls-remote` against the same URL and branch. PyPluginStore cannot install a private repository until Git access works outside PyPluginStore too.
