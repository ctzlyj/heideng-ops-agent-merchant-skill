"""Merchant-only filesystem/executable boundaries; the parent supplies sanitized env."""
from __future__ import annotations
import os
from pathlib import Path
import shutil

class RuntimeConfigurationError(ValueError):
    pass

def merchant_home(environment=None):
    environment = os.environ if environment is None else environment
    value = environment.get("HEIDENG_MERCHANT_HOME", "")
    if not value:
        raise RuntimeConfigurationError("HEIDENG_MERCHANT_HOME_REQUIRED")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimeConfigurationError("HEIDENG_MERCHANT_HOME_MUST_BE_ABSOLUTE")
    return path.resolve()

def merchant_path(value=None, *parts, environment=None):
    home = merchant_home(environment)
    path = (Path(value) if value is not None else home.joinpath("comparison", *parts)).resolve()
    if not path.is_relative_to(home):
        raise RuntimeConfigurationError("STATE_MUST_BE_INSIDE_MERCHANT_HOME")
    package = Path(__file__).resolve().parents[1]
    if path == package or package in path.parents:
        raise RuntimeConfigurationError("STATE_MUST_BE_OUTSIDE_INSTALLATION")
    return path

def official_executable(value=None):
    merchant_home()
    if not os.environ.get("JDO_HOME"):
        raise RuntimeConfigurationError("MERCHANT_JDO_HOME_REQUIRED")
    merchant_path(os.environ["JDO_HOME"])
    configured = value or os.environ.get("JDO_CLI_PATH")
    executable = configured or shutil.which("jdo-cli")
    if not executable or not Path(executable).is_file():
        raise RuntimeConfigurationError("EXTERNAL_JDO_CLI_REQUIRED")
    return str(Path(executable).resolve())
