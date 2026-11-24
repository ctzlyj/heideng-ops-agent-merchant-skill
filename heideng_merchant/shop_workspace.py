"""Verify a merchant-owned workspace page and attach its browser to an already verified CLI shop."""
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from .host_connection_controller import CHANNELS, WORKSPACE_URL, BrowserStartError, HostConnectionController
from .mature_runtime import merchant_profile_directory, unique_browser_directory
from .safety import SafetyError, atomic_json, read_json, safe_join
from .state import FileLock, merchant_home, process_alive


MARKER = '.heideng-workspace.json'
STORE = ('shopName', 'shopId', 'venderId')


def store_fields(identity):
    return {key:str(identity.get(key) or '') for key in STORE}


def verification(profile, identity, directory, channel, method):
    return {**store_fields(identity), 'profile':profile, 'browserProfileDir':str(directory),
            'browserChannel':channel, 'method':method, 'checkedAt':int(time.time())}


def recorded_workspace(entry, profile, identity, directory, *, allow_candidate=False):
    record = entry.get('browserVerification')
    methods = ('workspace-page', 'oauth-task-profile') if allow_candidate else ('workspace-page',)
    if (not directory or not isinstance(record,dict) or record.get('method') not in methods
            or not record.get('checkedAt') or record.get('profile') != profile or store_fields(record) != store_fields(identity)
            or record.get('browserChannel') not in CHANNELS or record['browserChannel'] != entry.get('browserChannel')
            or record.get('browserProfileDir') != str(directory)):
        return False
    return read_json(safe_join(directory,MARKER)) == record


def compare_page(observed, expected):
    if not observed.get('shopName'):
        return 'waiting-login'
    if observed['shopName'] != expected['shopName'] or any(
            observed.get(k) and str(observed[k]) != str(expected[k]) for k in ('shopId','venderId')):
        return 'mismatch'
    return 'verified' if observed.get('shopId') else 'waiting-shop-id'


def candidate_matches(directory, profile, identity, channel):
    if not directory:
        return False
    record = read_json(safe_join(directory,MARKER),{})
    return (isinstance(record,dict) and record.get('status') != 'mismatch'
            and (not record or record.get('profile') == profile and store_fields(record) == store_fields(identity)
                 and record.get('browserChannel') == channel))


def legacy_candidate(root, entries, identity, entry, directory):
    """Only a connector-owned session for this exact store can restore an old browser binding."""
    if not directory or entry.get('browserChannel') not in CHANNELS:
        return False
    for value in (identity['venderId'],identity['shopName']):
        key = hashlib.sha256(str(value).encode()).hexdigest()[:16]
        saved = read_json(safe_join(root,f'browser-controller/{key}/session.json'),{}) or {}
        shop = saved.get('shopIdentity') or {}
        if (saved.get('profileDir') != str(directory) or saved.get('browserChannel') != entry['browserChannel']
                or shop.get('shopName') != identity['shopName']
                or (shop.get('venderId') and str(shop['venderId']) != str(identity['venderId']))):
            continue
        if not shop.get('shopId') and any(other.get('shopName') == identity['shopName']
                and store_fields(other) != store_fields(identity) for other in entries.values()):
            continue
        if not shop.get('shopId') or str(shop['shopId']) == str(identity['shopId']):
            return True
    return False


def signal_login(job):
    if not re.fullmatch(r'web-[0-9a-f]{16}',job or ''):
        return {'ok':False,'status':'job-lost'}
    path = safe_join(merchant_home(),f'browser-controller/workspace-jobs/{job}.json')
    current = read_json(path,{})
    if (current.get('jobId') != job or current.get('status') != 'waiting-login'
            or current.get('expiresAt',0) <= time.time() or process_alive(current.get('pid')) is not True):
        return {'ok':False,'status':'job-lost','message':'该网页核店任务已结束，请沿原店的网页入口恢复。'}
    path.with_suffix('.login-completed').touch(exist_ok=True)
    return {'ok':True,'status':'workspace_check_requested','jobId':job}


def ensure_workspace(sl, profile, shop, channel, timeout, progress, *, prepare=None):
    if not 1 <= timeout <= 3600 or channel is not None and channel not in CHANNELS:
        raise ValueError('网页检查需要有效的浏览器通道和等待时长。')
    target = sl.exact_authorized_shop(profile,shop)
    if not target.get('ok'):
        return target
    if prepare:
        prepare()
    identity = target['identity']
    key = json.dumps([profile,identity['shopId'],identity['venderId']],ensure_ascii=True)
    root = merchant_home()
    lock = safe_join(root,'browser-controller/workspace-'+hashlib.sha256(key.encode()).hexdigest()[:24]+'.lock')
    try:
        with FileLock(lock, timeout=0):
            return _visit(sl,root,profile,shop,identity,key,channel,timeout,progress)
    except BrowserStartError as exc:
        return {'ok':False,'status':'blocked','officialReady':True,'webLoginVerified':False,'errorKind':exc.kind,'message':exc.hint}
    except SafetyError as exc:
        if str(exc) != 'resource-busy':
            raise
        return {'ok':False,'status':'busy','officialReady':True,'webLoginVerified':False,
                'message':'原店网页任务正在使用自己的浏览器，请沿该任务继续。'}


