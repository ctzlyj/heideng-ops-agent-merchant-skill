"""Track the designated upstream without installing an unsafe raw Skill."""
import re,time
from pathlib import Path
from .safety import SafetyError,atomic_json,read_json
from .distribution import version_key

REPOSITORY='ctzlyj/jd-pop-main-video-skill'
AUDITED_COMMIT='29548089f7b71ac77ddb584caac0966a98df24ab'

class VideoSource:
 def __init__(self,state):self.state=Path(state);self.path=self.state/'video-source.json'
 def status(self):
  record=read_json(self.path,{})
  return {'repository':REPOSITORY,'auditedVersion':'0.3.0','auditedCommit':AUDITED_COMMIT,'recorded':record or None,'generationEnabled':False,'status':'source-known-generation-provider-pending','access':'upstream-private-access-required','distributionLicense':'unconfirmed','rawSkillInstalled':False,'internalRoutesForbidden':True}
 def record(self,commit,version,files):
  if not re.fullmatch('[0-9a-f]{40}',str(commit)):raise SafetyError('exact-upstream-commit-required')
  version_key(version)
  if not isinstance(files,dict) or not files:raise SafetyError('upstream-file-checksums-required')
  from .safety import safe_join
  for name,sha in files.items():
   safe_join(self.state,name)
   if not re.fullmatch('[0-9a-f]{64}',str(sha)):raise SafetyError('invalid-upstream-file-checksum')
  record={'repository':REPOSITORY,'commit':commit,'version':version,'fileSha256':files,'recordedAt':time.time(),'activation':'not-activated'}
  atomic_json(self.path,record);return record
 def discover(self,github_reader):
  # Reader owns authenticated GitHub transport; never export its token or private headers.
  latest=github_reader('repos/'+REPOSITORY+'/commits/main')
  sha=latest.get('sha')
  if not re.fullmatch('[0-9a-f]{40}',str(sha)):raise SafetyError('invalid-upstream-discovery-response')
  current=read_json(self.path,{})
  return {'repository':REPOSITORY,'latestCommit':sha,'recordedCommit':current.get('commit',AUDITED_COMMIT),'updateAvailable':sha!=current.get('commit',AUDITED_COMMIT),'activation':'requires-reviewed-file-checksums-idle-and-license','generationEnabled':False}
