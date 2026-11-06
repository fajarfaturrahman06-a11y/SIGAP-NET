"""Configuration normalization, SHA-256 integrity, and semantic diff.

Supported formats:
  * MikroTik / RouterOS style sections:
        /ip firewall filter
        set enabled=disabled
        set note=Core edge router - baseline v1
        add chain=input action=accept comment="allow mgmt"
  * Flat key/value:      key = value   |   key: value   |   key value
  * Lines starting with # or ! are comments and are ignored.

Semantic normalization removes formatting noise (CRLF, quotes, outer whitespace,
ordering) while keeping meaningful value changes. Values are preserved in full,
including spaces. Boolean normalization is key-aware: for `disabled=yes` the
meaning is "disabled", while `disabled=no` means "enabled".
"""
import hashlib
import re
from dataclasses import dataclass

VOLATILE_KEYS = {
    'timestamp', 'last-modified', 'last_modified', 'uptime', 'clock',
    'generated-at', 'generated_at', 'export-time',
}

_FLAG_TRUE = {'yes', 'true', 'enable', 'enabled', 'on', '1'}
_FLAG_FALSE = {'no', 'false', 'disable', 'disabled', 'off', '0'}

# Keys whose positive meaning is "enabled". `disabled` is handled inversely.
_ENABLED_KEYS = {
    'enabled', 'active', 'allow-remote-requests', 'remote', 'forward',
    'secure', 'authentication', 'accounting',
}

_KEY_CHARS = set('abcdefghijklmnopqrstuvwxyz'
                 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-')


def normalize_text(text: str) -> str:
    text = (text or '').lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    return text


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def normalize_value(value: str, key: str | None = None) -> str:
    """Normalize a value, applying boolean rules only to boolean-like keys."""
    value = _strip_quotes(value or '')
    value = re.sub(r'\s+', ' ', value).strip()
    base_key = (key or '').split('.')[-1].strip().lower()
    low = value.lower()

    if base_key == 'disabled':
        if low in _FLAG_TRUE:
            return 'disabled'
        if low in _FLAG_FALSE:
            return 'enabled'
        return value
    if base_key in _ENABLED_KEYS:
        if low in _FLAG_TRUE:
            return 'enabled'
        if low in _FLAG_FALSE:
            return 'disabled'
        return value
    return value


def normalize_key(value: str) -> str:
    return re.sub(r'\s+', '-', (value or '').strip().lower())


def normalize_section(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip().lower()).lstrip('/')


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode('utf-8')).hexdigest()


@dataclass
class ConfigEntry:
    section: str
    param: str
    value: str
    lineno: int
    raw: str

    @property
    def full_key(self):
        return f'{self.section}:{self.param}'


@dataclass
class Change:
    change_type: str          # ADDED | REMOVED | MODIFIED
    section: str
    param: str
    old_value: str | None
    new_value: str | None
    old_lineno: int | None = None
    new_lineno: int | None = None
    old_raw: str | None = None
    new_raw: str | None = None

    @property
    def full_key(self):
        return f'{self.section}:{self.param}'

    def as_dict(self):
        return {
            'change_type': self.change_type,
            'section': self.section,
            'param': self.param,
            'old_value': self.old_value,
            'new_value': self.new_value,
        }


def _split_assignments(text: str):
    """Split RouterOS `key=value` pairs while preserving spaces in values.

    Returns (prefix, pairs) where prefix is the token before the first pair
    (e.g. `ssh` in `ssh disabled=yes`). Values may contain spaces, quoted
    strings, and `=` characters; a new pair only starts after whitespace.
    """
    pairs: list[tuple[str, str]] = []
    first_start = None
    i = 0
    n = len(text)

    while i < n:
        # Find an unquoted `=`.
        ch = text[i]
        if ch in ('"', "'"):
            quote = ch
            i += 1
            while i < n:
                if text[i] == '\\':
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch != '=':
            i += 1
            continue

        # Walk left over a key and require a token boundary before it.
        k = i - 1
        while k >= 0 and text[k] in _KEY_CHARS:
            k -= 1
        key = text[k + 1:i]
        if not key or (k >= 0 and not text[k].isspace()):
            i += 1
            continue

        # Scan the value until whitespace followed by another `key=`.
        j = i + 1
        end = n
        quote = None
        while j < n:
            c = text[j]
            if quote:
                if c == '\\':
                    j += 2
                    continue
                if c == quote:
                    quote = None
                j += 1
                continue
            if c in ('"', "'"):
                quote = c
                j += 1
                continue
            if c.isspace():
                t = j
                while t < n and text[t].isspace():
                    t += 1
                match = re.match(r'[A-Za-z0-9_.\-]+=', text[t:])
                if match:
                    end = j
                    break
            j += 1

        value = text[i + 1:end].strip()
        pairs.append((key, value))
        if first_start is None:
            first_start = k + 1
        i = end

    prefix = text[:first_start].strip() if first_start is not None else text.strip()
    return prefix, pairs


