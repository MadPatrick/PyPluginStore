# Plan: Support Codeberg and GitLab Plugin Repositories

## Phase 1: Runtime Host Support [checkpoint: 845f564]

- [x] Task: Add tests for multi-host clone URLs, identities, repo links, and remote raw plugin lookup 8a55c7c
- [x] Task: Implement multi-host repository URL helpers in plugin runtime and UI 8a55c7c
- [x] Task: Regenerate `plugin.py` 8a55c7c
- [x] Task: Conductor - User Manual Verification 'Runtime Host Support' (waived by user instruction) 845f564

## Phase 2: Registry Automation Support [checkpoint: 626ed72]

- [x] Task: Add tests for validation and scanner behavior on Codeberg and GitLab entries 8a55c7c
- [x] Task: Update validation and scheduled scanner scripts for supported hosts 8a55c7c
- [x] Task: Update workflow naming and scan entrypoint if needed 8a55c7c
- [x] Task: Conductor - User Manual Verification 'Registry Automation Support' (waived by user instruction) 626ed72

## Phase 3: Verification

- [x] Task: Run focused and full test suites 8a55c7c
- [x] Task: Review diff and update Conductor track status 8a55c7c
- [ ] Task: Conductor - User Manual Verification 'Verification' (Protocol in workflow.md)

## Verification Notes

- `pytest tests/test_plugin_registry.py tests/test_ui_smoke.py tests/test_registry_scripts.py` passed.
- `python .github/scripts/generate_plugin.py` regenerated `plugin.py`.
- `pytest` passed.
- Live branch checks passed for `https://codeberg.org/Hoog/Domoticz-Stromer-plugin` `main` and `https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin` `master`.
