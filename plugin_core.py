

import base64
import html
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import json
import shutil
from datetime import datetime, timedelta

import Domoticz


API_PAYLOAD_MAX_LENGTH = 2000
DEFAULT_GIT_HOST = "github.com"
SUPPORTED_GIT_HOSTS = ("github.com", "gitlab.com", "codeberg.org")
REPOSITORY_PATH_STOP_PARTS = {
    "-",
    "blob",
    "commits",
    "issues",
    "pulls",
    "raw",
    "releases",
    "src",
    "tree",
}


def parameter_get(parameters, key, default):
    try:
        return parameters.get(key, default)
    except AttributeError:
        try:
            return parameters[key]
        except Exception:
            return default


class HostRuntime:
    platform_name = "generic"

    def __init__(self, parameters):
        self.parameters = parameters
        self._git_ownership_reported = set()
        self._git_ownership_safe_directory_reported = set()
        self._git_ownership_repair_attempted = set()

    def parameter(self, key, default):
        return parameter_get(self.parameters, key, default)

    def plugin_home_folder(self):
        return os.path.abspath(self.parameter("HomeFolder", str(os.getcwd()) + os.sep))

    def current_plugin_folder(self):
        return os.path.basename(os.path.normpath(self.plugin_home_folder()))

    def plugins_dir(self):
        return os.path.abspath(os.path.join(self.plugin_home_folder(), ".."))

    def domoticz_dir(self):
        return os.path.abspath(os.path.join(self.plugin_home_folder(), "..", ".."))

    def shared_deps_dir(self):
        return os.path.join(self.plugin_home_folder(), ".shared_deps")

    def templates_dir(self):
        return os.path.join(self.domoticz_dir(), "www", "templates")

    def images_dir(self):
        return os.path.join(self.domoticz_dir(), "www", "images")

    def ui_html_source(self):
        return os.path.join(self.plugin_home_folder(), "pypluginstore.html")

    def ui_html_destination(self):
        return os.path.join(self.templates_dir(), "pypluginstore.html")

    def ui_asset_source(self, asset_name):
        return os.path.join(self.plugin_home_folder(), asset_name)

    def ui_asset_destination(self, asset_name):
        return os.path.join(self.images_dir(), asset_name)

    def requirements_file(self, plugin_key):
        return os.path.join(self.resolve_plugin_dir(plugin_key), "requirements.txt")

    def pending_operations_file(self):
        return os.path.join(self.plugin_home_folder(), "pending_operations.json")

    def restart_log_file(self):
        return os.path.join(self.plugin_home_folder(), "restart_domoticz.log")

    def self_update_log_file(self):
        return os.path.join(self.plugin_home_folder(), "self_update.log")

    def append_restart_log(self, message):
        timestamp = datetime.now().isoformat(timespec="seconds")
        try:
            with open(self.restart_log_file(), "a", encoding="utf-8") as restart_log:
                restart_log.write("[{}] {}\n".format(timestamp, message))
            return True
        except Exception as e:
            Domoticz.Error(f"Failed to write Domoticz restart log: {e}")
            return False

    def get_git_env(self):
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def git_result_output(self, result):
        if result is None:
            return ""
        return "\n".join(
            part.strip()
            for part in (getattr(result, "stderr", ""), getattr(result, "stdout", ""))
            if part and part.strip()
        )

    def is_git_dubious_ownership(self, result):
        output = self.git_result_output(result).lower()
        return "detected dubious ownership in repository" in output

    def username_for_uid(self, uid):
        try:
            import pwd
            return pwd.getpwuid(uid).pw_name
        except Exception:
            return ""

    def groupname_for_gid(self, gid):
        try:
            import grp
            return grp.getgrgid(gid).gr_name
        except Exception:
            return ""

    def format_owner(self, uid, gid):
        user = self.username_for_uid(uid)
        group = self.groupname_for_gid(gid)
        numeric = str(uid) + ":" + str(gid)
        if user and group:
            return user + ":" + group + " (" + numeric + ")"
        return numeric

    def path_owner_description(self, path):
        if not path:
            return ""
        try:
            stat_result = os.stat(path)
            return self.format_owner(stat_result.st_uid, stat_result.st_gid)
        except Exception:
            return ""

    def process_owner_description(self):
        if not hasattr(os, "geteuid"):
            return ""
        uid = os.geteuid()
        gid = os.getegid() if hasattr(os, "getegid") else -1
        return self.format_owner(uid, gid)

    def git_ownership_guidance(self, cwd):
        details = []
        expected_owner = self.process_owner_description()
        current_owner = self.path_owner_description(cwd)
        if current_owner:
            details.append("Current owner: " + current_owner + ".")
        if expected_owner:
            details.append("Expected owner: " + expected_owner + " (the Domoticz process user).")
        return " ".join(details)

    def git_ownership_repair_message(self, cwd):
        return (
            "Git refused the plugin repository because file ownership does not match the Domoticz user. "
            "Trying to fix ownership for " + str(cwd) + "."
        )

    def git_ownership_repair_enabled(self):
        value = str(self.parameter("Mode7", "Disabled") or "").strip().lower()
        return value in ("enabled", "true", "yes", "allow")

    def git_ownership_failure_message(self, cwd):
        location = " for " + str(cwd) if cwd else ""
        guidance = self.git_ownership_guidance(cwd)
        guidance = " " + guidance if guidance else ""
        if not self.git_ownership_repair_enabled():
            return (
                "Git refused the plugin repository because file ownership does not match the Domoticz user. "
                "PyPluginStore will not change file ownership automatically" + location + "; "
                "fix the plugin folder ownership manually if Git still fails."
                + guidance
            )
        return (
            "Git refused the plugin repository because file ownership does not match the Domoticz user. "
            "PyPluginStore could not fix ownership" + location + "; fix the plugin folder ownership manually."
            + guidance
        )

    def has_safe_directory_option(self, command):
        return any(str(part).startswith("safe.directory=") for part in command)

    def safe_git_command(self, command, cwd):
        safe_command = list(command)
        repo_dir = os.path.realpath(os.path.abspath(cwd))
        if len(safe_command) > 0 and safe_command[0] == "git" and not self.has_safe_directory_option(safe_command):
            safe_command.insert(1, "-c")
            safe_command.insert(2, "safe.directory=" + repo_dir)
        return safe_command

    def should_use_safe_git_directory(self, command, cwd):
        return (
            len(command) > 0
            and command[0] == "git"
            and self.is_managed_plugin_repository(cwd)
        )

    def format_command(self, command):
        return " ".join(str(part) for part in command)

    def command_available(self, command):
        return shutil.which(command) is not None

    def command_can_run(self, command, timeout=10):
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout
            )
            return result.returncode == 0
        except Exception:
            return False

    def _run_git_once(self, command, cwd, timeout=15):
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                env=self.get_git_env(),
                capture_output=True,
                text=True,
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            Domoticz.Error("Git command timed out in " + str(cwd) + ": " + self.format_command(command))
        except OSError as e:
            Domoticz.Error("Git ErrorNo:" + str(e.errno))
            Domoticz.Error("Git StrError:" + str(e.strerror))
        except Exception as e:
            Domoticz.Error("Git command failed in " + str(cwd) + ": " + str(e))
        return None

    def is_managed_plugin_repository(self, path):
        repo_dir = os.path.realpath(os.path.abspath(path))
        plugins_dir = os.path.realpath(self.plugins_dir())
        try:
            inside_plugins_dir = os.path.commonpath([repo_dir, plugins_dir]) == plugins_dir
        except ValueError:
            inside_plugins_dir = False
        return repo_dir != plugins_dir and inside_plugins_dir and os.path.isdir(os.path.join(repo_dir, ".git"))

    def chown_path(self, path, uid, gid):
        stat_result = os.lstat(path)
        target_gid = stat_result.st_gid if gid == -1 else gid
        if stat_result.st_uid == uid and stat_result.st_gid == target_gid:
            return
        try:
            os.chown(path, uid, gid, follow_symlinks=False)
        except TypeError:
            if not os.path.islink(path):
                os.chown(path, uid, gid)

    def repair_git_repository_ownership(self, cwd):
        if not hasattr(os, "chown") or not hasattr(os, "geteuid"):
            return False

        repo_dir = os.path.realpath(os.path.abspath(cwd))
        if not self.is_managed_plugin_repository(repo_dir):
            return False

        uid = os.geteuid()
        gid = os.getegid() if hasattr(os, "getegid") else -1
        try:
            for root, dirs, files in os.walk(repo_dir, topdown=True, followlinks=False):
                self.chown_path(root, uid, gid)
                for name in dirs:
                    self.chown_path(os.path.join(root, name), uid, gid)
                for name in files:
                    self.chown_path(os.path.join(root, name), uid, gid)
            return True
        except Exception as e:
            Domoticz.Debug("Could not fix Git repository ownership for " + repo_dir + ": " + str(e))
            return False

    def handle_git_ownership_failure(self, result, command, cwd, timeout):
        repo_dir = os.path.realpath(os.path.abspath(cwd))

        safe_command = self.safe_git_command(command, cwd)
        if safe_command != list(command):
            if repo_dir not in self._git_ownership_safe_directory_reported:
                Domoticz.Log("Git refused the plugin repository due to file ownership; retrying with safe.directory bypass.")
                self._git_ownership_safe_directory_reported.add(repo_dir)

            retry_result = self._run_git_once(safe_command, cwd, timeout=timeout)
            if retry_result is not None and not self.is_git_dubious_ownership(retry_result):
                return retry_result

        if repo_dir in self._git_ownership_repair_attempted:
            return result

        self._git_ownership_repair_attempted.add(repo_dir)
        if not self.git_ownership_repair_enabled():
            if repo_dir not in self._git_ownership_reported:
                Domoticz.Error(self.git_ownership_failure_message(repo_dir))
                self._git_ownership_reported.add(repo_dir)
            return result

        # Fallback to original chown repair if safe.directory fails
        if repo_dir not in self._git_ownership_reported:
            Domoticz.Error(self.git_ownership_repair_message(repo_dir))
            self._git_ownership_reported.add(repo_dir)

        if not self.repair_git_repository_ownership(repo_dir):
            Domoticz.Error(self.git_ownership_failure_message(repo_dir))
            return result

        Domoticz.Log("Fixed plugin repository ownership; retrying Git command.")
        retry_result = self._run_git_once(command, cwd, timeout=timeout)
        if retry_result is not None and self.is_git_dubious_ownership(retry_result):
            Domoticz.Error(self.git_ownership_failure_message(repo_dir))
        return retry_result

    def run_git(self, command, cwd, timeout=15):
        actual_command = command
        if self.should_use_safe_git_directory(command, cwd):
            actual_command = self.safe_git_command(command, cwd)
        result = self._run_git_once(actual_command, cwd, timeout=timeout)
        if result is not None and result.returncode != 0 and self.is_git_dubious_ownership(result):
            return self.handle_git_ownership_failure(result, actual_command, cwd, timeout)
        return result

    def make_web_readable(self, path):
        return None

    def validate_plugin_key(self, plugin_key):
        plugin_key = str(plugin_key or "").strip()
        if not plugin_key or plugin_key in (".", ".."):
            raise ValueError("Invalid plugin key")
        if plugin_key.startswith(".") or "/" in plugin_key or "\\" in plugin_key:
            raise ValueError("Invalid plugin key")
        if os.path.basename(plugin_key) != plugin_key:
            raise ValueError("Invalid plugin key")
        return plugin_key

    def is_path_inside(self, target_path, base_path):
        target_path = os.path.normcase(os.path.abspath(target_path))
        base_path = os.path.normcase(os.path.abspath(base_path))
        try:
            return os.path.commonpath([target_path, base_path]) == base_path
        except ValueError:
            return False

    def resolve_plugin_dir(self, plugin_key):
        plugin_key = self.validate_plugin_key(plugin_key)
        plugin_dir = os.path.abspath(os.path.join(self.plugins_dir(), plugin_key))
        if not self.is_path_inside(plugin_dir, self.plugins_dir()):
            raise ValueError("Invalid plugin path")
        return plugin_dir

    def restart_command_groups(self):
        return []

    def detached_popen_kwargs(self):
        return {}

    def build_restart_helper(self, command_groups, log_file, startup_delay=2, command_delay=3):
        helper = """
import datetime
import subprocess
import time
import traceback

command_groups = __COMMAND_GROUPS__
log_file = __LOG_FILE__
startup_delay = __STARTUP_DELAY__
command_delay = __COMMAND_DELAY__
failures = []

def write_log(message):
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with open(log_file, "a", encoding="utf-8") as restart_log:
            restart_log.write("[{}] {}\\n".format(timestamp, message))
    except Exception:
        pass

def classify_restart_failure(failed_attempts):
    combined_output = "\\n".join(
        [
            "\\n".join(
                [
                    str(failure.get("stdout", "")),
                    str(failure.get("stderr", "")),
                    str(failure.get("exception", "")),
                ]
            )
            for failure in failed_attempts
        ]
    ).lower()

    sudo_password_markers = (
        "a password is required",
        "password is required",
        "a terminal is required to read the password",
        "wachtwoord is verplicht",
    )
    permission_markers = (
        "access denied",
        "permission denied",
        "not authorized",
        "interactive authentication required",
        "authentication is required",
    )
    service_missing_markers = (
        "unit domoticz.service not found",
        "domoticz.service not found",
        "unrecognized service",
    )
    command_missing_markers = (
        "no such file or directory",
        "command not found",
        "not found",
    )

    if any(marker in combined_output for marker in sudo_password_markers):
        return (
            "Domoticz restart failed: sudo requires an interactive password. "
            "Configure a narrowly scoped NOPASSWD sudoers rule for the exact Domoticz restart command, or restart Domoticz manually."
        )
    if any(marker in combined_output for marker in permission_markers):
        return (
            "Domoticz restart failed: the Domoticz OS user is not allowed to restart domoticz.service. "
            "Grant only the required service-restart permission, or restart Domoticz manually."
        )
    if any(marker in combined_output for marker in service_missing_markers):
        return (
            "Domoticz restart failed: domoticz.service was not found. "
            "Check the Domoticz service name and restart it manually."
        )
    if any(marker in combined_output for marker in command_missing_markers):
        return (
            "Domoticz restart failed: one or more restart commands were not available on this host. "
            "Check the Domoticz service manager and restart it manually."
        )
    return "Domoticz restart failed: all configured restart commands failed. Review the command output above."

write_log("restart helper started")
if startup_delay:
    time.sleep(startup_delay)
for group_index, command_group in enumerate(command_groups, start=1):
    write_log("trying command group {}".format(group_index))
    success = True
    for index, command in enumerate(command_group):
        write_log("running: {}".format(subprocess.list2cmdline(command)))
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20
            )
            write_log("return code: {}".format(result.returncode))
            if result.stdout:
                write_log("stdout: {}".format(result.stdout.strip()))
            if result.stderr:
                write_log("stderr: {}".format(result.stderr.strip()))
            if result.returncode != 0:
                failures.append({
                    "command": subprocess.list2cmdline(command),
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                })
                success = False
                break
            if index < len(command_group) - 1 and command_delay:
                time.sleep(command_delay)
        except Exception as e:
            write_log("exception: {}".format(e))
            write_log(traceback.format_exc().strip())
            failures.append({
                "command": subprocess.list2cmdline(command),
                "exception": str(e),
            })
            success = False
            break
    if success:
        write_log("restart command group completed")
        break
else:
    write_log("all restart command groups failed")
    write_log("failure summary: {}".format(classify_restart_failure(failures)))
"""
        return (
            helper
            .replace("__COMMAND_GROUPS__", repr(command_groups))
            .replace("__LOG_FILE__", repr(log_file))
            .replace("__STARTUP_DELAY__", repr(startup_delay))
            .replace("__COMMAND_DELAY__", repr(command_delay))
        )

    def restart_domoticz(self):
        command_groups = self.restart_command_groups()
        if not command_groups:
            return False, "Domoticz restart is not configured for this platform."

        helper = self.build_restart_helper(command_groups, self.restart_log_file())
        self.append_restart_log("restart requested")
        self.append_restart_log("launching Python restart helper: " + str(sys.executable))
        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        popen_kwargs.update(self.detached_popen_kwargs())

        try:
            subprocess.Popen([sys.executable, "-c", helper], **popen_kwargs)
            return True, "Domoticz restart requested"
        except Exception as e:
            Domoticz.Error(f"Failed to schedule Domoticz restart: {e}")
            return False, str(e)

    def git_failure_message(self, result, fallback, cwd=""):
        if result is None:
            return fallback
        if self.is_git_dubious_ownership(result):
            return self.git_ownership_failure_message(cwd)
        output = (result.stderr or result.stdout or "").strip()
        return output or fallback

    def log_git_result(self, label, result):
        if not label or result is None:
            return
        if result.stdout:
            Domoticz.Debug("Git " + label + " Response:" + result.stdout.strip())
        if result.stderr and not self.is_git_dubious_ownership(result):
            Domoticz.Debug("Git " + label + " Error:" + result.stderr.strip())

    def require_git_success(self, plugin_dir, command, timeout=15, fallback=None, log_label=""):
        result = self.run_git(command, plugin_dir, timeout=timeout)
        self.log_git_result(log_label, result)
        fallback = fallback or "Git command failed: " + self.format_command(command)
        if result is None:
            return result, fallback
        if result.returncode != 0:
            return result, self.git_failure_message(
                result,
                fallback,
                plugin_dir,
            )
        return result, ""

    def validate_self_update_candidate(self, plugin_dir, target_ref):
        required_paths = ("plugin.py", "plugin_core.py", "pypluginstore.html", "registry.json")
        for candidate_path in required_paths:
            _, message = self.require_git_success(
                plugin_dir,
                ["git", "cat-file", "-e", f"{target_ref}:{candidate_path}"],
                fallback="Self update target is missing " + candidate_path + ".",
            )
            if message:
                return False, message

        for python_path in ("plugin.py", "plugin_core.py"):
            result, message = self.require_git_success(
                plugin_dir,
                ["git", "show", f"{target_ref}:{python_path}"],
                fallback="Could not read " + python_path + " from self update target.",
            )
            if message:
                return False, message
            try:
                compile(result.stdout, python_path, "exec")
            except SyntaxError as e:
                return False, "Self update target has invalid Python syntax in " + python_path + ": " + str(e)

        return True, ""

    def preflight_self_update(self, plugin_dir):
        if not self.command_available("git"):
            return False, "Git is not available, so PyPluginStore cannot self-update.", {}
        if not os.path.isdir(os.path.join(plugin_dir, ".git")):
            return False, "PyPluginStore is not installed as a git repository.", {}

        result, message = self.require_git_success(
            plugin_dir,
            ["git", "rev-parse", "--is-inside-work-tree"],
            fallback="Could not verify the PyPluginStore git repository.",
        )
        if message:
            return False, message, {}
        if result.stdout.strip().lower() != "true":
            return False, "PyPluginStore folder is not a git work tree.", {}

        result, message = self.require_git_success(
            plugin_dir,
            ["git", "rev-parse", "--show-toplevel"],
            fallback="Could not verify the PyPluginStore git work tree root.",
        )
        if message:
            return False, message, {}
        repo_root = os.path.normcase(os.path.abspath(result.stdout.strip()))
        expected_root = os.path.normcase(os.path.abspath(plugin_dir))
        if repo_root != expected_root:
            return False, "PyPluginStore self-update must run from the repository root.", {}

        result, message = self.require_git_success(
            plugin_dir,
            ["git", "status", "--porcelain", "--untracked-files=no"],
            fallback="Could not check PyPluginStore working tree status.",
        )
        if message:
            return False, message, {}
        if result.stdout.strip():
            return False, "PyPluginStore has local tracked file changes; self-update refused.", {}

        result, message = self.require_git_success(
            plugin_dir,
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            fallback="PyPluginStore branch has no upstream; self-update refused.",
        )
        if message:
            return False, message, {}
        upstream_ref = result.stdout.strip()
        if not upstream_ref:
            return False, "PyPluginStore branch has no upstream; self-update refused.", {}

        _, message = self.require_git_success(
            plugin_dir,
            ["git", "fetch", "--prune"],
            timeout=60,
            fallback="Could not fetch PyPluginStore updates from the upstream remote.",
        )
        if message:
            return False, message, {}

        _, message = self.require_git_success(
            plugin_dir,
            ["git", "rev-parse", "--verify", upstream_ref],
            fallback="Could not verify the PyPluginStore upstream revision.",
        )
        if message:
            return False, message, {}

        _, message = self.require_git_success(
            plugin_dir,
            ["git", "merge-base", "--is-ancestor", "HEAD", upstream_ref],
            fallback="PyPluginStore local branch has diverged from upstream; self-update refused.",
        )
        if message:
            return False, message, {}

        result, message = self.require_git_success(
            plugin_dir,
            ["git", "rev-list", "--left-right", "--count", "HEAD..." + upstream_ref],
            fallback="Could not compare PyPluginStore with upstream.",
        )
        if message:
            return False, message, {}
        try:
            ahead, behind = [int(value) for value in result.stdout.split()[:2]]
        except Exception:
            return False, "Could not parse PyPluginStore upstream comparison.", {}
        if ahead:
            return False, "PyPluginStore has local commits; self-update refused.", {}
        if behind == 0:
            return True, "PyPluginStore is already up-to-date.", {"already_current": True, "upstream_ref": upstream_ref}

        valid_candidate, message = self.validate_self_update_candidate(plugin_dir, upstream_ref)
        if not valid_candidate:
            return False, message, {}

        return True, "Self update pre-flight checks passed.", {
            "already_current": False,
            "upstream_ref": upstream_ref,
        }

    def build_self_update_helper(self, plugin_dir, log_file, upstream_ref, startup_delay=1):
        helper = """
import datetime
import os
import subprocess
import time
import traceback

plugin_dir = __PLUGIN_DIR__
log_file = __LOG_FILE__
upstream_ref = __UPSTREAM_REF__
startup_delay = __STARTUP_DELAY__
safe_directory = os.path.realpath(os.path.abspath(plugin_dir))

def write_log(message):
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with open(log_file, "a", encoding="utf-8") as update_log:
            update_log.write("[{}] {}\\n".format(timestamp, message))
    except Exception:
        pass

write_log("self update helper started")
if startup_delay:
    time.sleep(startup_delay)

if not os.path.isdir(os.path.join(plugin_dir, ".git")):
    write_log("not a git repository: {}".format(plugin_dir))
    raise SystemExit(1)

env = os.environ.copy()
env["GIT_TERMINAL_PROMPT"] = "0"

def git_command(*args):
    return ["git", "-c", "safe.directory=" + safe_directory] + list(args)

def run_command(command, timeout):
    write_log("running: {}".format(subprocess.list2cmdline(command)))
    try:
        result = subprocess.run(
            command,
            cwd=plugin_dir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        write_log("return code: {}".format(result.returncode))
        if result.stdout:
            write_log("stdout: {}".format(result.stdout.strip()))
        if result.stderr:
            write_log("stderr: {}".format(result.stderr.strip()))
        if result.returncode != 0:
            write_log("self update failed")
            raise SystemExit(result.returncode)
        return result
    except Exception as e:
        write_log("exception: {}".format(e))
        write_log(traceback.format_exc().strip())
        raise

status = run_command(git_command("status", "--porcelain", "--untracked-files=no"), 15)
if status.stdout.strip():
    write_log("tracked files changed after pre-flight; self update refused")
    raise SystemExit(1)

run_command(git_command("fetch", "--prune"), 60)
run_command(git_command("merge", "--ff-only", upstream_ref), 120)
write_log("self update completed")
"""
        return (
            helper
            .replace("__PLUGIN_DIR__", repr(plugin_dir))
            .replace("__LOG_FILE__", repr(log_file))
            .replace("__UPSTREAM_REF__", repr(upstream_ref))
            .replace("__STARTUP_DELAY__", repr(startup_delay))
        )

    def schedule_self_update(self, plugin_dir):
        preflight_success, preflight_message, preflight_plan = self.preflight_self_update(plugin_dir)
        if not preflight_success or preflight_plan.get("already_current"):
            return preflight_success, preflight_message

        helper = self.build_self_update_helper(
            plugin_dir,
            self.self_update_log_file(),
            preflight_plan["upstream_ref"],
        )
        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        popen_kwargs.update(self.detached_popen_kwargs())

        try:
            subprocess.Popen([sys.executable, "-c", helper], **popen_kwargs)
            return True, "Self update started after pre-flight checks. Reload the Plugin Store after Domoticz finishes reloading the plugin."
        except Exception as e:
            Domoticz.Error(f"Failed to schedule PyPluginStore self update: {e}")
            return False, str(e)

    def dependency_install_command(self, requirements_file, target_dir):
        if self.command_available("uv") and sys.executable:
            return ["uv", "pip", "install", "--python", sys.executable, "-r", requirements_file, "--target", target_dir]

        if sys.executable and self.command_can_run([sys.executable, "-m", "pip", "--version"]):
            return [sys.executable, "-m", "pip", "install", "-r", requirements_file, "--target", target_dir]

        for command in ("pip3", "pip"):
            if self.command_available(command):
                return [command, "install", "-r", requirements_file, "--target", target_dir]
        return None

    def install_requirements(self, requirements_file, target_dir, plugin_key):
        if not os.path.isfile(requirements_file):
            Domoticz.Log("No requirements.txt found for plugin: " + plugin_key)
            return True, "No requirements.txt found"

        Domoticz.Log("requirements.txt found for plugin: " + plugin_key)
        os.makedirs(target_dir, exist_ok=True)

        install_command = self.dependency_install_command(requirements_file, target_dir)
        if not install_command:
            Domoticz.Log("Neither 'uv' nor a working pip command found. Skipping automatic dependency installation.")
            Domoticz.Log(f"Please install dependencies manually from {requirements_file} into {target_dir}")
            return False, "No Python dependency installer found"

        Domoticz.Log("Installing dependencies using: " + self.format_command(install_command))
        try:
            pr = subprocess.Popen(install_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            out, error = pr.communicate()
            if pr.returncode == 0:
                Domoticz.Log("Dependencies installed successfully: " + out.strip())
                return True, ""
            Domoticz.Error("Error installing dependencies: " + error.strip())
            return False, error.strip()
        except Exception as e:
            Domoticz.Error("Error running installation command: " + str(e))
            return False, str(e)

    def is_locked_file_error(self, error):
        return False

    def is_locked_file_message(self, message):
        return False


class LinuxHostRuntime(HostRuntime):
    platform_name = "linux"

    def get_git_env(self):
        env = super().get_git_env()
        env["LANG"] = "en_US.UTF-8"
        env["LC_ALL"] = "en_US.UTF-8"
        return env

    def make_web_readable(self, path):
        try:
            os.chmod(path, 0o644)
        except Exception as e:
            Domoticz.Debug(f"Could not update file permissions for {path}: {e}")

    def restart_command_groups(self):
        return [
            [["systemctl", "restart", "domoticz.service"]],
            [["sudo", "-n", "systemctl", "restart", "domoticz.service"]],
            [["service", "domoticz", "restart"]],
            [["sudo", "-n", "service", "domoticz", "restart"]],
        ]

    def detached_popen_kwargs(self):
        return {"start_new_session": True}


class WindowsHostRuntime(HostRuntime):
    platform_name = "windows"

    def windows_restart_script_file(self):
        return os.path.join(self.plugin_home_folder(), "restart_domoticz.ps1")

    def windows_restart_command_file(self):
        return os.path.join(self.plugin_home_folder(), "restart_domoticz.cmd")

    def windows_restart_probe_file(self):
        return os.path.join(self.plugin_home_folder(), "restart_domoticz_probe.ps1")

    def windows_restart_task_name(self):
        return r"\PyPluginStore-Domoticz-Restart"

    def schtasks_executable(self):
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        candidate = os.path.join(system_root, "System32", "schtasks.exe")
        if os.path.isfile(candidate):
            return candidate
        return "schtasks.exe"

    def powershell_executable(self):
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        candidate = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if os.path.isfile(candidate):
            return candidate
        return "powershell.exe"

    def powershell_quote(self, value):
        return "'" + str(value).replace("'", "''") + "'"

    def powershell_encoded_command(self, script):
        return base64.b64encode(script.encode("utf-16le")).decode("ascii")

    def probe_powershell_file_execution(self):
        probe_file = self.windows_restart_probe_file()
        try:
            with open(probe_file, "w", encoding="utf-8", newline="\r\n") as probe_script:
                probe_script.write("Write-Output 'PyPluginStore PowerShell file execution probe'\n")

            result = subprocess.run(
                [
                    self.powershell_executable(),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    probe_file,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.append_restart_log("PowerShell .ps1 probe return code: " + str(result.returncode))
            if result.stdout:
                self.append_restart_log("PowerShell .ps1 probe stdout: " + result.stdout.strip())
            if result.stderr:
                self.append_restart_log("PowerShell .ps1 probe stderr: " + result.stderr.strip())
            if result.returncode != 0:
                self.append_restart_log("PowerShell .ps1 execution probe failed")
                if "running scripts is disabled" in str(result.stderr).lower():
                    self.append_restart_log("PowerShell execution policy blocks .ps1 files")
                return False
            return True
        except Exception as e:
            self.append_restart_log("PowerShell .ps1 probe exception: " + str(e))
            return False

    def probe_powershell_encoded_command(self):
        script = (
            "$LogFile = {log_file}\n"
            "$timestamp = (Get-Date).ToString(\"s\")\n"
            "Add-Content -LiteralPath $LogFile -Value \"[$timestamp] PowerShell EncodedCommand probe succeeded\" -Encoding UTF8\n"
            "Write-Output 'PyPluginStore PowerShell EncodedCommand probe'\n"
        ).format(log_file=self.powershell_quote(self.restart_log_file()))

        try:
            result = subprocess.run(
                [
                    self.powershell_executable(),
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    self.powershell_encoded_command(script),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            self.append_restart_log("PowerShell EncodedCommand probe return code: " + str(result.returncode))
            if result.stdout:
                self.append_restart_log("PowerShell EncodedCommand probe stdout: " + result.stdout.strip())
            if result.stderr:
                self.append_restart_log("PowerShell EncodedCommand probe stderr: " + result.stderr.strip())
            return result.returncode == 0
        except Exception as e:
            self.append_restart_log("PowerShell EncodedCommand probe exception: " + str(e))
            return False

    def build_windows_restart_script(self):
        script = r"""
$ErrorActionPreference = "Continue"
$LogFile = __LOG_FILE__
$ServiceNames = @(__SERVICE_NAMES__)

function Write-RestartLog {
    param([string]$Message)
    try {
        $timestamp = (Get-Date).ToString("s")
        Add-Content -LiteralPath $LogFile -Value "[$timestamp] $Message" -Encoding UTF8
    } catch {
    }
}

function Write-CommandOutput {
    param($Output)
    if ($null -eq $Output) {
        return
    }
    foreach ($line in $Output) {
        Write-RestartLog ("output: " + [string]$line)
    }
}

function Invoke-ExternalCommand {
    param([string[]]$Command)
    Write-RestartLog ("running: " + ($Command -join " "))
    try {
        $commandArgs = @()
        if ($Command.Count -gt 1) {
            $commandArgs = $Command[1..($Command.Count - 1)]
        }
        $output = & $Command[0] @commandArgs 2>&1
        $exitCode = $LASTEXITCODE
        Write-CommandOutput $output
        Write-RestartLog ("return code: " + $exitCode)
        return ($exitCode -eq 0)
    } catch {
        Write-RestartLog ("exception: " + $_.Exception.Message)
        return $false
    }
}

Write-RestartLog "restart helper started"
Start-Sleep -Seconds 2

foreach ($serviceName in $ServiceNames) {
    Write-RestartLog ("running: Restart-Service -Name " + $serviceName + " -Force")
    try {
        $output = Restart-Service -Name $serviceName -Force -ErrorAction Stop 2>&1
        Write-CommandOutput $output
        Write-RestartLog ("Restart-Service completed for " + $serviceName)
        exit 0
    } catch {
        Write-RestartLog ("exception: " + $_.Exception.Message)
    }
}

foreach ($serviceName in $ServiceNames) {
    $stopOk = Invoke-ExternalCommand @("sc.exe", "stop", $serviceName)
    Start-Sleep -Seconds 3
    $startOk = Invoke-ExternalCommand @("sc.exe", "start", $serviceName)
    if ($stopOk -and $startOk) {
        Write-RestartLog ("sc stop/start completed for " + $serviceName)
        exit 0
    }
}

Write-RestartLog "all restart command groups failed"
exit 1
"""
        service_names = [self.powershell_quote("Domoticz"), self.powershell_quote("domoticz")]
        return (
            script
            .replace("__LOG_FILE__", self.powershell_quote(self.restart_log_file()))
            .replace("__SERVICE_NAMES__", ", ".join(service_names))
        )

    def build_windows_restart_command(self, script_file):
        powershell_command = (
            "$ErrorActionPreference = 'Stop'; "
            "$LogFile = {log_file}; "
            "function Write-RestartLog {{ "
            "param([string]$Message) "
            "try {{ "
            "$timestamp = (Get-Date).ToString('s'); "
            "Add-Content -LiteralPath $LogFile -Value ('[{{0}}] {{1}}' -f $timestamp, $Message) -Encoding UTF8 "
            "}} catch {{}} "
            "}}; "
            "try {{ "
            "Write-RestartLog 'scheduled task helper started'; "
            "$script = [System.IO.File]::ReadAllText({script_file}); "
            "Invoke-Expression $script; "
            "exit $LASTEXITCODE "
            "}} catch {{ "
            "Write-RestartLog ('scheduled task helper exception: ' + $_.Exception.Message); "
            "exit 1 "
            "}}"
        ).format(
            log_file=self.powershell_quote(self.restart_log_file()),
            script_file=self.powershell_quote(script_file),
        )
        return '@echo off\r\n"{}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "{}"\r\n'.format(
            self.powershell_executable(),
            powershell_command,
        )

    def run_schtasks(self, args, timeout=20):
        command = [self.schtasks_executable()] + args
        self.append_restart_log("running: " + subprocess.list2cmdline(command))
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
            )
            self.append_restart_log("return code: " + str(result.returncode))
            if result.stdout:
                self.append_restart_log("stdout: " + result.stdout.strip())
            if result.stderr:
                self.append_restart_log("stderr: " + result.stderr.strip())
            return result.returncode == 0
        except Exception as e:
            self.append_restart_log("exception: " + str(e))
            return False

    def schedule_windows_restart_task(self, command_file):
        task_time = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
        task_action = 'cmd.exe /d /c ""{}""'.format(command_file)
        task_name = self.windows_restart_task_name()
        if not self.run_schtasks([
            "/Create",
            "/TN", task_name,
            "/SC", "ONCE",
            "/ST", task_time,
            "/TR", task_action,
            "/RU", "SYSTEM",
            "/RL", "HIGHEST",
            "/F",
        ]):
            return False
        return self.run_schtasks(["/Run", "/TN", task_name])

    def restart_domoticz(self):
        script_file = self.windows_restart_script_file()
        command_file = self.windows_restart_command_file()
        try:
            self.append_restart_log("restart requested")
            script = self.build_windows_restart_script()
            with open(script_file, "w", encoding="utf-8", newline="\r\n") as restart_script:
                restart_script.write(script)
            with open(command_file, "w", encoding="utf-8", newline="\r\n") as restart_command:
                restart_command.write(self.build_windows_restart_command(script_file))

            self.probe_powershell_file_execution()
            if not self.probe_powershell_encoded_command():
                return False, "PowerShell EncodedCommand probe failed. See restart_domoticz.log."

            self.append_restart_log("launching Windows scheduled restart task: " + command_file)
            if not self.schedule_windows_restart_task(command_file):
                return False, "Failed to schedule Windows restart task. See restart_domoticz.log."
            return True, "Domoticz restart requested"
        except Exception as e:
            self.append_restart_log("failed to schedule restart: " + str(e))
            Domoticz.Error(f"Failed to schedule Domoticz restart: {e}")
            return False, str(e)

    def restart_command_groups(self):
        return [
            [[
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "Restart-Service -Name 'Domoticz' -Force -ErrorAction Stop",
            ]],
            [["sc", "stop", "Domoticz"], ["sc", "start", "Domoticz"]],
            [["sc", "stop", "domoticz"], ["sc", "start", "domoticz"]],
        ]

    def detached_popen_kwargs(self):
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        if creationflags:
            return {"creationflags": creationflags}
        return {}

    def is_locked_file_error(self, error):
        winerror = getattr(error, "winerror", None)
        if winerror in (5, 32, 33):
            return True
        return isinstance(error, PermissionError)

    def is_locked_file_message(self, message):
        message = str(message or "").lower()
        locked_markers = (
            "access is denied",
            "being used by another process",
            "could not unlink",
            "unable to unlink",
            "permission denied",
        )
        return any(marker in message for marker in locked_markers)


def make_host_runtime(parameters):
    if platform.system() == "Windows":
        return WindowsHostRuntime(parameters)
    return LinuxHostRuntime(parameters)


class RegistryEntry:
    def __init__(
        self,
        key,
        author,
        repository,
        description,
        branch,
        updated_at="",
        platforms=None,
        updated_at_slot_present=False,
        local=False,
    ):
        self.key = str(key or "")
        self.author = str(author or "")
        self.repository = str(repository or "")
        self.description = str(description or "")
        self.branch = str(branch or "master")
        self.updated_at = str(updated_at or "")
        self.platforms = list(platforms or ["unknown"])
        self.updated_at_slot_present = bool(updated_at_slot_present or self.updated_at)
        self.local = bool(local)

    def to_legacy_list(self):
        entry = [self.author, self.repository, self.description, self.branch]
        if self.updated_at_slot_present or self.updated_at:
            entry.append(self.updated_at)
        return entry

    def copy_with(self, author=None, repository=None, branch=None):
        return RegistryEntry(
            self.key,
            self.author if author is None else author,
            self.repository if repository is None else repository,
            self.description,
            self.branch if branch is None else branch,
            self.updated_at,
            self.platforms,
            self.updated_at_slot_present,
            self.local,
        )


class RegistryService:
    def __init__(self, plugin):
        self.plugin = plugin

    def normalize_entry(self, key, data, local=False, default_platforms=None):
        platforms = ["unknown"]
        if isinstance(data, dict):
            author = data.get("author", data.get("owner", ""))
            repository = data.get("repository", data.get("repo", ""))
            description = data.get("description", "")
            branch = data.get("branch", "master")
            updated_at = data.get("updated_at", "")
            platforms = self.plugin.normalize_platforms(data.get("platforms", data.get("platform", None)))
            entry = RegistryEntry(
                key,
                author,
                repository,
                description,
                branch,
                updated_at,
                platforms,
                bool(updated_at),
                local,
            )
        elif isinstance(data, list):
            raw_entry = list(data[:5])
            if len(data) > 5:
                platforms = self.plugin.normalize_platforms(data[5])
            elif default_platforms is not None:
                platforms = self.plugin.normalize_platforms(default_platforms)
            if len(raw_entry) < 4:
                Domoticz.Error("Plugin '" + str(key) + "' registry entry must contain owner, repository, description and branch.")
                return None, ["unknown"]
            updated_at = raw_entry[4] if len(raw_entry) >= 5 else ""
            entry = RegistryEntry(
                key,
                raw_entry[0],
                raw_entry[1],
                raw_entry[2],
                raw_entry[3],
                updated_at,
                platforms,
                len(raw_entry) >= 5,
                local,
            )
        else:
            Domoticz.Error("Plugin '" + str(key) + "' has an invalid registry entry.")
            return None, ["unknown"]

        return entry, platforms

    def normalize_registry(self, registry, local_keys=None):
        local_keys = set(local_keys or [])
        normalized_registry = {}
        plugin_platforms = {}
        registry_entries = {}
        for key, data in registry.items():
            if key == "Idle":
                normalized_registry[key] = data
                plugin_platforms[key] = ["unknown"]
                continue

            try:
                self.plugin.get_host().validate_plugin_key(key)
            except ValueError as e:
                Domoticz.Error("Skipping invalid plugin key '" + str(key) + "': " + str(e))
                continue

            entry, platforms = self.normalize_entry(key, data, local=key in local_keys)
            if entry is None:
                continue
            normalized_registry[key] = entry.to_legacy_list()
            plugin_platforms[key] = platforms
            registry_entries[key] = entry
        return normalized_registry, plugin_platforms, registry_entries


class UpdateStatusService:
    def __init__(self, plugin):
        self.plugin = plugin

    def refresh_single_plugin_update_status(self, plugin_key, plugin_dir, fetch_first=True):
        if plugin_key not in self.plugin.plugin_data:
            self.plugin.update_status[plugin_key] = "unknown"
            return "unknown"

        update_status = self.plugin.getGitUpdateStatus(plugin_dir, plugin_key, fetch_first=fetch_first)
        self.plugin.update_status[plugin_key] = update_status
        return update_status

    def refresh_installed_update_statuses(self, installed_plugins=None, plugins_dir=None):
        if plugins_dir is None:
            plugins_dir = self.plugin.get_host().plugins_dir()
        if installed_plugins is None:
            installed_plugins = self.plugin.getInstalledPlugins(plugins_dir)

        update_status = {}
        for plugin_key in installed_plugins:
            if plugin_key not in self.plugin.plugin_data:
                update_status[plugin_key] = "unknown"
                continue

            try:
                plugin_dir = self.plugin.resolve_installed_plugin_dir(plugin_key, plugins_dir)
            except ValueError as e:
                Domoticz.Error(str(e))
                update_status[plugin_key] = "unknown"
                continue
            update_status[plugin_key] = self.plugin.refresh_single_plugin_update_status(plugin_key, plugin_dir)

        self.plugin.update_status.update(update_status)
        return update_status

    def get_git_update_status(self, plugin_dir, plugin_key=None, fetch_first=True):
        if not os.path.isdir(os.path.join(plugin_dir, ".git")):
            return "unknown"

        try:
            if fetch_first and not self.plugin.fetch_git_repo(plugin_dir):
                return "unknown"

            remote_ref = self.plugin.get_git_remote_ref(plugin_dir) or "@{u}"
            if plugin_key:
                update_times = dict(self.plugin.update_times) if self.plugin.update_times else self.plugin.load_cached_update_times()
                if self.plugin.refresh_git_update_time(plugin_key, plugin_dir, update_times, remote_ref):
                    self.plugin.save_update_times_cache(update_times)
                    self.plugin.apply_update_times(update_times)

            ahead_behind = self.plugin.get_git_ahead_behind(plugin_dir, remote_ref)
            if ahead_behind is None:
                return "unknown"

            behind = ahead_behind[1]
            if behind > 0:
                return "available"
            return "current"
        except Exception as e:
            Domoticz.Debug(f"Could not determine update status for {plugin_dir}: {e}")
            return "unknown"


class GitInstallUpdateStrategy:
    def __init__(self, plugin):
        self.plugin = plugin

    def install(self, entry):
        Domoticz.Debug("InstallPythonPlugin called")

        host = self.plugin.get_host()
        plugins_dir = host.plugins_dir()
        try:
            plugin_dir = host.resolve_plugin_dir(entry.key)
            plugin_key = host.validate_plugin_key(entry.key)
        except ValueError as e:
            Domoticz.Error(str(e))
            return False, str(e)

        try:
            existing_plugin_dir = self.plugin.resolve_installed_plugin_dir(plugin_key, plugins_dir)
        except ValueError as e:
            Domoticz.Error(str(e))
            return False, str(e)

        if os.path.isdir(existing_plugin_dir):
            existing_folder = os.path.basename(existing_plugin_dir)
            Domoticz.Log("Plugin " + plugin_key + " is already installed in folder " + existing_folder + ".")
            self.plugin.refresh_single_plugin_update_time(plugin_key, existing_plugin_dir, fetch_first=False)
            self.plugin.refresh_single_plugin_update_status(plugin_key, existing_plugin_dir, fetch_first=False)
            self.plugin.installDependencies(plugin_key)
            return True, "Plugin already installed."

        Domoticz.Log("Installing Plugin:" + entry.description)
        clone_command = [
            "git",
            "clone",
            "-b",
            entry.branch or "master",
            self.plugin.build_git_clone_url(entry.author, entry.repository),
            plugin_key,
        ]
        Domoticz.Log("Calling: " + " ".join(clone_command))

        result, clone_message = host.require_git_success(
            plugins_dir,
            clone_command,
            timeout=120,
            fallback="Git clone failed",
            log_label="Clone",
        )
        if clone_message:
            Domoticz.Error("Git clone failed for plugin " + plugin_key + ".")
            return False, clone_message
        Domoticz.Log("Plugin " + plugin_key + " installed successfully.")

        if not os.path.isdir(plugin_dir):
            Domoticz.Error("Plugin folder was not created: " + plugin_dir)
            return False, "Plugin folder was not created."

        self.plugin.refresh_single_plugin_update_time(plugin_key, plugin_dir, fetch_first=False)
        self.plugin.refresh_single_plugin_update_status(plugin_key, plugin_dir, fetch_first=False)
        self.plugin.installDependencies(plugin_key)
        Domoticz.Log("---Restarting Domoticz MAY BE REQUIRED to activate new plugins---")
        return True, ""

    def update(self, entry, queue_on_lock=True):
        Domoticz.Debug("UpdatePythonPlugin called")

        host = self.plugin.get_host()
        try:
            plugin_key = host.validate_plugin_key(entry.key)
            plugin_dir = self.plugin.resolve_installed_plugin_dir(plugin_key)
        except ValueError as e:
            Domoticz.Error(str(e))
            return False, str(e)

        is_self_update = plugin_key == self.plugin.get_current_plugin_folder()

        if entry.description in self.plugin.exception_list:
            Domoticz.Log("Plugin:" + entry.description + " excluded by Exclusion file (exclusion.txt). Skipping!!!")
            return True, "Excluded by exception list"

        if is_self_update:
            Domoticz.Log("Self update requested for PyPluginStore.")
            update_success, update_message = host.schedule_self_update(plugin_dir)
            if update_success:
                self.plugin.update_status[plugin_key] = "unknown"
            return update_success, update_message

        Domoticz.Log("Resetting and Updating Plugin:" + plugin_key)

        branch = entry.branch or "master"
        fetch_command = ["git", "fetch", "origin"]
        Domoticz.Debug("Calling: " + " ".join(fetch_command) + " on folder " + plugin_dir)
        fetch_result, fetch_message = host.require_git_success(
            plugin_dir,
            fetch_command,
            timeout=60,
            fallback="Git fetch failed",
            log_label="Fetch",
        )
        if fetch_message:
            return False, fetch_message

        diff_command = ["git", "diff", "--quiet", "HEAD...origin/" + branch]
        Domoticz.Debug("Calling: " + " ".join(diff_command) + " on folder " + plugin_dir)
        diff_result = host.run_git(diff_command, plugin_dir, timeout=15)
        host.log_git_result("Diff", diff_result)
        if diff_result is None:
            return False, "Git diff failed"
        if diff_result.returncode not in (0, 1):
            return False, host.git_failure_message(diff_result, "Git diff failed", plugin_dir)
        is_already_current = (diff_result is not None and diff_result.returncode == 0)

        checkout_command = ["git", "checkout", "-B", branch, "origin/" + branch]
        Domoticz.Debug("Calling: " + " ".join(checkout_command) + " on folder " + plugin_dir)
        checkout_result, checkout_message = host.require_git_success(
            plugin_dir,
            checkout_command,
            timeout=30,
            fallback="Git checkout failed",
            log_label="Checkout",
        )
        if checkout_message:
            if checkout_result is not None and host.is_locked_file_message(host.git_result_output(checkout_result)):
                message = "Plugin files are in use; update queued for the next startup."
                if queue_on_lock:
                    self.plugin.queuePendingOperation("update", plugin_key)
                Domoticz.Error(message)
                return False, message
            return False, checkout_message

        reset_command = ["git", "reset", "--hard", "origin/" + branch]
        Domoticz.Debug("Calling: " + " ".join(reset_command) + " on folder " + plugin_dir)
        reset_result, reset_message = host.require_git_success(
            plugin_dir,
            reset_command,
            timeout=30,
            fallback="Git reset failed",
            log_label="Reset",
        )
        if reset_message:
            if reset_result is not None and host.is_locked_file_message(host.git_result_output(reset_result)):
                message = "Plugin files are in use; update queued for the next startup."
                if queue_on_lock:
                    self.plugin.queuePendingOperation("update", plugin_key)
                Domoticz.Error(message)
                return False, message
            return False, reset_message

        if is_already_current:
            Domoticz.Log("Plugin " + plugin_key + " already Up-To-Date")
        else:
            Domoticz.Log("Succesfully pulled gitHub update for plugin " + plugin_key)
            Domoticz.Log("---Restarting Domoticz MAY BE REQUIRED to activate new plugins---")

        self.plugin.refresh_single_plugin_update_time(plugin_key, plugin_dir, fetch_first=False)
        self.plugin.refresh_single_plugin_update_status(plugin_key, plugin_dir, fetch_first=False)
        self.plugin.installDependencies(plugin_key)
        return True, ""

    def check_for_update(self, entry):
        Domoticz.Debug("CheckForUpdatePythonPlugin called")

        if entry.description in self.plugin.exception_list:
            self.plugin.update_status[entry.key] = "unknown"
            Domoticz.Log("Plugin:" + entry.description + " excluded by Exclusion file (exclusion.txt). Skipping!!!")
            return None

        Domoticz.Debug("Checking Plugin:" + entry.key + " for updates")

        try:
            plugin_dir = self.plugin.resolve_installed_plugin_dir(entry.key)
        except ValueError as e:
            self.plugin.update_status[entry.key] = "unknown"
            Domoticz.Error(str(e))
            return None

        if not os.path.isdir(os.path.join(plugin_dir, ".git")):
            self.plugin.update_status[entry.key] = "unknown"
            Domoticz.Log("Plugin:" + entry.key + " is not installed from gitHub. Ignoring!!.")
            return None

        update_status = self.plugin.getGitUpdateStatus(plugin_dir, entry.key)
        self.plugin.update_status[entry.key] = update_status
        if update_status == "available":
            Domoticz.Log("Found that we are behind on plugin " + entry.key)
            self.plugin.fnSelectedNotify(entry.key)
        elif update_status == "current":
            Domoticz.Log("Plugin " + entry.key + " already Up-To-Date")
        else:
            Domoticz.Debug("Could not determine update status for " + entry.key + ".")

        return None


class BasePlugin:
    enabled = False
    pluginState = "Not Ready"
    sessionCookie = ""
    privateKey = b""
    socketOn = "FALSE"

    def __init__(self):
        self.debug = False
        self.error = False
        self.nextpoll = None
        self.pollinterval = 60
        self.exception_list = []
        self.secpoluser_list = {}
        self.plugin_data = {}
        self.registry_entries = {}
        self.local_plugin_keys = []
        self.update_times = {}
        self.update_status = {}
        self.plugin_platforms = {}
        self.last_update_date = None
        self.last_update_status_refresh_date = None
        self.host = None
        self.installed_plugin_folders = {}
        self.installed_plugin_match_details = {}
        self.registry_service = RegistryService(self)
        self.update_status_service = UpdateStatusService(self)
        self.install_update_strategy = GitInstallUpdateStrategy(self)

    def get_host(self):
        parameters = globals().get("Parameters", {})
        if self.host is None or self.host.parameters is not parameters:
            self.host = make_host_runtime(parameters)
        return self.host

    def get_current_plugin_folder(self):
        return self.get_host().current_plugin_folder()

    def get_git_env(self):
        return self.get_host().get_git_env()

    def get_plugin_home_folder(self):
        return self.get_host().plugin_home_folder()

    def get_bundled_update_times_file(self):
        return os.path.join(self.get_plugin_home_folder(), "update_times.json")

    def get_update_times_cache_file(self):
        return os.path.join(self.get_plugin_home_folder(), "update_times.cache.json")

    def get_update_times_url(self):
        return "https://raw.githubusercontent.com/adrighem/PyPluginStore/refs/heads/master/update_times.json"

    def get_registry_url(self):
        return "https://raw.githubusercontent.com/adrighem/PyPluginStore/refs/heads/master/registry.json"

    def get_bundled_registry_file(self):
        return os.path.join(self.get_plugin_home_folder(), "registry.json")

    def get_local_registry_file(self):
        return os.path.join(self.get_plugin_home_folder(), "registry_local.json")

    def get_registry_entry(self, plugin_key):
        data = self.plugin_data.get(plugin_key)
        if data is not None:
            has_explicit_platforms = (
                plugin_key in self.plugin_platforms
                or (isinstance(data, list) and len(data) > 5)
                or (
                    isinstance(data, dict)
                    and ("platforms" in data or "platform" in data)
                )
            )
            entry, platforms = self.registry_service.normalize_entry(
                plugin_key,
                data,
                local=plugin_key in self.local_plugin_keys,
                default_platforms=self.plugin_platforms.get(plugin_key),
            )
            if entry is None:
                return None
            self.registry_entries[plugin_key] = entry
            if has_explicit_platforms:
                self.plugin_platforms[plugin_key] = platforms
            return entry

        return self.registry_entries.get(plugin_key)

    def get_registry_entry_for_operation(self, plugin_key, author="", repository="", branch=""):
        entry = self.get_registry_entry(plugin_key)
        if entry is None:
            entry = RegistryEntry(plugin_key, author, repository, "", branch or "master")
        else:
            entry = entry.copy_with(
                author=author if author else None,
                repository=repository if repository else None,
                branch=branch if branch else None,
            )
        return entry

    def supported_git_host(self, hostname):
        hostname = str(hostname or "").strip().lower()
        return hostname if hostname in SUPPORTED_GIT_HOSTS else ""

    def clean_repository_path_parts(self, path_parts):
        cleaned_parts = []
        for part in path_parts:
            part = urllib.parse.unquote(str(part or "").strip())
            if not part:
                continue
            if part in REPOSITORY_PATH_STOP_PARTS:
                break
            cleaned_parts.append(part)

        if cleaned_parts and cleaned_parts[-1].endswith(".git"):
            cleaned_parts[-1] = cleaned_parts[-1][:-4]
        return cleaned_parts

    def split_supported_repo_reference(self, repo_reference):
        repo_reference = str(repo_reference or "").strip().rstrip("/")
        if not repo_reference:
            return "", []

        if re.match(r"^[^/@:]+@[^:]+:.+", repo_reference):
            user_host, path = repo_reference.split(":", 1)
            host = self.supported_git_host(user_host.split("@")[-1])
            if not host:
                return "", []
            return host, self.clean_repository_path_parts(path.split("/"))

        parsed_url = urllib.parse.urlparse(repo_reference)
        if parsed_url.hostname:
            host = self.supported_git_host(parsed_url.hostname)
            if not host:
                return "", []
            return host, self.clean_repository_path_parts(parsed_url.path.split("/"))

        shorthand_url = urllib.parse.urlparse("//" + repo_reference)
        host = self.supported_git_host(shorthand_url.hostname)
        if host:
            return host, self.clean_repository_path_parts(shorthand_url.path.split("/"))

        return "", []

    def repository_path_from_entry(self, author, repository):
        repository = str(repository or "").strip().strip("/")
        host, path_parts = self.split_supported_repo_reference(author)
        if not host:
            host = DEFAULT_GIT_HOST
            path_parts = self.clean_repository_path_parts(str(author or "").strip().split("/"))

        if repository:
            path_parts = list(path_parts) + [repository]

        return host, self.clean_repository_path_parts(path_parts)

    def quote_url_path_parts(self, path_parts):
        return "/".join(urllib.parse.quote(str(part), safe="") for part in path_parts)

    def build_git_clone_url(self, author, repository):
        author = str(author or "").strip()
        repository = str(repository or "").strip()

        if author.startswith("git@") or author.startswith("ssh://") or author.startswith("file://"):
            return author.rstrip("/")

        if author.startswith("http://") or author.startswith("https://"):
            clone_url = author.rstrip("/")
            parsed_url = urllib.parse.urlparse(clone_url)
            host, path_parts = self.split_supported_repo_reference(clone_url)
            if parsed_url.scheme in ("http", "https") and host and len(path_parts) >= 2:
                clone_url = parsed_url.scheme + "://" + host + "/" + self.quote_url_path_parts(path_parts)
                if not clone_url.endswith(".git"):
                    clone_url += ".git"
            return clone_url

        host, path_parts = self.repository_path_from_entry(author, repository)
        if host and len(path_parts) >= 2:
            return "https://" + host + "/" + self.quote_url_path_parts(path_parts) + ".git"

        return f"https://github.com/{author}/{repository}.git"

    def build_raw_plugin_url(self, author, repository, branch):
        host, path_parts = self.repository_path_from_entry(author, repository)
        if not host or len(path_parts) < 2:
            return ""

        repo_path = self.quote_url_path_parts(path_parts)
        branch = urllib.parse.quote(str(branch or ""), safe="")
        if host == "github.com":
            return "https://raw.githubusercontent.com/" + repo_path + "/" + branch + "/plugin.py"
        if host == "gitlab.com":
            return "https://gitlab.com/" + repo_path + "/-/raw/" + branch + "/plugin.py"
        if host == "codeberg.org":
            return "https://codeberg.org/" + repo_path + "/raw/branch/" + branch + "/plugin.py"
        return ""

    def normalize_plugin_folder_name(self, folder_name):
        folder_name = str(folder_name or "").strip().strip("/\\")
        if folder_name.endswith(".git"):
            folder_name = folder_name[:-4]
        return folder_name.lower()

    def plugin_folder_name_from_clone_url(self, clone_url):
        clone_url = str(clone_url or "").strip().rstrip("/")
        if not clone_url:
            return ""
        if clone_url.endswith(".git"):
            clone_url = clone_url[:-4]

        if re.match(r"^[^/@:]+@[^:]+:.+", clone_url):
            path = clone_url.split(":", 1)[1]
        else:
            parsed_url = urllib.parse.urlparse(clone_url)
            path = parsed_url.path if parsed_url.scheme else clone_url

        return os.path.basename(path.rstrip("/"))

    def normalize_git_remote_url(self, remote_url):
        remote_url = str(remote_url or "").strip()
        if not remote_url:
            return ""

        remote_url = remote_url.replace(" (fetch)", "").replace(" (push)", "").strip()
        if re.match(r"^[^/@:]+@[^:]+:.+", remote_url):
            user_host, path = remote_url.split(":", 1)
            host = user_host.split("@")[-1]
            path = path.strip("/")
            if path.endswith(".git"):
                path = path[:-4]
            return (host + "/" + path).lower()

        parsed_url = urllib.parse.urlparse(remote_url)
        if parsed_url.scheme == "file":
            file_path = urllib.request.url2pathname(parsed_url.path)
            return "file://" + os.path.normcase(os.path.abspath(file_path)).rstrip(os.sep).lower()

        if parsed_url.hostname:
            path = parsed_url.path.strip("/")
            if path.endswith(".git"):
                path = path[:-4]
            return (parsed_url.hostname + "/" + path).lower()

        remote_url = remote_url.rstrip("/")
        if remote_url.endswith(".git"):
            remote_url = remote_url[:-4]
        return remote_url.lower()

    def normalize_git_repo_identity(self, repo_url):
        host, path_parts = self.split_supported_repo_reference(repo_url)
        if not host or len(path_parts) < 2:
            return ""
        return (host + "/" + "/".join(path_parts)).lower()

    def normalize_github_repo_identity(self, repo_url):
        return self.normalize_git_repo_identity(repo_url)

    def normalize_plugin_metadata_value(self, value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def strip_domoticz_plugin_affixes(self, value):
        original_value = str(value or "").strip()
        if original_value.endswith(".git"):
            original_value = original_value[:-4]

        cleaned_value = original_value
        for pattern in (
            r"^domoticz[-_ ]+plugin[-_ ]+",
            r"^domoticz[-_ ]+for[-_ ]+",
            r"^domoticz[-_ ]+",
            r"[-_ ]+domoticz[-_ ]+plugin$",
            r"[-_ ]+for[-_ ]+domoticz$",
            r"[-_ ]+domoticz$",
        ):
            cleaned_value = re.sub(pattern, "", cleaned_value, flags=re.IGNORECASE)

        cleaned_value = re.sub(r"^[-_ ]+|[-_ ]+$", "", cleaned_value)
        if cleaned_value != original_value:
            cleaned_value = re.sub(r"^plugin[-_ ]+", "", cleaned_value, flags=re.IGNORECASE)
            cleaned_value = re.sub(r"[-_ ]+plugin$", "", cleaned_value, flags=re.IGNORECASE)
            cleaned_value = re.sub(r"^[-_ ]+|[-_ ]+$", "", cleaned_value)

        return cleaned_value or original_value

    def parse_domoticz_plugin_metadata(self, plugin_dir):
        plugin_file = os.path.join(plugin_dir, "plugin.py")
        if not os.path.isfile(plugin_file):
            return None

        try:
            with open(plugin_file, "r", encoding="utf-8", errors="ignore") as f:
                source_code = f.read(256 * 1024)
        except Exception as e:
            Domoticz.Debug("Could not read plugin metadata from " + plugin_file + ": " + str(e))
            return None

        plugin_tag = re.search(r"<plugin\b([^>]*)>", source_code, re.IGNORECASE | re.DOTALL)
        if not plugin_tag:
            return None

        metadata = {}
        for match in re.finditer(r"([A-Za-z_][\w:.-]*)\s*=\s*(\"([^\"]*)\"|'([^']*)')", plugin_tag.group(1)):
            value = match.group(3) if match.group(3) is not None else match.group(4)
            metadata[match.group(1).lower()] = html.unescape(value or "")
        return metadata

    def plugin_metadata_matches_registry(self, plugin_key, plugin_dir, metadata=None):
        entry = self.get_registry_entry(plugin_key)
        if entry is None:
            return False

        if metadata is None:
            metadata = self.parse_domoticz_plugin_metadata(plugin_dir)
            if metadata is None:
                Domoticz.Debug("Skipped possible plugin match for folder " + os.path.basename(plugin_dir) + " because plugin.py metadata could not be verified.")
                return False

        clone_url = self.build_git_clone_url(entry.author, entry.repository)
        expected_repo_identity = self.normalize_github_repo_identity(clone_url)
        externallink = metadata.get("externallink", "")
        externallink_identity = self.normalize_github_repo_identity(externallink)
        if externallink_identity:
            if externallink_identity == expected_repo_identity:
                return True
            Domoticz.Debug("Skipped possible plugin match for folder " + os.path.basename(plugin_dir) + " because externallink points to another repository.")
            return False

        repo_folder = self.plugin_folder_name_from_clone_url(clone_url)
        expected_names = set()
        for expected_name in (plugin_key, entry.repository, repo_folder):
            expected_names.add(self.normalize_plugin_metadata_value(expected_name))
            expected_names.add(
                self.normalize_plugin_metadata_value(
                    self.strip_domoticz_plugin_affixes(expected_name)
                )
            )
        expected_names.discard("")

        metadata_names = [
            self.normalize_plugin_metadata_value(metadata.get("key", "")),
            self.normalize_plugin_metadata_value(metadata.get("name", "")),
        ]
        if any(metadata_name in expected_names for metadata_name in metadata_names if metadata_name):
            return True

        plugin_key_metadata = self.normalize_plugin_metadata_value(metadata.get("key", ""))
        if plugin_key_metadata and plugin_key_metadata not in expected_names:
            Domoticz.Debug("Skipped possible plugin match for folder " + os.path.basename(plugin_dir) + " because plugin metadata key does not match.")
            return False

        return True

    def add_lookup_candidate(self, lookup, lookup_key, plugin_key):
        if not lookup_key:
            return
        if lookup_key not in lookup:
            lookup[lookup_key] = []
        if plugin_key not in lookup[lookup_key]:
            lookup[lookup_key].append(plugin_key)

    def prefer_local_lookup_candidates(self, lookup):
        local_plugin_keys = set(self.local_plugin_keys)
        if not local_plugin_keys:
            return

        for lookup_key, matched_keys in list(lookup.items()):
            local_matches = [plugin_key for plugin_key in matched_keys if plugin_key in local_plugin_keys]
            if local_matches and len(local_matches) != len(matched_keys):
                lookup[lookup_key] = local_matches

    def add_install_name_candidate(self, name_lookup, candidate, plugin_key):
        self.add_lookup_candidate(name_lookup, self.normalize_plugin_folder_name(candidate), plugin_key)

    def add_flexible_name_candidate(self, name_lookup, candidate, plugin_key):
        self.add_lookup_candidate(name_lookup, self.normalize_plugin_metadata_value(candidate), plugin_key)

    def add_domoticz_affix_name_candidate(self, name_lookup, candidate, plugin_key):
        self.add_flexible_name_candidate(name_lookup, self.strip_domoticz_plugin_affixes(candidate), plugin_key)

    def build_installed_plugin_lookup(self):
        exact_name_lookup = {}
        archive_name_lookup = {}
        flexible_name_lookup = {}
        metadata_name_lookup = {}
        remote_lookup = {}
        repo_identity_lookup = {}

        for plugin_key in self.plugin_data:
            entry = self.get_registry_entry(plugin_key)
            if plugin_key == "Idle" or entry is None:
                continue

            exact_name_lookup[self.normalize_plugin_folder_name(plugin_key)] = plugin_key
            self.add_flexible_name_candidate(flexible_name_lookup, plugin_key, plugin_key)
            self.add_flexible_name_candidate(metadata_name_lookup, plugin_key, plugin_key)

        for plugin_key in self.plugin_data:
            entry = self.get_registry_entry(plugin_key)
            if plugin_key == "Idle" or entry is None:
                continue

            repository = entry.repository
            branch = entry.branch
            clone_url = self.build_git_clone_url(entry.author, repository)
            repo_folder = self.plugin_folder_name_from_clone_url(clone_url)
            name_candidates = [repository, repo_folder]

            for candidate in name_candidates:
                if not candidate:
                    continue
                self.add_install_name_candidate(archive_name_lookup, candidate, plugin_key)
                self.add_flexible_name_candidate(flexible_name_lookup, candidate, plugin_key)
                self.add_domoticz_affix_name_candidate(flexible_name_lookup, candidate, plugin_key)
                self.add_flexible_name_candidate(metadata_name_lookup, candidate, plugin_key)
                if branch:
                    self.add_install_name_candidate(archive_name_lookup, candidate + "-" + branch, plugin_key)
                    self.add_install_name_candidate(archive_name_lookup, candidate + "_" + branch, plugin_key)
                    self.add_flexible_name_candidate(flexible_name_lookup, candidate + "-" + branch, plugin_key)
                    self.add_flexible_name_candidate(flexible_name_lookup, candidate + "_" + branch, plugin_key)
                    stripped_candidate = self.strip_domoticz_plugin_affixes(candidate)
                    self.add_flexible_name_candidate(flexible_name_lookup, stripped_candidate + "-" + branch, plugin_key)
                    self.add_flexible_name_candidate(flexible_name_lookup, stripped_candidate + "_" + branch, plugin_key)

            remote_key = self.normalize_git_remote_url(clone_url)
            self.add_lookup_candidate(remote_lookup, remote_key, plugin_key)
            repo_identity = self.normalize_github_repo_identity(clone_url)
            self.add_lookup_candidate(repo_identity_lookup, repo_identity, plugin_key)

        for lookup in (
            archive_name_lookup,
            flexible_name_lookup,
            metadata_name_lookup,
            remote_lookup,
            repo_identity_lookup,
        ):
            self.prefer_local_lookup_candidates(lookup)

        return (
            exact_name_lookup,
            archive_name_lookup,
            flexible_name_lookup,
            metadata_name_lookup,
            remote_lookup,
            repo_identity_lookup,
        )

    def get_git_remote_urls(self, plugin_dir):
        result = self.run_git_command(plugin_dir, ["git", "remote", "-v"], timeout=10)
        remote_urls = []
        if result is not None and result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] in ("(fetch)", "(push)") and parts[1] not in remote_urls:
                    remote_urls.append(parts[1])

        if not remote_urls:
            remote_url = self.get_git_remote_url(plugin_dir, "origin")
            if remote_url and not any(char.isspace() for char in remote_url):
                remote_urls.append(remote_url)
        return remote_urls

    def make_installed_plugin_match(self, plugin_key, source, priority, detail):
        return {
            "key": plugin_key,
            "source": source,
            "priority": priority,
            "detail": detail,
        }

    def match_detail_for_response(self, plugin_folder, match):
        return {
            "folder": plugin_folder,
            "source": match.get("source", ""),
            "detail": match.get("detail", ""),
        }

    def log_installed_plugin_match(self, plugin_folder, match):
        Domoticz.Debug(
            "Detected installed plugin "
            + match.get("key", "")
            + " in folder "
            + plugin_folder
            + " using "
            + match.get("source", "unknown source")
            + ". "
            + match.get("detail", "")
        )

    def match_lookup_candidate(self, plugin_folder, lookup_key, lookup, source, priority, detail, reason):
        if not lookup_key:
            return None

        matched_keys = lookup.get(lookup_key, [])
        if len(matched_keys) == 1:
            return self.make_installed_plugin_match(matched_keys[0], source, priority, detail)
        if len(matched_keys) > 1:
            Domoticz.Debug(
                "Could not use "
                + reason
                + " for folder "
                + plugin_folder
                + " because it matches multiple registry entries: "
                + ", ".join(matched_keys)
            )
        return None

    def match_unique_lookup_candidate(self, plugin_folder, lookup_key, lookup, reason):
        match = self.match_lookup_candidate(
            plugin_folder,
            lookup_key,
            lookup,
            reason,
            0,
            "",
            reason,
        )
        if match:
            return match["key"]
        return ""

    def match_unique_archive_match_candidate(self, plugin_folder, archive_name_lookup):
        return self.match_lookup_candidate(
            plugin_folder,
            self.normalize_plugin_folder_name(plugin_folder),
            archive_name_lookup,
            "repository/archive folder name",
            40,
            "Folder name matches a unique repository or GitHub archive folder name.",
            "folder name",
        )

    def match_unique_archive_candidate(self, plugin_folder, archive_name_lookup):
        match = self.match_unique_archive_match_candidate(plugin_folder, archive_name_lookup)
        if match:
            return match["key"]
        return ""

    def match_unique_flexible_folder_match_candidate(self, plugin_folder, flexible_name_lookup):
        return self.match_lookup_candidate(
            plugin_folder,
            self.normalize_plugin_metadata_value(plugin_folder),
            flexible_name_lookup,
            "normalized folder name",
            50,
            "Folder name matches after punctuation, spacing, case, and Domoticz affix normalization.",
            "normalized folder name",
        )

    def match_unique_flexible_folder_candidate(self, plugin_folder, flexible_name_lookup):
        match = self.match_unique_flexible_folder_match_candidate(plugin_folder, flexible_name_lookup)
        if match:
            return match["key"]
        return ""

    def match_metadata_externallink_candidate(self, plugin_folder, metadata, repo_identity_lookup):
        externallink_identity = self.normalize_github_repo_identity(metadata.get("externallink", ""))
        if not externallink_identity:
            return None

        match = self.match_lookup_candidate(
            plugin_folder,
            externallink_identity,
            repo_identity_lookup,
            "plugin.py externallink",
            20,
            "plugin.py externallink points to a unique registry repository.",
            "plugin externallink",
        )
        if match:
            return match

        if not repo_identity_lookup.get(externallink_identity, []):
            Domoticz.Debug("Could not use plugin.py externallink for folder " + plugin_folder + " because it does not match the registry.")
        return None

    def match_metadata_externallink(self, plugin_folder, metadata, repo_identity_lookup):
        match = self.match_metadata_externallink_candidate(plugin_folder, metadata, repo_identity_lookup)
        if match:
            return match["key"]
        return ""

    def match_metadata_names_candidate(self, plugin_folder, metadata, metadata_name_lookup):
        matched_keys = []
        matched_fields = []
        for metadata_field in ("key", "name"):
            metadata_key = self.normalize_plugin_metadata_value(metadata.get(metadata_field, ""))
            for matched_key in metadata_name_lookup.get(metadata_key, []):
                if matched_key not in matched_keys:
                    matched_keys.append(matched_key)
                    matched_fields.append(metadata_field)

        if len(matched_keys) == 1:
            return self.make_installed_plugin_match(
                matched_keys[0],
                "plugin.py key/name",
                60,
                "plugin.py " + "/".join(matched_fields) + " metadata matches a unique registry entry.",
            )
        if len(matched_keys) > 1:
            Domoticz.Debug(
                "Could not use plugin.py key/name metadata for folder "
                + plugin_folder
                + " because it matches multiple registry entries: "
                + ", ".join(matched_keys)
            )
        return None

    def match_metadata_names(self, plugin_folder, metadata, metadata_name_lookup):
        match = self.match_metadata_names_candidate(plugin_folder, metadata, metadata_name_lookup)
        if match:
            return match["key"]
        return ""

    def inferred_folder_match_is_valid(self, matched_key, plugin_path, metadata):
        if metadata is None:
            return True
        return self.plugin_metadata_matches_registry(matched_key, plugin_path, metadata)

    def add_valid_inferred_folder_candidate(self, candidates, rejected_keys, candidate, plugin_folder, plugin_path, metadata):
        if not candidate:
            return
        matched_key = candidate["key"]
        if matched_key in rejected_keys:
            return
        if self.inferred_folder_match_is_valid(matched_key, plugin_path, metadata):
            candidates.append(candidate)
            return

        rejected_keys.add(matched_key)
        Domoticz.Debug(
            "Skipped "
            + candidate.get("source", "folder")
            + " candidate "
            + matched_key
            + " for folder "
            + plugin_folder
            + " because plugin.py metadata does not confirm it; continuing with lower priority evidence."
        )

    def choose_installed_plugin_match(self, candidates):
        valid_candidates = [candidate for candidate in candidates if candidate]
        if not valid_candidates:
            return None
        local_plugin_keys = set(self.local_plugin_keys)
        local_candidates = [candidate for candidate in valid_candidates if candidate.get("key") in local_plugin_keys]
        if local_candidates:
            valid_candidates = local_candidates
        valid_candidates.sort(key=lambda candidate: candidate.get("priority", 1000))
        return valid_candidates[0]

    def match_installed_plugin(
        self,
        plugin_folder,
        plugin_path,
        exact_name_lookup,
        archive_name_lookup,
        flexible_name_lookup,
        metadata_name_lookup,
        remote_lookup,
        repo_identity_lookup,
    ):
        candidates = []
        plugin_file = os.path.join(plugin_path, "plugin.py")
        is_git_repo = os.path.isdir(os.path.join(plugin_path, ".git"))
        remote_urls = self.get_git_remote_urls(plugin_path) if is_git_repo else []
        for remote_url in remote_urls:
            match = self.match_lookup_candidate(
                plugin_folder,
                self.normalize_git_remote_url(remote_url),
                remote_lookup,
                "git remote",
                10,
                "Git remote URL matches a unique registry repository.",
                "git remote",
            )
            if match:
                candidates.append(match)

        metadata = self.parse_domoticz_plugin_metadata(plugin_path) if os.path.isfile(plugin_file) else None
        if metadata is not None:
            candidates.append(self.match_metadata_externallink_candidate(plugin_folder, metadata, repo_identity_lookup))

        matched_key = exact_name_lookup.get(self.normalize_plugin_folder_name(plugin_folder), "")
        if matched_key:
            candidates.append(
                self.make_installed_plugin_match(
                    matched_key,
                    "exact folder key",
                    30,
                    "Folder name exactly matches a registry plugin key.",
                )
            )

        rejected_inferred_keys = set()
        self.add_valid_inferred_folder_candidate(
            candidates,
            rejected_inferred_keys,
            self.match_unique_archive_match_candidate(plugin_folder, archive_name_lookup),
            plugin_folder,
            plugin_path,
            metadata,
        )

        self.add_valid_inferred_folder_candidate(
            candidates,
            rejected_inferred_keys,
            self.match_unique_flexible_folder_match_candidate(plugin_folder, flexible_name_lookup),
            plugin_folder,
            plugin_path,
            metadata,
        )

        if metadata is not None:
            candidates.append(self.match_metadata_names_candidate(plugin_folder, metadata, metadata_name_lookup))
        elif not os.path.isfile(plugin_file) and not candidates:
            Domoticz.Debug("No registry match found for folder " + plugin_folder + " from git, folder, or metadata because plugin.py was not found.")

        match = self.choose_installed_plugin_match(candidates)
        if match:
            self.log_installed_plugin_match(plugin_folder, match)
        else:
            Domoticz.Debug("No registry match found for folder " + plugin_folder + ".")
        return match

    def match_installed_plugin_key(
        self,
        plugin_folder,
        plugin_path,
        exact_name_lookup,
        archive_name_lookup,
        flexible_name_lookup,
        metadata_name_lookup,
        remote_lookup,
        repo_identity_lookup,
    ):
        match = self.match_installed_plugin(
            plugin_folder,
            plugin_path,
            exact_name_lookup,
            archive_name_lookup,
            flexible_name_lookup,
            metadata_name_lookup,
            remote_lookup,
            repo_identity_lookup,
        )
        if match:
            return match["key"]
        return ""

    def load_registry_file(self, registry_file, label, missing_is_error=False):
        if not os.path.isfile(registry_file):
            if missing_is_error:
                Domoticz.Error("No " + label + " registry found.")
            else:
                Domoticz.Debug("No " + label + " registry file found.")
            return None

        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)
            if isinstance(registry, dict):
                Domoticz.Log("Loaded " + label + " plugin registry.")
                return registry
            Domoticz.Error(label + " registry file does not contain a JSON object.")
        except Exception as e:
            Domoticz.Error("Error reading " + label + " registry file: " + str(e))
        return None

    def fetch_remote_registry(self):
        Domoticz.Debug("Fetching plugin registry from GitHub.")
        try:
            req = urllib.request.Request(self.get_registry_url())
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    registry = json.loads(response.read().decode("utf-8"))
                    if isinstance(registry, dict):
                        Domoticz.Log("Successfully fetched plugin registry from GitHub.")
                        return registry
                    Domoticz.Error("Remote registry.json does not contain a JSON object.")
                else:
                    Domoticz.Error("Failed to fetch registry, status code: " + str(response.status))
        except Exception as e:
            Domoticz.Error("Error fetching registry: " + str(e))
        return None

    def load_bundled_registry(self):
        return self.load_registry_file(self.get_bundled_registry_file(), "bundled", True)

    def load_local_registry(self):
        return self.load_registry_file(self.get_local_registry_file(), "local")

    def load_update_times_file(self, update_times_file, label):
        if not os.path.isfile(update_times_file):
            Domoticz.Debug("No " + label + " update_times file found.")
            return {}

        try:
            with open(update_times_file, "r", encoding="utf-8") as f:
                update_times = json.load(f)
            if isinstance(update_times, dict):
                Domoticz.Debug("Loaded update times from " + label + " file.")
                return update_times
            Domoticz.Error(label + " update_times file does not contain a JSON object.")
        except Exception as e:
            Domoticz.Error("Error reading " + label + " update_times file: " + str(e))
        return {}

    def load_bundled_update_times(self):
        return self.load_update_times_file(self.get_bundled_update_times_file(), "bundled")

    def load_cached_update_times(self):
        return self.load_update_times_file(self.get_update_times_cache_file(), "cached")

    def save_update_times_cache(self, update_times):
        update_times_file = self.get_update_times_cache_file()
        try:
            with open(update_times_file, "w", encoding="utf-8") as f:
                json.dump(update_times, f, indent=4)
                f.write("\n")
            Domoticz.Log("Updated update_times.cache.json.")
            return True
        except Exception as e:
            Domoticz.Error("Error writing update_times.cache.json: " + str(e))
            return False

    def load_update_times(self):
        update_times = {}
        Domoticz.Debug("Fetching update times from GitHub.")
        try:
            req = urllib.request.Request(self.get_update_times_url())
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    update_times = json.loads(response.read().decode("utf-8"))
                    if isinstance(update_times, dict):
                        Domoticz.Log("Successfully fetched update times from GitHub.")
                    else:
                        Domoticz.Error("Remote update_times.json does not contain a JSON object.")
                        update_times = {}
                else:
                    Domoticz.Error("Failed to fetch update times, status code: " + str(response.status))
        except Exception as e:
            Domoticz.Error("Error fetching update times: " + str(e))

        if not update_times:
            update_times = self.load_bundled_update_times()

        cached_update_times = self.load_cached_update_times()
        for key, cached_updated_at in cached_update_times.items():
            if self.is_better_update_time(cached_updated_at, update_times.get(key, "")):
                update_times[key] = cached_updated_at

        if update_times:
            self.save_update_times_cache(update_times)
        return update_times

    def apply_update_times(self, update_times):
        self.update_times = update_times
        for key, data in self.plugin_data.items():
            if key == "Idle":
                continue

            updated_at = update_times.get(key, "")
            entry = self.get_registry_entry(key)
            if entry is not None:
                entry.updated_at = updated_at
                entry.updated_at_slot_present = True

            if not isinstance(data, list):
                continue

            if len(data) == 4:
                data.append(updated_at)
            elif len(data) >= 5:
                data[4] = updated_at

    def parse_update_time(self, updated_at):
        if not updated_at:
            return None
        try:
            return datetime.strptime(str(updated_at), "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return None

    def is_better_update_time(self, candidate, current):
        if not candidate:
            return False
        if not current:
            return True

        candidate_time = self.parse_update_time(candidate)
        current_time = self.parse_update_time(current)
        if candidate_time and current_time:
            return candidate_time > current_time
        if candidate_time and not current_time:
            return True
        return False

    def overlay_git_update_time(self, plugin_key, updated_at, update_times=None, remote_url="", remote_ref=""):
        if plugin_key not in self.plugin_data:
            return False

        if update_times is None:
            update_times = self.update_times

        current_updated_at = update_times.get(plugin_key, "")
        if not self.is_better_update_time(updated_at, current_updated_at):
            return False

        update_times[plugin_key] = updated_at

        data = self.plugin_data.get(plugin_key)
        if isinstance(data, list):
            if len(data) == 4:
                data.append(updated_at)
            elif len(data) >= 5:
                data[4] = updated_at
        entry = self.get_registry_entry(plugin_key)
        if entry is not None:
            entry.updated_at = updated_at
            entry.updated_at_slot_present = True

        Domoticz.Log("Git update date changed for " + plugin_key + ": " + updated_at)
        if remote_url:
            Domoticz.Debug("Update date source for " + plugin_key + ": " + remote_url + " " + remote_ref)
        return True

    def run_git_command(self, plugin_dir, command, timeout=15):
        return self.get_host().run_git(command, plugin_dir, timeout=timeout)

    def fetch_git_repo(self, plugin_dir):
        result = self.run_git_command(plugin_dir, ["git", "fetch", "--quiet"], timeout=15)
        if result is None:
            return False
        self.get_host().log_git_result("Fetch", result)
        return result.returncode == 0

    def get_git_current_branch(self, plugin_dir):
        result = self.run_git_command(plugin_dir, ["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=10)
        if result is not None and result.returncode == 0:
            branch = result.stdout.strip()
            if branch and branch != "HEAD":
                return branch
        return ""

    def get_git_remote_name(self, plugin_dir, branch=""):
        if branch:
            result = self.run_git_command(plugin_dir, ["git", "config", "--get", "branch." + branch + ".remote"], timeout=10)
            if result is not None and result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

        result = self.run_git_command(plugin_dir, ["git", "remote"], timeout=10)
        if result is not None and result.returncode == 0:
            remotes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if "origin" in remotes:
                return "origin"
            if remotes:
                return remotes[0]
        return "origin"

    def get_git_remote_url(self, plugin_dir, remote_name):
        result = self.run_git_command(plugin_dir, ["git", "remote", "get-url", remote_name], timeout=10)
        if result is not None and result.returncode == 0:
            return result.stdout.strip()
        return ""

    def git_ref_exists(self, plugin_dir, ref_name):
        result = self.run_git_command(plugin_dir, ["git", "rev-parse", "--verify", ref_name], timeout=10)
        return result is not None and result.returncode == 0

    def get_git_remote_ref(self, plugin_dir):
        result = self.run_git_command(
            plugin_dir,
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            timeout=10
        )
        if result is not None and result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        branch = self.get_git_current_branch(plugin_dir)
        remote_name = self.get_git_remote_name(plugin_dir, branch)
        if branch:
            branch_ref = remote_name + "/" + branch
            if self.git_ref_exists(plugin_dir, branch_ref):
                return branch_ref

        result = self.run_git_command(plugin_dir, ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/" + remote_name + "/HEAD"], timeout=10)
        if result is not None and result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        return ""

    def get_git_remote_commit_date(self, plugin_dir, remote_ref):
        if not remote_ref:
            return ""

        result = self.run_git_command(plugin_dir, ["git", "log", "-1", "--format=%ct", remote_ref], timeout=10)
        if result is None or result.returncode != 0:
            if result is not None and result.stderr:
                Domoticz.Debug("Git Log Error:" + result.stderr.strip())
            return ""

        timestamp = result.stdout.strip()
        if not timestamp:
            return ""

        try:
            return datetime.utcfromtimestamp(int(timestamp)).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception as e:
            Domoticz.Debug("Could not parse git commit timestamp '" + timestamp + "': " + str(e))
            return ""

    def get_git_ahead_behind(self, plugin_dir, remote_ref):
        if not remote_ref:
            return None

        result = self.run_git_command(
            plugin_dir,
            ["git", "rev-list", "--left-right", "--count", "HEAD..." + remote_ref],
            timeout=10
        )
        if result is None or result.returncode != 0:
            if result is not None and result.stderr:
                Domoticz.Debug("Git Rev-List Error:" + result.stderr.strip())
            return None

        ahead_behind = result.stdout.strip().split()
        if len(ahead_behind) < 2:
            return None

        try:
            return int(ahead_behind[0]), int(ahead_behind[1])
        except ValueError:
            return None

    def refresh_git_update_time(self, plugin_key, plugin_dir, update_times=None, remote_ref=""):
        if not plugin_key or not os.path.isdir(os.path.join(plugin_dir, ".git")):
            return False

        if not remote_ref:
            remote_ref = self.get_git_remote_ref(plugin_dir)

        updated_at = self.get_git_remote_commit_date(plugin_dir, remote_ref)
        if not updated_at:
            return False

        remote_name = remote_ref.split("/", 1)[0] if "/" in remote_ref else "origin"
        remote_url = self.get_git_remote_url(plugin_dir, remote_name)
        return self.overlay_git_update_time(plugin_key, updated_at, update_times, remote_url, remote_ref)

    def refresh_single_plugin_update_time(self, plugin_key, plugin_dir, fetch_first=True):
        if not os.path.isdir(os.path.join(plugin_dir, ".git")):
            return False

        if fetch_first and not self.fetch_git_repo(plugin_dir):
            return False

        update_times = dict(self.update_times) if self.update_times else self.load_cached_update_times()
        changed = self.refresh_git_update_time(plugin_key, plugin_dir, update_times)
        if changed:
            self.save_update_times_cache(update_times)
            self.apply_update_times(update_times)
        return changed

    def add_installed_plugin(self, installed_plugins, plugin_key):
        if plugin_key and plugin_key not in installed_plugins:
            installed_plugins.append(plugin_key)

    def getInstalledPlugins(self, plugins_dir):
        installed_plugins = []
        installed_plugin_folders = {}
        installed_plugin_match_details = {}
        (
            exact_name_lookup,
            archive_name_lookup,
            flexible_name_lookup,
            metadata_name_lookup,
            remote_lookup,
            repo_identity_lookup,
        ) = self.build_installed_plugin_lookup()

        try:
            plugin_folders = os.listdir(plugins_dir)
        except Exception as e:
            Domoticz.Error("Could not scan Domoticz plugins folder: " + str(e))
            self.installed_plugin_folders = {}
            self.installed_plugin_match_details = {}
            return installed_plugins

        for plugin_folder in plugin_folders:
            plugin_path = os.path.join(plugins_dir, plugin_folder)
            if not os.path.isdir(plugin_path) or plugin_folder.startswith("."):
                continue

            is_git_repo = os.path.isdir(os.path.join(plugin_path, ".git"))
            match = self.match_installed_plugin(
                plugin_folder,
                plugin_path,
                exact_name_lookup,
                archive_name_lookup,
                flexible_name_lookup,
                metadata_name_lookup,
                remote_lookup,
                repo_identity_lookup,
            )
            matched_key = match["key"] if match else ""
            if matched_key:
                self.add_installed_plugin(installed_plugins, matched_key)
                installed_plugin_folders[matched_key] = plugin_folder
                detail = self.match_detail_for_response(plugin_folder, match)
                detail["is_git"] = is_git_repo
                installed_plugin_match_details[matched_key] = detail
                if plugin_folder not in self.plugin_data:
                    self.add_installed_plugin(installed_plugins, plugin_folder)
                    installed_plugin_folders[plugin_folder] = plugin_folder
                    installed_plugin_match_details[plugin_folder] = {
                        "folder": plugin_folder,
                        "source": "local folder alias",
                        "detail": "Physical folder is also listed because it is not a registry plugin key.",
                        "is_git": is_git_repo,
                    }
            elif plugin_folder not in self.plugin_data:
                self.add_installed_plugin(installed_plugins, plugin_folder)
                installed_plugin_folders[plugin_folder] = plugin_folder
                installed_plugin_match_details[plugin_folder] = {
                    "folder": plugin_folder,
                    "source": "local folder",
                    "detail": "No registry match was found; folder is listed as a local plugin.",
                    "is_git": is_git_repo,
                }

        self.installed_plugin_folders = installed_plugin_folders
        self.installed_plugin_match_details = installed_plugin_match_details
        return installed_plugins

    def get_installed_plugin_folder(self, plugin_key, plugins_dir=None):
        plugin_key = self.get_host().validate_plugin_key(plugin_key)
        if plugins_dir is None:
            plugins_dir = self.get_host().plugins_dir()

        plugin_folder = self.installed_plugin_folders.get(plugin_key, "")
        if plugin_folder and os.path.isdir(os.path.join(plugins_dir, plugin_folder)):
            return plugin_folder

        self.getInstalledPlugins(plugins_dir)
        return self.installed_plugin_folders.get(plugin_key, plugin_key)

    def resolve_installed_plugin_dir(self, plugin_key, plugins_dir=None):
        host = self.get_host()
        plugin_key = host.validate_plugin_key(plugin_key)
        if plugins_dir is None:
            plugins_dir = host.plugins_dir()

        plugins_dir = os.path.abspath(plugins_dir)
        plugin_folder = host.validate_plugin_key(self.get_installed_plugin_folder(plugin_key, plugins_dir))
        plugin_dir = os.path.abspath(os.path.join(plugins_dir, plugin_folder))
        if not host.is_path_inside(plugin_dir, plugins_dir):
            raise ValueError("Invalid plugin path")
        return plugin_dir

    def getCachedUpdateStatuses(self, installed_plugins):
        update_status = {}
        for plugin_key in installed_plugins:
            if plugin_key not in self.plugin_data:
                update_status[plugin_key] = "unknown"
                continue
            update_status[plugin_key] = self.update_status.get(plugin_key, "unknown")
        return update_status

    def get_plugin_versions(self, installed_plugins, update_status, plugins_dir):
        versions = {}
        for plugin_key in installed_plugins:
            entry = self.get_registry_entry(plugin_key)
            if entry is None:
                continue

            try:
                plugin_dir = self.resolve_installed_plugin_dir(plugin_key, plugins_dir)
            except ValueError:
                continue

            local_meta = self.parse_domoticz_plugin_metadata(plugin_dir)
            installed_version = local_meta.get("version") if local_meta else None
            available_version = None

            if update_status.get(plugin_key) == "available":
                url = self.build_raw_plugin_url(entry.author, entry.repository, entry.branch)
                if not url:
                    Domoticz.Debug("Could not build remote version URL for " + str(entry.repository))
                    continue
                try:
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=5) as response:
                        source_code = response.read().decode('utf-8', errors='ignore')
                        plugin_tag = re.search(r"<plugin\b([^>]*)>", source_code, re.IGNORECASE | re.DOTALL)
                        if plugin_tag:
                            for match in re.finditer(r"([A-Za-z_][\w:.-]*)\s*=\s*(\"([^\"]*)\"|'([^']*)')", plugin_tag.group(1)):
                                if match.group(1).lower() == 'version':
                                    val = match.group(3) if match.group(3) is not None else match.group(4)
                                    available_version = html.unescape(val or "")
                                    break
                except Exception as e:
                    Domoticz.Debug(f"Could not fetch remote version for {entry.repository}: {e}")

            if installed_version or available_version:
                versions[plugin_key] = {}
                if installed_version:
                    versions[plugin_key]["installed"] = installed_version
                if available_version:
                    versions[plugin_key]["available"] = available_version
        return versions

    def refresh_single_plugin_update_status(self, plugin_key, plugin_dir, fetch_first=True):
        return self.update_status_service.refresh_single_plugin_update_status(plugin_key, plugin_dir, fetch_first)

    def refreshInstalledUpdateStatuses(self, installed_plugins=None, plugins_dir=None):
        return self.update_status_service.refresh_installed_update_statuses(installed_plugins, plugins_dir)

    def get_managed_installed_plugin_keys(self, plugins_dir=None):
        if plugins_dir is None:
            plugins_dir = self.get_host().plugins_dir()

        managed_plugins = []
        for plugin_key in self.getInstalledPlugins(plugins_dir):
            if plugin_key in self.plugin_data and plugin_key not in managed_plugins:
                managed_plugins.append(plugin_key)
        return managed_plugins

    def add_self_to_registry(self):
        self_key = self.get_current_plugin_folder()
        if not self_key:
            return

        entry = RegistryEntry(
            self_key,
            "adrighem",
            "PyPluginStore",
            "PyPluginStore plugin manager",
            "master",
            self.update_times.get(self_key, ""),
            ["linux", "windows"],
            True,
        )
        self.registry_entries[self_key] = entry
        self.plugin_data[self_key] = entry.to_legacy_list()
        self.plugin_platforms[self_key] = entry.platforms

    def normalize_platforms(self, platforms):
        if not platforms:
            return ["unknown"]
        if isinstance(platforms, str):
            platforms = [platforms]
        if not isinstance(platforms, list):
            return ["unknown"]

        normalized = []
        for platform_name in platforms:
            platform_name = str(platform_name or "").strip().lower()
            if platform_name in ("linux", "windows") and platform_name not in normalized:
                normalized.append(platform_name)

        return normalized or ["unknown"]

    def normalize_registry_entry(self, key, data):
        entry, platforms = self.registry_service.normalize_entry(key, data)
        if entry is None:
            return None, platforms
        return entry.to_legacy_list(), platforms

    def normalize_registry(self, registry):
        normalized_registry, plugin_platforms, registry_entries = self.registry_service.normalize_registry(registry)
        self.registry_entries = registry_entries
        return normalized_registry, plugin_platforms

    def fetch_registry(self):
        registry = self.fetch_remote_registry()
        if registry is None:
            registry = self.load_bundled_registry()

        local_registry = self.load_local_registry()
        registry_loaded = registry is not None or local_registry is not None
        merged_registry = dict(registry) if registry is not None else {}
        local_plugin_keys = []

        if local_registry:
            merged_registry.update(local_registry)
            local_plugin_keys = sorted(local_registry.keys())
            Domoticz.Log("Merged " + str(len(local_registry)) + " local plugin registry entries.")

        if registry_loaded:
            (
                self.plugin_data,
                self.plugin_platforms,
                self.registry_entries,
            ) = self.registry_service.normalize_registry(merged_registry, local_plugin_keys)
            self.local_plugin_keys = local_plugin_keys
        elif self.plugin_data:
            Domoticz.Error("No plugin registry found. Keeping existing plugin registry.")
        else:
            self.plugin_data = {}
            self.registry_entries = {}
            self.plugin_platforms = {}
            self.local_plugin_keys = []
            Domoticz.Error("No plugin registry found. Plugins cannot be managed.")

        update_times = self.load_update_times()
        self.apply_update_times(update_times)
        self.add_self_to_registry()

    def sendDomoticzNotification(self, subject, message):
        send_notification = getattr(Domoticz, "SendNotification", None)
        if not callable(send_notification):
            Domoticz.Log("Notification skipped because this Domoticz version does not expose SendNotification: " + subject)
            return False

        try:
            send_notification(subject, message)
            Domoticz.Debug("Notification sent natively.")
            return True
        except Exception as e:
            Domoticz.Error("Failed to send notification: " + str(e))
            return False

    def onStart(self):
        import json
        Domoticz.Debug("onStart called")

        if Parameters["Mode6"] == 'Debug':
            self.debug = True
            Domoticz.Debugging(1)
            DumpConfigToLog()
        else:
            Domoticz.Debugging(0)

        Domoticz.Log(f"Domoticz Node Name is: {platform.node()}")
        Domoticz.Log(f"Domoticz Platform System is: {platform.system()}")
        Domoticz.Debug(f"Domoticz Platform Release is: {platform.release()}")
        Domoticz.Debug(f"Domoticz Platform Version is: {platform.version()}")
        Domoticz.Log(f"Default Python Version is: {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")

        host = self.get_host()
        Domoticz.Log(f"PyPluginStore host runtime is: {host.platform_name}")

        plugins_dir = host.plugins_dir()

        current_folder = self.get_current_plugin_folder()
        if not current_folder.startswith("00-"):
            warn_msg = f"PyPluginStore is in '{current_folder}'. It is strongly advised to rename the folder to start with '00-' (e.g., '00-PyPluginStore') so it loads first."
            Domoticz.Error(warn_msg)
            self.sendDomoticzNotification("PyPluginStore Setup Warning", warn_msg)

        # Inject shared dependencies into sys.path
        shared_deps_dir = host.shared_deps_dir()
        if os.path.isdir(shared_deps_dir) and shared_deps_dir not in sys.path:
            sys.path.insert(0, shared_deps_dir)
            Domoticz.Log(f"Injected PyPluginStore shared dependencies into sys.path: {shared_deps_dir}")

        # Autoinstall/Update Custom UI
        templates_dir = host.templates_dir()
        try:
            html_src = host.ui_html_source()
            ui_asset_names = ["pypluginstore-icon.png"]
            images_dir = host.images_dir()
            html_dst = host.ui_html_destination()
            
            if os.path.isfile(html_src):
                if not os.path.exists(templates_dir):
                    Domoticz.Debug(f"Creating templates directory: {templates_dir}")
                    os.makedirs(templates_dir, exist_ok=True)
                if not os.path.exists(images_dir):
                    Domoticz.Debug(f"Creating images directory: {images_dir}")
                    os.makedirs(images_dir, exist_ok=True)
                
                # Remove legacy UI if it exists
                old_html_dst = os.path.join(templates_dir, "pp-manager.html")
                if os.path.isfile(old_html_dst):
                    try:
                        os.remove(old_html_dst)
                        Domoticz.Log(f"Removed legacy UI file: {old_html_dst}")
                    except Exception as e:
                        Domoticz.Error(f"Failed to remove legacy UI file: {e}")
                
                # Check if we need to copy (exists and different, or doesn't exist)
                should_copy = True
                if os.path.isfile(html_dst):
                    src_mtime = os.path.getmtime(html_src)
                    dst_mtime = os.path.getmtime(html_dst)
                    if src_mtime <= dst_mtime:
                        should_copy = False
                
                if should_copy:
                    shutil.copyfile(html_src, html_dst)
                    host.make_web_readable(html_dst)
                    Domoticz.Log(f"Custom UI autoinstalled/updated: {html_dst}")
                else:
                    Domoticz.Debug("Custom UI is already up to date.")

                for asset_name in ui_asset_names:
                    asset_src = host.ui_asset_source(asset_name)
                    asset_dst = host.ui_asset_destination(asset_name)
                    if os.path.isfile(asset_src):
                        shutil.copyfile(asset_src, asset_dst)
                        host.make_web_readable(asset_dst)
                        Domoticz.Debug(f"Custom UI asset installed/updated: {asset_dst}")
        except Exception as e:
            Domoticz.Error(f"Custom UI autoinstall failed: {e}")
            Domoticz.Debug(f"Check permissions for: {templates_dir}")

        if 1 not in Devices:
            Domoticz.Device(Name="API Payload", Unit=1, TypeName="Text", DeviceID="PPM_API_PAYLOAD", Used=1).Create()
        if 2 not in Devices:
            Domoticz.Device(Name="API Trigger", Unit=2, Type=244, Subtype=73, Switchtype=9, DeviceID="PPM_API_TRIGGER", Used=1).Create()
            
        self.fetch_registry()
        self.processPendingOperations()

        if Parameters.get("Mode5") == 'True':
            Domoticz.Log("Plugin Security Scan is enabled")
            secpoluserFile = os.path.join(self.get_plugin_home_folder(), "secpoluser.txt")
            Domoticz.Debug("Checking for SecPolUser file on:" + secpoluserFile)
            if os.path.isfile(secpoluserFile):
                Domoticz.Log("secpoluser file found. Processing!!!")
                with open(secpoluserFile) as secpoluserFileHandle:
                    for line in secpoluserFileHandle:
                        line = line.strip()
                        if line.startswith("--->"):
                            secpoluserSection = line[4:]
                            Domoticz.Log("secpoluser settings found for plugin:" + secpoluserSection)
                        elif line and not line.startswith("--->"):
                            Domoticz.Debug("SecPolUserList exception (" + secpoluserSection + "): '" + line + "'")
                            if secpoluserSection not in self.secpoluser_list:
                                self.secpoluser_list[secpoluserSection] = []
                            self.secpoluser_list[secpoluserSection].append(line)
                Domoticz.Log("SecPolUserList exception:" + str(self.secpoluser_list))
            else:
                self.secpoluser_list = {"Global":[]}

            # Scan all plugins in the plugins directory
            for plugin_folder in os.listdir(plugins_dir):
                plugin_path = os.path.join(plugins_dir, plugin_folder)

                # Make sure it's a directory and not the manager itself
                if os.path.isdir(plugin_path) and plugin_folder != self.get_current_plugin_folder():

                    # Recursively walk through the plugin's folder to find all .py files
                    for root, _, files in os.walk(plugin_path):
                        # Optional: skip hidden folders like .git or .shared_deps
                        if '/.' in root.replace('\\', '/'):
                            continue

                        for file in files:
                            if file.endswith('.py'):
                                py_file = os.path.join(root, file)
                                self.parseFileForSecurityIssues(py_file, plugin_folder)

        exceptionFile = os.path.join(self.get_plugin_home_folder(), "exceptions.txt")
        Domoticz.Debug("Checking for Exception file on:" + exceptionFile)
        if os.path.isfile(exceptionFile):
            Domoticz.Log("Exception file found. Processing!!!")
            with open(exceptionFile) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        Domoticz.Log("File ReadLine result:'" + line + "'")
                        self.exception_list.append(line)
        Domoticz.Debug("self.exception_list:" + str(self.exception_list))

        if Parameters["Mode4"] == 'All':
            Domoticz.Log("Updating All Plugins!!!")
            for plugin_key in self.get_managed_installed_plugin_keys(plugins_dir):
                entry = self.get_registry_entry(plugin_key)
                if entry is not None:
                    self.UpdatePythonPlugin(entry.author, entry.repository, plugin_key)

        if Parameters["Mode4"] == 'AllNotify':
            Domoticz.Log("Collecting Updates for All Plugins!!!")
            for plugin_key in self.get_managed_installed_plugin_keys(plugins_dir):
                entry = self.get_registry_entry(plugin_key)
                if entry is not None:
                    self.CheckForUpdatePythonPlugin(entry.author, entry.repository, plugin_key)

        Domoticz.Log("Plugin Manager Ready. Use the 'Custom' menu to manage plugins.")
        Domoticz.Heartbeat(60)

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug(f"onCommand called for Unit {Unit}: Command '{Command}', Level: {Level}")
        if Unit == 2 and Command.lower() == "on":
            if 1 in Devices:
                payload_str = str(Devices[1].sValue or "")

                if not payload_str:
                    Domoticz.Debug("API payload device is empty; ignoring trigger.")
                    return
                
                # 1. DoS Protection: commands are small, but the shared bridge can still contain a large prior response.
                if len(payload_str) > API_PAYLOAD_MAX_LENGTH:
                    if self.isApiResponsePayloadString(payload_str):
                        Domoticz.Debug("Ignoring stale API response left in payload device.")
                        Devices[1].Update(nValue=0, sValue="")
                        return

                    Domoticz.Error("API Payload exceeds length limit.")
                    Devices[1].Update(nValue=0, sValue="")
                    return

                Domoticz.Debug(f"API Payload received: {payload_str}")
                try:
                    # Clear payload device immediately to prevent replay/abuse
                    Devices[1].Update(nValue=0, sValue="")
                    
                    payload = json.loads(payload_str)
                    
                    # 2. Type Validation: Ensure we got a dictionary
                    if not isinstance(payload, dict):
                        raise ValueError("Payload must be a JSON object")

                    if self.isApiResponsePayload(payload):
                        Domoticz.Debug("Ignoring stale API response left in payload device.")
                        return
                    
                    # 3. Content Sanitization
                    self.tx_id = str(payload.get("tx_id", ""))[:50] # Limit tx_id length
                    self.handleApiCommand(payload)
                except Exception as e:
                    Domoticz.Error(f"Failed to parse API payload: {e}")
                    self.sendApiResponse({"status": "error", "message": "Invalid JSON payload or structure"})

    def isApiResponsePayload(self, payload):
        return (
            isinstance(payload, dict)
            and payload.get("status") in ("success", "error")
            and "tx_id" in payload
        )

    def isApiResponsePayloadString(self, payload_str):
        try:
            return self.isApiResponsePayload(json.loads(payload_str))
        except Exception:
            return re.match(r'^\s*\{\s*"status"\s*:\s*"(success|error)"', payload_str) is not None

    def loadPendingOperations(self):
        pending_file = self.get_host().pending_operations_file()
        if not os.path.isfile(pending_file):
            return []
        try:
            with open(pending_file, "r", encoding="utf-8") as f:
                operations = json.load(f)
            if isinstance(operations, list):
                return operations
            Domoticz.Error("pending_operations.json does not contain a JSON list.")
        except Exception as e:
            Domoticz.Error("Error reading pending_operations.json: " + str(e))
        return []

    def savePendingOperations(self, operations):
        pending_file = self.get_host().pending_operations_file()
        try:
            if operations:
                with open(pending_file, "w", encoding="utf-8") as f:
                    json.dump(operations, f, indent=4)
                    f.write("\n")
            elif os.path.isfile(pending_file):
                os.remove(pending_file)
            return True
        except Exception as e:
            Domoticz.Error("Error writing pending_operations.json: " + str(e))
            return False

    def queuePendingOperation(self, action, plugin_key):
        try:
            plugin_key = self.get_host().validate_plugin_key(plugin_key)
        except ValueError as e:
            Domoticz.Error(str(e))
            return False

        operations = self.loadPendingOperations()
        operation = {"action": action, "plugin_key": plugin_key}
        for existing_operation in operations:
            if existing_operation.get("action") == action and existing_operation.get("plugin_key") == plugin_key:
                Domoticz.Debug("Pending operation already queued: " + action + " " + plugin_key)
                return True

        operations.append(operation)
        if self.savePendingOperations(operations):
            Domoticz.Log("Queued pending operation: " + action + " " + plugin_key)
            return True
        return False

    def processPendingOperations(self):
        operations = self.loadPendingOperations()
        if not operations:
            return

        Domoticz.Log("Processing pending plugin operations.")
        remaining_operations = []
        for operation in operations:
            action = operation.get("action")
            plugin_key = operation.get("plugin_key")
            if action == "remove":
                success, message = self.removePlugin(plugin_key, queue_on_lock=False)
            elif action == "update":
                entry = self.get_registry_entry(plugin_key)
                if entry is not None:
                    success, message = self.UpdatePythonPlugin(
                        entry.author,
                        entry.repository,
                        plugin_key,
                        queue_on_lock=False
                    )
                else:
                    success = False
                    message = "Plugin not found in registry"
            else:
                success = True
                message = "Unknown pending operation ignored"

            if success:
                Domoticz.Log("Completed pending operation: " + str(action) + " " + str(plugin_key))
            else:
                Domoticz.Error("Pending operation failed for " + str(plugin_key) + ": " + str(message))
                remaining_operations.append(operation)

        self.savePendingOperations(remaining_operations)

    def removePlugin(self, plugin_key, queue_on_lock=True):
        host = self.get_host()
        try:
            plugin_key = host.validate_plugin_key(plugin_key)
            plugin_target_dir = self.resolve_installed_plugin_dir(plugin_key)
        except ValueError as e:
            return False, str(e)

        if os.path.basename(plugin_target_dir) == self.get_current_plugin_folder():
            return False, "Plugin directory not found or cannot remove self"

        if not os.path.isdir(plugin_target_dir):
            return False, "Plugin directory not found or cannot remove self"

        try:
            shutil.rmtree(plugin_target_dir)
            removed_folder = os.path.basename(plugin_target_dir)
            self.installed_plugin_folders = {
                key: folder
                for key, folder in self.installed_plugin_folders.items()
                if folder != removed_folder
            }
            return True, ""
        except Exception as e:
            if queue_on_lock and host.is_locked_file_error(e):
                self.queuePendingOperation("remove", plugin_key)
                return False, "Plugin files are in use; removal queued for the next startup."
            return False, str(e)

    def handleApiCommand(self, payload):
        # Ensure action is a safe string
        action = str(payload.get("action", ""))
        plugins_dir = self.get_host().plugins_dir()
        
        if action == "list_plugins":
            installed_plugins = self.getInstalledPlugins(plugins_dir)
            cached_update_status = self.getCachedUpdateStatuses(installed_plugins)
            versions = self.get_plugin_versions(installed_plugins, cached_update_status, plugins_dir)
                    
            self.sendApiResponse({
                "status": "success",
                "action": action,
                "data": self.plugin_data,
                "installed": installed_plugins,
                "manager_key": self.get_current_plugin_folder(),
                "local_plugins": self.local_plugin_keys,
                "installed_match_details": self.installed_plugin_match_details,
                "update_status": cached_update_status,
                "versions": versions,
                "platforms": self.plugin_platforms
            })
        elif action == "refresh_update_status":
            self.fetch_registry()
            installed_plugins = self.getInstalledPlugins(plugins_dir)
            update_status = self.refreshInstalledUpdateStatuses(installed_plugins, plugins_dir)
            versions = self.get_plugin_versions(installed_plugins, update_status, plugins_dir)
            self.sendApiResponse({
                "status": "success",
                "action": action,
                "data": self.plugin_data,
                "installed": installed_plugins,
                "manager_key": self.get_current_plugin_folder(),
                "local_plugins": self.local_plugin_keys,
                "installed_match_details": self.installed_plugin_match_details,
                "update_status": update_status,
                "versions": versions,
                "platforms": self.plugin_platforms
            })
        elif action == "install":
            plugin_key = payload.get("plugin_key")
            entry = self.get_registry_entry(plugin_key)
            if entry is not None:
                install_success, install_message = self.InstallPythonPlugin(entry.author, entry.repository, plugin_key, entry.branch)
                if install_success:
                    self.sendApiResponse({"status": "success", "action": action, "plugin_key": plugin_key})
                else:
                    self.sendApiResponse({"status": "error", "message": install_message or "Plugin install failed"})
            else:
                self.sendApiResponse({"status": "error", "message": "Plugin not found"})
        elif action == "update":
            plugin_key = payload.get("plugin_key")
            entry = self.get_registry_entry(plugin_key)
            if entry is not None:
                update_success, update_message = self.UpdatePythonPlugin(entry.author, entry.repository, plugin_key)
                if update_success:
                    response = {"status": "success", "action": action, "plugin_key": plugin_key}
                    if update_message:
                        response["message"] = update_message
                    self.sendApiResponse(response)
                else:
                    self.sendApiResponse({"status": "error", "message": update_message or "Plugin update failed"})
            else:
                self.sendApiResponse({"status": "error", "message": "Plugin not found"})
        elif action == "restart_domoticz":
            restart_success, restart_message = self.restartDomoticz()
            if restart_success:
                self.sendApiResponse({
                    "status": "success",
                    "action": action,
                    "message": restart_message
                })
            else:
                self.sendApiResponse({"status": "error", "message": restart_message})
        elif action == "remove":
            plugin_key = payload.get("plugin_key", "")
            remove_success, remove_message = self.removePlugin(plugin_key)
            if remove_success:
                self.sendApiResponse({"status": "success", "action": action, "plugin_key": plugin_key})
            else:
                self.sendApiResponse({"status": "error", "message": remove_message})
        else:
            self.sendApiResponse({"status": "error", "message": f"Unknown action: {action}"})

    def getInstalledUpdateStatuses(self, installed_plugins, plugins_dir):
        return self.refreshInstalledUpdateStatuses(installed_plugins, plugins_dir)

    def getGitUpdateStatus(self, plugin_dir, plugin_key=None, fetch_first=True):
        return self.update_status_service.get_git_update_status(plugin_dir, plugin_key, fetch_first)

    def sendApiResponse(self, response_dict):
        if 1 in Devices:
            try:
                if hasattr(self, 'tx_id') and self.tx_id:
                    response_dict['tx_id'] = self.tx_id
                response_str = json.dumps(response_dict)
                Devices[1].Update(nValue=0, sValue=response_str)
            except Exception as e:
                Domoticz.Error(f"Failed to send API response: {e}")

    def onStop(self):
        Domoticz.Debug("onStop called")
        Domoticz.Log("Plugin is stopping.")
        Domoticz.Debugging(0)

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")

        now = datetime.now()
        Domoticz.Debug(f"Current time: {now.strftime('%H:%M')}")

        plugins_dir = self.get_host().plugins_dir()

        if self.last_update_status_refresh_date is None or self.last_update_status_refresh_date < now.date():
            Domoticz.Log("Refreshing plugin update status cache.")
            self.last_update_status_refresh_date = now.date()
            self.refreshInstalledUpdateStatuses(plugins_dir=plugins_dir)

        if now.hour >= 12 and (self.last_update_date is None or self.last_update_date < now.date()):
            Domoticz.Log("Its time!!. Trigering Actions!!!")
            self.last_update_date = now.date()

            if Parameters["Mode4"] == 'All':
                Domoticz.Log("Checking Updates for All Plugins!!!")
                for plugin_key in self.get_managed_installed_plugin_keys(plugins_dir):
                    entry = self.get_registry_entry(plugin_key)
                    if entry is not None:
                        self.UpdatePythonPlugin(entry.author, entry.repository, plugin_key)

            if Parameters["Mode4"] == 'AllNotify':
                Domoticz.Log("Collecting Updates for All Plugins!!!")
                for plugin_key in self.get_managed_installed_plugin_keys(plugins_dir):
                    entry = self.get_registry_entry(plugin_key)
                    if entry is not None:
                        self.CheckForUpdatePythonPlugin(entry.author, entry.repository, plugin_key)

    def InstallPythonPlugin(self, ppAuthor, ppRepository, ppKey, ppBranch):
        entry = self.get_registry_entry_for_operation(ppKey, ppAuthor, ppRepository, ppBranch)
        return self.install_update_strategy.install(entry)

    def UpdatePythonPlugin(self, ppAuthor, ppRepository, ppKey, queue_on_lock=True):
        entry = self.get_registry_entry_for_operation(ppKey, ppAuthor, ppRepository)
        return self.install_update_strategy.update(entry, queue_on_lock=queue_on_lock)

    def CheckForUpdatePythonPlugin(self, ppAuthor, ppRepository, ppKey):
        entry = self.get_registry_entry_for_operation(ppKey, ppAuthor, ppRepository)
        return self.install_update_strategy.check_for_update(entry)

    def fnSelectedNotify(self, plugin_key):
        Domoticz.Debug("fnSelectedNotify called")
        Domoticz.Log("Preparing Notification")
        entry = self.get_registry_entry(plugin_key)
        plugin_name = entry.description if entry is not None and entry.description else plugin_key
        MailSubject = platform.node() + ": Domoticz Plugin Updates Available for " + plugin_name
        MailBody = plugin_name + " has updates available!!"
        self.sendDomoticzNotification(MailSubject, MailBody)
        return None

    def parseIntValue(self, s):
        Domoticz.Debug("parseIntValue called")
        try:
            return int(s)
        except:
            return None

    def is_private_ip(self, ip_str):
        try:
            octets = [int(o) for octet in ip_str.split('.') for o in octet.split()] # Handle potential spaces
            octets = [int(o) for o in ip_str.split('.')]
            if len(octets) != 4: return False
            # Loopback
            if octets[0] == 127: return True
            # Class A private
            if octets[0] == 10: return True
            # Class B private
            if octets[0] == 172 and 16 <= octets[1] <= 31: return True
            # Class C private
            if octets[0] == 192 and octets[1] == 168: return True
            # Link-local
            if octets[0] == 169 and octets[1] == 254: return True
            # Broadcast / Software versions (e.g. 0.0.0.0)
            if octets[0] == 0: return True
            # Ignore Chrome version numbers (e.g. 124.0.0.0)
            if octets[1] == 0 and octets[2] == 0 and octets[3] == 0: return True
            return False
        except:
            return False

    def parseFileForSecurityIssues(self, pyfilename, pypluginid):
        import ast
        Domoticz.Debug("parseFileForSecurityIssues called")
        if Parameters.get("Mode5") == 'True':
            Domoticz.Log(f"Scanning {pyfilename} for security issues...")

        if pypluginid not in self.secpoluser_list:
            self.secpoluser_list[pypluginid] = []

        ip_pattern = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')

        try:
            # 1. Prevent Large File DoS: Limit file read to 5MB
            MAX_FILE_SIZE = 5 * 1024 * 1024
            with open(pyfilename, "r", encoding="utf-8", errors="ignore") as file:
                source_code = file.read(MAX_FILE_SIZE)
                if file.read(1):
                    Domoticz.Error(f"Plugin file {pyfilename} exceeds 5MB limit. Plugin considered UNSAFE.")
                    return

            try:
                tree = ast.parse(source_code)
            except (SyntaxError, RecursionError, MemoryError, Exception) as e:
                Domoticz.Error(f"Failed to parse plugin file {pyfilename} (Possible AST Bomb or invalid syntax): {e}. Plugin considered UNSAFE.")
                return

            class SecurityScanner(ast.NodeVisitor):
                def __init__(self):
                    self.findings = []

                def get_full_name(self, node):
                    if isinstance(node, ast.Name):
                        return node.id
                    elif isinstance(node, ast.Attribute):
                        val = self.get_full_name(node.value)
                        return f"{val}.{node.attr}" if val else node.attr
                    return ""

                def visit_Call(self, node):
                    func_full_name = self.get_full_name(node.func)

                    func_base_name = ""
                    if isinstance(node.func, ast.Name):
                        func_base_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_base_name = node.func.attr

                    exact_matches = {'os.system', 'os.popen', 'eval', 'exec', '__import__', 'compile', 'pickle.loads', 'pickle.load', 'os.remove', 'os.unlink', 'shutil.rmtree'}

                    if func_full_name in exact_matches:
                        self.findings.append((node.lineno, f"Suspicious Call: {func_full_name}"))
                    elif func_full_name.startswith('subprocess.'):
                        # Specifically look for shell=True which is the biggest risk
                        is_shell = False
                        for keyword in node.keywords:
                            if keyword.arg == 'shell' and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                                is_shell = True
                        if is_shell:
                            self.findings.append((node.lineno, f"Dangerous Subprocess (shell=True): {func_full_name}"))
                    elif func_base_name in {'eval', 'exec', '__import__', 'compile'}:
                        self.findings.append((node.lineno, f"Suspicious Call: {func_base_name}"))
                    elif func_base_name in {'system', 'popen', 'rmtree', 'unlink'}:
                        self.findings.append((node.lineno, f"Potentially Suspicious Call (Alias?): {func_base_name}"))

                    self.generic_visit(node)

                def visit_Name(self, node):
                    if node.id in {'eval', 'exec', '__import__', 'compile'} and isinstance(getattr(node, 'ctx', None), ast.Load):
                        self.findings.append((node.lineno, f"Dangerous Builtin Referenced: {node.id}"))
                    self.generic_visit(node)

            scanner = SecurityScanner()
            scanner.visit(tree)

            ast_findings_map = {}
            for lineno, finding in scanner.findings:
                if lineno not in ast_findings_map:
                    ast_findings_map[lineno] = []
                if finding not in ast_findings_map[lineno]:
                    ast_findings_map[lineno].append(finding)

            lines = source_code.splitlines()
            for i, text in enumerate(lines):
                lineNum = i + 1
                clean_text = text.strip()

                # Ignore comments, empty lines, and explicit overrides
                if not clean_text or clean_text.startswith('#') or '<param field=' in clean_text or '# security-ignore' in text or '# nosec' in text:
                    continue

                findings = []

                for ip in ip_pattern.findall(clean_text):
                    if all(0 <= int(octet) <= 255 for octet in ip.split('.')):
                        if not self.is_private_ip(ip):
                            findings.append(f"Public IP Address: {ip}")

                if lineNum in ast_findings_map:
                    findings.extend(ast_findings_map[lineNum])

                for finding in findings:
                    is_excluded = False
                    combined_exclusions = self.secpoluser_list.get("Global", []) + self.secpoluser_list[pypluginid]
                    for exclusion in combined_exclusions:
                        if exclusion in clean_text or exclusion in finding:
                            is_excluded = True
                            break

                    if not is_excluded:
                        Domoticz.Error(f"Security Finding in {pypluginid}: --> {finding} <-- LINE: {lineNum} FILE: {pyfilename}")
                        Domoticz.Error(f"Code context: {clean_text}")

        except Exception as e:
            Domoticz.Error(f"Error reading or processing {pyfilename}: {str(e)}")

    def restartDomoticz(self):
        Domoticz.Log("Domoticz service restart requested from PyPluginStore UI.")
        return self.get_host().restart_domoticz()

    def installDependencies(self, plugin_key):
        Domoticz.Debug("installDependencies called")
        host = self.get_host()
        try:
            requirements_file = os.path.join(self.resolve_installed_plugin_dir(plugin_key), "requirements.txt")
        except ValueError as e:
            Domoticz.Error(str(e))
            return False, str(e)
        return host.install_requirements(requirements_file, host.shared_deps_dir(), plugin_key)

global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
    return
