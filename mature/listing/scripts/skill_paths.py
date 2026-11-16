"""Resolve optional source dependencies only as isolated mature siblings."""
from __future__ import annotations
from pathlib import Path
import re

SKILL_ROOT = Path(__file__).resolve().parents[1]


def installed_skill_dir(name: str, *, skill_root: Path | None = None,
                        home: Path | None = None) -> Path | None:
    """No home/env/registry/catalog fallback. A missing sibling stays missing.

    home is a compatibility argument and is deliberately never consulted.
    """
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', name):
        raise ValueError('Invalid mature sibling dependency name')
    root = Path(skill_root or SKILL_ROOT).resolve()
    base = root.parent
    candidate = base / name
    if not candidate.is_dir():
        return None
    resolved = candidate.resolve()
    if resolved.parent != base:
        raise ValueError('Mature dependency escapes isolated sibling directory')
    return resolved
