"""Pillow-only public runtime; never modifies the browser runtime or source images."""
import json
from .auth_runtime import BrowserRuntime
from .safety import SafetyError,safe_join,read_json

class ImageRuntime(BrowserRuntime):
 packages=('Pillow',)
 runtime_name='image'
 runtime_channel='original-image-decoder'
 def _probe(self,python,home):
  raw=self._run([str(python),'-I','-B','-c',"import PIL.Image,importlib.metadata as m,json; print(json.dumps({'Pillow':m.version('Pillow')}))"],home,30)
  try:return json.loads(raw)
  except (ValueError,TypeError):raise SafetyError('image-runtime-probe-invalid') from None
 def home(self):
  if not self.ready():raise SafetyError('image-runtime-not-prepared')
  return safe_join(self.state,read_json(self.receipt)['home'])
