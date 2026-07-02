# Tech Stack

- Runtime plugin: Python, generated from `plugin_core.py` into `plugin.py`.
- UI: static HTML, CSS, and JavaScript in `pypluginstore.html`.
- Registry: `registry.json` plus optional local overrides.
- Automation: GitHub Actions workflows in `.github/workflows/`.
- Registry scanner and validation scripts: Python scripts in `.github/scripts/`.
- Tests: `pytest` test suite under `tests/`.

Development commands:

```bash
python .github/scripts/generate_plugin.py
pytest
```
