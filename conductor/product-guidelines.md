# Product Guidelines

- Keep the plugin manager simple for Domoticz users: registry entries should install without users needing to understand Git forge differences.
- Preserve existing GitHub registry behavior and backward compatibility.
- Avoid adding hosted-service-specific behavior to user-facing flows unless it is necessary for correctness.
- Keep public issue and PR communication concise and focused on the change.
- Prefer conservative scanner behavior: discover root-level Domoticz `plugin.py` repositories first, and avoid adding repositories that need unsupported subdirectory installs.
- Prefer curated, checksum-pinned stable release archives over mutable branch tips.
- Keep Git available for plugins without validated releases and as an explicit user-selected fallback; never silently fall back after release verification fails.
- Resolve forge-specific releases in repository automation and publish normalized metadata so the Domoticz runtime remains forge-neutral and does not depend on hosted API availability or rate limits.
- Migrate existing Git checkouts only through the normal upgrade flow, with dirty-tree detection, local-file preservation, rollback, and clear blocked states.
