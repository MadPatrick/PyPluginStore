

import base64
from collections.abc import Mapping
import hashlib
import html
import http.client
import ipaddress
import io
import json
import math
import os
import platform
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import tokenize
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import Domoticz


API_PAYLOAD_MAX_LENGTH = 2000
SELF_UPDATE_STARTUP_DELAY_SECONDS = 5
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

    def self_update_state_file(self):
        return os.path.join(self.plugin_home_folder(), "self_update_state.json")

    def git_index_lock_file(self, plugin_dir):
        return os.path.join(plugin_dir, ".git", "index.lock")

    def has_git_index_lock(self, plugin_dir):
        return os.path.exists(self.git_index_lock_file(plugin_dir))

    def git_index_lock_message(self, plugin_dir):
        lock_file = self.git_index_lock_file(plugin_dir)
        return (
            "PyPluginStore git index lock exists at " + lock_file
            + "; stop any running git command, then remove the lock file if it is stale and retry self-update."
        )

    def utc_timestamp(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def read_self_update_state(self):
        default_state = {
            "operation": "self_update",
            "phase": "idle",
            "message": "",
            "log_file": self.self_update_log_file(),
        }
        state_file = self.self_update_state_file()
        if not os.path.isfile(state_file):
            return default_state

        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            if not isinstance(state, dict):
                raise ValueError("state file does not contain a JSON object")
            default_state.update(state)
            default_state["operation"] = "self_update"
            default_state["log_file"] = default_state.get("log_file") or self.self_update_log_file()
            return default_state
        except Exception as e:
            default_state.update({
                "phase": "stale_unknown",
                "message": "Could not read self-update state: " + str(e),
            })
            return default_state

    def write_json_atomic(self, path, data, sort_keys=True):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=sort_keys)
                f.write("\n")
            os.replace(tmp_path, path)
        except Exception:
            try:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise

    def write_self_update_state(self, phase, message="", previous_state=None, **fields):
        now = self.utc_timestamp()
        state = dict(previous_state or {})
        state.setdefault("created_at", now)
        state.update({
            "operation": "self_update",
            "phase": phase,
            "message": message,
            "updated_at": now,
            "log_file": self.self_update_log_file(),
        })
        for key, value in fields.items():
            if value is not None:
                state[key] = value
        self.write_json_atomic(self.self_update_state_file(), state)
        return state

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
        if self.has_git_index_lock(plugin_dir):
            return False, self.git_index_lock_message(plugin_dir), {}

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

        current_result, message = self.require_git_success(
            plugin_dir,
            ["git", "rev-parse", "--verify", "HEAD"],
            fallback="Could not verify the current PyPluginStore revision.",
        )
        if message:
            return False, message, {}
        current_commit = current_result.stdout.strip().splitlines()[0] if current_result.stdout.strip() else ""

        target_result, message = self.require_git_success(
            plugin_dir,
            ["git", "rev-parse", "--verify", upstream_ref],
            fallback="Could not verify the PyPluginStore upstream revision.",
        )
        if message:
            return False, message, {}
        target_commit = target_result.stdout.strip().splitlines()[0] if target_result.stdout.strip() else ""

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
            return True, "PyPluginStore is already up-to-date.", {
                "already_current": True,
                "upstream_ref": upstream_ref,
                "current_commit": current_commit,
                "target_commit": target_commit,
            }

        valid_candidate, message = self.validate_self_update_candidate(plugin_dir, upstream_ref)
        if not valid_candidate:
            return False, message, {}
        if self.has_git_index_lock(plugin_dir):
            return False, self.git_index_lock_message(plugin_dir), {}

        return True, "Self update pre-flight checks passed.", {
            "already_current": False,
            "upstream_ref": upstream_ref,
            "current_commit": current_commit,
            "target_commit": target_commit,
        }

    def build_self_update_helper(
        self,
        plugin_dir,
        log_file,
        upstream_ref,
        state_file=None,
        job_id="",
        state_template=None,
        startup_delay=SELF_UPDATE_STARTUP_DELAY_SECONDS,
    ):
        state_file = state_file or self.self_update_state_file()
        state_template = dict(state_template or {})
        helper = """
import datetime
import json
import os
import subprocess
import time
import traceback

plugin_dir = __PLUGIN_DIR__
log_file = __LOG_FILE__
upstream_ref = __UPSTREAM_REF__
state_file = __STATE_FILE__
job_id = __JOB_ID__
state_template = __STATE_TEMPLATE__
startup_delay = __STARTUP_DELAY__
safe_directory = os.path.realpath(os.path.abspath(plugin_dir))
index_lock_file = os.path.join(plugin_dir, ".git", "index.lock")

def write_log(message):
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with open(log_file, "a", encoding="utf-8") as update_log:
            update_log.write("[{}] {}\\n".format(timestamp, message))
    except Exception:
        pass

def write_state(phase, message="", **extra):
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = dict(state_template)
    state.setdefault("created_at", timestamp)
    state.update({
        "operation": "self_update",
        "phase": phase,
        "message": message,
        "updated_at": timestamp,
        "log_file": log_file,
        "job_id": job_id,
        "upstream_ref": upstream_ref,
    })
    state.update(extra)
    try:
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        tmp_state_file = state_file + ".tmp"
        with open(tmp_state_file, "w", encoding="utf-8") as state_handle:
            json.dump(state, state_handle, indent=2, sort_keys=True)
            state_handle.write("\\n")
        os.replace(tmp_state_file, state_file)
    except Exception as e:
        write_log("failed to write state: {}".format(e))

write_log("self update helper started")
write_state("running", "Self update helper is running.")
if startup_delay:
    time.sleep(startup_delay)

if not os.path.isdir(os.path.join(plugin_dir, ".git")):
    write_log("not a git repository: {}".format(plugin_dir))
    write_state("failed", "PyPluginStore is not installed as a git repository.")
    raise SystemExit(1)

env = os.environ.copy()
env["GIT_TERMINAL_PROMPT"] = "0"

def git_command(*args):
    return ["git", "-c", "safe.directory=" + safe_directory] + list(args)

def git_index_lock_message():
    return (
        "PyPluginStore git index lock exists at {}; "
        "stop any running git command, then remove the lock file if it is stale and retry self-update."
    ).format(index_lock_file)

def refuse_git_index_lock():
    if os.path.exists(index_lock_file):
        message = git_index_lock_message()
        write_log(message)
        write_state("failed", message)
        raise SystemExit(1)

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
            write_state(
                "failed",
                "Self update command failed: {}".format(subprocess.list2cmdline(command)),
                return_code=result.returncode
            )
            raise SystemExit(result.returncode)
        return result
    except Exception as e:
        write_log("exception: {}".format(e))
        write_log(traceback.format_exc().strip())
        write_state("failed", "Self update helper exception: {}".format(e))
        raise

refuse_git_index_lock()
status = run_command(git_command("status", "--porcelain", "--untracked-files=no"), 15)
if status.stdout.strip():
    write_log("tracked files changed after pre-flight; self update refused")
    write_state("failed", "Tracked files changed after pre-flight; self update refused.")
    raise SystemExit(1)

run_command(git_command("fetch", "--prune"), 60)
refuse_git_index_lock()
run_command(git_command("merge", "--ff-only", upstream_ref), 120)
head = run_command(git_command("rev-parse", "--short", "HEAD"), 15).stdout.strip()
write_log("self update completed")
write_state(
    "applied_needs_reload",
    "Self update completed. Reload the Plugin Store after Domoticz finishes reloading the plugin.",
    applied_commit=head
)
"""
        return (
            helper
            .replace("__PLUGIN_DIR__", repr(plugin_dir))
            .replace("__LOG_FILE__", repr(log_file))
            .replace("__UPSTREAM_REF__", repr(upstream_ref))
            .replace("__STATE_FILE__", repr(state_file))
            .replace("__JOB_ID__", repr(job_id))
            .replace("__STATE_TEMPLATE__", repr(state_template))
            .replace("__STARTUP_DELAY__", repr(startup_delay))
        )

    def schedule_self_update(self, plugin_dir):
        Domoticz.Log("Starting PyPluginStore self-update pre-flight.")
        preflight_success, preflight_message, preflight_plan = self.preflight_self_update(plugin_dir)
        if not preflight_success or preflight_plan.get("already_current"):
            phase = "confirmed" if preflight_plan.get("already_current") else "preflight_failed"
            state = self.write_self_update_state(
                phase,
                preflight_message,
                job_id=self.utc_timestamp().replace("-", "").replace(":", ""),
                upstream_ref=preflight_plan.get("upstream_ref", ""),
                current_commit=preflight_plan.get("current_commit", ""),
                target_commit=preflight_plan.get("target_commit", ""),
            )
            if preflight_success:
                Domoticz.Log("PyPluginStore self-update pre-flight completed: " + preflight_message)
            else:
                Domoticz.Error("PyPluginStore self-update pre-flight failed: " + preflight_message)
            return preflight_success, preflight_message

        job_id = self.utc_timestamp().replace("-", "").replace(":", "")
        state = self.write_self_update_state(
            "scheduled",
            "Self update helper scheduled.",
            job_id=job_id,
            upstream_ref=preflight_plan["upstream_ref"],
            current_commit=preflight_plan.get("current_commit", ""),
            target_commit=preflight_plan.get("target_commit", ""),
        )
        log_file = self.self_update_log_file()
        Domoticz.Log("PyPluginStore self-update helper scheduled; detailed output: " + log_file)

        helper = self.build_self_update_helper(
            plugin_dir,
            log_file,
            preflight_plan["upstream_ref"],
            self.self_update_state_file(),
            job_id,
            state,
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
            self.write_self_update_state(
                "failed",
                str(e),
                previous_state=state,
                job_id=job_id,
                upstream_ref=preflight_plan["upstream_ref"],
            )
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


RELEASE_INDEX_SCHEMA_VERSION = 1
DELIVERY_POLICY_SCHEMA_VERSION = 1
RELEASE_PROVIDERS = {
    "codeberg",
    "forgejo",
    "generic",
    "gitea",
    "github",
    "gitlab",
}
RELEASE_ARTIFACT_KINDS = {
    "asset_zip",
    "generic_zip",
    "source_zip",
}
RELEASE_POLICY_ARTIFACTS = {"asset_zip", "source_zip"}
RELEASE_ARTIFACT_PROVENANCE = {
    "attached_asset",
    "forge_release_asset",
    "forge_source_archive",
    "generic_manifest",
    "release_asset",
}
RELEASE_PREFERRED_MODES = {"git", "release", "release_if_indexed"}
LOWER_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
RELEASE_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
RELEASE_SECRET_REQUEST_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "cookie2",
    "private-token",
}
RELEASE_HEADER_NAME_PATTERN = re.compile(
    r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$"
)
RELEASE_CONTENT_LENGTH_PATTERN = re.compile(r"^[0-9]+$")
RELEASE_INVALID_PERCENT_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")
RELEASE_HOST_LABEL_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
RELEASE_HTTP_CHUNK_SIZE = 64 * 1024
RELEASE_MAX_DNS_ANSWERS = 64


def _require_document(value, label, required_keys, optional_keys=()):
    """Validate a versioned metadata object and return it unchanged."""
    if not isinstance(value, dict):
        raise ValueError(label + " must be an object.")

    required = set(required_keys)
    allowed = required | set(optional_keys)
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise ValueError(label + " is missing fields: " + ", ".join(missing))
    if unknown:
        raise ValueError(label + " has unknown fields: " + ", ".join(unknown))
    return value


