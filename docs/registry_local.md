# registry_local.json How-To

Use `registry_local.json` for plugins that should only appear in your own PyPluginStore installation: private repositories, local forks, test branches, or plugins that are not ready for the public registry.

Create the file in the installed PyPluginStore folder:

- Linux: `/path/to/domoticz/plugins/00-PyPluginStore/registry_local.json`
- Windows: `C:\path\to\domoticz\plugins\00-PyPluginStore\registry_local.json`

PyPluginStore loads the public `registry.json` first, then overlays `registry_local.json`. Local entries show a **Local** badge in the Plugin Store UI. If a local entry uses the same key as a public entry, the local entry wins.

After editing the file, click **Refresh status** in the Plugin Store UI or restart Domoticz.

## Recommended Format

Use object-style entries. The file itself must be valid JSON: double-quoted strings, no comments, and no trailing commas.

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

`author` and `repo` are accepted aliases for older files, but new entries should use `owner` and `repository`.

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

Validate the JSON before restarting:

```bash
python -m json.tool /path/to/domoticz/plugins/00-PyPluginStore/registry_local.json
```

If a private plugin appears but install fails, check that the Domoticz OS user can run `git ls-remote` against the same URL and branch. PyPluginStore cannot install a private repository until Git access works outside PyPluginStore too.
