"""Pure URL boundary retained from the merchant 0.1.5 endpoint validator."""
import ipaddress,re,urllib.parse
from .safety import SafetyError

INTERNAL=('jd.local','jd.com','oxygen','joybuilder','360buyimg.com','skillhub')

def validate_external_endpoint(url):
 if not isinstance(url,str):raise SafetyError('external-https-endpoint-required')
 p=urllib.parse.urlsplit(url);host=(p.hostname or '').lower().rstrip('.')
 if p.scheme!='https' or not host or p.username or p.password or p.query or p.fragment or p.port not in (None,443):raise SafetyError('external-https-endpoint-required')
 if any(x in host for x in INTERNAL) or host=='localhost' or host.endswith(('.local','.internal','.localhost')):raise SafetyError('internal-media-source-forbidden')
 try:
  if not ipaddress.ip_address(host).is_global:raise SafetyError('private-media-source-forbidden')
 except ValueError:pass
 if not re.fullmatch('[a-z0-9.-]+',host):raise SafetyError('invalid-external-host')
 return url