def _require_nonempty_string(value, label):
    """Return a non-empty metadata string without silently coercing types."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(label + " must be a non-empty string.")
    if CONTROL_CHARACTER_PATTERN.search(value):
        raise ValueError(label + " contains control characters.")
    return value


def _require_positive_integer(value, label):
    """Return a positive integer, rejecting booleans and numeric strings."""
    if type(value) is not int or value <= 0:
        raise ValueError(label + " must be a positive integer.")
    return value


def _require_boolean(value, label):
    """Return a real JSON boolean."""
    if type(value) is not bool:
        raise ValueError(label + " must be a boolean.")
    return value


def _require_sha256(value, label):
    """Return a canonical lowercase SHA-256 digest."""
    value = _require_nonempty_string(value, label)
    if not LOWER_SHA256_PATTERN.fullmatch(value):
        raise ValueError(label + " must be a lowercase SHA-256 digest.")
    return value


def _require_git_commit(value, label, required=True):
    """Return a full lowercase Git object identifier."""
    if value in (None, "") and not required:
        return ""
    value = _require_nonempty_string(value, label)
    if not GIT_COMMIT_PATTERN.fullmatch(value):
        raise ValueError(label + " must be a full lowercase Git commit ID.")
    return value


def _parse_utc_timestamp(value, label):
    """Parse the canonical UTC timestamp format used by release metadata."""
    value = _require_nonempty_string(value, label)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(label + " must be an ISO 8601 UTC timestamp.") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError(label + " must be a canonical UTC timestamp.")
    return parsed.replace(tzinfo=timezone.utc)


def _normalize_relative_metadata_path(value, label, allow_root=True):
    """Normalize a safe POSIX path used in reviewed release metadata."""
    value = _require_nonempty_string(value, label)
    if value == "." and allow_root:
        return value
    if (
        value.startswith(("/", "\\"))
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise ValueError(label + " must be a relative POSIX path.")

    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(label + " must be a normalized relative path.")
    return "/".join(parts)


def _require_https_url(value, label):
    """Validate a public HTTPS metadata or artifact URL."""
    value = _require_nonempty_string(value, label)
    try:
        parsed = urllib.parse.urlparse(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError(label + " is not a valid URL.") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(label + " must be a public HTTPS URL.")
    if port is not None and not (1 <= port <= 65535):
        raise ValueError(label + " has an invalid port.")
    return value


def _repository_host(parsed_url):
    """Return a lowercase host and optional explicit port from a URL."""
    hostname = str(parsed_url.hostname or "").lower()
    if not hostname:
        return ""
    try:
        port = parsed_url.port
    except ValueError:
        return ""
    return hostname + ((":" + str(port)) if port is not None else "")


def normalize_repository_identity(source, repository=""):
    """Return the forge-neutral host/path identity for a repository."""
    source = str(source or "").strip().rstrip("/")
    repository = str(repository or "").strip().strip("/")
    if not source:
        return ""

    host = ""
    path = ""
    if re.match(r"^[^/@\s:]+@[^/\s:]+:.+$", source):
        user_host, path = source.split(":", 1)
        host = user_host.split("@", 1)[-1].lower()
    else:
        parsed = urllib.parse.urlparse(source)
        if parsed.scheme:
            if parsed.scheme not in ("http", "https", "ssh"):
                return ""
            host = _repository_host(parsed)
            path = parsed.path
        else:
            shorthand = urllib.parse.urlparse("//" + source)
            first_part = source.split("/", 1)[0]
            if shorthand.hostname and ("." in first_part or ":" in first_part):
                host = _repository_host(shorthand)
                path = shorthand.path
            else:
                host = DEFAULT_GIT_HOST
                path = source

    if not host:
        return ""
    path_parts = []
    for part in path.split("/"):
        part = urllib.parse.unquote(part.strip())
        if not part:
            continue
        if (
            CONTROL_CHARACTER_PATTERN.search(part)
            or "/" in part
            or "\\" in part
            or part in (".", "..")
        ):
            return ""
        if part in REPOSITORY_PATH_STOP_PARTS:
            break
        path_parts.append(part)
    if repository:
        if "/" in repository or "\\" in repository:
            return ""
        path_parts.append(repository)
    if path_parts and path_parts[-1].endswith(".git"):
        path_parts[-1] = path_parts[-1][:-4]
    if len(path_parts) < 2 or any(not part for part in path_parts):
        return ""
    return (host + "/" + "/".join(path_parts)).lower()


def _registry_entry_identity(data):
    """Extract a normalized repository identity from a registry entry."""
    if isinstance(data, list) and len(data) >= 2:
        return normalize_repository_identity(data[0], data[1])
    if isinstance(data, dict):
        return normalize_repository_identity(
            data.get("author", data.get("owner", "")),
            data.get("repository", data.get("repo", "")),
        )
    return ""


def _load_json_object(contents, label):
    """Load UTF-8 JSON while rejecting duplicate object keys."""
    if not isinstance(contents, (bytes, bytearray)):
        raise ValueError(label + " must be bytes.")

    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(label + " contains duplicate key " + str(key) + ".")
            result[key] = value
        return result

    try:
        document = json.loads(
            bytes(contents).decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(label + " is not valid UTF-8 JSON.") from error
    if not isinstance(document, dict):
        raise ValueError(label + " must contain a JSON object.")
    return document


@dataclass
class ReleasePolicy:
    """Reviewed provider discovery policy from a registry entry."""

    provider: str
    channel: str
    tag_pattern: str
    artifact: str
    source_path: str
    mutable_paths: list
    api_base: str = ""
    manifest_url: str = ""
    asset_name: str = ""
    asset_pattern: str = ""
    allowed_origins: list = None

    @classmethod
    def from_document(cls, document):
        """Parse and validate the release portion of a delivery policy."""
        document = _require_document(
            document,
            "delivery.release",
            ("provider",),
            (
                "api_base",
                "allowed_origins",
                "artifact",
                "asset_name",
                "asset_pattern",
                "channel",
                "manifest_url",
                "mutable_paths",
                "source_path",
                "tag_pattern",
            ),
        )
        provider = _require_nonempty_string(
            document["provider"], "delivery.release.provider"
        ).lower()
        if provider not in RELEASE_PROVIDERS:
            raise ValueError("delivery.release.provider is not supported.")

        channel = _require_nonempty_string(
            document.get("channel", "stable"), "delivery.release.channel"
        )
        tag_pattern = document.get("tag_pattern", "")
        if tag_pattern:
            tag_pattern = _require_nonempty_string(
                tag_pattern, "delivery.release.tag_pattern"
            )
            try:
                re.compile(tag_pattern)
            except re.error as error:
                raise ValueError(
                    "delivery.release.tag_pattern is not a valid regular expression."
                ) from error

        artifact = _require_nonempty_string(
            document.get("artifact", "source_zip"),
            "delivery.release.artifact",
        )
        if artifact not in RELEASE_POLICY_ARTIFACTS:
            raise ValueError("delivery.release.artifact is not supported.")
        source_path = _normalize_relative_metadata_path(
            document.get("source_path", "."),
            "delivery.release.source_path",
        )

        mutable_paths_document = document.get("mutable_paths", [])
        if not isinstance(mutable_paths_document, list):
            raise ValueError("delivery.release.mutable_paths must be a list.")
        mutable_paths = []
        for value in mutable_paths_document:
            path = _normalize_relative_metadata_path(
                value, "delivery.release.mutable_paths entry", allow_root=False
            )
            first_part = path.split("/", 1)[0].lower()
            if first_part in (".git", ".pypluginstore") or path.lower() in (
                ".pypluginstore.json",
                "plugin.py",
            ):
                raise ValueError("delivery.release.mutable_paths contains a reserved path.")
            if path in mutable_paths:
                raise ValueError("delivery.release.mutable_paths contains a duplicate.")
            mutable_paths.append(path)

        api_base = document.get("api_base", "")
        if api_base:
            api_base = _require_https_url(api_base, "delivery.release.api_base")
        manifest_url = document.get("manifest_url", "")
        if manifest_url:
            manifest_url = _require_https_url(
                manifest_url, "delivery.release.manifest_url"
            )
        if provider == "generic" and not manifest_url:
            raise ValueError("Generic release policy requires manifest_url.")
        if provider != "generic" and manifest_url:
            raise ValueError("manifest_url is only valid for the generic provider.")

        allowed_origins_document = document.get("allowed_origins", [])
        if not isinstance(allowed_origins_document, list):
            raise ValueError("delivery.release.allowed_origins must be a list.")
        allowed_origins = []
        for origin in allowed_origins_document:
            origin = _require_https_url(
                origin, "delivery.release.allowed_origins entry"
            )
            parsed_origin = urllib.parse.urlparse(origin)
            if parsed_origin.path not in ("", "/") or parsed_origin.query:
                raise ValueError(
                    "delivery.release.allowed_origins entries must be origins."
                )
            normalized_origin = (
                "https://" + _repository_host(parsed_origin)
            )
            if normalized_origin in allowed_origins:
                raise ValueError(
                    "delivery.release.allowed_origins contains a duplicate."
                )
            allowed_origins.append(normalized_origin)

        asset_name = document.get("asset_name", "")
        if asset_name:
            asset_name = _require_nonempty_string(
                asset_name, "delivery.release.asset_name"
            )
        asset_pattern = document.get("asset_pattern", "")
        if asset_pattern:
            asset_pattern = _require_nonempty_string(
                asset_pattern, "delivery.release.asset_pattern"
            )
            try:
                re.compile(asset_pattern)
            except re.error as error:
                raise ValueError(
                    "delivery.release.asset_pattern is not a valid regular expression."
                ) from error
        if asset_name and asset_pattern:
            raise ValueError("Choose either asset_name or asset_pattern, not both.")
        if artifact == "source_zip" and (asset_name or asset_pattern):
            raise ValueError("Source ZIP policies cannot select a release asset.")

        return cls(
            provider=provider,
            channel=channel,
            tag_pattern=tag_pattern,
            artifact=artifact,
            source_path=source_path,
            mutable_paths=mutable_paths,
            api_base=api_base,
            manifest_url=manifest_url,
            asset_name=asset_name,
            asset_pattern=asset_pattern,
            allowed_origins=allowed_origins,
        )


@dataclass
class DeliveryPolicy:
    """Backward-compatible release/Git selection policy."""

    schema_version: int
    preferred: str
    git_supported: bool
    release: object = None

    @classmethod
    def implicit(cls):
        """Return the policy assigned to a legacy registry list entry."""
        return cls(
            schema_version=DELIVERY_POLICY_SCHEMA_VERSION,
            preferred="release_if_indexed",
            git_supported=True,
            release=None,
        )

    @classmethod
    def git_only(cls):
        """Return the policy for local-registry entries in unsigned v1."""
        return cls(
            schema_version=DELIVERY_POLICY_SCHEMA_VERSION,
            preferred="git",
            git_supported=True,
            release=None,
        )

    @classmethod
    def from_document(cls, document):
        """Parse a versioned registry delivery policy."""
        document = _require_document(
            document,
            "delivery",
            ("schema_version", "preferred", "git_supported"),
            ("release",),
        )
        if (
            type(document["schema_version"]) is not int
            or document["schema_version"] != DELIVERY_POLICY_SCHEMA_VERSION
        ):
            raise ValueError("delivery.schema_version is not supported.")
        preferred = _require_nonempty_string(
            document["preferred"], "delivery.preferred"
        )
        if preferred not in RELEASE_PREFERRED_MODES:
            raise ValueError("delivery.preferred is not supported.")
        git_supported = _require_boolean(
            document["git_supported"], "delivery.git_supported"
        )
        release_document = document.get("release")
        release = (
            ReleasePolicy.from_document(release_document)
            if release_document is not None
            else None
        )
        if preferred == "release" and release is None:
            raise ValueError("Release delivery requires delivery.release.")
        if preferred == "git" and not git_supported:
            raise ValueError("Git delivery requires git_supported.")
        return cls(
            schema_version=DELIVERY_POLICY_SCHEMA_VERSION,
            preferred=preferred,
            git_supported=git_supported,
            release=release,
        )


@dataclass
class ReleaseArtifact:
    """Provider-neutral, checksum-pinned ZIP artifact metadata."""

    kind: str
    provenance: str
    migration_eligible: bool
    url: str
    sha256: str
    size: int
    tree_sha256: str
    root_prefix: str
    source_path: str

    @classmethod
    def from_document(cls, document):
        """Parse a normalized release artifact descriptor."""
        document = _require_document(
            document,
            "release artifact",
            (
                "kind",
                "provenance",
                "migration_eligible",
                "url",
                "sha256",
                "size",
                "tree_sha256",
                "root_prefix",
                "source_path",
            ),
        )
        kind = _require_nonempty_string(document["kind"], "artifact.kind")
        if kind not in RELEASE_ARTIFACT_KINDS:
            raise ValueError("artifact.kind is not supported.")
        provenance = _require_nonempty_string(
            document["provenance"], "artifact.provenance"
        )
        if provenance not in RELEASE_ARTIFACT_PROVENANCE:
            raise ValueError("artifact.provenance is not supported.")

        root_prefix = _require_nonempty_string(
            document["root_prefix"], "artifact.root_prefix"
        )
        if root_prefix != ".":
            root_prefix = _normalize_relative_metadata_path(
                root_prefix, "artifact.root_prefix", allow_root=False
            )
            if "/" in root_prefix:
                raise ValueError("artifact.root_prefix must identify one wrapper.")
        elif kind == "source_zip":
            raise ValueError("Forge source ZIP artifacts require one wrapper.")

        return cls(
            kind=kind,
            provenance=provenance,
            migration_eligible=_require_boolean(
                document["migration_eligible"], "artifact.migration_eligible"
            ),
            url=_require_https_url(document["url"], "artifact.url"),
            sha256=_require_sha256(document["sha256"], "artifact.sha256"),
            size=_require_positive_integer(document["size"], "artifact.size"),
            tree_sha256=_require_sha256(
                document["tree_sha256"], "artifact.tree_sha256"
            ),
            root_prefix=root_prefix,
            source_path=_normalize_relative_metadata_path(
                document["source_path"], "artifact.source_path"
            ),
        )


@dataclass
class ReleaseDescriptor:
    """One accepted release target independent of its source forge."""

    revision: int
    release_id: str
    supersedes: list
    provider: str
    repository_identity: str
    version: str
    tag: str
    released_at: str
    commit: str
    artifact: ReleaseArtifact
    source_revision: str = ""

    @classmethod
    def from_document(cls, document):
        """Parse a normalized release descriptor."""
        document = _require_document(
            document,
            "release descriptor",
            (
                "revision",
                "release_id",
                "supersedes",
                "provider",
                "repository_identity",
                "version",
                "tag",
                "released_at",
                "artifact",
            ),
            ("commit", "source_revision"),
        )
        provider = _require_nonempty_string(
            document["provider"], "release.provider"
        ).lower()
        if provider not in RELEASE_PROVIDERS:
            raise ValueError("release.provider is not supported.")

        repository_identity = normalize_repository_identity(
            document["repository_identity"]
        )
        if not repository_identity:
            raise ValueError("release.repository_identity is invalid.")

        release_id = _require_nonempty_string(
            document["release_id"], "release.release_id"
        )
        supersedes_document = document["supersedes"]
        if not isinstance(supersedes_document, list):
            raise ValueError("release.supersedes must be a list.")
        supersedes = []
        for value in supersedes_document:
            predecessor = _require_nonempty_string(
                value, "release.supersedes entry"
            )
            if predecessor == release_id or predecessor in supersedes:
                raise ValueError("release.supersedes contains invalid lineage.")
            supersedes.append(predecessor)

        source_revision = document.get("source_revision", "")
        if source_revision:
            source_revision = _require_nonempty_string(
                source_revision, "release.source_revision"
            )
        if provider == "generic" and not source_revision:
            raise ValueError("Generic releases require source_revision.")
        commit = _require_git_commit(
            document.get("commit", ""),
            "release.commit",
            required=provider != "generic",
        )
        artifact = ReleaseArtifact.from_document(document["artifact"])
        if not commit and artifact.migration_eligible:
            raise ValueError("A release without a commit cannot be migration eligible.")

        released_at = _require_nonempty_string(
            document["released_at"], "release.released_at"
        )
        _parse_utc_timestamp(released_at, "release.released_at")
        return cls(
            revision=_require_positive_integer(
                document["revision"], "release.revision"
            ),
            release_id=release_id,
            supersedes=supersedes,
            provider=provider,
            repository_identity=repository_identity,
            version=_require_nonempty_string(
                document["version"], "release.version"
            ),
            tag=_require_nonempty_string(document["tag"], "release.tag"),
            released_at=released_at,
            commit=commit,
            artifact=artifact,
            source_revision=source_revision,
        )

    def same_accepted_target(self, other):
        """Return whether an equal revision still names the accepted source."""
        if not isinstance(other, ReleaseDescriptor):
            return False
        common_fields_match = (
            self.revision == other.revision
            and self.release_id == other.release_id
            and self.supersedes == other.supersedes
            and self.provider == other.provider
            and self.repository_identity == other.repository_identity
            and self.version == other.version
            and self.tag == other.tag
            and self.released_at == other.released_at
            and self.commit == other.commit
            and self.source_revision == other.source_revision
            and self.artifact.kind == other.artifact.kind
            and self.artifact.provenance == other.artifact.provenance
            and self.artifact.migration_eligible
            == other.artifact.migration_eligible
            and self.artifact.tree_sha256 == other.artifact.tree_sha256
            and self.artifact.source_path == other.artifact.source_path
        )
        if not common_fields_match:
            return False
        if self.artifact.provenance == "forge_source_archive":
            return True
        return (
            self.artifact.url == other.artifact.url
            and self.artifact.sha256 == other.artifact.sha256
            and self.artifact.size == other.artifact.size
            and self.artifact.root_prefix == other.artifact.root_prefix
        )


@dataclass
class ReleaseTombstone:
    """Reviewed release de-certification metadata."""

    repository_identity: str
    last_revision: int
    release_id: str
    reason: str
    removed_at: str

    @classmethod
    def from_document(cls, document):
        """Parse a de-certification tombstone."""
        document = _require_document(
            document,
            "release tombstone",
            (
                "repository_identity",
                "last_revision",
                "release_id",
                "reason",
                "removed_at",
            ),
        )
        repository_identity = normalize_repository_identity(
            document["repository_identity"]
        )
        if not repository_identity:
            raise ValueError("tombstone.repository_identity is invalid.")
        removed_at = _require_nonempty_string(
            document["removed_at"], "tombstone.removed_at"
        )
        _parse_utc_timestamp(removed_at, "tombstone.removed_at")
        return cls(
            repository_identity=repository_identity,
            last_revision=_require_positive_integer(
                document["last_revision"], "tombstone.last_revision"
            ),
            release_id=_require_nonempty_string(
                document["release_id"], "tombstone.release_id"
            ),
            reason=_require_nonempty_string(document["reason"], "tombstone.reason"),
            removed_at=removed_at,
        )


@dataclass
class ReleaseIndex:
    """Validated release targets bound to exact public registry bytes."""

    schema_version: int
    sequence: int
    generated_at: str
    expires_at: str
    registry_sha256: str
    plugins: dict
    tombstones: dict

    @classmethod
    def from_document(cls, document, registry_bytes, now=None, previous=None):
        """Validate and normalize a release index document."""
        document = _require_document(
            document,
            "release index",
            (
                "schema_version",
                "sequence",
                "generated_at",
                "expires_at",
                "registry_sha256",
                "plugins",
            ),
            ("tombstones",),
        )
        if (
            type(document["schema_version"]) is not int
            or document["schema_version"] != RELEASE_INDEX_SCHEMA_VERSION
        ):
            raise ValueError("release_index.schema_version is not supported.")
        sequence = _require_positive_integer(
            document["sequence"], "release_index.sequence"
        )
        if previous is not None:
            if not isinstance(previous, cls):
                raise ValueError("previous release index is invalid.")
            if sequence <= previous.sequence:
                raise ValueError("release_index.sequence must increase.")

        generated_at = _require_nonempty_string(
            document["generated_at"], "release_index.generated_at"
        )
        expires_at = _require_nonempty_string(
            document["expires_at"], "release_index.expires_at"
        )
        generated_time = _parse_utc_timestamp(
            generated_at, "release_index.generated_at"
        )
        expiry_time = _parse_utc_timestamp(expires_at, "release_index.expires_at")
        if expiry_time <= generated_time:
            raise ValueError("release index validity window is invalid.")
        if now is None:
            now = datetime.now(timezone.utc)
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("release index validation time must be timezone-aware.")
        if expiry_time <= now.astimezone(timezone.utc):
            raise ValueError("release index is expired.")

        registry = _load_json_object(registry_bytes, "registry")
        expected_registry_sha256 = _require_sha256(
            document["registry_sha256"], "release_index.registry_sha256"
        )
        actual_registry_sha256 = hashlib.sha256(bytes(registry_bytes)).hexdigest()
        if expected_registry_sha256 != actual_registry_sha256:
            raise ValueError("release index does not match registry bytes.")

        plugins_document = document["plugins"]
        tombstones_document = document.get("tombstones", {})
        if not isinstance(plugins_document, dict):
            raise ValueError("release_index.plugins must be an object.")
        if not isinstance(tombstones_document, dict):
            raise ValueError("release_index.tombstones must be an object.")
        if set(plugins_document) & set(tombstones_document):
            raise ValueError("A plugin cannot be active and de-certified together.")

        plugins = {}
        active_release_ids = set()
        for plugin_key, entry_document in plugins_document.items():
            if plugin_key not in registry:
                raise ValueError("Release index contains an unknown plugin.")
            descriptor = ReleaseDescriptor.from_document(entry_document)
            registry_identity = _registry_entry_identity(registry[plugin_key])
            if not registry_identity or descriptor.repository_identity != registry_identity:
                raise ValueError("Release repository does not match the registry.")
            if descriptor.release_id in active_release_ids:
                raise ValueError("Release index contains a duplicate release identity.")
            active_release_ids.add(descriptor.release_id)
            plugins[plugin_key] = descriptor

        tombstones = {}
        for plugin_key, tombstone_document in tombstones_document.items():
            if plugin_key not in registry:
                raise ValueError("Release index contains an unknown tombstone plugin.")
            tombstone = ReleaseTombstone.from_document(tombstone_document)
            registry_identity = _registry_entry_identity(registry[plugin_key])
            if not registry_identity or tombstone.repository_identity != registry_identity:
                raise ValueError("Tombstone repository does not match the registry.")
            tombstones[plugin_key] = tombstone

        result = cls(
            schema_version=RELEASE_INDEX_SCHEMA_VERSION,
            sequence=sequence,
            generated_at=generated_at,
            expires_at=expires_at,
            registry_sha256=expected_registry_sha256,
            plugins=plugins,
            tombstones=tombstones,
        )
        if previous is not None:
            result._validate_lineage(previous)
        return result

    def _validate_lineage(self, previous):
        """Reject revision regressions, gaps, mutations, and silent removals."""
        for plugin_key, previous_release in previous.plugins.items():
            current_release = self.plugins.get(plugin_key)
            tombstone = self.tombstones.get(plugin_key)
            if current_release is None:
                if tombstone is None:
                    raise ValueError("Accepted release disappeared without a tombstone.")
                if (
                    tombstone.repository_identity
                    != previous_release.repository_identity
                    or tombstone.last_revision != previous_release.revision
                    or tombstone.release_id != previous_release.release_id
                ):
                    raise ValueError("Release tombstone does not match prior state.")
                continue

            if current_release.revision < previous_release.revision:
                raise ValueError("Release revision regressed.")
            if current_release.revision == previous_release.revision:
                if not current_release.same_accepted_target(previous_release):
                    raise ValueError("An accepted release revision was mutated.")
                continue

            if current_release.release_id == previous_release.release_id:
                raise ValueError(
                    "A higher release revision must name a new release."
                )

            required_predecessors = set(previous_release.supersedes)
            required_predecessors.add(previous_release.release_id)
            if not required_predecessors.issubset(set(current_release.supersedes)):
                raise ValueError("Release lineage has a predecessor gap.")

        for plugin_key, previous_tombstone in previous.tombstones.items():
            current_tombstone = self.tombstones.get(plugin_key)
            if current_tombstone is None:
                raise ValueError("A de-certified release was reactivated without review.")
            if (
                current_tombstone.repository_identity
                != previous_tombstone.repository_identity
                or current_tombstone.last_revision < previous_tombstone.last_revision
                or current_tombstone.release_id != previous_tombstone.release_id
            ):
                raise ValueError("Release tombstone regressed or changed identity.")


@dataclass
class ReleaseMetadataSelection:
    """The registry/index pair selected for runtime use."""

    sequence: int
    registry_bytes: bytes
    release_index_bytes: bytes
    release_index: object
    release_authorized: bool
    reason: str = ""


@dataclass
class _ReleaseMetadataGeneration:
    """One complete and hash-verified on-disk metadata generation."""

    sequence: int
    registry_bytes: bytes
    release_index_bytes: bytes
    release_index: ReleaseIndex


class ReleaseMetadataStore:
    """Durably cache and recover exact registry/release-index generations."""

    def __init__(
        self,
        metadata_root,
        bundled_registry_path=None,
        bundled_index_path=None,
        clock=None,
        fault_injector=None,
    ):
        self.metadata_root = os.path.abspath(str(metadata_root))
        self.generations_dir = os.path.join(self.metadata_root, "generations")
        self.watermark_path = os.path.join(
            self.metadata_root, "trust-state.json"
        )
        self.pointer_path = os.path.join(self.metadata_root, "current.json")
        self.bundled_registry_path = bundled_registry_path
        self.bundled_index_path = bundled_index_path
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.fault_injector = fault_injector

    def _event(self, event):
        """Expose a completed durability boundary to crash-injection tests."""
        if self.fault_injector is not None:
            self.fault_injector(event)

    def _ensure_directories(self):
        """Create the manager-owned metadata and generation directories."""
        os.makedirs(self.generations_dir, exist_ok=True)

    def _fsync_directory(self, path):
        """Persist directory entry changes where the platform supports it."""
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            if os.name == "nt":
                return
            raise
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _json_bytes(self, document):
        """Serialize small state documents deterministically."""
        return (
            json.dumps(document, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

    def _write_generation_file(
        self, path, contents, written_event, fsynced_event
    ):
        """Write and fsync one file inside an unpublished generation."""
        with open(path, "xb") as metadata_file:
            metadata_file.write(contents)
            self._event(written_event)
            metadata_file.flush()
            os.fsync(metadata_file.fileno())
            self._event(fsynced_event)

    def _write_atomic_state(
        self,
        path,
        document,
        written_event,
        fsynced_event,
        replaced_event,
        directory_fsynced_event,
    ):
        """Atomically replace a durable metadata state document."""
        self._ensure_directories()
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=os.path.basename(path) + ".tmp-",
            dir=self.metadata_root,
        )
        with os.fdopen(descriptor, "wb") as state_file:
            state_file.write(self._json_bytes(document))
            self._event(written_event)
            state_file.flush()
            os.fsync(state_file.fileno())
            self._event(fsynced_event)
        os.replace(temporary_path, path)
        self._event(replaced_event)
        self._fsync_directory(self.metadata_root)
        self._event(directory_fsynced_event)

    def _write_watermark(self, sequence):
        """Raise the durable highest-sequence watermark."""
        self._write_atomic_state(
            self.watermark_path,
            {
                "schema_version": RELEASE_INDEX_SCHEMA_VERSION,
                "highest_sequence": sequence,
            },
            "watermark_written",
            "watermark_fsynced",
            "watermark_replaced",
            "metadata_fsynced_after_watermark",
        )

    def _write_pointer(self, sequence):
        """Point runtime readers at one complete metadata generation."""
        self._write_atomic_state(
            self.pointer_path,
            {
                "schema_version": RELEASE_INDEX_SCHEMA_VERSION,
                "sequence": sequence,
            },
            "pointer_written",
            "pointer_fsynced",
            "pointer_replaced",
            "metadata_fsynced_after_pointer",
        )

    def _read_state_sequence(self, path, field):
        """Read one small state document without repairing invalid data."""
        if not os.path.isfile(path):
            return "missing", 0
        try:
            with open(path, "rb") as state_file:
                document = _load_json_object(state_file.read(), path)
            allowed = {field, "schema_version"}
            if set(document) - allowed or field not in document:
                raise ValueError("State document has unexpected fields.")
            if "schema_version" in document and (
                type(document["schema_version"]) is not int
                or document["schema_version"] != RELEASE_INDEX_SCHEMA_VERSION
            ):
                raise ValueError("State document schema is unsupported.")
            sequence = _require_positive_integer(document[field], field)
            return "valid", sequence
        except (OSError, ValueError, TypeError):
            return "invalid", 0

    def _historical_index(self, registry_bytes, index_bytes):
        """Validate a stored pair without applying current-time expiry."""
        document = _load_json_object(index_bytes, "release_index.json")
        generated_at = _parse_utc_timestamp(
            document.get("generated_at"), "release_index.generated_at"
        )
        return ReleaseIndex.from_document(
            document,
            registry_bytes=registry_bytes,
            now=generated_at,
        )

    def _generation_from_directory(self, generation_path):
        """Load one complete generation, returning None if it is corrupt."""
        generation_name = os.path.basename(generation_path)
        if (
            not generation_name.isdigit()
            or os.path.islink(generation_path)
            or not os.path.isdir(generation_path)
        ):
            return None
        try:
            sequence = _require_positive_integer(
                int(generation_name), "generation sequence"
            )
            with open(
                os.path.join(generation_path, "registry.json"), "rb"
            ) as registry_file:
                registry_bytes = registry_file.read()
            with open(
                os.path.join(generation_path, "release_index.json"), "rb"
            ) as index_file:
                index_bytes = index_file.read()
            with open(
                os.path.join(generation_path, "hashes.json"), "rb"
            ) as hashes_file:
                hashes = _load_json_object(
                    hashes_file.read(), "generation hashes"
                )
            if set(hashes) != {
                "registry_sha256",
                "release_index_sha256",
            }:
                raise ValueError("Generation hashes have unexpected fields.")
            registry_sha256 = _require_sha256(
                hashes["registry_sha256"], "generation registry hash"
            )
            index_sha256 = _require_sha256(
                hashes["release_index_sha256"], "generation index hash"
            )
            if hashlib.sha256(registry_bytes).hexdigest() != registry_sha256:
                raise ValueError("Cached registry hash mismatch.")
            if hashlib.sha256(index_bytes).hexdigest() != index_sha256:
                raise ValueError("Cached release index hash mismatch.")
            release_index = self._historical_index(
                registry_bytes, index_bytes
            )
            if release_index.sequence != sequence:
                raise ValueError(
                    "Generation directory does not match embedded sequence."
                )
            return _ReleaseMetadataGeneration(
                sequence=sequence,
                registry_bytes=registry_bytes,
                release_index_bytes=index_bytes,
                release_index=release_index,
            )
        except (OSError, ValueError, TypeError):
            return None

    def _scan_generations(self):
        """Return all complete generations ordered by increasing sequence."""
        if not os.path.isdir(self.generations_dir):
            return []
        generations = []
        try:
            names = os.listdir(self.generations_dir)
        except OSError:
            return generations
        for name in names:
            if not name.isdigit():
                continue
            generation = self._generation_from_directory(
                os.path.join(self.generations_dir, name)
            )
            if generation is not None:
                generations.append(generation)
        return sorted(generations, key=lambda generation: generation.sequence)

    def _read_bundle_bytes(self):
        """Read bundled bytes for bootstrap or registry-only fallback."""
        registry_bytes = b""
        index_bytes = b""
        try:
            if self.bundled_registry_path:
                with open(self.bundled_registry_path, "rb") as registry_file:
                    registry_bytes = registry_file.read()
                _load_json_object(registry_bytes, "bundled registry")
        except (OSError, ValueError):
            registry_bytes = b""
        try:
            if self.bundled_index_path:
                with open(self.bundled_index_path, "rb") as index_file:
                    index_bytes = index_file.read()
        except OSError:
            index_bytes = b""
        return registry_bytes, index_bytes

    def _is_fresh(self, release_index):
        """Return whether an otherwise valid index may authorize mutations."""
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("Release metadata clock must be timezone-aware.")
        expires_at = _parse_utc_timestamp(
            release_index.expires_at, "release_index.expires_at"
        )
        return expires_at > now.astimezone(timezone.utc)

    def _selection(self, generation, reason=""):
        """Build a runtime selection and apply current freshness rules."""
        release_authorized = self._is_fresh(generation.release_index)
        if not release_authorized and not reason:
            reason = "Release metadata is expired; release changes are paused."
        return ReleaseMetadataSelection(
            sequence=generation.sequence,
            registry_bytes=generation.registry_bytes,
            release_index_bytes=generation.release_index_bytes,
            release_index=(
                generation.release_index if release_authorized else None
            ),
            release_authorized=release_authorized,
            reason=reason,
        )

    def _unauthorized_selection(
        self, reason, registry_bytes=b"", sequence=0, index_bytes=b""
    ):
        """Return registry data while refusing all release mutations."""
        return ReleaseMetadataSelection(
            sequence=sequence,
            registry_bytes=registry_bytes,
            release_index_bytes=index_bytes,
            release_index=None,
            release_authorized=False,
            reason=reason,
        )

    def _trusted_generation(self, repair=True):
        """Select the highest complete generation at or above the watermark."""
        watermark_status, watermark = self._read_state_sequence(
            self.watermark_path, "highest_sequence"
        )
        if watermark_status == "invalid":
            raise ValueError(
                "The durable release metadata watermark is malformed."
            )

        generations = self._scan_generations()
        eligible = [
            generation
            for generation in generations
            if generation.sequence >= watermark
        ]
        generation = eligible[-1] if eligible else None
        if generation is None:
            if watermark > 0:
                raise ValueError(
                    "The generation named by the durable watermark is unavailable."
                )
            return None, 0, generations

        pointer_status, pointer = self._read_state_sequence(
            self.pointer_path, "sequence"
        )
        pointer_matches = (
            pointer_status == "valid" and pointer == generation.sequence
        )
        watermark_matches = watermark == generation.sequence
        if repair and (not watermark_matches or not pointer_matches):
            self._event("recovery_selected")
            if not watermark_matches:
                self._write_watermark(generation.sequence)
            if not pointer_matches:
                self._write_pointer(generation.sequence)
        return generation, watermark, generations

    def _persist_generation(
        self, registry_bytes, index_bytes, release_index
    ):
        """Publish an exact pair, then durably raise trust and current state."""
        self._ensure_directories()
        sequence = release_index.sequence
        final_path = os.path.join(self.generations_dir, str(sequence))
        if os.path.exists(final_path):
            raise ValueError("Release metadata generation already exists.")
        temporary_path = tempfile.mkdtemp(
            prefix=str(sequence) + ".tmp-", dir=self.generations_dir
        )

        self._write_generation_file(
            os.path.join(temporary_path, "registry.json"),
            registry_bytes,
            "registry_written",
            "registry_fsynced",
        )
        self._write_generation_file(
            os.path.join(temporary_path, "release_index.json"),
            index_bytes,
            "index_written",
            "index_fsynced",
        )
        hashes = self._json_bytes(
            {
                "registry_sha256": hashlib.sha256(
                    registry_bytes
                ).hexdigest(),
                "release_index_sha256": hashlib.sha256(
                    index_bytes
                ).hexdigest(),
            }
        )
        self._write_generation_file(
            os.path.join(temporary_path, "hashes.json"),
            hashes,
            "hashes_written",
            "hashes_fsynced",
        )
        self._fsync_directory(temporary_path)
        self._event("generation_fsynced")
        os.replace(temporary_path, final_path)
        self._event("generation_renamed")
        self._fsync_directory(self.generations_dir)
        self._event("generations_fsynced")
        self._write_watermark(sequence)
        self._write_pointer(sequence)
        return _ReleaseMetadataGeneration(
            sequence=sequence,
            registry_bytes=registry_bytes,
            release_index_bytes=index_bytes,
            release_index=release_index,
        )

    def accept_remote(self, registry_bytes, index_bytes):
        """Validate and durably accept a fresh, increasing remote pair."""
        if not isinstance(registry_bytes, (bytes, bytearray)) or not isinstance(
            index_bytes, (bytes, bytearray)
        ):
            raise ValueError("Remote release metadata must be bytes.")
        registry_bytes = bytes(registry_bytes)
        index_bytes = bytes(index_bytes)

        prior_generation, watermark, _ = self._trusted_generation(repair=True)
        document = _load_json_object(index_bytes, "release_index.json")
        release_index = ReleaseIndex.from_document(
            document,
            registry_bytes=registry_bytes,
            now=self.clock(),
            previous=(
                prior_generation.release_index
                if prior_generation is not None
                else None
            ),
        )
        if release_index.sequence <= watermark:
            raise ValueError("Release metadata sequence does not raise trust.")

        generation = self._persist_generation(
            registry_bytes, index_bytes, release_index
        )
        return self._selection(generation)

    def load(self):
        """Recover the highest trusted pair or return a registry-only fallback."""
        bundled_registry, bundled_index = self._read_bundle_bytes()
        generations = self._scan_generations()
        fallback_generation = generations[-1] if generations else None
        fallback_registry = (
            fallback_generation.registry_bytes
            if fallback_generation is not None
            else bundled_registry
        )
        fallback_sequence = (
            fallback_generation.sequence if fallback_generation is not None else 0
        )

        try:
            generation, watermark, _ = self._trusted_generation(repair=True)
        except ValueError as error:
            return self._unauthorized_selection(
                str(error),
                registry_bytes=fallback_registry,
                sequence=fallback_sequence,
            )
        if generation is not None:
            return self._selection(generation)

        if not bundled_registry:
            return self._unauthorized_selection(
                "No valid bundled or cached plugin registry is available."
            )
        if not bundled_index:
            return self._unauthorized_selection(
                "The bundled release index is unavailable.",
                registry_bytes=bundled_registry,
            )

        try:
            bundled_release_index = self._historical_index(
                bundled_registry, bundled_index
            )
        except ValueError as error:
            return self._unauthorized_selection(
                "The bundled release index is invalid: " + str(error),
                registry_bytes=bundled_registry,
            )
        if bundled_release_index.sequence < watermark:
            return self._unauthorized_selection(
                "The bundled release index is below the durable watermark.",
                registry_bytes=bundled_registry,
                sequence=bundled_release_index.sequence,
                index_bytes=bundled_index,
            )
        if not self._is_fresh(bundled_release_index):
            return self._unauthorized_selection(
                "The bundled release index is expired.",
                registry_bytes=bundled_registry,
                sequence=bundled_release_index.sequence,
                index_bytes=bundled_index,
            )

        generation = self._persist_generation(
            bundled_registry, bundled_index, bundled_release_index
        )
        return self._selection(generation)


INSTALL_METADATA_SCHEMA_VERSION = 1
WINDOWS_RESERVED_PATH_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *("com" + str(number) for number in range(1, 10)),
    *("lpt" + str(number) for number in range(1, 10)),
}


def _require_plugin_key(value, label="plugin_key"):
    """Validate one cross-platform plugin directory key."""
    value = _require_nonempty_string(value, label)
    invalid_windows_characters = '<>:"/\\|?*'
    if (
        value in (".", "..")
        or value.startswith(".")
        or value.endswith((".", " "))
        or any(character in value for character in invalid_windows_characters)
        or os.path.basename(value) != value
    ):
        raise ValueError(label + " is not a safe plugin key.")
    windows_stem = value.split(".", 1)[0].casefold()
    if windows_stem in WINDOWS_RESERVED_PATH_NAMES:
        raise ValueError(label + " is reserved on Windows.")
    return value


def _require_audit_path(value, label):
    """Validate one canonical, cross-platform relative audit path."""
    path = _normalize_relative_metadata_path(value, label, allow_root=False)
    if unicodedata.normalize("NFC", path) != path:
        raise ValueError(label + " must use NFC Unicode normalization.")
    parts = path.split("/")
    for part in parts:
        if part.endswith((".", " ")) or ":" in part:
            raise ValueError(label + " is not portable across supported hosts.")
        windows_stem = part.split(".", 1)[0].casefold()
        if windows_stem in WINDOWS_RESERVED_PATH_NAMES:
            raise ValueError(label + " contains a Windows-reserved name.")
    first_part = parts[0].casefold()
    if first_part in (".git", ".pypluginstore") or path.casefold() in (
        ".pypluginstore.json",
        "plugin.py",
    ):
        raise ValueError(label + " is manager-reserved or executable code.")
    return path


def _require_artifact_file_path(value, label):
    """Validate one portable regular-file path from a pristine artifact."""
    path = _normalize_relative_metadata_path(value, label, allow_root=False)
    if unicodedata.normalize("NFC", path) != path:
        raise ValueError(label + " must use NFC Unicode normalization.")
    parts = path.split("/")
    for part in parts:
        if part.endswith((".", " ")) or ":" in part:
            raise ValueError(label + " is not portable across supported hosts.")
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_PATH_NAMES:
            raise ValueError(label + " contains a Windows-reserved name.")
    if parts[0].casefold() in (".git", ".pypluginstore") or path.casefold() == (
        ".pypluginstore.json"
    ):
        raise ValueError(label + " is manager-reserved.")
    return path


class ReleaseHttpError(Exception):
    """Categorized runtime release-download failure."""

    def __init__(self, reason, message="", *, status=None, url=None):
        self.reason = str(reason)
        self.status = status
        self.url = url
        super().__init__(message or self.reason)


class SystemResolver:
    """Resolve stream addresses using the operating-system resolver."""

    def resolve(self, hostname, port):
        answers = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        addresses = []
        seen = set()
        for family, _kind, _protocol, _canonical, socket_address in answers:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            address = socket_address[0]
            if address not in seen:
                seen.add(address)
                addresses.append(address)
        return addresses


class _ReleaseResponseHeaders(Mapping):
    """Expose wire header pairs without hiding case-fold duplicates."""

    def __init__(self, pairs):
        self._pairs = tuple(pairs)

    def __getitem__(self, key):
        for name, value in self._pairs:
            if name == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (name for name, _value in self._pairs)

    def __len__(self):
        return len(self._pairs)

    def items(self):
        return iter(self._pairs)


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    """Connect to one validated IP while authenticating the URL hostname."""

    def __init__(
        self,
        connect_ip,
        server_hostname,
        port,
        timeout,
        context,
    ):
        super().__init__(
            server_hostname,
            port=port,
            timeout=timeout,
            context=context,
        )
        self._connect_ip = connect_ip
        self._server_hostname = server_hostname

    def connect(self):
        if self._tunnel_host is not None:
            raise RuntimeError("Pinned HTTPS connections do not support proxies.")

        address = ipaddress.ip_address(self._connect_ip)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        endpoint = (
            (str(address), self.port, 0, 0)
            if family == socket.AF_INET6
            else (str(address), self.port)
        )
        raw_socket = socket.socket(family, socket.SOCK_STREAM)
        try:
            raw_socket.settimeout(self.timeout)
            raw_socket.connect(endpoint)
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._server_hostname,
            )
        except Exception:
            raw_socket.close()
            self.sock = None
            raise


class _PinnedHttpsResponse:
    """Adapt ``http.client`` responses to the bounded stream contract."""

    def __init__(self, response, connection):
        self._response = response
        self._connection = connection
        self.status = response.status
        self.headers = _ReleaseResponseHeaders(response.getheaders())
        self._closed = False

    def iter_bytes(self, chunk_size):
        while True:
            chunk = self._response.read(chunk_size)
            if not chunk:
                return
            yield chunk

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._response.close()
        finally:
            self._connection.close()


class PinnedHttpsTransport:
    """Direct stdlib HTTPS transport that never consults proxy settings."""

    def __init__(self, context=None):
        self.context = ssl.create_default_context() if context is None else context
        if not callable(getattr(self.context, "wrap_socket", None)):
            raise ValueError("context must provide wrap_socket().")

    def request(
        self,
        method,
        url,
        *,
        connect_ip,
        server_hostname,
        host_header,
        headers,
        connect_timeout,
        read_timeout,
    ):
        target = _validate_release_url(url)
        if method != "GET":
            raise ValueError("PinnedHttpsTransport only supports GET.")
        if (
            server_hostname != target.hostname
            or host_header != target.host_header
        ):
            raise ValueError("TLS and Host identities must match the URL.")
        try:
            pinned_address = str(ipaddress.ip_address(connect_ip))
        except ValueError as error:
            raise ValueError("connect_ip must be an IP address literal.") from error
        request_headers = _validate_release_request_headers(headers)
        parsed = urllib.parse.urlsplit(target.url)
        request_target = parsed.path or "/"
        if parsed.query:
            request_target += "?" + parsed.query

        connection = _PinnedHttpsConnection(
            pinned_address,
            target.hostname,
            target.port,
            connect_timeout,
            self.context,
        )
        try:
            connection.connect()
            connection.putrequest(
                method,
                request_target,
                skip_host=True,
                skip_accept_encoding=True,
            )
            connection.putheader("Host", target.host_header)
            for name, value in request_headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            connection.sock.settimeout(read_timeout)
            response = connection.getresponse()
            return _PinnedHttpsResponse(response, connection)
        except Exception:
            connection.close()
            raise


@dataclass(frozen=True)
class ReleaseDownload:
    """Verified metadata for one durable runtime artifact download."""

    path: str
    size: int
    sha256: str
    final_url: str
    redirects: int
    verified: bool


@dataclass(frozen=True)
class _ValidatedReleaseUrl:
    url: str
    hostname: str
    port: int
    host_header: str
    origin: tuple


def _release_http_error(reason, message, *, status=None, url=None):
    return ReleaseHttpError(reason, message, status=status, url=url)


def _validate_release_url(url):
    """Validate an absolute credential-free HTTPS request target."""
    if not isinstance(url, str) or not url:
        raise _release_http_error(
            "https_required",
            "An absolute HTTPS URL is required.",
        )
    if (
        CONTROL_CHARACTER_PATTERN.search(url)
        or any(character.isspace() for character in url)
        or "\\" in url
        or "#" in url
        or RELEASE_INVALID_PERCENT_PATTERN.search(url)
    ):
        raise _release_http_error("invalid_url", "URL is not canonical.", url=url)
    try:
        parsed = urllib.parse.urlsplit(url)
        explicit_port = parsed.port
    except ValueError as error:
        raise _release_http_error(
            "invalid_url",
            "URL authority is invalid.",
            url=url,
        ) from error
    if parsed.scheme.lower() != "https":
        raise _release_http_error(
            "https_required",
            "An absolute HTTPS URL is required.",
            url=url,
        )
    hostname = parsed.hostname
    if (
        not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "*" in hostname
        or hostname.startswith(".")
        or hostname.endswith(".")
        or parsed.netloc.endswith(":")
    ):
        raise _release_http_error(
            "invalid_url",
            "URL must have a canonical credential-free authority.",
            url=url,
        )
    port = 443 if explicit_port is None else explicit_port
    if not 1 <= port <= 65535:
        raise _release_http_error("invalid_url", "URL port is invalid.", url=url)
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise _release_http_error(
            "invalid_url",
            "URL hostname is invalid.",
            url=url,
        ) from error
    try:
        ipaddress.ip_address(ascii_hostname)
        hostname_is_ip = True
    except ValueError:
        hostname_is_ip = False
    if (
        not ascii_hostname
        or CONTROL_CHARACTER_PATTERN.search(ascii_hostname)
        or "%" in ascii_hostname
        or len(ascii_hostname) > 253
        or (
            not hostname_is_ip
            and any(
                not RELEASE_HOST_LABEL_PATTERN.fullmatch(label)
                for label in ascii_hostname.split(".")
            )
        )
    ):
        raise _release_http_error(
            "invalid_url",
            "URL hostname is invalid.",
            url=url,
        )

    host_name = (
        "[" + ascii_hostname + "]" if ":" in ascii_hostname else ascii_hostname
    )
    host_header = host_name
    if explicit_port is not None:
        host_header += ":" + str(explicit_port)
    return _ValidatedReleaseUrl(
        url=url,
        hostname=ascii_hostname,
        port=port,
        host_header=host_header,
        origin=("https", ascii_hostname, port),
    )


def _validate_release_origin_allowlist(allowed_origins):
    """Return exact HTTPS origins from reviewed configuration."""
    if allowed_origins is None:
        return set()
    if isinstance(allowed_origins, (str, bytes)) or not isinstance(
        allowed_origins,
        (list, tuple, set, frozenset),
    ):
        raise _release_http_error(
            "invalid_origin_allowlist",
            "Origin allowlist must be a collection of exact HTTPS origins.",
        )

    validated = set()
    for origin in allowed_origins:
        if (
            not isinstance(origin, str)
            or not origin
            or CONTROL_CHARACTER_PATTERN.search(origin)
            or any(character.isspace() for character in origin)
            or "\\" in origin
            or "?" in origin
            or "#" in origin
        ):
            raise _release_http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid value.",
            )
        try:
            parsed = urllib.parse.urlsplit(origin)
            explicit_port = parsed.port
        except ValueError as error:
            raise _release_http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid authority.",
            ) from error
        hostname = parsed.hostname
        if (
            parsed.scheme.lower() != "https"
            or not parsed.netloc
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in hostname
            or hostname.startswith(".")
            or hostname.endswith(".")
            or parsed.netloc.endswith(":")
        ):
            raise _release_http_error(
                "invalid_origin_allowlist",
                "Origin allowlist values must be exact HTTPS origins.",
            )
        port = 443 if explicit_port is None else explicit_port
        if not 1 <= port <= 65535:
            raise _release_http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid port.",
            )
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise _release_http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid hostname.",
            ) from error
        try:
            ipaddress.ip_address(ascii_hostname)
            hostname_is_ip = True
        except ValueError:
            hostname_is_ip = False
        if (
            not ascii_hostname
            or "%" in ascii_hostname
            or len(ascii_hostname) > 253
            or (
                not hostname_is_ip
                and any(
                    not RELEASE_HOST_LABEL_PATTERN.fullmatch(label)
                    for label in ascii_hostname.split(".")
                )
            )
        ):
            raise _release_http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid hostname.",
            )
        validated.add(("https", ascii_hostname, port))
    return validated


def _validate_release_request_headers(headers):
    """Validate caller headers and force an undecoded response body."""
    if headers is None:
        headers = {}
    if not isinstance(headers, Mapping):
        raise ValueError("headers must be a mapping.")

    result = {}
    seen = set()
    for name, value in headers.items():
        if (
            not isinstance(name, str)
            or not RELEASE_HEADER_NAME_PATTERN.fullmatch(name)
        ):
            raise ValueError("HTTP header name is invalid.")
        lower_name = name.lower()
        if lower_name in seen:
            raise ValueError("HTTP header names must be unique ignoring case.")
        seen.add(lower_name)
        if not isinstance(value, str) or CONTROL_CHARACTER_PATTERN.search(value):
            raise ValueError("HTTP header value is invalid.")
        if lower_name == "host":
            raise ValueError("Host is controlled by the pinned transport.")
        if lower_name == "accept-encoding":
            continue
        result[name] = value
    result["Accept-Encoding"] = "identity"
    return result


def _strip_release_cross_origin_secrets(headers):
    """Remove credentials and ambient cookies on an approved origin change."""
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in RELEASE_SECRET_REQUEST_HEADERS
    }


def _release_response_headers(response, url):
    """Normalize response headers while rejecting case-fold duplicates."""
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        raise _release_http_error(
            "invalid_response_headers",
            "HTTP response headers are not a mapping.",
            url=url,
        )
    normalized = {}
    for name, value in headers.items():
        if (
            not isinstance(name, str)
            or not RELEASE_HEADER_NAME_PATTERN.fullmatch(name)
        ):
            raise _release_http_error(
                "invalid_response_headers",
                "HTTP response contains an invalid header name.",
                url=url,
            )
        lower_name = name.lower()
        if lower_name in normalized:
            raise _release_http_error(
                "invalid_response_headers",
                "HTTP response contains duplicate headers.",
                url=url,
            )
        if not isinstance(value, str) or CONTROL_CHARACTER_PATTERN.search(value):
            raise _release_http_error(
                "invalid_response_headers",
                "HTTP response contains an invalid header value.",
                url=url,
            )
        normalized[lower_name] = value
    return normalized


def _safe_close_release_response(response):
    """Best-effort close without masking a categorized fetch failure."""
    try:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


@dataclass(frozen=True)
class ReleaseArchiveLimits:
    """Conservative resource limits for one untrusted release ZIP."""

    max_archive_size: int = 50 * 1024 * 1024
    max_expanded_size: int = 250 * 1024 * 1024
    max_entries: int = 5000
    max_file_size: int = 50 * 1024 * 1024
    max_compression_ratio: float = 100.0

    def __post_init__(self):
        for field_name in (
            "max_archive_size",
            "max_expanded_size",
            "max_entries",
            "max_file_size",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(field_name + " must be a positive integer.")
        ratio = self.max_compression_ratio
        if (
            type(ratio) not in (int, float)
            or not math.isfinite(ratio)
            or ratio <= 0
        ):
            raise ValueError(
                "max_compression_ratio must be a finite positive number."
            )


class SafeReleaseHttpClient:
    """Stream one bounded artifact through independently pinned HTTPS hops."""

    def __init__(
        self,
        *,
        resolver=None,
        transport=None,
        max_redirects=3,
        connect_timeout=5.0,
        read_timeout=30.0,
        max_bytes=50 * 1024 * 1024,
        stream_chunk_size=RELEASE_HTTP_CHUNK_SIZE,
    ):
        if type(max_redirects) is not int or max_redirects < 0:
            raise ValueError("max_redirects must be a non-negative integer.")
        for value, label in (
            (connect_timeout, "connect_timeout"),
            (read_timeout, "read_timeout"),
        ):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(label + " must be a finite positive number.")
        if (
            type(max_bytes) is not int
            or max_bytes <= 0
            or max_bytes > sys.maxsize
        ):
            raise ValueError("max_bytes must be a positive integer.")
        if type(stream_chunk_size) is not int or stream_chunk_size <= 0:
            raise ValueError("stream_chunk_size must be a positive integer.")
        if resolver is None:
            resolver = SystemResolver()
        if transport is None:
            transport = PinnedHttpsTransport()
        if not callable(getattr(resolver, "resolve", None)):
            raise ValueError("resolver must provide resolve().")
        if not callable(getattr(transport, "request", None)):
            raise ValueError("transport must provide request().")

        self.resolver = resolver
        self.transport = transport
        self.max_redirects = max_redirects
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_bytes = max_bytes
        self.stream_chunk_size = min(stream_chunk_size, max_bytes)

    def _resolve_public_address(self, hostname, port, url):
        """Validate the entire DNS answer, then pin its first public address."""
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None
        if literal is not None:
            answers = [hostname]
        else:
            try:
                answers = self.resolver.resolve(hostname, port)
            except Exception as error:
                raise _release_http_error(
                    "dns_resolution_failed",
                    "DNS resolution failed.",
                    url=url,
                ) from error
        if isinstance(answers, (str, bytes)):
            answers = None
        try:
            answer_iterator = iter(answers) if answers is not None else iter(())
        except Exception as error:
            raise _release_http_error(
                "dns_resolution_failed",
                "DNS answer is invalid.",
                url=url,
            ) from error

        parsed_addresses = []
        for answer_index in range(RELEASE_MAX_DNS_ANSWERS + 1):
            try:
                answer = next(answer_iterator)
            except StopIteration:
                break
            except Exception as error:
                raise _release_http_error(
                    "dns_resolution_failed",
                    "DNS answer could not be read.",
                    url=url,
                ) from error
            if answer_index == RELEASE_MAX_DNS_ANSWERS:
                raise _release_http_error(
                    "dns_resolution_failed",
                    "DNS answer contains too many addresses.",
                    url=url,
                )
            if not isinstance(answer, str):
                raise _release_http_error(
                    "dns_resolution_failed",
                    "DNS answer contains a malformed address.",
                    url=url,
                )
            try:
                address = ipaddress.ip_address(answer)
            except ValueError as error:
                raise _release_http_error(
                    "dns_resolution_failed",
                    "DNS answer contains a malformed address.",
                    url=url,
                ) from error
            public_address = getattr(address, "ipv4_mapped", None) or address
            if not public_address.is_global or public_address.is_multicast:
                raise _release_http_error(
                    "non_public_address",
                    "DNS answer contains a non-public address.",
                    url=url,
                )
            parsed_addresses.append(str(address))
        if not parsed_addresses:
            raise _release_http_error(
                "dns_resolution_failed",
                "DNS answer is empty.",
                url=url,
            )
        return parsed_addresses[0]

    def _request(self, target, headers):
        """Open one pinned transport request without retrying unknown bytes."""
        connect_ip = self._resolve_public_address(
            target.hostname,
            target.port,
            target.url,
        )
        try:
            return self.transport.request(
                "GET",
                target.url,
                connect_ip=connect_ip,
                server_hostname=target.hostname,
                host_header=target.host_header,
                headers=dict(headers),
                connect_timeout=self.connect_timeout,
                read_timeout=self.read_timeout,
            )
        except TimeoutError as error:
            raise _release_http_error(
                "timeout",
                "HTTP request timed out.",
                url=target.url,
            ) from error
        except ReleaseHttpError:
            raise
        except Exception as error:
            raise _release_http_error(
                "transport_error",
                "HTTP transport failed.",
                url=target.url,
            ) from error

    def _response_length(self, response_headers, target, expected_size):
        content_encoding = response_headers.get("content-encoding")
        if (
            content_encoding is not None
            and content_encoding.strip().lower() != "identity"
        ):
            raise _release_http_error(
                "unsupported_content_encoding",
                "Compressed response bodies are not accepted.",
                url=target.url,
            )

        content_length = response_headers.get("content-length")
        if content_length is None:
            return None
        if not RELEASE_CONTENT_LENGTH_PATTERN.fullmatch(content_length):
            raise _release_http_error(
                "invalid_content_length",
                "Content-Length is malformed.",
                url=target.url,
            )
        normalized_length = content_length.lstrip("0") or "0"
        maximum_length = str(self.max_bytes)
        if (
            len(normalized_length) > len(maximum_length)
            or (
                len(normalized_length) == len(maximum_length)
                and normalized_length > maximum_length
            )
        ):
            raise _release_http_error(
                "content_too_large",
                "Declared response size exceeds the limit.",
                url=target.url,
            )
        declared_size = int(normalized_length)
        if declared_size > self.max_bytes:
            raise _release_http_error(
                "content_too_large",
                "Declared response size exceeds the limit.",
                url=target.url,
            )
        if expected_size is not None and declared_size != expected_size:
            raise _release_http_error(
                "length_mismatch",
                "Declared response size differs from expected size.",
                url=target.url,
            )
        return declared_size

    def _remove_partial_download(self, destination):
        try:
            os.remove(destination)
        except FileNotFoundError:
            pass

    def _write_chunk(self, output, chunk, target):
        view = memoryview(chunk)
        while view:
            try:
                written = output.write(view)
            except Exception as error:
                raise _release_http_error(
                    "write_failed",
                    "Release artifact could not be written.",
                    url=target.url,
                ) from error
            if type(written) is not int or written <= 0:
                raise _release_http_error(
                    "write_failed",
                    "Release artifact write did not make progress.",
                    url=target.url,
                )
            view = view[written:]

    def _read_download_to_path(
        self,
        response,
        target,
        response_headers,
        destination,
        expected_sha256,
        expected_size,
        redirects,
    ):
        """Stream, verify, and durably persist one successful response."""
        declared_size = self._response_length(
            response_headers,
            target,
            expected_size,
        )
        iterator = getattr(response, "iter_bytes", None)
        if not callable(iterator):
            raise _release_http_error(
                "transport_error",
                "HTTP response does not expose a byte iterator.",
                url=target.url,
            )

        try:
            output = open(destination, "xb", buffering=0)
        except FileExistsError as error:
            raise _release_http_error(
                "destination_exists",
                "Release download destination already exists.",
                url=target.url,
            ) from error
        except Exception as error:
            raise _release_http_error(
                "write_failed",
                "Release download destination could not be created.",
                url=target.url,
            ) from error

        digest = hashlib.sha256()
        actual_size = 0
        try:
            try:
                for chunk in iterator(self.stream_chunk_size):
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise _release_http_error(
                            "transport_error",
                            "HTTP response yielded non-byte data.",
                            url=target.url,
                        )
                    chunk = bytes(chunk)
                    if actual_size + len(chunk) > self.max_bytes:
                        raise _release_http_error(
                            "content_too_large",
                            "Streamed response exceeds the size limit.",
                            url=target.url,
                        )
                    self._write_chunk(output, chunk, target)
                    actual_size += len(chunk)
                    digest.update(chunk)
            except ReleaseHttpError:
                raise
            except TimeoutError as error:
                raise _release_http_error(
                    "timeout",
                    "HTTP response stream timed out.",
                    url=target.url,
                ) from error
            except Exception as error:
                raise _release_http_error(
                    "transport_error",
                    "HTTP response stream failed.",
                    url=target.url,
                ) from error

            if declared_size is not None and actual_size != declared_size:
                raise _release_http_error(
                    "length_mismatch",
                    "Received bytes differ from Content-Length.",
                    url=target.url,
                )
            if expected_size is not None and actual_size != expected_size:
                raise _release_http_error(
                    "length_mismatch",
                    "Received bytes differ from expected size.",
                    url=target.url,
                )
            actual_digest = digest.hexdigest()
            if expected_sha256 and actual_digest != expected_sha256:
                raise _release_http_error(
                    "digest_mismatch",
                    "Received bytes differ from expected SHA-256.",
                    url=target.url,
                )
            try:
                output.flush()
                os.fsync(output.fileno())
            except Exception as error:
                raise _release_http_error(
                    "write_failed",
                    "Release artifact could not be made durable.",
                    url=target.url,
                ) from error
            try:
                output.close()
            except Exception as error:
                raise _release_http_error(
                    "write_failed",
                    "Release artifact could not be closed.",
                    url=target.url,
                ) from error
            return ReleaseDownload(
                path=destination,
                size=actual_size,
                sha256=actual_digest,
                final_url=target.url,
                redirects=redirects,
                verified=bool(expected_sha256 or expected_size is not None),
            )
        except BaseException:
            try:
                output.close()
            finally:
                self._remove_partial_download(destination)
            raise

    def download_to_path(
        self,
        url,
        destination,
        *,
        expected_sha256=None,
        expected_size=None,
        allowed_origins=(),
        headers=None,
    ):
        """Download and verify one artifact into a brand-new durable file."""
        if expected_sha256 is None:
            expected_sha256 = ""
        if not isinstance(expected_sha256, str) or (
            expected_sha256
            and not LOWER_SHA256_PATTERN.fullmatch(expected_sha256)
        ):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest.")
        if expected_size is not None and (
            type(expected_size) is not int
            or expected_size <= 0
            or expected_size > self.max_bytes
        ):
            raise ValueError(
                "expected_size must be a positive integer within max_bytes."
            )
        request_headers = _validate_release_request_headers(headers)
        reviewed_origins = _validate_release_origin_allowlist(allowed_origins)
        target = _validate_release_url(url)
        try:
            destination_path = os.fspath(destination)
        except TypeError as error:
            raise ValueError("destination must be a filesystem path.") from error
        if not isinstance(destination_path, str) or not destination_path:
            raise ValueError("destination must be a non-empty text path.")
        if os.path.lexists(destination_path):
            raise _release_http_error(
                "destination_exists",
                "Release download destination already exists.",
                url=target.url,
            )

        approved_origins = set(reviewed_origins)
        approved_origins.add(target.origin)
        redirects = 0
        while True:
            response = self._request(target, request_headers)
            try:
                status = getattr(response, "status", None)
                if type(status) is not int:
                    raise _release_http_error(
                        "transport_error",
                        "HTTP response status is invalid.",
                        url=target.url,
                    )
                response_headers = _release_response_headers(
                    response,
                    target.url,
                )
                if status in RELEASE_REDIRECT_STATUSES:
                    if redirects >= self.max_redirects:
                        raise _release_http_error(
                            "too_many_redirects",
                            "HTTP redirect limit exceeded.",
                            status=status,
                            url=target.url,
                        )
                    location = response_headers.get("location")
                    if not location:
                        raise _release_http_error(
                            "redirect_location_missing",
                            "HTTP redirect did not include Location.",
                            status=status,
                            url=target.url,
                        )
                    next_url = urllib.parse.urljoin(target.url, location)
                    next_target = _validate_release_url(next_url)
                    if next_target.origin != target.origin:
                        if next_target.origin not in approved_origins:
                            raise _release_http_error(
                                "origin_not_allowed",
                                "Redirect target origin was not reviewed.",
                                status=status,
                                url=next_target.url,
                            )
                        request_headers = _strip_release_cross_origin_secrets(
                            request_headers
                        )
                    redirects += 1
                    target = next_target
                    continue
                if status != 200:
                    raise _release_http_error(
                        "http_error",
                        "HTTP response status is not a successful download.",
                        status=status,
                        url=target.url,
                    )
                return self._read_download_to_path(
                    response,
                    target,
                    response_headers,
                    destination_path,
                    expected_sha256,
                    expected_size,
                    redirects,
                )
            finally:
                _safe_close_release_response(response)


@dataclass(frozen=True)
class ReleaseArchiveExtraction:
    """Inventory returned after a complete safe extraction."""

    root_prefix: str
    root_path: str
    file_count: int
    expanded_size: int


@dataclass(frozen=True)
class _SafeZipMember:
    info: object
    parts: tuple
    canonical_parts: tuple
    is_directory: bool


class SafeZipExtractor:
    """Inspect and stream an untrusted ZIP without using ``extractall``."""

    CHUNK_SIZE = 64 * 1024
    RESERVED_METADATA_PARTS = {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        ".pypluginstore",
        ".pypluginstore.json",
    }
    WINDOWS_FORBIDDEN_CHARACTERS = '<>:"|?*'

    def __init__(self, limits):
        if not isinstance(limits, ReleaseArchiveLimits):
            raise ValueError("limits must be ReleaseArchiveLimits.")
        self.limits = limits

    def _portable_parts(self, path, label):
        if not isinstance(path, str) or not path:
            raise ValueError(label + " is empty.")
        if (
            path.startswith(("/", "\\"))
            or "\\" in path
            or re.match(r"^[A-Za-z]:", path)
        ):
            raise ValueError(label + " is not a relative POSIX path.")
        parts = path.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(label + " is not a normalized relative path.")

        for part in parts:
            if unicodedata.normalize("NFC", part) != part:
                raise ValueError(label + " must use NFC Unicode normalization.")
            if any(
                unicodedata.category(character) == "Cc"
                for character in part
            ):
                raise ValueError(label + " contains a control character.")
            if part.endswith((".", " ")):
                raise ValueError(label + " has a trailing dot or space.")
            if any(
                character in self.WINDOWS_FORBIDDEN_CHARACTERS
                for character in part
            ):
                raise ValueError(label + " is not portable on Windows.")
            windows_stem = part.split(".", 1)[0].casefold()
            if windows_stem in WINDOWS_RESERVED_PATH_NAMES:
                raise ValueError(label + " contains a Windows-reserved name.")
            if part.casefold() in self.RESERVED_METADATA_PARTS:
                raise ValueError(label + " contains manager or VCS metadata.")
        return tuple(parts)

    def _expected_root(self, expected_root_prefix):
        if expected_root_prefix == ".":
            return "."
        parts = self._portable_parts(
            expected_root_prefix,
            "expected_root_prefix",
        )
        if len(parts) != 1:
            raise ValueError("expected_root_prefix must be one exact wrapper.")
        return parts[0]

    def _member(self, info, expected_root_prefix):
        original_name = getattr(info, "orig_filename", info.filename)
        if original_name != info.filename or "\x00" in original_name:
            raise ValueError("ZIP member contains a NUL byte.")
        if info.flag_bits & (0x1 | 0x40):
            raise ValueError("Encrypted ZIP members are not supported.")

        is_directory = original_name.endswith("/")
        path = original_name[:-1] if is_directory else original_name
        parts = self._portable_parts(path, "ZIP member name")
        if expected_root_prefix != ".":
            if parts[0] != expected_root_prefix:
                raise ValueError("ZIP wrapper does not match the indexed root.")
            if len(parts) == 1 and not is_directory:
                raise ValueError("The indexed ZIP root must be a directory.")

        unix_mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(unix_mode) if info.create_system == 3 else 0
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError("ZIP member has an unsupported file type.")
        if is_directory:
            if file_type == stat.S_IFREG or info.file_size != 0:
                raise ValueError("ZIP directory metadata is inconsistent.")
        elif file_type == stat.S_IFDIR:
            raise ValueError("ZIP file metadata is inconsistent.")

        return _SafeZipMember(
            info=info,
            parts=parts,
            canonical_parts=tuple(part.casefold() for part in parts),
            is_directory=is_directory,
        )

    def _inspect(self, archive, expected_root_prefix):
        try:
            infos = archive.infolist()
        except Exception as error:
            raise ValueError("ZIP central directory is invalid.") from error
        if not infos:
            raise ValueError("ZIP archive is empty.")
        if len(infos) > self.limits.max_entries:
            raise ValueError("ZIP archive contains too many members.")

        members = []
        member_paths = set()
        node_kinds = {}
        component_spellings = {}
        expanded_size = 0
        for info in infos:
            member = self._member(info, expected_root_prefix)
            canonical_parts = member.canonical_parts

            for index, (canonical_part, original_part) in enumerate(
                zip(canonical_parts, member.parts)
            ):
                spelling_key = (canonical_parts[:index], canonical_part)
                previous_spelling = component_spellings.get(spelling_key)
                if (
                    previous_spelling is not None
                    and previous_spelling != original_part
                ):
                    raise ValueError("ZIP member paths collide across hosts.")
                component_spellings[spelling_key] = original_part

            if canonical_parts in member_paths:
                raise ValueError("ZIP archive contains duplicate member paths.")
            for prefix_length in range(1, len(canonical_parts)):
                prefix = canonical_parts[:prefix_length]
                if node_kinds.get(prefix) == "file":
                    raise ValueError("ZIP file and directory paths collide.")
                node_kinds.setdefault(prefix, "directory")

            existing_kind = node_kinds.get(canonical_parts)
            if member.is_directory:
                if existing_kind == "file":
                    raise ValueError("ZIP file and directory paths collide.")
                node_kinds[canonical_parts] = "directory"
            else:
                if existing_kind is not None:
                    raise ValueError("ZIP file and directory paths collide.")
                node_kinds[canonical_parts] = "file"
            member_paths.add(canonical_parts)

            if type(info.file_size) is not int or info.file_size < 0:
                raise ValueError("ZIP member has an invalid expanded size.")
            if type(info.compress_size) is not int or info.compress_size < 0:
                raise ValueError("ZIP member has an invalid compressed size.")
            if not member.is_directory:
                if info.file_size > self.limits.max_file_size:
                    raise ValueError("ZIP member exceeds the per-file limit.")
                expanded_size += info.file_size
                if expanded_size > self.limits.max_expanded_size:
                    raise ValueError("ZIP archive exceeds the expansion limit.")
                if info.file_size:
                    if info.compress_size == 0 or (
                        info.file_size
                        > self.limits.max_compression_ratio
                        * info.compress_size
                    ):
                        raise ValueError(
                            "ZIP member exceeds the compression-ratio limit."
                        )
            members.append(member)
        return members

    def _target_path(self, destination, parts):
        target = os.path.abspath(os.path.join(destination, *parts))
        try:
            inside = os.path.commonpath((destination, target)) == destination
        except ValueError:
            inside = False
        if not inside:
            raise ValueError("ZIP member escapes the extraction directory.")
        return target

    def _extract_members(self, archive, members, destination):
        file_count = 0
        expanded_size = 0
        for member in members:
            target = self._target_path(destination, member.parts)
            if member.is_directory:
                os.makedirs(target, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(target), exist_ok=True)
            member_size = 0
            with archive.open(member.info, "r") as source, open(
                target, "xb"
            ) as output:
                while True:
                    chunk = source.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    member_size += len(chunk)
                    expanded_size += len(chunk)
                    if member_size > self.limits.max_file_size:
                        raise ValueError("ZIP member exceeds the per-file limit.")
                    if expanded_size > self.limits.max_expanded_size:
                        raise ValueError("ZIP archive exceeds the expansion limit.")
                    output.write(chunk)
            if member_size != member.info.file_size:
                raise ValueError("ZIP member size differs from its metadata.")
            file_count += 1
        return file_count, expanded_size

    def _remove_destination(self, destination):
        try:
            if os.path.isdir(destination) and not os.path.islink(destination):
                shutil.rmtree(destination)
            elif os.path.lexists(destination):
                os.remove(destination)
        except FileNotFoundError:
            pass

    def extract(
        self,
        archive_path,
        destination,
        *,
        expected_root_prefix,
    ):
        """Validate then extract one ZIP into a brand-new directory."""
        created_destination = False
        destination_path = None
        try:
            root_prefix = self._expected_root(expected_root_prefix)
            archive_path = os.path.abspath(os.fspath(archive_path))
            destination_path = os.path.abspath(os.fspath(destination))
            if os.path.lexists(destination_path):
                raise ValueError("Extraction destination already exists.")

            path_stat = os.lstat(archive_path)
            if not stat.S_ISREG(path_stat.st_mode):
                raise ValueError("Release archive must be a regular file.")
            open_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            open_flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(archive_path, open_flags)
            try:
                archive_stat = os.fstat(descriptor)
                if not stat.S_ISREG(archive_stat.st_mode):
                    raise ValueError("Release archive must be a regular file.")
                if (
                    archive_stat.st_dev != path_stat.st_dev
                    or archive_stat.st_ino != path_stat.st_ino
                ):
                    raise ValueError("Release archive changed while being opened.")
                if archive_stat.st_size > self.limits.max_archive_size:
                    raise ValueError(
                        "Release archive exceeds the compressed limit."
                    )

                with os.fdopen(descriptor, "rb") as archive_file:
                    descriptor = None
                    with zipfile.ZipFile(archive_file, "r") as archive:
                        members = self._inspect(archive, root_prefix)
                        os.mkdir(destination_path)
                        created_destination = True
                        file_count, expanded_size = self._extract_members(
                            archive,
                            members,
                            destination_path,
                        )
            finally:
                if descriptor is not None:
                    os.close(descriptor)

            return ReleaseArchiveExtraction(
                root_prefix=root_prefix,
                root_path=(
                    destination_path
                    if root_prefix == "."
                    else os.path.join(destination_path, root_prefix)
                ),
                file_count=file_count,
                expanded_size=expanded_size,
            )
        except BaseException as error:
            if created_destination and destination_path is not None:
                self._remove_destination(destination_path)
            if isinstance(error, ValueError):
                raise
            if isinstance(error, Exception):
                raise ValueError("Release ZIP extraction failed.") from error
            raise


class ReleaseArtifactValidationError(ValueError):
    """Categorized failure while certifying an extracted release tree."""

    def __init__(self, reason, message=""):
        self.reason = str(reason)
        super().__init__(message or self.reason)


@dataclass(frozen=True)
class ReleaseArtifactValidation:
    """Canonical identity and install inventory for a staged artifact."""

    source_root: str
    plugin_key: str
    identity_source: str
    tree_sha256: str
    artifact_files: dict


@dataclass(frozen=True)
class _ReleaseTreeFile:
    relative_path: str
    physical_path: str
    size: int
    sha256: str
    device: int
    inode: int


class ReleaseArtifactValidationService:
    """Certify a safe extracted tree before transaction staging."""

    CHUNK_SIZE = 64 * 1024

    def __init__(self, plugin, limits=None):
        if plugin is None:
            raise ValueError("plugin is required.")
        if limits is None:
            limits = ReleaseArchiveLimits()
        if not isinstance(limits, ReleaseArchiveLimits):
            raise ValueError("limits must be ReleaseArchiveLimits.")
        self.plugin = plugin
        self.limits = limits
        self.path_validator = SafeZipExtractor(limits)

    def _error(self, reason, message):
        return ReleaseArtifactValidationError(reason, message)

    def _directory_stat(self, path, reason, message):
        try:
            path_stat = os.lstat(path)
        except OSError as error:
            raise self._error(reason, message) from error
        if not stat.S_ISDIR(path_stat.st_mode):
            raise self._error(reason, message)
        return path_stat

    def _root_layout(self, extraction_dir, root_prefix):
        try:
            root_prefix = self.path_validator._expected_root(root_prefix)
        except ValueError as error:
            raise self._error(
                "root_layout",
                "The indexed archive root is invalid.",
            ) from error
        try:
            extraction_path = os.path.abspath(os.fspath(extraction_dir))
        except TypeError as error:
            raise self._error(
                "root_layout",
                "The extraction directory is invalid.",
            ) from error
        self._directory_stat(
            extraction_path,
            "root_layout",
            "The extraction directory is missing or unsafe.",
        )
        if root_prefix == ".":
            return extraction_path
        try:
            entries = list(os.scandir(extraction_path))
        except OSError as error:
            raise self._error(
                "root_layout",
                "The extraction directory could not be inspected.",
            ) from error
        if len(entries) != 1 or entries[0].name != root_prefix:
            raise self._error(
                "root_layout",
                "The extracted archive does not have the indexed wrapper.",
            )
        root_path = os.path.abspath(entries[0].path)
        try:
            inside = os.path.commonpath((extraction_path, root_path)) == (
                extraction_path
            )
        except ValueError:
            inside = False
        if not inside:
            raise self._error(
                "root_layout",
                "The extracted archive root escapes its staging directory.",
            )
        self._directory_stat(
            root_path,
            "root_layout",
            "The indexed archive root is missing or unsafe.",
        )
        return root_path

    def _portable_relative_path(self, relative_path):
        try:
            parts = self.path_validator._portable_parts(
                relative_path,
                "artifact path",
            )
        except ValueError as error:
            raise self._error(
                "unsafe_tree",
                "The extracted artifact contains an unsafe path.",
            ) from error
        try:
            relative_path.encode("utf-8")
        except UnicodeError as error:
            raise self._error(
                "unsafe_tree",
                "The extracted artifact path is not valid UTF-8.",
            ) from error
        return parts

    def _register_components(self, spellings, canonical_parts, parts):
        for index, (canonical_part, original_part) in enumerate(
            zip(canonical_parts, parts)
        ):
            spelling_key = (canonical_parts[:index], canonical_part)
            previous = spellings.get(spelling_key)
            if previous is not None and previous != original_part:
                raise self._error(
                    "unsafe_tree",
                    "The extracted artifact contains a cross-host path collision.",
                )
            spellings[spelling_key] = original_part

    def _opened_regular_file(self, path, path_stat):
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise self._error(
                "unsafe_tree",
                "An artifact file could not be opened safely.",
            ) from error
        try:
            opened_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened_stat.st_mode)
                or opened_stat.st_dev != path_stat.st_dev
                or opened_stat.st_ino != path_stat.st_ino
                or opened_stat.st_size != path_stat.st_size
            ):
                raise self._error(
                    "unsafe_tree",
                    "An artifact file changed while being opened.",
                )
            return descriptor, opened_stat
        except BaseException:
            os.close(descriptor)
            raise

    def _hash_regular_file(self, path, path_stat):
        descriptor, opened_stat = self._opened_regular_file(path, path_stat)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(descriptor, "rb") as source:
                descriptor = None
                while True:
                    chunk = source.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.limits.max_file_size:
                        raise self._error(
                            "unsafe_tree",
                            "An artifact file exceeds the per-file limit.",
                        )
                    digest.update(chunk)
        except ReleaseArtifactValidationError:
            raise
        except OSError as error:
            raise self._error(
                "unsafe_tree",
                "An artifact file could not be read safely.",
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if size != opened_stat.st_size:
            raise self._error(
                "unsafe_tree",
                "An artifact file changed while being read.",
            )
        return size, digest.hexdigest(), opened_stat

    def _scan_tree(self, root_path):
        files = []
        directories = {".": root_path}
        node_spellings = {}
        node_paths = {}
        stack = [(root_path, "")]
        entry_count = 0
        expanded_size = 0

        while stack:
            directory, relative_directory = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError as error:
                raise self._error(
                    "unsafe_tree",
                    "The extracted artifact tree could not be inspected.",
                ) from error
            for entry in entries:
                entry_count += 1
                if entry_count > self.limits.max_entries:
                    raise self._error(
                        "unsafe_tree",
                        "The extracted artifact contains too many entries.",
                    )
                relative_path = (
                    entry.name
                    if not relative_directory
                    else relative_directory + "/" + entry.name
                )
                parts = self._portable_relative_path(relative_path)
                canonical_parts = tuple(part.casefold() for part in parts)
                self._register_components(
                    node_spellings,
                    canonical_parts,
                    parts,
                )
                previous_path = node_paths.get(canonical_parts)
                if previous_path is not None and previous_path != relative_path:
                    raise self._error(
                        "unsafe_tree",
                        "The extracted artifact contains colliding paths.",
                    )
                node_paths[canonical_parts] = relative_path

                try:
                    path_stat = entry.stat(follow_symlinks=False)
                except OSError as error:
                    raise self._error(
                        "unsafe_tree",
                        "An artifact path could not be inspected safely.",
                    ) from error
                if stat.S_ISDIR(path_stat.st_mode):
                    directories[relative_path] = entry.path
                    stack.append((entry.path, relative_path))
                    continue
                if not stat.S_ISREG(path_stat.st_mode):
                    raise self._error(
                        "unsafe_tree",
                        "The extracted artifact contains a link or special file.",
                    )
                if getattr(path_stat, "st_nlink", 1) > 1:
                    raise self._error(
                        "unsafe_tree",
                        "The extracted artifact contains a hard-linked file.",
                    )
                if path_stat.st_size > self.limits.max_file_size:
                    raise self._error(
                        "unsafe_tree",
                        "An artifact file exceeds the per-file limit.",
                    )
                size, digest, opened_stat = self._hash_regular_file(
                    entry.path,
                    path_stat,
                )
                expanded_size += size
                if expanded_size > self.limits.max_expanded_size:
                    raise self._error(
                        "unsafe_tree",
                        "The extracted artifact exceeds the expansion limit.",
                    )
                files.append(
                    _ReleaseTreeFile(
                        relative_path=relative_path,
                        physical_path=entry.path,
                        size=size,
                        sha256=digest,
                        device=opened_stat.st_dev,
                        inode=opened_stat.st_ino,
                    )
                )
        if not files:
            raise self._error(
                "unsafe_tree",
                "The extracted artifact does not contain regular files.",
            )
        return files, directories

    def _tree_digest(self, files):
        records = []
        for file_record in files:
            path_bytes = file_record.relative_path.encode("utf-8")
            record = (
                path_bytes
                + b"\0"
                + str(file_record.size).encode("ascii")
                + b"\0"
                + file_record.sha256.encode("ascii")
                + b"\n"
            )
            records.append((path_bytes, record))
        records.sort(key=lambda item: item[0])
        return hashlib.sha256(
            b"".join(record for _path, record in records)
        ).hexdigest()

    def _tree_fingerprint(self, files):
        return sorted(
            (
                file_record.relative_path,
                file_record.size,
                file_record.sha256,
                file_record.device,
                file_record.inode,
            )
            for file_record in files
        )

    def _source_tree(self, root_path, files, directories, source_path):
        try:
            source_path = _normalize_relative_metadata_path(
                source_path,
                "artifact.source_path",
            )
            if source_path != ".":
                self.path_validator._portable_parts(
                    source_path,
                    "artifact.source_path",
                )
        except ValueError as error:
            raise self._error(
                "source_path",
                "The indexed source path is invalid.",
            ) from error
        if source_path not in directories:
            raise self._error(
                "source_path",
                "The indexed source path is not a staged directory.",
            )
        source_root = root_path if source_path == "." else directories[source_path]
        prefix = "" if source_path == "." else source_path + "/"
        selected = []
        for file_record in files:
            if prefix and not file_record.relative_path.startswith(prefix):
                continue
            installed_path = (
                file_record.relative_path
                if not prefix
                else file_record.relative_path[len(prefix) :]
            )
            if not installed_path:
                continue
            selected.append((installed_path, file_record))
        selected.sort(key=lambda item: item[0].encode("utf-8"))
        return source_root, selected

    def _read_verified_contents(self, file_record):
        try:
            path_stat = os.lstat(file_record.physical_path)
        except OSError as error:
            raise self._error(
                "unsafe_tree",
                "An artifact file disappeared during validation.",
            ) from error
        descriptor, opened_stat = self._opened_regular_file(
            file_record.physical_path,
            path_stat,
        )
        try:
            with os.fdopen(descriptor, "rb") as source:
                descriptor = None
                contents = source.read(self.limits.max_file_size + 1)
        except OSError as error:
            raise self._error(
                "unsafe_tree",
                "An artifact file could not be re-read safely.",
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if (
            len(contents) != file_record.size
            or len(contents) != opened_stat.st_size
            or opened_stat.st_dev != file_record.device
            or opened_stat.st_ino != file_record.inode
            or hashlib.sha256(contents).hexdigest() != file_record.sha256
        ):
            raise self._error(
                "unsafe_tree",
                "An artifact file changed during validation.",
            )
        return contents

    def _compile_python(self, selected_files):
        plugin_metadata = None
        for installed_path, file_record in selected_files:
            if not installed_path.casefold().endswith(".py"):
                continue
            contents = self._read_verified_contents(file_record)
            try:
                compile(
                    contents,
                    file_record.physical_path,
                    "exec",
                    dont_inherit=True,
                )
            except (
                SyntaxError,
                UnicodeError,
                ValueError,
                OverflowError,
                RecursionError,
            ) as error:
                raise self._error(
                    "compile_failed",
                    "Python source failed compilation: " + installed_path,
                ) from error
            if installed_path == "plugin.py":
                plugin_metadata = self._parse_plugin_metadata(contents)
        return plugin_metadata

    def _parse_plugin_metadata(self, contents):
        try:
            encoding, _lines = tokenize.detect_encoding(
                io.BytesIO(contents).readline
            )
            source_code = contents.decode(encoding)
        except (SyntaxError, UnicodeError, LookupError) as error:
            raise self._error(
                "identity_mismatch",
                "The staged plugin metadata encoding is invalid.",
            ) from error
        plugin_tags = re.findall(
            r"<plugin\b([^>]*)>",
            source_code,
            re.IGNORECASE | re.DOTALL,
        )
        if len(plugin_tags) != 1:
            raise self._error(
                "identity_mismatch",
                "The staged plugin must contain one Domoticz plugin tag.",
            )
        metadata = {}
        for match in re.finditer(
            r"([A-Za-z_][\w:.-]*)\s*=\s*(\"([^\"]*)\"|'([^']*)')",
            plugin_tags[0],
        ):
            key = match.group(1).lower()
            if key in metadata:
                raise self._error(
                    "identity_ambiguous",
                    "The staged plugin metadata contains duplicate attributes.",
                )
            value = match.group(3) if match.group(3) is not None else match.group(4)
            metadata[key] = html.unescape(value or "")
        return metadata

    def _repository_lookup(self):
        lookup = {}
        keys = list(getattr(self.plugin, "plugin_data", {}))
        for key in getattr(self.plugin, "registry_entries", {}):
            if key not in keys:
                keys.append(key)
        for key in keys:
            entry = self.plugin.get_registry_entry(key)
            if entry is None:
                continue
            identity = normalize_repository_identity(
                entry.author,
                entry.repository,
            )
            if not identity:
                continue
            lookup.setdefault(identity, [])
            if key not in lookup[identity]:
                lookup[identity].append(key)
        return lookup

    def _identity_tier(self, candidates, plugin_key, source):
        unique = []
        for candidate in candidates:
            if candidate and candidate not in unique:
                unique.append(candidate)
        if len(unique) > 1:
            raise self._error(
                "identity_ambiguous",
                "The staged plugin identity matches multiple entries.",
            )
        if not unique:
            return ""
        if unique[0] != plugin_key:
            raise self._error(
                "identity_mismatch",
                "The staged plugin identity resolves to another plugin.",
            )
        return source

    def _certify_identity(
        self,
        source_root,
        plugin_key,
        metadata,
        repository_identity,
    ):
        entry = self.plugin.get_registry_entry(plugin_key)
        if entry is None:
            raise self._error(
                "identity_mismatch",
                "The requested plugin is not present in the registry.",
            )
        configured_identity = normalize_repository_identity(
            entry.author,
            entry.repository,
        )
        if not configured_identity:
            raise self._error(
                "identity_mismatch",
                "The registry repository identity is invalid.",
            )
        if repository_identity is not None:
            normalized_identity = normalize_repository_identity(
                repository_identity
            )
            if (
                not normalized_identity
                or normalized_identity != configured_identity
            ):
                raise self._error(
                    "identity_mismatch",
                    "The release repository identity differs from the registry.",
                )

        try:
            lookups = self.plugin.build_installed_plugin_lookup()
        except Exception as error:
            raise self._error(
                "identity_mismatch",
                "The staged plugin identity could not be certified.",
            ) from error
        source_folder = os.path.basename(source_root)

        external_link = metadata.get("externallink", "")
        if external_link:
            external_identity = normalize_repository_identity(external_link)
            if not external_identity:
                raise self._error(
                    "identity_mismatch",
                    "The staged plugin externallink is invalid.",
                )
            source = self._identity_tier(
                self._repository_lookup().get(external_identity, []),
                plugin_key,
                "plugin.py externallink",
            )
            if source:
                return source

        exact_key = lookups[0].get(
            self.plugin.normalize_plugin_folder_name(source_folder),
            "",
        )
        source = self._identity_tier(
            [exact_key] if exact_key else [],
            plugin_key,
            "exact folder key",
        )
        if source:
            return source

        folder_tiers = (
            (
                lookups[1].get(
                    self.plugin.normalize_plugin_folder_name(source_folder),
                    [],
                ),
                "repository/archive folder name",
            ),
            (
                lookups[2].get(
                    self.plugin.normalize_plugin_metadata_value(source_folder),
                    [],
                ),
                "normalized folder name",
            ),
        )
        for candidates, source_label in folder_tiers:
            if len(set(candidates)) > 1:
                raise self._error(
                    "identity_ambiguous",
                    "The staged plugin identity matches multiple entries.",
                )
            if candidates and self.plugin.plugin_metadata_matches_registry(
                candidates[0],
                source_root,
                metadata,
            ):
                source = self._identity_tier(
                    candidates,
                    plugin_key,
                    source_label,
                )
                if source:
                    return source

        metadata_candidates = []
        for field in ("key", "name"):
            normalized = self.plugin.normalize_plugin_metadata_value(
                metadata.get(field, "")
            )
            for candidate in lookups[3].get(normalized, []):
                if candidate not in metadata_candidates:
                    metadata_candidates.append(candidate)
        source = self._identity_tier(
            metadata_candidates,
            plugin_key,
            "plugin.py key/name",
        )
        if source:
            return source
        raise self._error(
            "identity_mismatch",
            "The staged plugin identity does not match the requested plugin.",
        )

    def validate(
        self,
        *,
        extraction_dir,
        root_prefix,
        source_path,
        plugin_key,
        expected_tree_sha256=None,
        repository_identity=None,
    ):
        """Return canonical identity only after every runtime check succeeds."""
        try:
            plugin_key = _require_plugin_key(plugin_key)
        except ValueError as error:
            raise self._error(
                "identity_mismatch",
                "The requested plugin key is invalid.",
            ) from error
        if expected_tree_sha256 is not None:
            try:
                expected_tree_sha256 = _require_sha256(
                    expected_tree_sha256,
                    "expected_tree_sha256",
                )
            except ValueError as error:
                raise self._error(
                    "tree_mismatch",
                    "The expected artifact tree digest is invalid.",
                ) from error

        root_path = self._root_layout(extraction_dir, root_prefix)
        files, directories = self._scan_tree(root_path)
        tree_sha256 = self._tree_digest(files)
        if (
            expected_tree_sha256 is not None
            and tree_sha256 != expected_tree_sha256
        ):
            raise self._error(
                "tree_mismatch",
                "The staged artifact tree differs from the release index.",
            )
        source_root, selected_files = self._source_tree(
            root_path,
            files,
            directories,
            source_path,
        )
        selected_by_path = dict(selected_files)
        plugin_file = selected_by_path.get("plugin.py")
        if plugin_file is None or plugin_file.size <= 0:
            raise self._error(
                "plugin_missing",
                "The selected source tree requires a non-empty root plugin.py.",
            )
        metadata = self._compile_python(selected_files)
        if metadata is None:
            raise self._error(
                "identity_mismatch",
                "The staged plugin metadata could not be read.",
            )
        identity_source = self._certify_identity(
            source_root,
            plugin_key,
            metadata,
            repository_identity,
        )
        revalidated_files, _revalidated_directories = self._scan_tree(root_path)
        if self._tree_fingerprint(revalidated_files) != self._tree_fingerprint(
            files
        ):
            raise self._error(
                "unsafe_tree",
                "The staged artifact changed during validation.",
            )
        artifact_files = {
            installed_path: {
                "sha256": file_record.sha256,
                "size": file_record.size,
            }
            for installed_path, file_record in selected_files
        }
        return ReleaseArtifactValidation(
            source_root=source_root,
            plugin_key=plugin_key,
            identity_source=identity_source,
            tree_sha256=tree_sha256,
            artifact_files=artifact_files,
        )


@dataclass
class InstallMetadata:
    """Validated audit record stored in a release-managed plugin folder."""

    schema: int
    plugin_key: str
    management_mode: str
    repository_identity: str
    version: str
    tag: str
    release_id: str
    release_revision: int
    released_at: str
    commit: str
    artifact_sha256: str
    artifact_tree_sha256: str
    artifact_provenance: str
    artifact_files: dict
    preserved_files: dict
    index_sequence: int
    installed_at: str
    source_revision: str = ""

    @classmethod
    def from_document(cls, document):
        """Parse strict release-managed install metadata."""
        document = _require_document(
            document,
            "install metadata",
            (
                "schema",
                "plugin_key",
                "management_mode",
                "repository_identity",
                "version",
                "tag",
                "release_id",
                "release_revision",
                "released_at",
                "commit",
                "artifact_sha256",
                "artifact_tree_sha256",
                "artifact_provenance",
                "artifact_files",
                "preserved_files",
                "index_sequence",
                "installed_at",
            ),
            ("source_revision",),
        )
        if (
            type(document["schema"]) is not int
            or document["schema"] != INSTALL_METADATA_SCHEMA_VERSION
        ):
            raise ValueError("Install metadata schema is unsupported.")

        management_mode = _require_nonempty_string(
            document["management_mode"], "management_mode"
        )
        if management_mode != "release":
            raise ValueError("Install metadata must be release-managed.")

        raw_repository_identity = _require_nonempty_string(
            document["repository_identity"], "repository_identity"
        )
        repository_identity = normalize_repository_identity(
            raw_repository_identity
        )
        if (
            not repository_identity
            or repository_identity != raw_repository_identity
        ):
            raise ValueError("repository_identity must be normalized.")

        released_at = _require_nonempty_string(
            document["released_at"], "released_at"
        )
        installed_at = _require_nonempty_string(
            document["installed_at"], "installed_at"
        )
        released_time = _parse_utc_timestamp(released_at, "released_at")
        installed_time = _parse_utc_timestamp(installed_at, "installed_at")
        if installed_time < released_time:
            raise ValueError("installed_at cannot precede released_at.")

        source_revision = document.get("source_revision", "")
        if source_revision:
            source_revision = _require_nonempty_string(
                source_revision, "source_revision"
            )
        commit = _require_git_commit(
            document["commit"], "commit", required=not source_revision
        )
        if not commit and not source_revision:
            raise ValueError("Install metadata requires an immutable source revision.")

        tag = document["tag"]
        if (
            not isinstance(tag, str)
            or tag != tag.strip()
            or CONTROL_CHARACTER_PATTERN.search(tag)
        ):
            raise ValueError("tag must be a canonical string.")

        preserved_document = document["preserved_files"]
        if not isinstance(preserved_document, dict):
            raise ValueError("preserved_files must be an object.")
        preserved_files = {}
        normalized_paths = set()
        for raw_path, raw_digest in preserved_document.items():
            path = _require_audit_path(raw_path, "preserved_files path")
            collision_key = unicodedata.normalize("NFC", path).casefold()
            if collision_key in normalized_paths:
                raise ValueError("preserved_files contains colliding paths.")
            normalized_paths.add(collision_key)
            preserved_files[path] = _require_sha256(
                raw_digest, "preserved_files digest"
            )

        artifact_provenance = _require_nonempty_string(
            document["artifact_provenance"], "artifact_provenance"
        )
        if artifact_provenance not in RELEASE_ARTIFACT_PROVENANCE:
            raise ValueError("artifact_provenance is unsupported.")
        artifact_files_document = document["artifact_files"]
        if not isinstance(artifact_files_document, dict) or not artifact_files_document:
            raise ValueError("artifact_files must be a non-empty object.")
        artifact_files = {}
        artifact_collision_keys = set()
        for raw_path, raw_record in artifact_files_document.items():
            path = _require_artifact_file_path(raw_path, "artifact_files path")
            collision_key = path.casefold()
            if collision_key in artifact_collision_keys:
                raise ValueError("artifact_files contains colliding paths.")
            artifact_collision_keys.add(collision_key)
            raw_record = _require_document(
                raw_record,
                "artifact_files record",
                ("sha256", "size"),
            )
            artifact_files[path] = {
                "sha256": _require_sha256(
                    raw_record["sha256"], "artifact_files digest"
                ),
                "size": _require_positive_integer(
                    raw_record["size"], "artifact_files size"
                ),
            }
        if "plugin.py" not in {path.casefold() for path in artifact_files}:
            raise ValueError("artifact_files must include root plugin.py.")

        return cls(
            schema=INSTALL_METADATA_SCHEMA_VERSION,
            plugin_key=_require_plugin_key(document["plugin_key"]),
            management_mode=management_mode,
            repository_identity=repository_identity,
            version=_require_nonempty_string(document["version"], "version"),
            tag=tag,
            release_id=_require_nonempty_string(
                document["release_id"], "release_id"
            ),
            release_revision=_require_positive_integer(
                document["release_revision"], "release_revision"
            ),
            released_at=released_at,
            commit=commit,
            artifact_sha256=_require_sha256(
                document["artifact_sha256"], "artifact_sha256"
            ),
            artifact_tree_sha256=_require_sha256(
                document["artifact_tree_sha256"], "artifact_tree_sha256"
            ),
            artifact_provenance=artifact_provenance,
            artifact_files=artifact_files,
            preserved_files=preserved_files,
            index_sequence=_require_positive_integer(
                document["index_sequence"], "index_sequence"
            ),
            installed_at=installed_at,
            source_revision=source_revision,
        )

    def to_document(self):
        """Return the canonical JSON-compatible install audit document."""
        document = {
            "schema": self.schema,
            "plugin_key": self.plugin_key,
            "management_mode": self.management_mode,
            "repository_identity": self.repository_identity,
            "version": self.version,
            "tag": self.tag,
            "release_id": self.release_id,
            "release_revision": self.release_revision,
            "released_at": self.released_at,
            "commit": self.commit,
            "artifact_sha256": self.artifact_sha256,
            "artifact_tree_sha256": self.artifact_tree_sha256,
            "artifact_provenance": self.artifact_provenance,
            "artifact_files": {
                path: dict(record)
                for path, record in self.artifact_files.items()
            },
            "preserved_files": dict(self.preserved_files),
            "index_sequence": self.index_sequence,
            "installed_at": self.installed_at,
        }
        if self.source_revision:
            document["source_revision"] = self.source_revision
        return document


class InstallMetadataService:
    """Read and durably replace manager-owned plugin install metadata."""

    FILE_NAME = ".pypluginstore.json"
    TEMP_FILE_NAME = ".pypluginstore.json.tmp"

    def __init__(self, plugin):
        self.plugin = plugin

    def _paths(self, plugin_dir):
        """Return committed and temporary metadata paths for a plugin."""
        plugin_dir = os.path.abspath(str(plugin_dir))
        if not os.path.isdir(plugin_dir) or os.path.islink(plugin_dir):
            raise ValueError("Plugin metadata directory must be a real directory.")
        return (
            plugin_dir,
            os.path.join(plugin_dir, self.FILE_NAME),
            os.path.join(plugin_dir, self.TEMP_FILE_NAME),
        )

    def _fsync_directory(self, path):
        """Persist directory changes where supported by the host platform."""
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            if os.name == "nt":
                return
            raise
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _discard_temp(self, plugin_dir, temporary_path):
        """Discard an uncommitted write without ever promoting its contents."""
        if not os.path.lexists(temporary_path):
            return
        if os.path.isdir(temporary_path) and not os.path.islink(temporary_path):
            raise ValueError("Install metadata temporary path is not a file.")
        os.unlink(temporary_path)
        self._fsync_directory(plugin_dir)

    def read(self, plugin_dir):
        """Read committed metadata after discarding any orphan temporary file."""
        plugin_dir, metadata_path, temporary_path = self._paths(plugin_dir)
        self._discard_temp(plugin_dir, temporary_path)
        if not os.path.lexists(metadata_path):
            return None
        if os.path.islink(metadata_path) or not os.path.isfile(metadata_path):
            raise ValueError("Install metadata path is not a regular file.")
        try:
            with open(metadata_path, "rb") as metadata_file:
                document = _load_json_object(
                    metadata_file.read(), self.FILE_NAME
                )
        except OSError as error:
            raise ValueError("Could not read install metadata: " + str(error)) from error
        return InstallMetadata.from_document(document)

    def write(self, plugin_dir, metadata):
        """Fsync and atomically replace committed install metadata."""
        if not isinstance(metadata, InstallMetadata):
            raise ValueError("metadata must be validated InstallMetadata.")
        document = metadata.to_document()
        InstallMetadata.from_document(document)
        plugin_dir, metadata_path, temporary_path = self._paths(plugin_dir)
        self._discard_temp(plugin_dir, temporary_path)
        contents = (
            json.dumps(document, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

        try:
            with open(temporary_path, "xb") as metadata_file:
                metadata_file.write(contents)
                metadata_file.flush()
                os.fsync(metadata_file.fileno())
            os.replace(temporary_path, metadata_path)
            self._fsync_directory(plugin_dir)
        finally:
            if os.path.lexists(temporary_path):
                if os.path.isdir(temporary_path) and not os.path.islink(
                    temporary_path
                ):
                    raise ValueError(
                        "Install metadata temporary path is not a file."
                    )
                os.unlink(temporary_path)
                self._fsync_directory(plugin_dir)


CHANNEL_PREFERENCE_SCHEMA_VERSION = 1
CHANNEL_PREFERENCE_CHOICES = {"keep_git", "release"}


def _normalize_channel_repository_identity(value):
    """Normalize one safe forge-neutral repository identity."""
    value = _require_nonempty_string(value, "repository identity")
    if any(character.isspace() for character in value):
        raise ValueError("Repository identity cannot contain whitespace.")

    scp_style = re.match(r"^[^/@\s:]+@[^/\s:]+:.+$", value)
    if scp_style:
        repository_host = value.split("@", 1)[1].split(":", 1)[0]
        if "?" in value or "#" in value:
            raise ValueError("Repository identity cannot contain URL metadata.")
    else:
        has_scheme = re.match(
            r"^[A-Za-z][A-Za-z0-9+.-]*://", value
        )
        try:
            parsed = urllib.parse.urlparse(value if has_scheme else "//" + value)
            parsed.port
        except ValueError as error:
            raise ValueError("Repository identity is not a valid URL.") from error

        scheme = parsed.scheme.lower()
        if has_scheme and scheme not in ("https", "ssh"):
            raise ValueError(
                "Repository identity must use HTTPS or SSH."
            )
        if parsed.password is not None:
            raise ValueError("Repository identity cannot contain credentials.")
        if scheme == "https" and parsed.username is not None:
            raise ValueError("Repository identity cannot contain credentials.")
        if not has_scheme and (
            parsed.username is not None or parsed.password is not None
        ):
            raise ValueError("Repository identity cannot contain credentials.")
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError("Repository identity cannot contain URL metadata.")
        repository_host = parsed.hostname or ""

    if (
        not repository_host
        or repository_host in (".", "..")
        or repository_host.startswith(".")
        or repository_host.endswith(".")
        or "\\" in repository_host
    ):
        raise ValueError("Repository identity has an unsafe host.")

    normalized = normalize_repository_identity(value)
    if not normalized:
        raise ValueError("Repository identity is unsafe or incomplete.")
    return normalized


def _require_channel_preference(value):
    """Accept only an explicit, supported local channel choice."""
    if not isinstance(value, str) or value not in CHANNEL_PREFERENCE_CHOICES:
        raise ValueError("Channel preference must be keep_git or release.")
    return value


@dataclass
class ChannelPreferenceDocument:
    """Validated manager-owned repository channel preferences."""

    schema_version: int
    channels: dict

    @classmethod
    def from_document(cls, document):
        """Parse a strict channel-preference state document."""
        document = _require_document(
            document,
            "channel preferences",
            ("schema_version", "channels"),
        )
        if (
            type(document["schema_version"]) is not int
            or document["schema_version"]
            != CHANNEL_PREFERENCE_SCHEMA_VERSION
        ):
            raise ValueError("Channel preference schema is unsupported.")

        raw_channels = document["channels"]
        if not isinstance(raw_channels, dict):
            raise ValueError("channels must be an object.")

        channels = {}
        normalized_identities = set()
        for raw_identity, raw_preference in raw_channels.items():
            normalized_identity = _normalize_channel_repository_identity(
                raw_identity
            )
            if normalized_identity in normalized_identities:
                raise ValueError(
                    "Channel preferences contain colliding identities."
                )
            normalized_identities.add(normalized_identity)
            if normalized_identity != raw_identity:
                raise ValueError(
                    "Channel preference identities must be normalized."
                )
            channels[normalized_identity] = _require_channel_preference(
                raw_preference
            )

        return cls(
            schema_version=CHANNEL_PREFERENCE_SCHEMA_VERSION,
            channels=channels,
        )

    def to_document(self):
        """Return the canonical JSON-compatible preference document."""
        return {
            "schema_version": self.schema_version,
            "channels": dict(self.channels),
        }


class ChannelPreferenceService:
    """Durably store explicit channel choices outside plugin checkouts."""

    STATE_DIRECTORY_NAME = ".pypluginstore"
    FILE_NAME = "channels.json"
    TEMP_FILE_NAME = "channels.json.tmp"

    def __init__(self, plugin):
        self.plugin = plugin

    def _fsync_directory(self, path):
        """Persist directory changes where supported by the host platform."""
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            if os.name == "nt":
                return
            raise
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _paths(self, create_state_directory=False):
        """Resolve manager-owned state paths without entering a checkout."""
        manager_dir = os.path.abspath(self.plugin.get_plugin_home_folder())
        if not os.path.isdir(manager_dir) or os.path.islink(manager_dir):
            raise ValueError("Plugin manager home must be a real directory.")

        state_dir = os.path.join(manager_dir, self.STATE_DIRECTORY_NAME)
        if os.path.lexists(state_dir):
            if os.path.islink(state_dir) or not os.path.isdir(state_dir):
                raise ValueError(
                    "Plugin manager state path must be a real directory."
                )
        elif create_state_directory:
            os.mkdir(state_dir)
            self._fsync_directory(manager_dir)

        return (
            state_dir,
            os.path.join(state_dir, self.FILE_NAME),
            os.path.join(state_dir, self.TEMP_FILE_NAME),
        )

    def _discard_temp(self, state_dir, temporary_path):
        """Discard an interrupted write without promoting its contents."""
        if not os.path.lexists(temporary_path):
            return
        if os.path.isdir(temporary_path) and not os.path.islink(temporary_path):
            raise ValueError("Channel preference temporary path is not a file.")
        os.unlink(temporary_path)
        self._fsync_directory(state_dir)

    def read(self):
        """Load committed preferences after removing any orphan temp file."""
        state_dir, preferences_path, temporary_path = self._paths()
        if not os.path.isdir(state_dir):
            return ChannelPreferenceDocument(
                schema_version=CHANNEL_PREFERENCE_SCHEMA_VERSION,
                channels={},
            )

        self._discard_temp(state_dir, temporary_path)
        if not os.path.lexists(preferences_path):
            return ChannelPreferenceDocument(
                schema_version=CHANNEL_PREFERENCE_SCHEMA_VERSION,
                channels={},
            )
        if os.path.islink(preferences_path) or not os.path.isfile(
            preferences_path
        ):
            raise ValueError("Channel preference path is not a regular file.")
        try:
            with open(preferences_path, "rb") as preferences_file:
                document = _load_json_object(
                    preferences_file.read(), self.FILE_NAME
                )
        except OSError as error:
            raise ValueError(
                "Could not read channel preferences: " + str(error)
            ) from error
        return ChannelPreferenceDocument.from_document(document)

    def _write(self, preferences):
        """Fsync and atomically replace the preference state document."""
        if not isinstance(preferences, ChannelPreferenceDocument):
            raise ValueError(
                "preferences must be a validated ChannelPreferenceDocument."
            )
        document = preferences.to_document()
        ChannelPreferenceDocument.from_document(document)
        state_dir, preferences_path, temporary_path = self._paths(
            create_state_directory=True
        )
        self._discard_temp(state_dir, temporary_path)
        contents = (
            json.dumps(document, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

        try:
            with open(temporary_path, "xb") as preferences_file:
                preferences_file.write(contents)
                preferences_file.flush()
                os.fsync(preferences_file.fileno())
            os.replace(temporary_path, preferences_path)
            self._fsync_directory(state_dir)
        finally:
            if os.path.lexists(temporary_path):
                if os.path.isdir(temporary_path) and not os.path.islink(
                    temporary_path
                ):
                    raise ValueError(
                        "Channel preference temporary path is not a file."
                    )
                os.unlink(temporary_path)
                self._fsync_directory(state_dir)

    def get(self, repository_identity):
        """Return an explicit preference for one normalized identity."""
        identity = _normalize_channel_repository_identity(repository_identity)
        return self.read().channels.get(identity)

    def set(self, repository_identity, preference):
        """Set one explicit channel choice while preserving all others."""
        identity = _normalize_channel_repository_identity(repository_identity)
        preference = _require_channel_preference(preference)
        channels = dict(self.read().channels)
        channels[identity] = preference
        self._write(
            ChannelPreferenceDocument(
                schema_version=CHANNEL_PREFERENCE_SCHEMA_VERSION,
                channels=channels,
            )
        )

    def clear(self, repository_identity):
        """Clear one explicit choice and leave unrelated choices intact."""
        identity = _normalize_channel_repository_identity(repository_identity)
        channels = dict(self.read().channels)
        if identity not in channels:
            return
        del channels[identity]
        self._write(
            ChannelPreferenceDocument(
                schema_version=CHANNEL_PREFERENCE_SCHEMA_VERSION,
                channels=channels,
            )
        )


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
        delivery=None,
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
        self.delivery = delivery or DeliveryPolicy.implicit()

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
            self.delivery,
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
            updated_at = "" if local else data.get("updated_at", "")
            platforms = self.plugin.normalize_platforms(data.get("platforms", data.get("platform", None)))
            try:
                if local:
                    delivery = DeliveryPolicy.git_only()
                else:
                    delivery = (
                        DeliveryPolicy.from_document(data["delivery"])
                        if "delivery" in data
                        else DeliveryPolicy.implicit()
                    )
            except ValueError as error:
                Domoticz.Error(
                    "Plugin '" + str(key) + "' has invalid delivery policy: "
                    + str(error)
                )
                return None, ["unknown"]
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
                delivery,
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
            updated_at = "" if local else (raw_entry[4] if len(raw_entry) >= 5 else "")
            entry = RegistryEntry(
                key,
                raw_entry[0],
                raw_entry[1],
                raw_entry[2],
                raw_entry[3],
                updated_at,
                platforms,
                False if local else len(raw_entry) >= 5,
                local,
                DeliveryPolicy.git_only() if local else None,
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


@dataclass
class LocalRegistryDocument:
    """A byte-revisioned view of registry_local.json."""

    entries: dict
    revision: str
    path: str
    exists: bool
    writable: bool
    error_code: str = ""
    message: str = ""


class LocalRegistryError(Exception):
    """A structured local-registry operation failure."""

    def __init__(
        self,
        code,
        message,
        field_errors=None,
        reload_required=False,
        read_only=False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field_errors = dict(field_errors or {})
        self.reload_required = reload_required
        self.read_only = read_only


class LocalRegistryService:
    """Read, validate, and atomically mutate registry_local.json."""

    MISSING_REVISION_BYTES = b"PyPluginStore:missing-local-registry:v1"
    FIELD_LIMITS = {
        "key": 128,
        "repository_source": 1000,
        "description": 500,
        "branch": 255,
    }
    CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")

    def __init__(self, plugin):
        self.plugin = plugin

    def revision_for_bytes(self, contents):
        """Return a stable SHA-256 revision for exact file bytes."""
        return "sha256:" + hashlib.sha256(contents).hexdigest()

    def read_document(self):
        """Read the local registry without treating malformed data as empty."""
        path = self.plugin.get_local_registry_file()
        try:
            with open(path, "rb") as registry_file:
                contents = registry_file.read()
        except FileNotFoundError:
            return LocalRegistryDocument(
                entries={},
                revision=self.revision_for_bytes(self.MISSING_REVISION_BYTES),
                path=path,
                exists=False,
                writable=True,
            )
        except Exception as error:
            return LocalRegistryDocument(
                entries={},
                revision="",
                path=path,
                exists=True,
                writable=False,
                error_code="registry_read_failed",
                message=str(error),
            )

        revision = self.revision_for_bytes(contents)
        try:
            entries = json.loads(contents.decode("utf-8"))
            if not isinstance(entries, dict):
                raise ValueError("Local registry must contain a JSON object.")
        except json.JSONDecodeError as error:
            message = "{} at line {} column {}.".format(
                error.msg,
                error.lineno,
                error.colno,
            )
            return LocalRegistryDocument(
                entries={},
                revision=revision,
                path=path,
                exists=True,
                writable=False,
                error_code="invalid_local_registry",
                message=message,
            )
        except (UnicodeDecodeError, ValueError) as error:
            return LocalRegistryDocument(
                entries={},
                revision=revision,
                path=path,
                exists=True,
                writable=False,
                error_code="invalid_local_registry",
                message=str(error),
            )

        return LocalRegistryDocument(
            entries=entries,
            revision=revision,
            path=path,
            exists=True,
            writable=True,
        )

    def require_current_document(self, expected_revision):
        """Return the current writable document or raise a structured error."""
        document = self.read_document()
        if not document.writable:
            raise LocalRegistryError(
                document.error_code,
                document.message,
                read_only=True,
            )
        if str(expected_revision or "") != document.revision:
            raise LocalRegistryError(
                "registry_conflict",
                "registry_local.json changed after it was loaded.",
                reload_required=True,
            )
        return document

    def has_control_characters(self, value):
        return self.CONTROL_CHARACTERS.search(value) is not None

    def repository_source_is_valid(self, source):
        if re.match(r"^[^/@\s:]+@[^/\s:]+:.+$", source):
            return True

        parsed = urllib.parse.urlparse(source)
        if parsed.scheme in ("http", "https"):
            if parsed.username is not None or parsed.password is not None:
                return False
            return bool(parsed.hostname and parsed.path.strip("/"))
        if parsed.scheme == "ssh":
            return bool(parsed.hostname and parsed.path.strip("/"))
        if parsed.scheme == "file":
            return bool(parsed.path.strip("/"))

        host, path_parts = self.plugin.split_supported_repo_reference(source)
        return bool(host and len(path_parts) >= 2)

    def validate_entry(self, entry):
        """Validate and return the canonical persisted entry fields."""
        if not isinstance(entry, dict):
            raise LocalRegistryError(
                "invalid_local_registry_entry",
                "Local registry entry must be an object.",
            )

        values = {
            "key": str(entry.get("key") or "").strip(),
            "repository_source": str(
                entry.get("repository_source") or ""
            ).strip(),
            "description": str(entry.get("description") or "").strip(),
            "branch": str(entry.get("branch") or "master").strip() or "master",
        }
        field_errors = {}

        try:
            self.plugin.get_host().validate_plugin_key(values["key"])
        except ValueError:
            field_errors["key"] = "Enter a valid plugin key."

        for field, limit in self.FIELD_LIMITS.items():
            value = values[field]
            if len(value) > limit:
                field_errors[field] = "Use at most {} characters.".format(limit)
            elif self.has_control_characters(value):
                field_errors[field] = "Control characters are not allowed."

        if not values["repository_source"]:
            field_errors["repository_source"] = "Repository source is required."
        elif not self.repository_source_is_valid(values["repository_source"]):
            field_errors["repository_source"] = "Enter a valid repository source."

        if field_errors:
            raise LocalRegistryError(
                "invalid_local_registry_entry",
                "Check the highlighted local registry fields.",
                field_errors=field_errors,
            )

        return values

    def write_entries(self, entries):
        try:
            self.plugin.get_host().write_json_atomic(
                self.plugin.get_local_registry_file(),
                entries,
                sort_keys=False,
            )
        except Exception as error:
            raise LocalRegistryError(
                "registry_write_failed",
                "Could not write registry_local.json: " + str(error),
            ) from error
        return self.read_document()

    def upsert(self, expected_revision, original_key, entry):
        values = self.validate_entry(entry)
        original_key = str(original_key or "").strip()
        if original_key and values["key"] != original_key:
            raise LocalRegistryError(
                "invalid_local_registry_entry",
                "Plugin key cannot be renamed.",
                field_errors={"key": "Plugin key cannot be renamed."},
            )

        document = self.require_current_document(expected_revision)
        if original_key:
            if original_key not in document.entries:
                raise LocalRegistryError(
                    "local_registry_entry_not_found",
                    "Local registry entry was not found.",
                    reload_required=True,
                )
        elif values["key"] in document.entries:
            raise LocalRegistryError(
                "local_registry_entry_exists",
                "A local registry entry with this key already exists.",
                field_errors={"key": "This plugin key already exists locally."},
            )

        next_entries = dict(document.entries)
        next_entries[values["key"]] = {
            "owner": values["repository_source"],
            "description": values["description"],
            "branch": values["branch"],
        }
        return self.write_entries(next_entries)

    def delete(self, expected_revision, plugin_key):
        try:
            plugin_key = self.plugin.get_host().validate_plugin_key(plugin_key)
        except ValueError as error:
            raise LocalRegistryError(
                "invalid_local_registry_entry",
                "Enter a valid plugin key.",
                field_errors={"key": "Enter a valid plugin key."},
            ) from error

        document = self.require_current_document(expected_revision)
        if plugin_key not in document.entries:
            raise LocalRegistryError(
                "local_registry_entry_not_found",
                "Local registry entry was not found.",
                reload_required=True,
            )

        next_entries = dict(document.entries)
        del next_entries[plugin_key]
        return self.write_entries(next_entries)

    def entry_for_api(self, key, data, public_keys, installed_keys):
        errors = {}
        if isinstance(data, dict):
            author = data.get("author", data.get("owner", ""))
            repository = data.get("repository", data.get("repo", ""))
            description = data.get("description", "")
            branch = data.get("branch", "master")
        elif isinstance(data, list) and len(data) >= 4:
            author, repository, description, branch = data[:4]
        else:
            author = ""
            repository = ""
            description = ""
            branch = "master"
            errors["entry"] = "Entry must use a supported object or list format."

        source = ""
        if author or repository:
            source = self.plugin.build_git_clone_url(author, repository)

        entry = {
            "key": str(key),
            "repository_source": source,
            "description": str(description or ""),
            "branch": str(branch or "master"),
            "overrides_public": key in public_keys,
            "installed": key in installed_keys,
            "valid": not errors,
            "errors": errors,
        }
        if not errors:
            try:
                self.validate_entry(entry)
            except LocalRegistryError as error:
                entry["valid"] = False
                entry["errors"] = error.field_errors or {
                    "entry": error.message,
                }
        return entry

    def entries_for_api(self, document):
        public_keys = set(self.plugin.public_registry_data or {})
        installed_keys = set(
            self.plugin.getInstalledPlugins(self.plugin.get_host().plugins_dir())
        )
        return [
            self.entry_for_api(key, data, public_keys, installed_keys)
            for key, data in sorted(
                document.entries.items(),
                key=lambda item: str(item[0]).casefold(),
            )
        ]


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
            if plugin_key and self.plugin.installed_registry_mismatch(plugin_key, plugin_dir):
                return "mismatch"

            if fetch_first and not self.plugin.fetch_git_repo(plugin_dir):
                return "unknown"

            remote_ref = self.plugin.get_configured_git_remote_ref(plugin_key, plugin_dir) or self.plugin.get_git_remote_ref(plugin_dir) or "@{u}"
            if plugin_key:
                update_times = dict(self.plugin.update_times) if self.plugin.update_times else self.plugin.load_cached_update_times()
                if self.plugin.refresh_git_update_time(plugin_key, plugin_dir, update_times, remote_ref):
                    self.plugin.save_update_times_cache(update_times)
                    self.plugin.apply_update_times(update_times, include_local=True)

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

        if self.plugin.installed_registry_mismatch(plugin_key, plugin_dir):
            self.plugin.update_status[plugin_key] = "mismatch"
            return False, "Installed Git checkout does not match the configured registry entry. Add a matching registry_local.json override before updating."

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
        self.public_registry_data = None
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
        self.local_registry_service = LocalRegistryService(self)
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
        existing_entry = self.registry_entries.get(plugin_key)
        if existing_entry is not None:
            return existing_entry

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

    def registry_target_details(self, plugin_key):
        entry = self.get_registry_entry(plugin_key)
        if entry is None:
            return None

        clone_url = self.build_git_clone_url(entry.author, entry.repository)
        return {
            "repo": self.normalize_git_repo_identity(clone_url),
            "branch": entry.branch or "",
        }

    def installed_git_target_details(self, plugin_dir):
        current_branch = self.get_git_current_branch(plugin_dir)
        remote_name = self.get_git_remote_name(plugin_dir, current_branch)
        remote_url = self.get_git_remote_url(plugin_dir, remote_name)
        if not remote_url:
            remote_urls = self.get_git_remote_urls(plugin_dir)
            remote_url = remote_urls[0] if remote_urls else ""

        return {
            "repo": self.normalize_git_repo_identity(remote_url),
            "branch": current_branch,
        }

    def detect_installed_registry_mismatch(self, plugin_key, plugin_dir):
        if not plugin_key or not os.path.isdir(os.path.join(plugin_dir, ".git")):
            return {}

        configured = self.registry_target_details(plugin_key)
        if configured is None:
            return {}

        installed = self.installed_git_target_details(plugin_dir)
        configured_repo = configured.get("repo", "")
        installed_repo = installed.get("repo", "")
        configured_branch = configured.get("branch", "")
        installed_branch = installed.get("branch", "")

        repo_mismatch = bool(configured_repo and installed_repo and configured_repo != installed_repo)
        branch_mismatch = bool(configured_branch and installed_branch and configured_branch != installed_branch)
        if not repo_mismatch and not branch_mismatch:
            return {}

        return {
            "registry_mismatch": True,
            "repo_mismatch": repo_mismatch,
            "branch_mismatch": branch_mismatch,
            "configured_repo": configured_repo,
            "configured_branch": configured_branch,
            "installed_repo": installed_repo,
            "installed_branch": installed_branch,
        }

    def installed_registry_mismatch(self, plugin_key, plugin_dir=None):
        details = self.installed_plugin_match_details.get(plugin_key, {})
        if details.get("registry_mismatch"):
            return True
        if details and "registry_mismatch" in details:
            return False
        if plugin_dir is None:
            return False
        return bool(self.detect_installed_registry_mismatch(plugin_key, plugin_dir).get("registry_mismatch"))

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

    def apply_update_times(self, update_times, include_local=False):
        self.update_times = update_times
        for key, data in self.plugin_data.items():
            if key == "Idle":
                continue
            if key in self.local_plugin_keys and not include_local:
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
        is_local = plugin_key in self.local_plugin_keys
        if not is_local and not self.is_better_update_time(updated_at, current_updated_at):
            return False
        if is_local and current_updated_at == updated_at:
            entry = self.get_registry_entry(plugin_key)
            data = self.plugin_data.get(plugin_key)
            data_updated_at = data[4] if isinstance(data, list) and len(data) >= 5 else ""
            entry_updated_at = entry.updated_at if entry is not None else ""
            if data_updated_at == updated_at and entry_updated_at == updated_at:
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

    def get_configured_git_remote_ref(self, plugin_key, plugin_dir):
        entry = self.get_registry_entry(plugin_key)
        if entry is None or not entry.branch:
            return ""

        remote_name = self.get_git_remote_name(plugin_dir, entry.branch)
        branch_ref = remote_name + "/" + entry.branch
        if self.git_ref_exists(plugin_dir, branch_ref):
            return branch_ref
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
        if self.installed_registry_mismatch(plugin_key, plugin_dir):
            return False

        if not remote_ref:
            remote_ref = self.get_configured_git_remote_ref(plugin_key, plugin_dir) or self.get_git_remote_ref(plugin_dir)

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
            self.apply_update_times(update_times, include_local=True)
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
                if is_git_repo:
                    mismatch = self.detect_installed_registry_mismatch(matched_key, plugin_path)
                    if mismatch:
                        detail.update(mismatch)
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
            if self.installed_registry_mismatch(plugin_key):
                update_status[plugin_key] = "mismatch"
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

    def apply_registry_sources(self, public_registry, local_registry):
        public_registry = dict(public_registry or {})
        local_registry = dict(local_registry or {})
        merged_registry = dict(public_registry)
        merged_registry.update(local_registry)
        local_plugin_keys = sorted(local_registry.keys())

        (
            self.plugin_data,
            self.plugin_platforms,
            self.registry_entries,
        ) = self.registry_service.normalize_registry(
            merged_registry,
            local_plugin_keys,
        )
        self.local_plugin_keys = local_plugin_keys
        if local_plugin_keys:
            Domoticz.Log(
                "Merged "
                + str(len(local_plugin_keys))
                + " local plugin registry entries."
            )

    def reapply_local_registry(self, local_registry):
        if self.public_registry_data is None:
            self.fetch_registry()
            return

        self.apply_registry_sources(
            self.public_registry_data,
            local_registry,
        )
        self.apply_update_times(self.update_times, include_local=False)
        self.add_self_to_registry()

    def fetch_registry(self):
        registry = self.fetch_remote_registry()
        if registry is None:
            registry = self.load_bundled_registry()

        local_registry = self.load_local_registry()
        registry_loaded = registry is not None or local_registry is not None

        if registry_loaded:
            if registry is not None:
                self.public_registry_data = dict(registry)
            selected_public_registry = (
                registry
                if registry is not None
                else self.public_registry_data
            )
            self.apply_registry_sources(
                selected_public_registry,
                local_registry,
            )
        elif self.plugin_data:
            Domoticz.Error("No plugin registry found. Keeping existing plugin registry.")
        else:
            self.plugin_data = {}
            self.registry_entries = {}
            self.plugin_platforms = {}
            self.local_plugin_keys = []
            Domoticz.Error("No plugin registry found. Plugins cannot be managed.")

        update_times = self.load_update_times()
        self.apply_update_times(update_times, include_local=False)
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
        self.finalizeSelfUpdateState()

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
            Domoticz.Device(Name="API Payload", Unit=1, TypeName="Text", DeviceID="PPM_API_PAYLOAD").Create()
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
        
        if action == "get_local_registry":
            document = self.local_registry_service.read_document()
            if document.writable:
                self.sendApiResponse({
                    "status": "success",
                    "action": action,
                    "entries": self.local_registry_service.entries_for_api(
                        document
                    ),
                    "revision": document.revision,
                    "path": document.path,
                    "read_only": False,
                })
            else:
                self.sendApiResponse({
                    "status": "error",
                    "action": action,
                    "code": document.error_code,
                    "message": document.message,
                    "revision": document.revision,
                    "path": document.path,
                    "read_only": True,
                })
        elif action in (
            "upsert_local_registry_entry",
            "delete_local_registry_entry",
        ):
            try:
                if action == "upsert_local_registry_entry":
                    entry = payload.get("entry")
                    document = self.local_registry_service.upsert(
                        payload.get("expected_revision"),
                        payload.get("original_key"),
                        entry,
                    )
                    plugin_key = str(
                        entry.get("key") if isinstance(entry, dict) else ""
                    ).strip()
                else:
                    plugin_key = str(payload.get("plugin_key") or "").strip()
                    document = self.local_registry_service.delete(
                        payload.get("expected_revision"),
                        plugin_key,
                    )

                try:
                    self.reapply_local_registry(document.entries)
                except Exception as error:
                    self.fetch_registry()
                    self.sendApiResponse({
                        "status": "error",
                        "action": action,
                        "code": "registry_reapply_failed",
                        "message": (
                            "registry_local.json was saved, but the registry "
                            "could not be reapplied: " + str(error)
                        ),
                        "reload_required": True,
                        "read_only": False,
                    })
                    return

                self.sendApiResponse({
                    "status": "success",
                    "action": action,
                    "plugin_key": plugin_key,
                    "revision": document.revision,
                })
            except LocalRegistryError as error:
                self.sendApiResponse({
                    "status": "error",
                    "action": action,
                    "code": error.code,
                    "message": error.message,
                    "field_errors": error.field_errors,
                    "reload_required": error.reload_required,
                    "read_only": error.read_only,
                })
        elif action == "list_plugins":
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
                "platforms": self.plugin_platforms,
                "self_update": self.getSelfUpdateState()
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
                "platforms": self.plugin_platforms,
                "self_update": self.getSelfUpdateState()
            })
        elif action == "self_update_status":
            self.sendApiResponse({
                "status": "success",
                "action": action,
                "self_update": self.getSelfUpdateState()
            })
        elif action == "install":
            plugin_key = payload.get("plugin_key")
            entry = self.get_registry_entry(plugin_key)
            if entry is not None:
                install_success, install_message = self.InstallPythonPlugin(entry.author, entry.repository, plugin_key, entry.branch)
                if install_success:
                    self.sendApiResponse({"status": "success", "action": action, "plugin_key": plugin_key})
                else:
                    self.sendApiResponse({"status": "error", "action": action, "plugin_key": plugin_key, "message": install_message or "Plugin install failed"})
            else:
                self.sendApiResponse({"status": "error", "action": action, "plugin_key": plugin_key, "message": "Plugin not found"})
        elif action == "update":
            plugin_key = payload.get("plugin_key")
            entry = self.get_registry_entry(plugin_key)
            if entry is not None:
                update_success, update_message = self.UpdatePythonPlugin(entry.author, entry.repository, plugin_key)
                if update_success:
                    response = {"status": "success", "action": action, "plugin_key": plugin_key}
                    if plugin_key == self.get_current_plugin_folder():
                        response["operation"] = "self_update"
                        response["self_update"] = self.getSelfUpdateState()
                    if update_message:
                        response["message"] = update_message
                    self.sendApiResponse(response)
                else:
                    self.sendApiResponse({"status": "error", "action": action, "plugin_key": plugin_key, "message": update_message or "Plugin update failed"})
            else:
                self.sendApiResponse({"status": "error", "action": action, "plugin_key": plugin_key, "message": "Plugin not found"})
        elif action == "restart_domoticz":
            restart_success, restart_message = self.restartDomoticz()
            if restart_success:
                self.sendApiResponse({
                    "status": "success",
                    "action": action,
                    "message": restart_message
                })
            else:
                self.sendApiResponse({"status": "error", "action": action, "message": restart_message})
        elif action == "remove":
            plugin_key = payload.get("plugin_key", "")
            remove_success, remove_message = self.removePlugin(plugin_key)
            if remove_success:
                self.sendApiResponse({"status": "success", "action": action, "plugin_key": plugin_key})
            else:
                self.sendApiResponse({"status": "error", "action": action, "plugin_key": plugin_key, "message": remove_message})
        else:
            self.sendApiResponse({"status": "error", "action": action, "message": f"Unknown action: {action}"})

    def getInstalledUpdateStatuses(self, installed_plugins, plugins_dir):
        return self.refreshInstalledUpdateStatuses(installed_plugins, plugins_dir)

    def getGitUpdateStatus(self, plugin_dir, plugin_key=None, fetch_first=True):
        return self.update_status_service.get_git_update_status(plugin_dir, plugin_key, fetch_first)

    def getSelfUpdateState(self):
        return self.get_host().read_self_update_state()

    def finalizeSelfUpdateState(self):
        host = self.get_host()
        state = host.read_self_update_state()
        if state.get("phase") != "applied_needs_reload":
            return state

        plugin_dir = host.plugin_home_folder()
        result = host.run_git(["git", "rev-parse", "--verify", "HEAD"], plugin_dir, timeout=15)
        current_commit = result.stdout.strip().splitlines()[0] if result is not None and result.returncode == 0 and result.stdout.strip() else ""
        target_commit = str(state.get("target_commit") or "").strip()

        if not current_commit:
            message = "PyPluginStore self-update finalization could not verify the current revision."
            updated_state = host.write_self_update_state(
                "stale_unknown",
                message,
                previous_state=state,
            )
            Domoticz.Error(message + " Detailed output: " + host.self_update_log_file())
            return updated_state

        if target_commit and current_commit and not (current_commit.startswith(target_commit) or target_commit.startswith(current_commit)):
            message = "PyPluginStore self-update finalization found " + current_commit + " instead of target " + target_commit + "."
            updated_state = host.write_self_update_state(
                "failed",
                message,
                previous_state=state,
                confirmed_commit=current_commit,
            )
            Domoticz.Error(message + " Detailed output: " + host.self_update_log_file())
            return updated_state

        message = "PyPluginStore self-update confirmed."
        updated_state = host.write_self_update_state(
            "confirmed",
            message,
            previous_state=state,
            confirmed_commit=current_commit,
        )
        Domoticz.Log(message + " Detailed output: " + host.self_update_log_file())
        return updated_state

    def logApiErrorResponse(self, response_dict):
        if not isinstance(response_dict, dict) or response_dict.get("status") != "error":
            return

        action = str(response_dict.get("action") or "").strip()
        plugin_key = str(response_dict.get("plugin_key") or "").strip()
        message = str(response_dict.get("message") or "Unknown error")

        context = "API " + action if action else "API request"
        if plugin_key:
            context += " for " + plugin_key
        Domoticz.Error(context + " failed: " + message)

    def sendApiResponse(self, response_dict):
        self.logApiErrorResponse(response_dict)
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
