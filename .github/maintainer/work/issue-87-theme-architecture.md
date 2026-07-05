# Issue 87 Theme Management Architecture

Research date: 2026-07-04

This is a replacement architecture proposal for issue #87. It is based on current PyPluginStore structure plus a sample of real Domoticz theme repositories.

## Research Findings

Sources inspected:

- Domoticz theming docs: https://wiki.domoticz.com/How_to_theme_Domoticz
- Domoticz built-in styles: https://github.com/domoticz/domoticz/tree/development/www/styles
- Nightglass: https://github.com/galadril/Domoticz-Nightglass-Theme
- Aurora: https://github.com/flatsiedatsie/domoticz-aurora-theme
- Machinon: https://github.com/domoticz/Machinon
- OsiDark: https://github.com/basvdijk/domoticz-osidark-theme
- Darkcula: https://github.com/hakaesbe/domoticz-theme-darkcula
- Techie: https://github.com/maxwroc/techie
- Existing theme manager plugin: https://github.com/galadril/domoticz-theme-manager

Important findings:

- Domoticz themes live under `www/styles/<theme-folder>/`.
- The modern required entry point is `custom.css`. `style.css` is not the theme entry file.
- Optional files include `custom.js`, `common.css`, `dark.css`, `base.css`, fonts, images, and other CSS/JS assets.
- Domoticz serves missing theme files from `www/styles/default/`, so a valid theme can be very small.
- New theme folders usually require a Domoticz restart before they appear in the UI. Updates usually require a browser hard refresh, not a service restart.
- Themes can include JavaScript. They are not Python plugins, but they can still execute in the Domoticz browser context and should be treated as trusted code.
- Not all theme repositories can be cloned directly into the final style folder:
  - Nightglass, Aurora, Machinon, Darkcula, and Techie are direct-clone layouts with `custom.css` at repo root.
  - OsiDark keeps installable output in `dist/OsiDark/custom.css`; cloning the repo directly into `www/styles/osi-dark` would not create a usable theme.
  - Some repositories include extra non-theme content, so validation should happen before exposing or updating files in `www/styles`.
- Domoticz built-in themes currently include `default`, `dark-th3me`, `element-dark`, `element-light`, `elemental`, `simple-blue`, and `simple-gray`. These must be protected from removal.
- The existing standalone theme manager proves the use case, but it is Linux-only, GitHub-only, shell-string based, and does not validate theme layouts. PyPluginStore should reuse the idea, not the architecture.

## Recommendation

Implement theme management as a separate catalog in PyPluginStore, not as plugin management with renamed commands.

Themes should share low-level helpers with plugins where appropriate:

- Git URL parsing and clone URL building.
- Git fetch/status/ahead-behind logic.
- Safe path containment and key validation patterns.
- API bridge response style.

Themes should not share plugin-specific state directly:

- Keep `theme_data`, `theme_registry_entries`, `theme_update_status`, `local_theme_keys`, and `installed_theme_folders` separate from plugin equivalents.
- Do not reuse `UpdateStatusService` as-is because it writes into `plugin.update_status` and assumes `plugin.plugin_data`.
- Do not install dependencies or trigger plugin-specific restart messaging.

## Registry Schema

Add a remote-first `themes.json` with bundled fallback and a private overlay `themes_local.json`, matching the plugin registry behavior.

Use an explicit install plan so direct-clone and subdirectory-only themes are both supported:

```json
{
  "nightglass": {
    "display_name": "Nightglass",
    "author": "galadril",
    "repository": "Domoticz-Nightglass-Theme",
    "branch": "main",
    "description": "Modern dark Domoticz theme with presets and UI enhancements.",
    "target_dir": "nightglass",
    "source_path": ".",
    "entry_files": ["custom.css"],
    "contains_javascript": true,
    "requires_restart": "first_install"
  },
  "osi-dark": {
    "display_name": "OsiDark",
    "author": "basvdijk",
    "repository": "domoticz-osidark-theme",
    "branch": "master",
    "description": "Responsive Domoticz theme for phone, tablet, and desktop.",
    "target_dir": "osi-dark",
    "source_path": "dist/OsiDark",
    "entry_files": ["custom.css"],
    "contains_javascript": false,
    "requires_restart": "first_install"
  }
}
```