def parse_config(text: str) -> dict[str, ConfigEntry]:
    """Parse config text into a canonical map keyed by section:param."""
    entries: dict[str, ConfigEntry] = {}
    section = 'global'
    add_counter = 0

    for lineno, raw in enumerate(normalize_text(text).split('\n'), 1):
        line = raw.strip()
        if not line or line.startswith('#') or line.startswith('!'):
            continue

        if line.startswith('/'):
            section = normalize_section(line)
            continue

        lowered = line.lower()
        if lowered.startswith('set '):
            prefix, pairs = _split_assignments(line[4:])
            target = normalize_key(prefix) or 'default'
            if not pairs:
                entries[f'{section}:{target}'] = ConfigEntry(
                    section, target, 'enabled', lineno, raw)
                continue
            for key, value in pairs:
                key_norm = normalize_key(key)
                param = f'{target}.{key_norm}' if prefix else key_norm
                entries[f'{section}:{param}'] = ConfigEntry(
                    section, param, normalize_value(value, key_norm), lineno, raw)
            continue

        if lowered.startswith('add '):
            _prefix, pairs = _split_assignments(line[4:])
            identity = ''
            for key, value in pairs:
                if key.lower() == 'comment' and value:
                    identity = f'comment={normalize_value(value, key.lower())}'
                    break
            if not identity:
                for key, value in pairs:
                    if key.lower() in ('chain', 'action') and value:
                        identity = f'{key.lower()}={normalize_value(value, key.lower())}'
                        break
            if not identity:
                add_counter += 1
                identity = f'rule{add_counter}'
            base_identity = identity
            suffix = 1
            while any(entry.param.startswith(f'{identity}.')
                      for entry in entries.values()
                      if entry.section == section):
                suffix += 1
                identity = f'{base_identity}#{suffix}'
            for key, value in pairs:
                key_norm = normalize_key(key)
                param = f'{identity}.{key_norm}'
                entries[f'{section}:{param}'] = ConfigEntry(
                    section, param, normalize_value(value, key_norm), lineno, raw)
            continue

        if '=' in line:
            key, value = line.split('=', 1)
            param = normalize_key(key)
            if param in VOLATILE_KEYS:
                continue
            entries[f'{section}:{param}'] = ConfigEntry(
                section, param, normalize_value(value, param), lineno, raw)
            continue

        if ':' in line:
            key, value = line.split(':', 1)
            param = normalize_key(key)
            if param in VOLATILE_KEYS:
                continue
            entries[f'{section}:{param}'] = ConfigEntry(
                section, param, normalize_value(value, param), lineno, raw)
            continue

        parts = line.split(None, 1)
        param = normalize_key(parts[0])
        if param in VOLATILE_KEYS:
            continue
        value = normalize_value(parts[1], param) if len(parts) > 1 else 'enabled'
        entries[f'{section}:{param}'] = ConfigEntry(section, param, value, lineno, raw)

    return entries


def canonical_hash(entries: dict[str, ConfigEntry]) -> str:
    canonical = '\n'.join(
        f'{section}|{entry.param}|{entry.value}'
        for section, entry in sorted(entries.items())
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def config_hash(text: str) -> str:
    """SHA-256 of the normalized semantic representation."""
    return canonical_hash(parse_config(text))


def diff_configs(baseline_text: str, current_text: str):
    """Return (changes, baseline_entries, current_entries)."""
    baseline = parse_config(baseline_text)
    current = parse_config(current_text)
    changes: list[Change] = []

    for key in sorted(set(baseline) | set(current)):
        old = baseline.get(key)
        new = current.get(key)
        if old and not new:
            changes.append(Change('REMOVED', old.section, old.param,
                                  old.value, None, old_lineno=old.lineno,
                                  old_raw=old.raw))
        elif new and not old:
            changes.append(Change('ADDED', new.section, new.param,
                                  None, new.value, new_lineno=new.lineno,
                                  new_raw=new.raw))
        elif old and new and old.value != new.value:
            changes.append(Change('MODIFIED', new.section, new.param,
                                  old.value, new.value, old_lineno=old.lineno,
                                  new_lineno=new.lineno, old_raw=old.raw,
                                  new_raw=new.raw))
    return changes, baseline, current
