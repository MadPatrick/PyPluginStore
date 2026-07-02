# Support Codeberg and GitLab Plugin Repositories

Issue: https://github.com/adrighem/PyPluginStore/issues/76

## Requirements

- Registry entries can represent GitHub, Codeberg, and GitLab repositories.
- The Domoticz plugin runtime can install, match, update, link to, and fetch remote plugin versions for supported hosts.
- The web UI builds correct repository links for supported hosts.
- The validation script accepts and checks supported hosted repositories.
- The scheduled plugin scan discovers and refreshes supported Codeberg and GitLab repositories in addition to GitHub.
- Existing GitHub registry entries remain backward compatible.

## Acceptance Criteria

- Tests cover clone URL construction, repository identity normalization, UI URL generation, validation, and scanner behavior for Codeberg and GitLab.
- `plugin.py` is regenerated from `plugin_core.py`.
- Relevant tests pass.
- Commit body includes `Refs #76` if a commit is created.

## Out of Scope

- Installing plugins where `plugin.py` is not at the repository root.
- Supporting arbitrary self-hosted Gitea/GitLab instances in the scanner.
- Replacing the registry schema wholesale.
