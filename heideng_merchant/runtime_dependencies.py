"""Standalone dependency installation only; no business flow or employee bootstrap."""
from __future__ import annotations
import json, os, re, subprocess, sys, venv
from pathlib import Path
from .safety import SafetyError, clean_environment, file_sha, read_json, safe_join
from .state import FileLock

REQUIREMENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*\])?(?:[<>=!~]=?[A-Za-z0-9.*]+(?:,[<>=!~]=?[A-Za-z0-9.*]+)*)?')

def runtime_python(state):
    directory = Path(state)/'runtime-venv'
    path = directory/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if directory.exists() and (not path.is_file() or not (directory/'pyvenv.cfg').is_file()):
        raise SafetyError('merchant-runtime-invalid')
    if path.is_file() and 'include-system-site-packages = false' not in (directory/'pyvenv.cfg').read_text(encoding='utf-8').lower():
        raise SafetyError('merchant-runtime-invalid')
    return path if path.is_file() else Path(sys.executable)

def requirements_for_sources(package_root, optional=None):
    if optional not in (None,"cutout","updates"):raise SafetyError("unknown-public-dependency-group")
    core = Path(package_root)/'requirements-updates.txt'
    update_requirements = core.read_text(encoding='utf-8').splitlines() if core.is_file() else []
    if optional == "updates": return update_requirements
    root = Path(package_root)/'mature' 
    requirements = set(update_requirements)
    for source in sorted(root.iterdir()) if root.is_dir() else []:
        metadata = read_json(source/'provenance.json', {})
        filenames=['requirements.txt']
        if optional=='cutout' and source.name=='materials':filenames.append('requirements-cutout.txt')
        for filename in filenames:
            record = metadata.get('files', {}).get(filename)
            if not record:
                continue
            path = safe_join(source,filename)
            if file_sha(path)!=record.get('sha256'):
                raise SafetyError('mature-requirements-modified')
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                value = line.strip()
                if not value or value.startswith('#'):
                    continue
                if not REQUIREMENT.fullmatch(value):
                    raise SafetyError('standard-public-package-requirement-required')
                requirements.add(value)
    return sorted(requirements)

def prepare_runtime(state, package_root, optional=None):
    state = Path(state).resolve()
    directory = safe_join(state,'runtime-venv')
    requirements = requirements_for_sources(package_root, optional)
    if not requirements:
        return {'status':'not-required','independent':True}
    with FileLock(state/'install.lock'):
        if not directory.is_dir():
            venv.EnvBuilder(with_pip=True, system_site_packages=False).create(directory)
        interpreter = runtime_python(state)
        environment = clean_environment(state/'runtime-home')
        environment.update(PIP_CONFIG_FILE=os.devnull,PIP_DISABLE_PIP_VERSION_CHECK='1',PYTHONIOENCODING='utf-8')
        command = [str(interpreter), '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install', '--index-url', 'https://pypi.org/simple', '--only-binary=:all:', '--no-cache-dir', '--retries', '0', '--timeout', '30', *requirements]
        try:
            result = subprocess.run(command, env=environment, timeout=900, capture_output=True, text=True, encoding='utf-8', errors='replace')
        except (OSError, subprocess.TimeoutExpired):
            raise SafetyError('merchant-public-dependency-install-unavailable') from None
        if result.returncode:
            raise SafetyError('merchant-public-dependency-install-failed')
        # Pip exit alone does not prove the isolated source dependencies import.
        names = sorted({re.split(r'[\[<>=!~]', value, 1)[0] for value in requirements})
        mapping = {'pillow':'PIL','openpyxl':'openpyxl','requests':'requests','numpy':'numpy','opencv-python':'cv2','pyinstaller':'PyInstaller','httpx':'httpx','rembg':'rembg','playwright':'playwright'}
        probe = "import sys,json,importlib,importlib.metadata as m;d=json.loads(sys.argv[1]);[m.version(x) for x in d['names']];[importlib.import_module(x) for x in d['imports']]"
        inputs = json.dumps({'names':names,'imports':[mapping[x.lower()] for x in names if x.lower() in mapping]})
        check = subprocess.run([str(interpreter), '-I', '-c', probe, inputs], env=environment, timeout=60, capture_output=True)
        if check.returncode:
            raise SafetyError('merchant-isolated-dependency-import-failed')
    return {'status':'prepared','interpreter':str(interpreter),'independent':True,'index':'https://pypi.org/simple','businessOrPaidCalls':False,'dependencyScope':'core-plus-cutout' if optional=='cutout' else 'core-only'}
