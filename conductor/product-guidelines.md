# Product Guidelines

- Keep the plugin manager simple for Domoticz users: registry entries should install without users needing to understand Git forge differences.
- Preserve existing GitHub registry behavior and backward compatibility.
- Avoid adding hosted-service-specific behavior to user-facing flows unless it is necessary for correctness.
- Keep public issue and PR communication concise and focused on the change.
- Prefer conservative scanner behavior: discover root-level Domoticz `plugin.py` repositories first, and avoid adding repositories that need unsupported subdirectory installs.
