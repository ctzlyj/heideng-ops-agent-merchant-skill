"""Thin source dispatch. Mature Skills own business flow, identity and receipts."""
from __future__ import annotations
import hashlib, json, os, platform, socket, subprocess, sys, shutil, re
from pathlib import Path
from .safety import SafetyError, clean_environment, file_sha, read_json, safe_join, is_linked
from .state import FileLock

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ROUTES = {
    'connection': ('connection', 'scripts/linker.py'),
    'materials': ('materials', 'scripts/jd_material_agent.py'),
    'short-title': ('materials', 'scripts/jd_material_agent.py'),
    'listing': ('listing', 'scripts/jd_product_pipeline.py'),
    'photo-listing': ('listing', 'scripts/photo_listing.py'),
    'link-replica': ('listing', 'scripts/hot_replica_publish.py'),
    'shop-copy': ('listing', 'scripts/jd_product_pipeline.py'),
    'video-handoff': ('video', 'scripts/local_handoff.py'),
    'matrix-listing': ('listing', 'scripts/matrix_listing.py'),
    'images': ('listing', 'scripts/image_patch_update.py'),
    'image-refresh': ('refresh', 'scripts/new_job.py'),
    'collection': ('collection', 'scripts/prepare_batch.py'),
    'comparison': ('comparison', 'scripts/same_product_market.py'),
    'price-update': ('comparison', 'scripts/jingmai_api.py'),
    'diagnosis': ('diagnosis', 'scripts/cli.cjs'),
    'video-binding': ('listing', 'scripts/photo_video.py'),
}

class MatureSourceUnavailable(SafetyError):
    def __init__(self, capability):
        self.capability = capability
        super().__init__('mature-source-unavailable')