Schema notes:

- `target_dir` is the actual folder under `www/styles/`. It may differ from the registry key and display name.
- `source_path` is copied from the repository checkout into the target folder. Use `"."` for direct-clone themes.
- `entry_files` starts with `custom.css` and can later support themes with additional required files.
- `contains_javascript` should be set from registry metadata and verified by scanning the resolved source path for `.js`.
- `requires_restart` should default to `first_install`.
- Keep host support aligned with plugin registries: GitHub, GitLab, Codeberg, SSH, and `file://` where already supported by existing clone helpers.

## Backend Architecture

### Paths

Extend `HostRuntime` with theme-specific paths:

```python
def themes_dir(self):
    return os.path.join(self.domoticz_dir(), "www", "styles")

def theme_sources_dir(self):
    return os.path.join(self.plugin_home_folder(), ".theme_sources")

def resolve_theme_dir(self, theme_key_or_target_dir):
    # validate name and ensure the result stays inside themes_dir()
```

Use a separate `validate_theme_key` or generic safe folder validator. Allow registry keys to be lowercase, but do not require target folders to be lowercase because existing themes use names like `OsiDark` and user installations may be case-sensitive.

### Installation Model

Use a staging-and-mirror model for all managed themes:

1. Clone or update the source repository under `<plugin_home>/.theme_sources/<theme_key>/`.
2. Resolve `source_path` inside that checkout.
3. Validate required entry files, starting with `custom.css`.
4. Scan source files for basic metadata:
   - Has `custom.css`.
   - Has `custom.js` or any `.js`.
   - Has `theme.json`.
   - Optional preview image if configured.
5. Mirror the validated source directory into `<domoticz>/www/styles/<target_dir>/`.
6. Write a marker file in the target folder, for example `.pypluginstore-theme.json`, containing:
   - theme key
   - target dir
   - repository identity
   - branch
   - source path
   - installed commit
   - install/update timestamp
   - manager version if available

Why staging-and-mirror is preferable to direct clone:

- It supports OsiDark and other subdirectory layouts.
- It keeps `.git` out of the web-served style folder for managed installs.
- It lets PyPluginStore validate before changing active web assets.
- It avoids exposing non-theme repository content where possible.
- It gives consistent install/update behavior across all themes.

### Discovery

`list_themes` should classify each folder under `www/styles`:

- `builtin`: matches the protected built-in set.
- `managed`: has `.pypluginstore-theme.json`.
- `registry_match`: target folder or verified source identity matches a registry entry.
- `external_git`: contains `.git` but is not managed by PyPluginStore.
- `local`: has `custom.css` but is not in the registry and not managed.
- `invalid`: missing `custom.css`, or inaccessible.

Only managed themes should be removable by default. Registry-matched external git themes can be adopted later, but adoption should be explicit.

### Update Status

For managed themes, compare the source checkout against its upstream:

- `current`
- `available`
- `unknown`
- `local_changes` if the source checkout has local modifications

Do not use plugin update caches or plugin update timestamps. If timestamp sorting is needed, add a separate `theme_update_times.cache.json` later.

### Removal

Theme removal must be deliberately conservative:

- Refuse to remove built-in themes.
- Refuse to remove folders outside `themes_dir`.
- Refuse to remove folders without a PyPluginStore marker unless an explicit future "adopt/remove external" workflow exists.
- Remove both target folder and source checkout for managed themes.
- Queue removal on locked-file errors using the same pending-operation pattern if needed.

## API Commands

Add theme-specific API actions instead of overloading plugin actions:

- `list_themes`
- `refresh_theme_update_status`
- `install_theme`
- `update_theme`
- `remove_theme`

