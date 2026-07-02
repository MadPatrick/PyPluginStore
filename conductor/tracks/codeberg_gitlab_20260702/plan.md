# Plan: Support Codeberg and GitLab Plugin Repositories

## Phase 1: Runtime Host Support

- [~] Task: Add tests for multi-host clone URLs, identities, repo links, and remote raw plugin lookup
- [ ] Task: Implement multi-host repository URL helpers in plugin runtime and UI
- [ ] Task: Regenerate `plugin.py`
- [ ] Task: Conductor - User Manual Verification 'Runtime Host Support' (Protocol in workflow.md)

## Phase 2: Registry Automation Support

- [ ] Task: Add tests for validation and scanner behavior on Codeberg and GitLab entries
- [ ] Task: Update validation and scheduled scanner scripts for supported hosts
- [ ] Task: Update workflow naming and scan entrypoint if needed
- [ ] Task: Conductor - User Manual Verification 'Registry Automation Support' (Protocol in workflow.md)

## Phase 3: Verification

- [ ] Task: Run focused and full test suites
- [ ] Task: Review diff and update Conductor track status
- [ ] Task: Conductor - User Manual Verification 'Verification' (Protocol in workflow.md)