def node_for_merchant(environment):
    """A host can prepend an older bundled Node while a supported installation is on PATH."""
    seen = set()
    for directory in environment.get('PATH', '').split(os.pathsep):
        if not directory or not Path(directory).is_absolute():
            continue
        candidate = shutil.which('node', path=directory)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            probe = subprocess.run([candidate, '--version'], env=environment, capture_output=True,
                                   text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        match = re.fullmatch(r'v(\d+)\.\d+\.\d+\s*', probe.stdout)
        if probe.returncode == 0 and match and int(match.group(1)) >= 24:
            return candidate
    raise SafetyError('node-24-or-newer-required-for-mature-diagnosis')

def allowed_host(host):
    name = str(host or '').lower().rstrip('.')
    return not (name.endswith(('.local', '.internal')) or name in {'o2.jd.com', 'joyspace.jd.com', 'llm-gw.jd.com', 'oxygen.jd.com', 'joyagent.jd.com'})

def checked_command(command, system=None):
    first = command[0] if isinstance(command, (list, tuple)) and command else command
    name = str(first).replace('\\', '/').rsplit('/', 1)[-1].lower()
    if name.endswith(('.exe', '.cmd', '.bat')):
        name = name.rsplit('.', 1)[0]
    if name in {'o2', 'oxygen', 'lingjing'}:
        raise SafetyError('company-tool-forbidden')

def install_network_guard():
    original = socket.getaddrinfo
    def checked(host, *args, **kwargs):
        if not allowed_host(host):
            raise SafetyError('company-channel-forbidden')
        return original(host, *args, **kwargs)
    socket.getaddrinfo = checked
    original_popen = subprocess.Popen
    class CheckedPopen(original_popen):
        def __init__(self, args, *positional, **keyword):
            checked_command(args)
            super().__init__(args, *positional, **keyword)
    subprocess.Popen = CheckedPopen

def child_environment(state, inherited=None):
    state = Path(state).resolve()
    original = os.environ if inherited is None else inherited
    result = clean_environment(state/'runtime-home', original)
    cli_home = state/'cli-home'/'.jdo-cli'
    result.update(HEIDENG_MERCHANT_HOME=str(state), JDO_HOME=str(cli_home), JDO_CLI_HOME=str(cli_home), JINGMAI_LINKER_HOME=str(state/'linker'),
                  REMBG_HOME=str(state/'model-cache'/'rembg'), U2NET_HOME=str(state/'model-cache'/'u2net'),
                  JDO_ENV='prod', JINGMAI_LINKER_PORT=str(18000 + int(hashlib.sha256(str(state).encode()).hexdigest()[:6], 16) % 20000),
                  PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', HEIDENG_MERCHANT_PACKAGE=str(PACKAGE_ROOT))
    # Interpreter discovery uses the real machine before HOME is isolated; never copies credentials.
    from .runtime_dependencies import bridge_python
    interpreter = bridge_python(original)
    if interpreter:result['JDO_PYTHON312'] = str(interpreter)
    # Only merchant-namespaced inputs cross this boundary; no old LTS4AI or company keys.
    for name in ('HEIDENG_MERCHANT_LTS4AI_API_KEY', 'HEIDENG_MERCHANT_WEBCLI_BIN', 'HEIDENG_MERCHANT_BROWSER_CONFIG'):
        if name in original:
            result[name] = original[name]
    if original.get('HEIDENG_MERCHANT_BETA_IMAGE_BLOCKED') in ('quota-exhausted', 'unbounded-key'):
        result['HEIDENG_MERCHANT_BETA_IMAGE_BLOCKED'] = original['HEIDENG_MERCHANT_BETA_IMAGE_BLOCKED']
    if original.get('HEIDENG_MERCHANT_WEBCLI_COMMAND'):
        # An argv-prefix configuration, not an O2 alias or a credential.
        prefix = json.loads(original['HEIDENG_MERCHANT_WEBCLI_COMMAND'])
        if not isinstance(prefix, list) or not prefix or not all(isinstance(x, str) and x for x in prefix):
            raise SafetyError('invalid-merchant-webcli-command')
        checked_command(prefix)
        result['HEIDENG_WEBCLI_COMMAND_JSON'] = json.dumps(prefix)
    if original.get('HEIDENG_MERCHANT_SHOP_CDP'):
        from urllib.parse import urlsplit
        endpoint=original['HEIDENG_MERCHANT_SHOP_CDP'];parsed=urlsplit(endpoint)
        if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or not parsed.port or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise SafetyError('merchant-cdp-endpoint-required')
        result['HEIDENG_MERCHANT_SHOP_CDP']=endpoint
        result['SHOP_CDP']=endpoint
    return result


def windows_known_folder(folder_id):
    """Read a folder for the signed-in desktop user before HOME is isolated."""
    if os.name != 'nt':
        return None
    import ctypes
    buffer = ctypes.create_unicode_buffer(260)
    try:
        result = ctypes.windll.shell32.SHGetFolderPathW(None, folder_id, None, 0, buffer)
    except (OSError, AttributeError):
        return None
    if result == 0 and buffer.value:
        return Path(buffer.value)
    return None

def merchant_profile_directory(value):
    """Optional browser metadata, never cookies: only this merchant's owned directory."""
    home=os.environ.get('HEIDENG_MERCHANT_HOME')
    if not home or not isinstance(value,(str,Path)) or not str(value):return None
    root=Path(home).resolve()/'browser-profiles';path=Path(value)
    if not path.is_absolute() or path == root or not path.is_relative_to(root):return None
    try:path=safe_join(root,path.relative_to(root).as_posix())
    except SafetyError:return None
    if not path.is_dir():return None
    return path

def unique_browser_directory(entries, directory, identity):
    if not directory:return False
    for item in entries.values():
        if not isinstance(item,dict) or not item.get('browserProfileDir'):continue
        if Path(item['browserProfileDir']).resolve() == directory and any(
                str(item.get(k) or '') != str(identity.get(k) or '') for k in ('shopId','venderId','shopName')):
            return False
    return True

def registered_browser_profile(profile, identity):
    home=os.environ.get('HEIDENG_MERCHANT_HOME')
    if not home or not profile or not isinstance(identity,dict):return None
    registry=read_json(Path(home)/'linker/shops.json',{})
    if not isinstance(registry,dict) or not isinstance(registry.get('profiles',{}),dict):return None
    entry=registry.get('profiles',{}).get(profile,{})
    if not isinstance(entry,dict):return None
    if not str(identity.get('venderId') or '') or str(entry.get('venderId'))!=str(identity.get('venderId')):return None
    if entry.get('shopName')!=identity.get('shopName'):return None
    if identity.get('shopId') and str(entry.get('shopId'))!=str(identity.get('shopId')):return None
    directory = merchant_profile_directory(entry.get('browserProfileDir'))
    return directory if unique_browser_directory(registry['profiles'],directory,entry) else None

def browser_profile_channel(profile_dir):
    home = os.environ.get('HEIDENG_MERCHANT_HOME')
    path = merchant_profile_directory(profile_dir)
    if home and path:
        registry = read_json(Path(home)/'linker/shops.json', {})
        for entry in registry.get('profiles', {}).values():
            if not isinstance(entry, dict) or not entry.get('browserProfileDir'):continue
            if Path(entry['browserProfileDir']).resolve() != path:continue
            channel = entry.get('browserChannel')
            if channel in ('chrome', 'msedge', 'chromium'):return None if channel=='chromium' else channel
        # A legacy Edge profile has this metadata; do not try Chrome on it.
        if (path/'Last Version').is_file():
            version = (path/'Last Version').read_text(encoding='utf-8', errors='replace')
            if 'edge' in version.casefold():return 'msedge'
    return 'chrome'  # Mature default for legacy Chrome metadata; never opens a work profile.


def source_path(capability, entry=None, package_root=None):
    return _source_path(capability, entry, package_root, {})


def _source_path(capability, entry, package_root, checked):
    if capability not in ROUTES:
        raise SafetyError('unknown-mature-capability')
    source_name, default_entry = ROUTES[capability]
    root = Path(package_root or PACKAGE_ROOT)/'mature'/source_name
    provenance = checked.get(root) or read_json(root/'provenance.json')
    if not isinstance(provenance, dict):
        raise MatureSourceUnavailable(capability)
    path_name = entry or default_entry
    files = provenance.get('files')
    if not isinstance(files, dict) or path_name not in provenance.get('entrypoints', []):
        raise SafetyError('unregistered-mature-entrypoint')
    if root not in checked:
        for name, record in files.items():
            path = safe_join(root, name)
            if is_linked(path) or not path.is_file() or file_sha(path) != record.get('sha256'):
                raise SafetyError('mature-source-modified')
        actual = {x.relative_to(root).as_posix() for x in root.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.suffix not in ('.pyc', '.pyo')}
        if actual != set(files) | {'provenance.json'}:
            raise SafetyError('unregistered-mature-source-file')
        checked[root] = provenance
    return safe_join(root, path_name), provenance

def capability_contract(capability, registry):
    key = {'photo-listing':'listing','matrix-listing':'listing','price-update':'comparison','short-title':'materials','link-replica':'listing','shop-copy':'listing','video-handoff':'video','video-binding':'video','image-refresh':'images'}.get(capability, capability)
    row = next((x for x in registry.get('capabilities', []) if x.get('id')==key), {})
    return {'status':row.get('migration','verification-required'), 'knownBlockers':row.get('knownBlockers',[])}

def status(package_root=None):
    from .image_models import MODELS, TIER_CREDITS
    rows, checked, registry = [], {}, None
    for capability in ROUTES:
        try:
            path, source = _source_path(capability, None, package_root, checked)
            if registry is None:
                registry = read_json(Path(package_root or PACKAGE_ROOT)/'registry.json', {})
            rows.append({'capability': capability, 'source': source['repository'], 'upstreamVersion': source['upstreamVersion'], 'upstreamCommit': source['upstreamCommit'], 'entry': path.relative_to(Path(package_root or PACKAGE_ROOT)).as_posix(), 'matureImplementationReused': True, 'merchantAdaptation': capability_contract(capability, registry), 'liveMerchantVerified': False})
        except MatureSourceUnavailable:
            rows.append({'capability': capability, 'matureImplementationReused': False, 'status': 'blocked-source-or-distribution-permission', 'liveMerchantVerified': False})
        except SafetyError as error:
            rows.append({'capability': capability, 'matureImplementationReused': False, 'status': str(error), 'liveMerchantVerified': False})
    return {'architecture': 'mature-skill-dispatch', 'capabilities': rows, 'image': {'provider': 'lts4ai', 'endpoint': 'https://api.lts4ai.com/v1', 'model': 'gpt-image-2.5', 'models':list(MODELS), 'creditsByQuality':TIER_CREDITS, 'paidLiveVerified': False}, 'videoGeneration': {'status': 'awaiting-external-provider', 'companyFallback': False}, 'merchantLiveActionsExecuted': False, 'additionalVerificationRequested': False}

def collection_environment(state, arguments, environment):
    def option(name):
        for index,value in enumerate(arguments):
            if value.startswith(name+'='):return value.split('=',1)[1]
            if value==name and index+1<len(arguments):return arguments[index+1]
        return None
    supplied_root=option('--root') or os.environ.get('HEIDENG_COLLECTION_ROOT')
    if not supplied_root:
        if '--help' in arguments:return environment
        raise SafetyError('collection-output-root-required')
    output=Path(supplied_root).expanduser().resolve()
    base=Path(state).resolve()/'mature/collection/batches'
    supplied_stage=option('--state-dir') or os.environ.get('HEIDENG_COLLECTION_STATE_DIR')
    stage=Path(supplied_stage).expanduser().resolve() if supplied_stage else base/hashlib.sha256(str(output).encode('utf-8')).hexdigest()
    if stage==base or not stage.is_relative_to(base):raise SafetyError('collection-state-outside-merchant-home')
    environment.update(HEIDENG_COLLECTION_ROOT=str(output),HEIDENG_COLLECTION_STATE_DIR=str(stage),JD_COLLECTOR_ROOT=str(output),JD_COLLECTOR_STATE_DIR=str(stage),JD_BATCH_STATE_DIR=str(stage))
    from .runtime_dependencies import runtime_python
    environment['HEIDENG_COLLECTION_PYTHON']=str(runtime_python(state))
    # Only task-explicit merchant controls cross the boundary; old employee/global flags do not.
    controls={'HEIDENG_COLLECTION_MAX_REQUESTS':'JD_BATCH_MAX_REQUESTS','HEIDENG_COLLECTION_INTERVAL_MS':'JD_BATCH_INTERVAL_MS','HEIDENG_COLLECTION_ROUND_COOLDOWN_SECONDS':'JD_BATCH_ROUND_COOLDOWN_SECONDS','HEIDENG_COLLECTION_NAV_MIN_MS':'JD_COLLECTOR_NAV_MIN_MS','HEIDENG_COLLECTION_STAGE_EVERY':'JD_BATCH_STAGE_EVERY'}
    for original,target in controls.items():
        value=os.environ.get(original)
        if value is not None:
            if not re.fullmatch(r'[0-9]+',value):raise SafetyError('invalid-collection-runtime-control')
            environment[original]=value;environment[target]=value
    fallback=os.environ.get('HEIDENG_COLLECTION_ORIGINAL_PRICE_FALLBACK')
    if fallback is not None:
        if fallback not in ('0','1'):raise SafetyError('invalid-collection-fallback-choice')
        environment['HEIDENG_COLLECTION_ORIGINAL_PRICE_FALLBACK']=fallback
        environment['JD_BATCH_ORIGINAL_PRICE_FALLBACK']=fallback
    for name in ('HEIDENG_COLLECTION_BROWSER_TRANSPORT',):
        if os.environ.get(name):environment[name]=os.environ[name]
    return environment

def host_browser_controller_command(state):
    """Ready-made controller argv; host only repeats the original bridge command."""
    from .runtime_dependencies import runtime_python
    return [str(runtime_python(state)),'-I','-B',str(PACKAGE_ROOT/'scripts/host_connection_controller.py')]


def preflight(capability, arguments, *, state, entry=None, package_root=None):
    """Static dependencies/CLI bridge check before requesting a merchant key."""
    root = Path(package_root or PACKAGE_ROOT);path,_ = source_path(capability,entry,root)
    environment = child_environment(state);environment['HEIDENG_MERCHANT_PACKAGE']=str(root)
    environment.pop('HEIDENG_MERCHANT_LTS4AI_API_KEY',None)
    from .official import OfficialClient
    official=OfficialClient(state)
    if official.ready():environment['JDO_CLI_PATH']=str(official.executable())
    from .runtime_dependencies import runtime_python
    args=list(arguments)
    if args[:1]==['--']:args=args[1:]
    command=[str(runtime_python(state)),'-I','-B',str(root/'scripts/runtime_preflight.py'),capability,str(path),*args]
    result=subprocess.run(command,env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=150)
    if result.returncode:
        # Child's static diagnostics only; never propagate arbitrary stderr/env to the host.
        try:detail=json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError,IndexError):detail={}
        raise SafetyError('merchant-runtime-preflight-failed:'+str(detail.get('reason','check-interpreter-dependencies-and-command-arguments'))[:400])
    return {'status':'ready','businessExecuted':False,'paidCalls':False}


def run(capability, arguments, *, state, entry=None, package_root=None):
    from .runtime_dependencies import BROWSER_REPAIR_EXITS, prepare_runtime
    result = _run_with_lease(capability, arguments, state=state, entry=entry, package_root=package_root)
    if capability != 'connection' or entry not in (None, ROUTES['connection'][1]) or result not in BROWSER_REPAIR_EXITS:
        return result
    component = BROWSER_REPAIR_EXITS[result]
    try:
        prepare_runtime(state, package_root or PACKAGE_ROOT, optional='connection-browser')
    except (SafetyError, OSError, subprocess.SubprocessError) as error:
        if isinstance(error, SafetyError) and str(error) == 'resource-busy':
            raise SafetyError(f'浏览器隔离依赖 {component} 需要准备，商家安装目录正由其他任务占用；保留原连接后继续。') from None
        raise SafetyError(f'浏览器隔离依赖 {component} 未就绪，标准运行环境修复未完成。'
                          '请核对本机 Python、依赖下载网络和商家状态目录的写入权限。') from None
    result = _run_with_lease(capability, arguments, state=state, entry=entry, package_root=package_root)
    if result in BROWSER_REPAIR_EXITS:
        raise SafetyError(f'浏览器隔离运行环境修复后仍无法加载 {BROWSER_REPAIR_EXITS[result]}，请检查该解释器与本机架构。')
    return result


from .runtime_dependencies import ensure_core
from .official import OfficialClient


def _run_with_lease(capability, arguments, *, state, entry=None, package_root=None):
    root = Path(package_root or PACKAGE_ROOT)
    path, _ = source_path(capability, entry, root)
    state = Path(state).resolve()
    environment = child_environment(state)
    if capability == 'connection' and path.name == 'linker.py':
        environment['HEIDENG_MANAGED_CONNECTION_RUNTIME'] = '1'
    if capability == 'connection' and os.name == 'nt':
        for name, folder_id in (('HEIDENG_HOST_DESKTOP', 0x0010), ('HEIDENG_HOST_LOCAL_APPDATA', 0x001C)):
            folder = windows_known_folder(folder_id)
            if folder is not None:
                environment[name] = str(folder)
    environment["HEIDENG_MERCHANT_PACKAGE"] = str(root)
    from .official import OfficialClient
    official = OfficialClient(state)
    if official.ready():
        environment['JDO_CLI_PATH'] = str(official.executable())
    work = state/'work'/ROUTES[capability][0]
    work.mkdir(parents=True, exist_ok=True)
    arguments = list(arguments)
    if arguments[:1] == ['--']:
        arguments = arguments[1:]
    if capability == 'shop-copy' and path.name == 'jd_product_pipeline.py':
        arguments = ['shop-copy', *arguments]
    if capability=='collection':
        source_path('diagnosis',package_root=root)
        source_path('listing',package_root=root)
        environment=collection_environment(state,arguments,environment)
    if path.suffix=='.py' and capability!='connection' and not any(x in ('--help','-h','help') for x in arguments):
        from .runtime_dependencies import ensure_core
        ensure_core(state,root)
    with FileLock(state/'install.lock',shared=True):
        if path.suffix == '.py':
            from .runtime_dependencies import runtime_python
            command = [str(runtime_python(state)), '-I', '-B', str(root/'scripts/mature_entry.py'), str(path), *arguments]
        elif path.suffix == '.cjs' or (capability=='diagnosis' and path.suffix=='.js') or (capability=='collection' and path.suffix=='.mjs'):
            if capability=='collection':source_path('diagnosis',package_root=root)
            node = node_for_merchant(environment)
            if path.suffix=='.cjs' and official.ready() and arguments[:1] not in (['--help'],['help']) and '--dry-run' not in arguments:
                checked_command([str(official.executable())])
            command=[node,str(path),*arguments]
        else:
            raise SafetyError('javascript-entry-requires-reviewed-browser-transport')
        # No retry of a failed/unknown mature operation, no worker/state machine added here.
        import uuid
        from . import update_client
        task_id='run-'+uuid.uuid4().hex
        lease_id=update_client.usage(state,'begin',task_id,components=[ROUTES[capability][0]])
        update_client.usage(state,'heartbeat',task_id)
        try:
            result = subprocess.run(command, cwd=work, env=environment)
        finally:
            if lease_id:update_client.usage(state,'end',task_id)
    return result.returncode