Suggested `list_themes` response:

```json
{
  "status": "success",
  "action": "list_themes",
  "data": {},
  "installed": ["nightglass"],
  "managed": ["nightglass"],
  "local_themes": [],
  "protected_themes": ["default", "dark-th3me"],
  "installed_match_details": {},
  "update_status": {},
  "active_theme": ""
}
```

`active_theme` can be left empty in v1 unless we can read it reliably. Installing, updating, and removing themes should not try to change Domoticz settings in v1.

## Frontend Architecture

Add tabs, but make the UI catalog-driven instead of duplicating plugin rendering.

Use catalog configuration:

```javascript
const catalogs = {
  plugins: {
    listAction: "list_plugins",
    refreshAction: "refresh_update_status",
    installAction: "install",
    updateAction: "update",
    removeAction: "remove",
    itemLabel: "plugin"
  },
  themes: {
    listAction: "list_themes",
    refreshAction: "refresh_theme_update_status",
    installAction: "install_theme",
    updateAction: "update_theme",
    removeAction: "remove_theme",
    itemLabel: "theme"
  }
};
```

Theme cards should show:

- display name
- author/repository
- description
- installed/managed/local/built-in status
- update status
- JavaScript badge where applicable
- action buttons appropriate to classification

Theme operation messages:

- First install: "Theme installed. Restart Domoticz once, then select it under Setup -> Settings -> Interface."
- Update: "Theme updated. Hard refresh your browser to load the new files."
- Remove: "Theme removed. If it was active, switch to another theme and restart if Domoticz still shows cached assets."

Do not show "Domoticz restart may be required" for every theme update. Use operation-specific messages from the backend.

## Initial Registry Seed

Start small with high-confidence entries:

- `nightglass`: active, direct root layout, `custom.css` and `custom.js`, branch `main`.
- `aurora`: direct root layout, many optional feature files, legacy/unmaintained note.
- `machinon`: official/current, direct root layout, but includes extra repository content, so staged mirror is preferred.
- `osi-dark`: subdirectory install from `dist/OsiDark`, CSS-only.
- `darkcula` and `techie`: simple legacy CSS themes, optional if we want more breadth.

Exclude entries that do not contain a verifiable `custom.css` payload.

## Implementation Phases

1. Add theme path helpers, key validation, built-in protection, and tests.
2. Add `ThemeRegistryService` with remote `themes.json`, bundled fallback, and `themes_local.json` overlay.
3. Add source checkout and mirror install/update strategy.
4. Add theme discovery and classification.
5. Add API commands and focused backend tests.
6. Add UI tabs using a catalog config abstraction.
7. Add initial `themes.json` seed and validation tests.
8. Run `python .github/scripts/generate_plugin.py` and verify `plugin.py` freshness.

## Test Plan

Backend:

- `themes_dir` resolves to `<domoticz>/www/styles`.
- theme key and target path validation reject traversal and hidden folders.
- built-in folders cannot be removed.
- registry load merges remote/bundled themes with `themes_local.json`.
- direct-root install validates and mirrors `custom.css`.
- `source_path` install validates and mirrors `dist/OsiDark/custom.css`.
- invalid source path or missing `custom.css` fails without changing target.
- update status uses the source checkout, not plugin update state.
- managed remove deletes target and source checkout; unmanaged remove is refused.

Frontend:

- JavaScript syntax smoke test.
- tab switching loads the correct catalog action.
- installed-only/search/sort work for both plugins and themes.
- theme actions use theme API command names.
- theme success messages do not always mention plugin restarts.

Generated file:

- `tests/test_generated_plugin.py` stays green after running `generate_plugin.py`.

## Out of Scope for v1

- Automatically changing the active Domoticz theme.
- Editing theme-specific settings.
- Theme screenshots/previews in the API payload.
- Scanning or sandboxing JavaScript beyond clear UI labeling.
- Adopting existing manually cloned themes for update/remove.

