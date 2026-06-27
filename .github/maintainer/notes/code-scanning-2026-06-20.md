# Code Scanning Alerts - 2026-06-20

Status: resolved.

Alerts:
- `#5` - Incomplete URL substring sanitization in `plugin_core.py`.
- `#6` - Incomplete URL substring sanitization in generated `plugin.py`.
- `#7` - Incomplete URL substring sanitization in `plugin_core.py`.
- `#8` - Incomplete URL substring sanitization in generated `plugin.py`.

Fix:
- Replaced URL substring checks with `urllib.parse.urlparse` hostname checks in `build_git_clone_url`.
- Regenerated `plugin.py`.
- Added tests for hostile hostnames containing `github.com` in non-host positions.

Verification:
- `pytest -q`: 53 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.
- GitHub CodeQL workflow: passed.
- `gh-helper code adrighem/PyPluginStore`: no items found.
