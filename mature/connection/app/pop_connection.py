"""Durable handoff from an authorized CLI request to the original local service job."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4


class OtherAuthorizationActive(RuntimeError):
    """The manager rejected this start while holding its job lock, before creating a worker."""


def local_timeout():
    return 'local_cli_timeout', '本机官方 CLI 超时，未返回店铺身份；沿原 Profile 继续核验。'


def original_target(pending, profile, job_id, query):
    return (bool(job_id) and bool(profile) and profile != 'default' and pending.get('jobId') == job_id
            and pending.get('profile') == profile and pending.get('query') == query.strip())


def target_matches(identity, shop_name, vender_id, name_matches, exact_name=None):
    return (bool(identity.get('venderId')) and bool(identity.get('shopName'))
            and (not vender_id or str(identity['venderId']) == str(vender_id))
            and (not shop_name or name_matches(shop_name, [identity['shopName']]))
            and (not exact_name or identity['shopName'] == exact_name))


def explicit_profile(sl, result, profile, query):
    if result.get('status') != 'ready' or not profile or result.get('profile') == profile:
        return result
    # The lookup by shop can choose another alias. Verify the actually requested profile.
    if profile == 'default' or not sl.PROFILE_RE.fullmatch(profile):
        return {'ok':False, 'status':'mismatch', 'profile':profile, 'errorKind':'profile_mismatch'}
    try:
        identity = sl.verify_profile(profile)
        sl.assert_profile_proof(profile, identity)
    except sl.VerifyError as exc:
        return {'ok':False, 'status':'mismatch', 'profile':profile, 'errorKind':exc.kind}
    keys = ('shopId', 'venderId')
    if not all(identity.get(k) and str(identity[k]) == str(result.get(k) or '') for k in keys):
        return {'ok':False, 'status':'mismatch', 'profile':profile, 'errorKind':'profile_mismatch'}
    registered = sl.load_registry()['profiles'].get(profile, {})
    return {'ok':True, 'status':'ready', **sl._public(profile, identity, registered)}


def signal_workspace_check(job):
    stopped = getattr(job, '_shutdown_requested', None)
    if (job.stage != 'waiting_login' or job.status != 'waiting' or job._cancelled.is_set()
            or (stopped is not None and stopped.is_set())):
        return False
    job._workspace_check_requested.set()
    return True


def observe_workspace(job):
    if job._workspace_check_requested.is_set() and not job._workspace_check_handled:
        job._workspace_check_handled = True
        observe_original = getattr(job.browser, 'check_workspace_after_login', None)
        if callable(observe_original):
            observe_original()
    return job.browser.observe()


def reuse_receipt(data, profile, home, force=False):
    """Recognize the documented completion shape for reuse in the original CLI home."""
    return (isinstance(data, dict) and not force and data.get('command') == 'login' and data.get('ok') is True
            and data.get('cliVersion') == '0.3.7' and data.get('profile') == profile
            and type(data.get('timestamp')) is int and data['timestamp'] > 0
            and isinstance(data.get('home'), str) and bool(data['home'])
            and Path(data['home']).resolve() == Path(home).resolve()
            and data.get('authorizationStatus') == 'reused_existing_credentials'
            and data.get('authorizationStage') == 'credential_reuse'
            and all(data.get(k) is True for k in ('alreadyAuthorized','reusedAuthorization','loginCompleted',
                                                   'appKeyConfigured','appSecretStored','tokenStored'))
            and data.get('tokenMocked') is False and data.get('authorizeUrlPrinted') is False)


def _read(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise ValueError('原连接回执无法核实')
    return value


def _save(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'dispatch.lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if not stream.tell():
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _scope(payload):
    return {k:str(payload.get(k) or '') for k in ('profile', 'shopName', 'venderId')}


def _client(home, profile):
    return Path(home) / 'connect-requests' / sha256(profile.encode()).hexdigest() / 'original.json'


def _job_record(home, job_id):
    return Path(home) / 'connect-jobs' / 'pending' / (sha256(job_id.encode()).hexdigest() + '.json')


def pending_for(sl, job_id):
    current = sl.load_pending()
    if current.get('jobId') == job_id:
        return current
    return _read(_job_record(sl.linker_home(), job_id)) or {}


def _intent(sl, query, requested_profile):
    return requested_profile or 'lookup/' + sl.norm(query)


def _server(home, request_id):
    if not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise ValueError('连接请求编号无效')
    return Path(home) / 'connect-jobs' / request_id / 'receipt.json'


def _unknown(profile):
    return {'ok':False, 'status':'awaiting_auth', 'errorKind':'result_unknown', 'profile':profile,
            'message':'原连接提交结果待核实，保留原请求，未再次发起授权。', 'retryAllowed':False}


def _job_ack(record):
    return {'ok':True, 'status':'awaiting_auth', 'stage':'accepted', 'profile':record['jobProfile'],
            'authorizationRequestedProfile':record['scope']['profile'],
            'authorizationRequestId':record['requestId'], 'jobId':record['jobId']}


def _not_accepted(record):
    return {'ok':False, 'status':'busy', 'errorKind':'auth_busy', 'requestAccepted':False,
            'authorizationRequestId':record['requestId'], 'message':'另一笔授权还在进行。'}


def admit(home, payload, start):
    """The existing authenticated service calls this after validating the shop and before replying."""
    rid = payload['authorizationRequestId']
    path = _server(home, rid)
    scope = _scope(payload)
    with _lock(path.parent):
        record = _read(path)
        if record is not None:
            if record.get('scope') != scope or record.get('requestId') != rid:
                return _unknown(scope['profile'])
            if record.get('notAccepted'):
                return _not_accepted(record)
            if not record.get('jobId'):
                return _unknown(scope['profile'])
            return _job_ack(record)
        record = {'scope':scope, 'requestId':rid}
        _save(path, record)
        try:
            job = start()
        except OtherAuthorizationActive:
            record['notAccepted'] = True
            _save(path, record)
            return _not_accepted(record)
        bound_profile = scope['profile'] in (getattr(job, 'requested_profile', None), job.profile)
        same_vendor = bool(scope['venderId']) and str(getattr(job, 'expect_vender_id', '')) == scope['venderId']
        if not job.profile or not job.id or (not bound_profile and (payload.get('explicitAuthorizationProfile') or not same_vendor)):
            return _unknown(scope['profile'])
        record['jobId'] = job.id
        record['jobProfile'] = job.profile
        _save(path, record)
        return {**_job_ack(record), 'stage':job.stage, 'job':job.to_dict()}


def dispatch(sl, api, payload, pending_fields, *, requested_profile=None):
    """Save intent before POST and hand it to the existing pending-job logic before releasing the lock."""
    scope = _scope(payload)
    profile = scope['profile']
    locator = _intent(sl, pending_fields.get('query', scope['shopName']), requested_profile)
    path = _client(sl.linker_home(), locator)
    try:
        with _lock(path.parent):
            record = _read(path)
            if record is not None:
                previous = record['scope']
                if (requested_profile and previous['profile'] != profile
                        or previous['venderId'] and scope['venderId'] and previous['venderId'] != scope['venderId']
                        or previous['shopName'] != scope['shopName'] and not (
                            previous['venderId'] and previous['venderId'] == scope['venderId'])):
                    return _unknown(profile)
                scope = previous
            if record is None:
                record = {'scope':scope, 'requestId':uuid4().hex}
                _save(path, record)
                status, response = api('/api/connect', {**payload, 'authorizationRequestId':record['requestId'],
                                                        'explicitAuthorizationProfile':bool(requested_profile)})
                if status == 200 and response.get('requestAccepted') is False and response.get('authorizationRequestId') == record['requestId']:
                    path.unlink()
                    return response
                if (status == 200 and response.get('jobId') and response.get('ok') is True
                        and (response.get('profile') == profile or response.get('authorizationRequestedProfile') == profile)
                        and response.get('authorizationRequestId', record['requestId']) == record['requestId']):
                    record['jobId'] = response['jobId']
                    record['jobProfile'] = response['profile']
                    _save(path, record)
                else:
                    return _unknown(profile)
            else:
                if record.get('handedOff'):
                    pending = pending_for(sl, record['jobId'])
                    if pending.get('jobId') == record.get('jobId') and pending.get('profile') == record.get('jobProfile'):
                        status, current = api('/api/job')
                        job = current.get('job') or {}
                        if status != 200 or job.get('id') != record['jobId'] or job.get('profile') != record['jobProfile']:
                            return {**_unknown(record['jobProfile']), 'jobId':record['jobId']}
                        if job.get('status') in ('failed','cancelled','mismatch') and job.get('errorKind') not in (
                                'callback_unknown','result_unknown','native_receipt_pending','local_cli_timeout'):
                            # A definite terminal result releases this local handoff for the next invocation.
                            path.unlink()
                            return {'ok':False, 'status':job['status'], 'jobId':job['id'], 'profile':profile,
                                    'errorKind':job.get('errorKind'), 'message':job.get('message','')}
                        return {**_job_ack(record), 'stage':job.get('stage') or 'accepted'}
                    return {**_unknown(record['jobProfile']), 'jobId':record['jobId']}
                accepted = _read(_server(sl.linker_home(), record['requestId']))
                if not record.get('jobId'):
                    if not accepted or accepted.get('scope') != scope or accepted.get('requestId') != record['requestId']:
                        return _unknown(profile)
                    if accepted.get('notAccepted'):
                        path.unlink()
                        return _not_accepted(accepted)
                    if not accepted.get('jobId'):
                        return _unknown(profile)
                    record['jobId'] = accepted['jobId']
                    record['jobProfile'] = accepted['jobProfile']
                response = _job_ack(record)
            pending = {**pending_fields, 'profile':record['jobProfile'], 'jobId':record['jobId'],
                       'requestedProfile':scope['profile'], 'connectionIntent':locator,
                       'authorizationRequestId':record['requestId']}
            _save(_job_record(sl.linker_home(), record['jobId']), pending)
            previous = sl.load_pending()
            if (not previous or previous.get('jobId') == record['jobId']
                    or previous.get('authorizationRequestId') or previous.get('processRunning') is False):
                sl.save_pending(pending)
            record['handedOff'] = True
            _save(path, record)
            return response
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
        return _unknown(profile)


def finish_pending(home, pending):
    profile, rid = pending.get('connectionIntent'), pending.get('authorizationRequestId')
    if not profile or not rid:
        return
    path = _client(home, profile)
    with _lock(path.parent):
        record = _read(path)
        if record and record['requestId'] == rid and record.get('jobId') == pending.get('jobId'):
            path.unlink()


def settle_ready(sl, result, query, requested_profile):
    """A fresh verified identity resolves a prior request, including a lost service response."""
    profile = result.get('profile')
    if result.get('status') != 'ready' or not profile:
        return
    path = _client(sl.linker_home(), _intent(sl, query, requested_profile))
    if not path.is_file():
        return
    try:
        with _lock(path.parent):
            record = _read(path)
            if record is None:
                return
            scope = record['scope']
            if (profile in (scope.get('profile'), record.get('jobProfile')) and result.get('venderId') and result.get('shopName')
                    and (not scope['venderId'] or scope['venderId'] == str(result['venderId']))
                    and (not scope['shopName'] or sl.norm(scope['shopName']) == sl.norm(result['shopName']))):
                path.unlink()
    except (OSError, ValueError, KeyError):
        return


def owned_credential_slot(account, profile):
    """Return the vault target and slot from a CLI account bound to this Profile."""
    if not isinstance(account, str) or not account:
        return None
    parts = account.removeprefix('jdo-cli:').split(':')
    if (len(parts) == 4 and parts[0] == 'token' and parts[1] == profile
            and re.fullmatch(r'[0-9a-f]{16}', parts[2])):
        target = 'jdo-cli:' + ':'.join(parts)
    elif (len(parts) in (3, 4) and parts[-3] == 'token' and parts[-2] == profile
          and account.startswith('jdo-cli:')):
        target = account
    else:
        return None
    slot = parts[-1]
    return (target, slot) if slot == 'default' or slot.isascii() and slot.isdigit() else None


def official_status(status, profile, home, profiles_path, strict_inputs):
    if isinstance(status, dict) and isinstance(status.get('profile'), dict):
        record = status['profile']
        inputs = status.get('credentialInputs') or {}
        store = status.get('credentialStore') or {}
        if (not isinstance(inputs, dict) or not isinstance(store, dict)
                or status.get('defaultProfile') != profile or record.get('exists') is not True
                or not isinstance(record.get('path'), str)
                or Path(record['path']).resolve() != (profiles_path / f'{profile}.json').resolve()):
            return None
        if strict_inputs:
            account = owned_credential_slot(store.get('tokenCredentialAccount'), profile)
            if (not account or account[1] != str(record.get('venderId') or 'default')
                    or record.get('appKeyConfigured') is not True or store.get('appSecretStored') is not True
                    or inputs.get('appSecretFromEnv') is not False or inputs.get('accessTokenFromEnv') is not False):
                return None
        status = {
            'ok': status.get('ok'), 'profile': profile, 'home': status.get('home'),
            'tokenCredentialAccount': store.get('tokenCredentialAccount'),
            'oauthTokenStored': inputs.get('oauthTokenStored'),
            'oauthTokenMocked': inputs.get('oauthTokenMocked'),
        }
    elif strict_inputs:
        # The 0.3.7 public status binds the account via this nested Profile record.
        return None
    if (not isinstance(status, dict) or status.get('ok') is not True or status.get('profile') != profile
            or not isinstance(status.get('home'), str) or not status['home']
            or Path(status['home']).resolve() != home.resolve()
            or status.get('oauthTokenStored') is not True or status.get('oauthTokenMocked') is not False):
        return None
    return status