def _visit(sl,root,profile,shop,identity,key,requested,timeout,progress):
    entries = sl.load_registry()['profiles']
    entry = entries.get(profile) or {}
    original = merchant_profile_directory(entry.get('browserProfileDir'))
    if original and (not unique_browser_directory(entries,original,identity)
                     or not candidate_matches(original,profile,identity,entry.get('browserChannel'))):
        original = None
    # Reuse a previously verified same-store session; an arbitrary registry directory cannot select a browser.
    previous = original and (recorded_workspace(entry,profile,identity,original,allow_candidate=True)
                             or (not entry.get('browserVerification') and legacy_candidate(root,entries,identity,entry,original)))
    channel = requested or (entry.get('browserChannel') if previous else None)
    controller = HostConnectionController(state=root,shop_identity=store_fields(identity),
                                           workspace_key='workspace:'+key+':'+str(channel or 'default'))
    if previous and channel == entry['browserChannel']:
        controller._state = {'contextId':'workspace-'+uuid.uuid4().hex, 'browserChannel':channel,
                             'profileDir':str(original), 'shopIdentity':store_fields(identity)}
    else:
        stored = controller._load() or {}
        candidate = merchant_profile_directory(stored.get('profileDir'))
        if stored and (not candidate_matches(candidate,profile,identity,stored.get('browserChannel'))
                       or not unique_browser_directory(entries,candidate,identity)):
            controller._state = {}
    job = 'web-'+uuid.uuid4().hex[:16]
    job_path = safe_join(root,f'browser-controller/workspace-jobs/{job}.json')
    signal = job_path.with_suffix('.login-completed')
    deadline = time.monotonic()+timeout
    result = {'ok':False,'status':'waiting-login','officialReady':True,'webLoginVerified':False,
              'jobId':job,'profile':profile,'identity':store_fields(identity)}
    try:
        controller._launch(channel)
        try:
            controller.page.goto(WORKSPACE_URL,wait_until='domcontentloaded',timeout=20000)
        except Exception:
            return {**result,'status':'workspace-navigation-unconfirmed','browserChannel':controller.channel}
        controller.page.bring_to_front()
        atomic_json(job_path,{**result,'pid':os.getpid(),'expiresAt':time.time()+timeout})
        progress({**result,'browserChannel':controller.channel,'browserSelectionReason':controller.channel_reason})
        checked_workspace = False
        name_seen_at = None
        while time.monotonic() < deadline:
            if not checked_workspace and signal.exists():
                checked_workspace = True
                controller.check_workspace_after_login()
            observation = controller._observe()
            observed = (observation.get('identity') or {}) if observation.get('loggedIn') else {}
            status = compare_page(observed,identity)
            result.update(status=status,browserChannel=controller.channel,browserSelectionReason=controller.channel_reason)
            if status == 'mismatch':
                result['observedIdentity'] = observed
                break
            if status == 'waiting-shop-id':
                if name_seen_at is None:
                    name_seen_at = time.monotonic()
                    progress({**result,'message':'工作台已显示店名，正在核对同页店铺 ID。'})
                elif time.monotonic()-name_seen_at >= 10:
                    break
            else:
                name_seen_at = None
            if status == 'verified':
                final = sl.exact_authorized_shop(profile,shop)
                if not final.get('ok') or store_fields(final['identity']) != store_fields(identity):
                    return {**result,'status':'cli-identity-changed'}
                directory = merchant_profile_directory(controller.profile)
                with FileLock(root/'browser-controller/workspace-bindings.lock'):
                    entries = sl.load_registry()['profiles']
                    if not unique_browser_directory(entries,directory,identity):
                        return {**result,'status':'browser-profile-conflict'}
                    record = verification(profile,identity,directory,controller.channel,'workspace-page')
                    atomic_json(safe_join(directory,MARKER),record)
                    sl.update_registry(profile,identity,extra={'browserProfileDir':str(directory),'browserChannel':controller.channel,
                                                              'browserVerification':record})
                shortcut = sl.ensure_desktop_shortcut(profile,identity)
                return {**result,'ok':bool(shortcut.get('path')),'status':'web-verified' if shortcut.get('path') else 'shortcut-unavailable','webLoginVerified':True,
                        'checkedAt':record['checkedAt'],'browserProfileDir':str(directory),'desktopShortcut':shortcut}
            controller.page.wait_for_timeout(350)
        if result['status'] == 'waiting-shop-id':
            result['message'] = '当前工作台已显示店名，但没有能够核对的店铺 ID，原专用资料已保留。'
        elif result['status'] == 'waiting-login':
            result['message'] = '本次等待结束，仍未观察到该店工作台身份。可用原店铺命令继续。'
        if result['status'] == 'mismatch' or previous and controller.profile == original:
            atomic_json(safe_join(controller.profile,MARKER),{**store_fields(identity),'profile':profile,
                        'browserChannel':controller.channel,'status':result['status'],'checkedAt':int(time.time())})
        return result
    finally:
        try:
            controller._close()
        finally:
            atomic_json(job_path,{'jobId':job,'status':'closed','profile':profile})
