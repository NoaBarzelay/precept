"""Tiny, tolerant markdown-frontmatter helpers shared across the knowledge pillar.

Deliberately forgiving: a vault is real, messy human content, so a malformed or
missing frontmatter block never raises — it just yields an empty meta dict and the
whole text as the body. We parse only the two fields this slice cares about (`type`,
`updated`) as plain strings, so we don't depend on YAML typing quirks.
"""

from __future__ import annotations

import re

_FM = "---"
# Match a leading `---\n ... \n---` block at the very top of the file.
_FM_BLOCK = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
# A simple `key: value` line inside the block (value optional).
_KV = re.compile(r"^([A-Za-z][\w-]*)\s*:\s*(.*?)\s*$")
_H1 = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


def split(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_meta, body). Missing/malformed frontmatter -> ({}, text).

    Only top-level `key: value` scalars are read (nested YAML is ignored — this slice
    needs just `type` and `updated`). Values are stripped of surrounding quotes."""
    m = _FM_BLOCK.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = _KV.match(line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip().strip("'\"")
            meta[key] = val
    body = text[m.end():]
    return meta, body


def title_of(body: str, fallback: str) -> str:
    """The first H1 in the body, else the fallback (usually the filename stem)."""
    m = _H1.search(body)
    return m.group(1).strip() if m else fallback


def has_sources_section(body: str) -> bool:
    """True if the body contains a `## Sources` heading (knowledge-file requirement)."""
    return re.search(r"^\s*##\s+Sources\s*$", body, re.MULTILINE | re.IGNORECASE) is not None
