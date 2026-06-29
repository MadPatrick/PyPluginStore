# Issue 61: version numbers visible ?

Status: closed; shipped in `v2.13.0`.

## Intent
The user `Eddie-BS` is asking if it's possible to make the version number of a plugin visible (installed version / available version) in the UI.

## Analysis
- Currently, PyPluginStore detects updates (green Update button) and caches status, but might not explicitly display the string `v1.2.0` vs `v1.3.0` or similar.
- I need to check how `plugin_core.py` passes data to `pypluginstore.html` (the custom UI) and whether `version` information is easily available and injected into the HTML.

## Outcome
- Implemented lightweight installed and available version visibility in the plugin list.
- Closed on 2026-06-29.
