"""One-use confidential grant and bounded HTTPS multipart; no auth headers/retries."""
from __future__ import annotations
import hashlib,http.client,ipaddress,json,math,re,socket,ssl,time,uuid,tempfile
from pathlib import Path
from urllib.parse import urlsplit
from .safety import SafetyError,is_linked
from .video_contract import native_id

MAX_RESPONSE=65536


def _target(url):
    try:
        if not isinstance(url,str) or not 1<=len(url)<=16384 or any(ord(c)<33 or ord(c)>126 for c in url):raise ValueError()
        target=urlsplit(url)
        if target.scheme!='https' or not target.hostname or target.username is not None or target.password is not None or target.fragment or target.port not in (None,443):raise ValueError()
        host=target.hostname
        if not re.fullmatch(r'[A-Za-z0-9.-]{1,253}|[0-9A-Fa-f:]{2,45}',host) or host.lower() in ('localhost','localhost.localdomain') or host.endswith('.'):raise ValueError()
        return target,host
    except Exception:raise SafetyError('official-public-https-upload-grant-required') from None


class UploadGrant:
    __slots__=('_jd_id','_url','_used')
    def __init__(self,jd_id,url):self._jd_id=native_id(jd_id);_target(url);self._url=url;self._used=False
    @property
    def jd_video_id(self):return self._jd_id
    def __repr__(self):return '<confidential one-use native upload grant>'
    def __reduce__(self):raise TypeError('confidential-grant-not-serializable')
    def consume(self):
        if self._used:raise SafetyError('native-upload-grant-already-consumed')
        self._used=True;url=self._url;self._url='';return self._jd_id,url


def extract_grant(response,secrets=()):
    from .verification import business_payload
    data=business_payload(response)
    if not isinstance(data,dict):raise SafetyError('native-upload-grant-object-required')
    jd=native_id(data.get('jdVideoId'));url=data.get('httpsUploadUrl') or data.get('uploadUrl');_target(url)
    if any(secret and secret in url for secret in secrets):raise SafetyError('native-auth-credential-echo-in-upload-grant')
    return {'jdVideoId':jd,'uploadUrl':url}


def _deadline(deadline,clock):
    if isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or not math.isfinite(deadline) or deadline<=clock():raise SafetyError('native-video-approval-expired')


class TransferNotDispatched(SafetyError):pass


def transfer_video(grant,path,sha,size,deadline,*,resolver=None,connection_factory=None,clock=None,before_dispatch=None):
    clock=clock or time.time;_deadline(deadline,clock)
    if not isinstance(grant,UploadGrant) or not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha) or type(size) is not int or not 0<size<=500*1024*1024:raise TransferNotDispatched('approved-native-video-original-required')
    path=Path(path).absolute();connection=None;dispatched=False;snapshot=tempfile.TemporaryFile(mode='w+b')
    def timeout_bound():
        _deadline(deadline,clock)
        remaining=min(30,max(.01,deadline-clock()))
        if connection is not None:
            connection.timeout=remaining
            if getattr(connection,'sock',None) is not None:connection.sock.settimeout(remaining)
    def send(raw):
        timeout_bound();connection.send(raw);_deadline(deadline,clock)
    try:
        if is_linked(path) or path.stat().st_size!=size:raise SafetyError('native-video-original-file-changed')
        copied=0;digest=hashlib.sha256()
        with path.open('rb') as source:
            while True:
                _deadline(deadline,clock);chunk=source.read(min(65536,size-copied+1))
                if not chunk:break
                copied+=len(chunk)
                if copied>size:raise SafetyError('native-video-source-exceeds-approved-size')
                snapshot.write(chunk);digest.update(chunk)
        if copied!=size or digest.hexdigest()!=sha:raise SafetyError('native-video-original-hash-changed')
        snapshot.flush();snapshot.seek(0)
        jd,url=grant.consume();target,host=_target(url)
        addresses=(resolver or socket.getaddrinfo)(host,443,type=socket.SOCK_STREAM)
        ips=[row[4][0] for row in addresses]
        if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast or ipaddress.ip_address(ip).is_reserved for ip in ips):raise SafetyError('nonpublic-or-mixed-upload-dns-refused')
        timeout_bound();context=ssl.create_default_context();factory=connection_factory or http.client.HTTPSConnection
        connection=factory(host,443,timeout=min(30,max(.01,deadline-clock())),context=context)
        def pinned_connect(address,timeout=None,source_address=None):
            return socket.create_connection((ips[0],443),timeout=timeout,source_address=source_address)
        connection._create_connection=pinned_connect
        if callable(getattr(connection,'set_debuglevel',None)):connection.set_debuglevel(0)
        boundary='merchant-video-'+uuid.uuid4().hex
        prefix=('--'+boundary+'\r\nContent-Disposition: form-data; name="video_file"; filename="'+sha+'.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode('ascii');suffix=('\r\n--'+boundary+'--\r\n').encode('ascii')
        request_path=(target.path or '/')+('?' + target.query if target.query else '')
        timeout_bound();connection.putrequest('POST',request_path,skip_accept_encoding=True)
        connection.putheader('Content-Type','multipart/form-data; boundary='+boundary);connection.putheader('Content-Length',str(len(prefix)+size+len(suffix)))
        timeout_bound()
        if before_dispatch is not None:before_dispatch()
        timeout_bound()
        dispatched=True;connection.endheaders();send(prefix);sent=0
        while True:
            chunk=snapshot.read(65536)
            if not chunk:break
            sent+=len(chunk);send(chunk)
        send(suffix);timeout_bound();response=connection.getresponse();raw=bytearray()
        while len(raw)<=MAX_RESPONSE:
            timeout_bound();part=response.read(min(8192,MAX_RESPONSE+1-len(raw)))
            if not part:break
            raw.extend(part)
        if len(raw)>MAX_RESPONSE or not 200<=response.status<300:raise SafetyError('native-video-transfer-unconfirmed')
        try:decoded=json.loads(raw)
        except (ValueError,TypeError,UnicodeError):decoded=None
        if isinstance(decoded,dict):
            from .verification import business_payload
            business_payload(decoded)
            if decoded.get('error'):raise SafetyError('native-video-upload-negative-response')
        _deadline(deadline,clock)
        return {'jdVideoId':jd,'httpStatus':response.status,'sentBytes':sent,'originalSha256':sha,'responseSha256':hashlib.sha256(raw).hexdigest(),'responseBytes':len(raw),'singleAttempt':True,'storageVerified':False}
    except Exception:
        if dispatched:raise SafetyError('native-video-transfer-outcome-unknown-no-auto-retry') from None
        raise TransferNotDispatched('native-video-transfer-not-dispatched') from None
    finally:
        snapshot.close();url=''
        if connection is not None:
            try:connection.close()
            except Exception:pass
