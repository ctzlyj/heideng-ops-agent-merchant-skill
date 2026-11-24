"""Standalone dependency installation only; no business flow or employee bootstrap."""
from __future__ import annotations
import json, os, re, subprocess, sys, venv
from pathlib import Path
from . import require_local
from .safety import SafetyError, clean_environment, file_sha, read_json, safe_join
from .state import FileLock

REQUIREMENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*\])?(?:[<>=!~]=?[A-Za-z0-9.*]+(?:,[<>=!~]=?[A-Za-z0-9.*]+)*)?')

# Reserved child exits used only before starting a new local browser job. The
# outer dispatcher can then release its install lease to repair this runtime.
BROWSER_REPAIR_EXITS = {73: 'isolated-python', 74: 'greenlet', 75: 'cryptography', 76: 'playwright', 77: 'playwright-driver'}


def connection_python_problem(state):
    """Check the interpreter actually running linker.py, including native extensions."""
    if Path(sys.prefix).resolve() != (Path(state) / 'runtime-venv').resolve():
        return 73
    import importlib
    for code, module, symbol in ((74, 'greenlet', 'greenlet'),
                                 (75, 'cryptography.hazmat.primitives.asymmetric.ed25519', 'Ed25519PublicKey'),
                                 (76, 'playwright.sync_api', 'sync_playwright')):
        try:
            getattr(importlib.import_module(module), symbol)
        except (ImportError, OSError, AttributeError):
            return code
    # Detect missing shipped driver files without starting a second driver process.
    # Use the installed wheel's manifest so a different distribution layout is
    # left to the actual launch check.
    from importlib.metadata import PackageNotFoundError, distribution
    try:
        package = distribution('playwright')
    except PackageNotFoundError:
        return 76
    for member in package.files or ():
        if member.as_posix() in ('playwright/driver/node', 'playwright/driver/node.exe', 'playwright/driver/package/cli.js'):
            if not package.locate_file(member).is_file():
                return 77
    return None

