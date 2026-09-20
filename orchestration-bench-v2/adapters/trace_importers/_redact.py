"""Redaction shared by importers (contracts/CONTRACTS.md §8).

No private reasoning text is ever stored; these patterns cover the incidental strings
(paths, addresses, credentials) that survive in metadata fields.
"""
import re

_PATTERNS = (
    (re.compile(r'/(?:Users|home)/[^/\s"\']+'), '~'),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), '<redacted:email>'),
    (re.compile(r'\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}'), '<redacted:credential>'),
    (re.compile(r'\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{8,}'), '<redacted:credential>'),
    (re.compile(r'\bxox[abps]-[A-Za-z0-9-]{8,}'), '<redacted:credential>'),
    (re.compile(r'\b[Bb]earer\s+[A-Za-z0-9._\-]{8,}'), '<redacted:credential>'),
    (re.compile(r'(?i)\b(api[_-]?key|token|password|secret)\s*[=:]\s*\S+'), r'\1=<redacted:credential>'),
)


def redact(value):
    """Redact credentials, e-mail addresses and absolute home paths in any nested value."""
    if isinstance(value, str):
        for pattern, replacement in _PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
