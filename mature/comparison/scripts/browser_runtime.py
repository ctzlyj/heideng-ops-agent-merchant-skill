"""Thin transport to externally installed WebCLI; never installs or authenticates."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from merchant_runtime import RuntimeConfigurationError, merchant_path

class BrowserRuntimeError(RuntimeError):
    pass

def session_name(purpose):
    if purpose not in {"detail", "search", "preflight", "image"}:
        raise BrowserRuntimeError("INVALID_SESSION_PURPOSE")
    return "heideng-comparison-" + purpose + "-" + uuid.uuid4().hex

def choose_provider(providers, previous_error=None):
    if previous_error and previous_error not in {"BROWSER_BRIDGE_NOT_READY", "BROWSER_TOOL_UNAVAILABLE"}:
        raise BrowserRuntimeError(previous_error)
    capability = providers.get("webcli", {})
    if capability.get("connected") and capability.get("authorized") and {"detail", "search"} <= set(capability.get("capabilities", [])):
        return "webcli"
    return None

def webcli_command(environment):
    configured = environment.get("HEIDENG_WEBCLI_COMMAND_JSON")
    if configured:
        try:
            command = json.loads(configured)
        except ValueError as error:
            raise BrowserRuntimeError("EXTERNAL_WEBCLI_COMMAND_REQUIRED") from error
        if (not isinstance(command, list) or not command or
            any(not isinstance(value, str) or not value or "\x00" in value for value in command) or
            any(Path(value).name.lower() in {"o2", "o2.exe", "o2.cmd", "o2.ps1"} for value in command)):
            raise BrowserRuntimeError("EXTERNAL_WEBCLI_COMMAND_REQUIRED")
        return command
    executable = shutil.which("webcli", path=environment.get("PATH", ""))
    if not executable:
        raise BrowserRuntimeError("EXTERNAL_WEBCLI_NOT_INSTALLED")
    path = Path(executable)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        script = path.with_suffix(".ps1")
        powershell = shutil.which("powershell.exe", path=environment.get("PATH", ""))
        if not script.is_file() or not powershell:
            raise BrowserRuntimeError("EXTERNAL_WEBCLI_NATIVE_LAUNCHER_REQUIRED")
        return [powershell, "-NoProfile", "-NonInteractive", "-File", str(script)]
    return [str(path)]

class WebCliRunner:
    def __init__(self, command=None, timeout=150, environment=None):
        self.command = command
        self.timeout = max(float(timeout), 140)
        self.environment = dict(os.environ if environment is None else environment)

    def run(self, arguments, input_text=None):
        environment = self.environment.copy()
        environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", WEBCLI_WINDOW="background")
        environment.pop("NODE_OPTIONS", None)
        try:
            workspace = merchant_path(None, "browser-runtime", environment=environment)
            command = self.command or webcli_command(environment)
            # Apply the same command validation to an explicit constructor override.
            command = webcli_command({"HEIDENG_WEBCLI_COMMAND_JSON": json.dumps(command)})
            workspace.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run([*command, *arguments], input=input_text, capture_output=True, text=True,
                encoding="utf-8", errors="strict", timeout=self.timeout, env=environment, shell=False,
                cwd=workspace, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except RuntimeConfigurationError as error:
            raise BrowserRuntimeError(str(error)) from error
        except subprocess.TimeoutExpired as error:
            raise BrowserRuntimeError("BROWSER_RESULT_UNKNOWN") from error
        except (OSError, UnicodeError) as error:
            raise BrowserRuntimeError("BROWSER_TOOL_UNAVAILABLE") from error
        if completed.returncode != 0:
            raise BrowserRuntimeError("BROWSER_COMMAND_FAILED")
        return completed.stdout

    def json(self, arguments, input_text=None):
        text = self.run(arguments, input_text)
        if not text.strip():
            raise BrowserRuntimeError("BROWSER_RECEIPT_MISSING")
        try:
            value = json.loads(text)
        except ValueError as error:
            raise BrowserRuntimeError("BROWSER_JSON_INVALID") from error
        if isinstance(value, dict) and value.get("error"):
            raise BrowserRuntimeError("BROWSER_COMMAND_FAILED")
        return value

def invoke_webcli(arguments, timeout=150):
    arguments = list(arguments)
    if arguments and arguments[0] == "webcli":
        arguments = arguments[1:]
    return WebCliRunner(timeout=timeout).run(arguments)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["invoke", "session"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    parsed = parser.parse_args()
    try:
        if parsed.command == "session":
            if not parsed.arguments:
                raise BrowserRuntimeError("INVALID_SESSION_PURPOSE")
            print(session_name(parsed.arguments[0]))
        else:
            arguments = parsed.arguments[1:] if parsed.arguments[:1] == ["--"] else parsed.arguments
            print(invoke_webcli(arguments), end="")
        return 0
    except BrowserRuntimeError as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error), "platform_write_performed": False}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
