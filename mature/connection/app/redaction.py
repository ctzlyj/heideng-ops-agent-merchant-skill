"""Project outputs contain statuses, never raw authentication output."""
import re

_SECRET = re.compile(r'(?i)(cookie|authorization|access[_-]?token|refresh[_-]?token|token|app[_-]?secret|api[_-]?key|code|state)')
_URL = re.compile(r'https?://[^\s<>\"\']+')
_LABEL = re.compile(r'(?i)(cookie|authorization|access[_-]?token|refresh[_-]?token|token|app[_-]?secret|api[_-]?key|code|state)[\"\']?\s*[:=]\s*[^\r\n,}]+')


def safe_text(value):
    text = str(value or '')
    text = _URL.sub('[navigation omitted]', text)
    return _LABEL.sub('[private value omitted]', text)[:500]


def safe_value(value):
    if isinstance(value, dict):
        return {k: safe_value(v) for k, v in value.items() if not _SECRET.search(str(k))}
    if isinstance(value, list):
        return [safe_value(v) for v in value]
    if isinstance(value, str):
        return safe_text(value)
    return value