def bridge_python(inherited=None):
    """Resolve existing 3.12 before isolation, without running business or login."""
    import shutil
    env = os.environ if inherited is None else inherited
    explicit = env.get('HEIDENG_MERCHANT_PYTHON312') or env.get('JDO_PYTHON312')
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_file():raise SafetyError('merchant-python312-path-unavailable')
        return path  # Mature probe validates the actual interpreter version before using it.
    if sys.version_info[:2]==(3,12):return Path(sys.executable).resolve()
    candidates = [Path(sys.executable), Path(sys.base_prefix)/('python.exe' if os.name=='nt' else 'bin/python3.12')]
    if env.get('LOCALAPPDATA'):candidates.append(Path(env['LOCALAPPDATA'])/'Programs/Python/Python312/python.exe')
    found = shutil.which('python3.12', path=env.get('PATH'))
    if found:candidates.append(Path(found))
    if os.name == 'nt':
        try:
            proc = subprocess.run(['py','-3.12','-c','import sys;print(sys.executable)'], capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if proc.returncode == 0:candidates.append(Path(proc.stdout.strip()))
        except (OSError, subprocess.SubprocessError):pass
    for path in dict.fromkeys(candidates):
        if not path.is_file():continue
        try:
            proc = subprocess.run([str(path),'-I','-c','import sys;print(sys.version_info[:2] == (3,12))'], capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
            if proc.returncode == 0 and proc.stdout.strip() == 'True':return path.resolve()
        except (OSError, subprocess.SubprocessError):pass
    return None


def runtime_python(state):
    directory = Path(state)/'runtime-venv'
    path = directory/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    require_local(directory/'pyvenv.cfg',parents=True)
    require_local(path,parents=True)
    if directory.exists() and (not path.is_file() or not (directory/'pyvenv.cfg').is_file()):
        raise SafetyError('merchant-runtime-invalid')
    if path.is_file() and 'include-system-site-packages = false' not in (directory/'pyvenv.cfg').read_text(encoding='utf-8').lower():
        raise SafetyError('merchant-runtime-invalid')
    return path if path.is_file() else Path(sys.executable)

def requirements_for_sources(package_root, optional=None):
    if optional not in (None,"cutout","updates","connection-browser"):raise SafetyError("unknown-public-dependency-group")
    core = Path(package_root)/'requirements-updates.txt'
    update_requirements = core.read_text(encoding='utf-8').splitlines() if core.is_file() else []
    if optional == "updates": return update_requirements
    root = Path(package_root)/'mature' 
    requirements = set(update_requirements)
    for source in sorted(root.iterdir()) if root.is_dir() else []:
        if optional == 'connection-browser' and source.name != 'materials':
            continue
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
                if optional == 'connection-browser' and re.split(r'[\[<>=!~]', value, 1)[0].lower() != 'playwright':
                    continue
                requirements.add(value)
    if optional == 'connection-browser' and not any(x.lower().startswith('playwright') for x in requirements):
        raise SafetyError('merchant-browser-runtime-requirements-unavailable')
    return sorted(requirements)

def ensure_core(state, package_root):
    """Prepare missing existing core deps transparently, not each invocation or any model key."""
    state=Path(state).resolve();environment=clean_environment(state/'runtime-home')
    code='import httpx, requests, openpyxl, PIL, PyInstaller, playwright'
    def ready():
        try:
            result=subprocess.run([str(runtime_python(state)),'-I','-c',code],env=environment,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
            return result.returncode==0
        except (OSError,subprocess.SubprocessError):return False
    if ready():return {'status':'ready','prepared':False,'businessExecuted':False}
    prepare_runtime(state,package_root)
    if not ready():raise SafetyError('merchant-core-dependencies-unavailable')
    return {'status':'ready','prepared':True,'businessExecuted':False}


def reexec_update_runtime(state, argv=None):
    """Updates use the already prepared isolated cryptography; no package install or network."""
    if os.environ.get('HEIDENG_MERCHANT_UPDATE_RUNTIME')=='1':return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        return None
    except ImportError:
        interpreter=runtime_python(state)
        if interpreter.resolve()==Path(sys.executable).resolve():raise SafetyError('merchant-update-runtime-cryptography-required')
        env=clean_environment(Path(state)/'runtime-home',os.environ)
        env.update(HEIDENG_MERCHANT_UPDATE_RUNTIME='1',HEIDENG_MERCHANT_HOME=str(Path(state).resolve()))
        return subprocess.call([str(interpreter),'-I','-B',str(Path(__file__).resolve().parents[1]/'scripts/merchant.py'),*(sys.argv[1:] if argv is None else argv)],env=env)


def prepare_cutout_weights(state, package_root):
    """Prepare the reviewed Lite artifact through the mature offline entry; no shop or paid API."""
    state = Path(state).resolve()
    script = Path(package_root).resolve()/'mature/materials/scripts/jd_material_agent.py'
    environment = clean_environment(state/'runtime-home')
    environment['PYTHONIOENCODING'] = 'utf-8'
    command = [str(runtime_python(state)), '-I', '-B', str(script), 'prepare-cutout', '--download']
    try:
        result = subprocess.run(command, env=environment, timeout=900, capture_output=True, text=True, encoding='utf-8', errors='replace')
    except (OSError, subprocess.TimeoutExpired):
        raise SafetyError('merchant-cutout-weight-preparation-unavailable') from None
    if result.returncode:
        raise SafetyError('merchant-cutout-weight-preparation-failed')
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        raise SafetyError('merchant-cutout-weight-preparation-receipt-invalid') from None
    if payload.get('status') != 'prepared' or payload.get('model') != 'birefnet-general-lite':
        raise SafetyError('merchant-cutout-weight-preparation-receipt-invalid')
    return {'status':'prepared','model':payload['model'],'modelBytes':payload.get('modelBytes'),
            'sha256':payload.get('sha256'),'businessOrPaidCalls':False,'downloadDuringMerchantWrites':False}


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
        if optional == 'connection-browser':
            # Another host task may have completed the repair while this caller
            # was releasing its read lease. Verify the actual venv before pip.
            probe = ('import sys; sys.path.insert(0, sys.argv[1]); '
                     'from heideng_merchant.runtime_dependencies import connection_python_problem; '
                     'sys.exit(connection_python_problem(sys.argv[2]) or 0)')
            ready = subprocess.run([str(interpreter), '-I', '-B', '-c', probe, str(Path(package_root).resolve()), str(state)],
                                   env=environment, timeout=30, capture_output=True)
            if ready.returncode == 0:
                return {'status':'ready','interpreter':str(interpreter),'dependencyScope':optional,'businessOrPaidCalls':False}
        repair = ['--force-reinstall'] if optional == 'connection-browser' else []
        command = [str(interpreter), '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install', '--index-url', 'https://pypi.org/simple', '--only-binary=:all:', '--no-cache-dir', '--retries', '0', '--timeout', '30', *repair, *requirements]
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
    return {'status':'prepared','interpreter':str(interpreter),'independent':True,'index':'https://pypi.org/simple','businessOrPaidCalls':False,'dependencyScope':{'cutout':'core-plus-cutout','connection-browser':'connection-browser'}.get(optional,'core-only')}
