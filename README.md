# PyPluginStore for Domoticz (PyPluginStore)

A robust and modern plugin manager for Domoticz that allows you to install and automatically update other Python plugins directly from GitHub.

**Note:** This plugin runs exclusively on Linux Systems (including Raspberry Pi).

<img src="pypluginstore.png" alt="PyPluginStore" width="627" height="627">

> This project is based on the original [ycahome/pp-manager](https://github.com/ycahome/pp-manager). Thanks to the original maintainers and contributors for their hard work.

---

## 🚀 Key Features

*   **Custom Plugin Store UI:** A clean, modern web interface accessible from the Domoticz **Custom** menu.
*   **Search, Sort & Filter:** Find plugins in the registry with type-ahead search, sorting, and installed-plugin filtering.
*   **Install, Remove & Update:** Manage Domoticz Python plugins without manual folder management.
*   **Self Update:** PyPluginStore appears in the store under its installed folder name, so it can update itself like any other plugin.
*   **Update Status Checks:** Installed plugins show whether their git checkout is current or has updates available.
*   **Auto Updates & Notifications:** Automatically update installed plugins or run in notification-only mode.
*   **Restart Domoticz:** Request a Domoticz service restart from the Plugin Store UI after installs or updates.
*   **Dependency Management:** Install plugin dependencies with `uv` (recommended) or `pip`, or manage them manually.
*   **PEP 668 Compliant Isolation:** Dependencies are installed into `.shared_deps` without requiring `sudo` or global `pip` access.
*   **Remote and Local Registries:** Fetches the public `registry.json`, falls back to the bundled copy, and supports private/local overrides in `registry_local.json`.
*   **Security Scanning:** Uses AST-based scanning to flag risky plugin code before it is installed.

![PyPluginStore dashboard screenshot](store-screenshot.png)

## 🛡️ Advanced Security Scanning

PyPluginStore includes **Abstract Syntax Tree (AST)** based security scanning to help protect your Domoticz instance from malicious plugins:
*   **Deep Execution Detection:** Detects calls to dangerous functions like `os.system`, `subprocess` (specifically `shell=True`), `eval`, `exec`, and `pickle`.
*   **Smart IP Filtering:** Automatically ignores private, loopback, and broadcast IP addresses, as well as version numbers in User Agents, to reduce false positives.
*   **Developer Overrides:** Supports `# security-ignore` or `# nosec` comments to manually silence known-safe code findings.
*   **Destructive Operation Blocking:** Flags destructive file operations such as `shutil.rmtree` or `os.remove`.
*   **AST Bomb & DoS Protection:** Implements hard file size limits (5MB) and recursive parsing exception handling to prevent malicious files from crashing your plugin manager.

---

## 🛠 Prerequisites

1.  **Git:** Required to clone and update repositories. (`sudo apt install git`)
2.  **uv (Recommended):** For fast and safe Python dependency resolution. (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
3.  **pip/pip3 (Optional):** Fallback if `uv` is not installed.

---

## 📥 Installation

Navigate to your Domoticz `plugins` folder and clone this repository as `00-PyPluginStore`.

```bash
cd domoticz/plugins
git clone https://github.com/adrighem/PyPluginStore.git 00-PyPluginStore
```

### Why `00-PyPluginStore`?
Domoticz loads Python plugins alphabetically by folder name. Prefixing with `00-` ensures that the manager loads first. This enables `PyPluginStore` to set up the shared dependency environment (`.shared_deps`) so other plugins can load their required libraries immediately on startup.

After cloning, restart your Domoticz service:
```bash
sudo systemctl restart domoticz.service
```

---

## ⚙️ Configuration & Usage

Once installed and Domoticz is restarted:

1.  Go to **Setup -> Hardware** and add the **PyPluginStore** hardware.
2.  Make sure the **Custom** menu is enabled for your Domoticz user in **Setup -> Users**.
3.  Navigate to **Custom -> pypluginstore** in the top menu to open the Plugin Store dashboard.

PyPluginStore copies `pypluginstore.html` into `domoticz/www/templates` and its icon into `domoticz/www/images` on startup. Domoticz only shows the **Custom** menu when custom pages exist there and the menu is enabled for the current user. If you run Domoticz in Docker, make sure the web directories are mounted persistently so the copied page and image are visible to the Domoticz web UI.

### Settings (Hardware Page)

*   **Auto Update:**
    *   **All:** Continuously updates all installed plugins.
    *   **All (NotifyOnly):** Checks all plugins for updates and notifies you.
    *   **None:** Disables auto-updating.
*   **Debug:** Set to True for detailed logging.

### Restart Button

The **Restart Domoticz** button asks the host OS to restart `domoticz.service`. This is not handled by a Domoticz JSON API endpoint; it uses non-interactive service commands such as `sudo -n systemctl restart domoticz.service`, `systemctl restart domoticz.service`, and `service domoticz restart`.

For the button to work, the user running Domoticz must have permission to restart the service. On many systems this means adding a tightly scoped passwordless sudo rule for the Domoticz service restart command. If permissions are not configured, the request is sent but the service will keep running.

---

## 📦 Manual Dependency Management

If you prefer to manage dependencies manually or are on a system where automatic installation is restricted, you can install the required libraries for your plugins manually.

PyPluginStore looks for shared dependencies in its own `.shared_deps` directory and adds it to `sys.path`.

To install dependencies for a specific plugin manually:
1.  Check the `requirements.txt` file in the plugin's folder.
2.  Install them into the `00-PyPluginStore/.shared_deps` folder:
    ```bash
    pip install -r /path/to/plugin/requirements.txt --target /path/to/domoticz/plugins/00-PyPluginStore/.shared_deps
    ```

---

## 📚 For Plugin Developers (Adding to the Registry)

To add your plugin to the manager, simply submit a Pull Request to update `registry.json` in this repository.

When a Pull Request modifying `registry.json` is merged, a GitHub Action automatically updates the registry metadata including the latest repository push timestamps.

### Local private registry

Private or local-only plugins can be added to `registry_local.json` in the PyPluginStore plugin folder. This file uses the same format as `registry.json`, is loaded after the public registry, and is ignored by git so it stays local to your Domoticz installation.

```json
{
    "MyPrivatePlugin": [
        "github-user-or-org",
        "private-repository-name",
        "Description shown in PyPluginStore",
        "main"
    ]
}
```

Entries in `registry_local.json` override public entries with the same key and show a **Local** badge in the Plugin Store UI. Installing or updating private repositories still requires the Domoticz host to have working git access to those repositories.

The first two values are normally the GitHub owner and repository name. A full Git clone URL is also accepted as the first value for private/local entries; in that case the repository-name value is ignored for cloning.

---

## ⚠️ Security Warning
Auto-updating plugins without manually reviewing the code changes exposes your system to whatever the developer pushes. By using auto-update, you trust the developers of your installed plugins.

## 💬 Discussion & Support
Join the conversation on the official Domoticz forums:
https://forum.domoticz.com/viewtopic.php?t=44626
