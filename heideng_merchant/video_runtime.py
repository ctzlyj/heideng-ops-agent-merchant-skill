"""On-demand, hash-checked public PyAV decoder; no system FFmpeg or generation."""
import json,re,tempfile
from pathlib import Path
from .auth_runtime import BrowserRuntime
from .safety import SafetyError,read_json,safe_join,atomic_json,file_sha,is_linked

class VideoRuntime(BrowserRuntime):
    packages=('av',)
    runtime_name='video'
    runtime_channel='original-video-decoder'
    # Deliberately compatible with the project's Python >=3.11 minimum.
    # Newer PyAV releases require Python >=3.12. No silent version fallback.
    version='16.1.0'

    def _source_url(self,name):
        if name!='av':raise SafetyError('video-runtime-package-not-approved')
        return 'https://pypi.org/pypi/av/'+self.version+'/json'

    def _install(self,python,home,pins,sources):
        if pins!={'av':self.version}:raise SafetyError('video-runtime-version-not-approved')
        hashes=sources['av']['artifactSha256']
        if not hashes or any(not isinstance(h,str) or not re.fullmatch('[0-9a-f]{64}',h) for h in hashes):
            raise SafetyError('video-runtime-wheel-hashes-required')
        requirement='av=='+self.version+''.join(' --hash=sha256:'+h for h in sorted(set(hashes)))+'\n'
        with tempfile.NamedTemporaryFile(mode='w',encoding='ascii',suffix='.txt',dir=home,delete=False) as stream:
            stream.write(requirement);path=Path(stream.name)
        try:
            self._run([str(python),'-I','-m','pip','--isolated','install','--index-url','https://pypi.org/simple','--no-cache-dir','--only-binary=:all:','--require-hashes','--no-deps','-r',str(path)],home,300)
        finally:path.unlink(missing_ok=True)
        integrity=safe_join(home,'decoder-integrity.json');atomic_json(integrity,{'files':self._inventory(python)})
        self._installation_inventory_sha=file_sha(integrity)

    def _inventory(self,python):
        root=Path(python).parent.parent
        sites=[root/'Lib/site-packages'] if (root/'Lib/site-packages').is_dir() else list((root/'lib').glob('python*/site-packages'))
        if len(sites)!=1:raise SafetyError('video-runtime-package-root-invalid')
        files={};total=0
        for path in sorted(sites[0].rglob('*')):
            if is_linked(path):raise SafetyError('linked-video-runtime-dependency')
            if path.is_file():
                relative=path.relative_to(root).as_posix();safe_join(root,relative)
                total+=path.stat().st_size
                if len(files)>=20_000 or total>512*1024*1024:raise SafetyError('video-runtime-integrity-budget-exceeded')
                files[relative]=file_sha(path)
        if not files:raise SafetyError('video-runtime-dependency-files-required')
        return files

    def _receipt_details(self,python,home):
        return {'decoderIntegritySha256':self._installation_inventory_sha}

    def _probe(self,python,home):
        receipt=read_json(self.receipt,{})
        expected=receipt.get('decoderIntegritySha256') or getattr(self,'_installation_inventory_sha',None)
        integrity=safe_join(home,'decoder-integrity.json')
        if not expected or not integrity.is_file() or file_sha(integrity)!=expected or read_json(integrity).get('files')!=self._inventory(python):
            raise SafetyError('video-runtime-decoder-files-changed-before-import')
        raw=self._run([str(python),'-I','-B','-c',"import av,importlib.metadata as m,json; print(json.dumps({'av':m.version('av')}))"],home,30)
        try:return json.loads(raw)
        except (ValueError,TypeError):raise SafetyError('video-runtime-probe-invalid') from None

    def home(self):
        if not self.ready():raise SafetyError('video-runtime-not-prepared')
        return safe_join(self.state,read_json(self.receipt)['home'])
