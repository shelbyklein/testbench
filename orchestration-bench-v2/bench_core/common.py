"""Shared helpers and unknown-value semantics (contracts/CONTRACTS.md §3)."""
import contextlib
import fcntl
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNKNOWN = None
PROVENANCE = ('measured', 'estimated', 'unavailable')
EXCLUDED = {'.git', 'node_modules', '.bench', '.DS_Store', '__pycache__'}


def excluded_for(scenario):
    """Global exclusions plus the scenario's declared runtime paths (CONTRACTS.md §5)."""
    return EXCLUDED | set((scenario.get('participant') or {}).get('runtime_paths') or [])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def inventory(folder, excluded=EXCLUDED):
    folder = Path(folder)
    return {str(p.relative_to(folder)): digest(p) for p in sorted(folder.rglob('*'))
            if p.is_file() and not any(x in excluded for x in p.relative_to(folder).parts)}


def inventory_hash(hashes):
    return hashlib.sha256('\n'.join(f'{k}:{v}' for k, v in sorted(hashes.items())).encode()).hexdigest()


def measurement(value=UNKNOWN, unit='', provenance=None, source=None):
    if provenance is None:
        provenance = 'unavailable' if value is None else 'measured'
    result = {'value': value, 'unit': unit, 'provenance': provenance, 'source': source}
    validate_measurement(result)
    return result


def validate_measurement(obj):
    require(isinstance(obj, dict) and set(obj) >= {'value', 'unit', 'provenance'}, 'Measurement needs value, unit and provenance')
    require(obj['provenance'] in PROVENANCE, f'Unknown provenance: {obj["provenance"]}')
    value = obj['value']
    require((value is None) == (obj['provenance'] == 'unavailable'), 'Unavailable measurements are null; null measurements are unavailable')
    if value is not None:
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'Measurement value must be a nonnegative number')
        require(isinstance(obj.get('source'), str) and obj['source'].strip(), 'Measured or estimated values need a source')
    return obj


def total(measurements):
    """Sum known values without presenting a partial sum as complete."""
    known = [m['value'] for m in measurements if m and m.get('value') is not None]
    unknown = len(measurements) - len(known)
    return {'value': sum(known) if known else None, 'complete': unknown == 0 and bool(known), 'unknownCount': unknown}


@contextlib.contextmanager
def experiment_lock(exp_dir):
    """Serialize experiment.json writers across the operator and review processes."""
    marker = Path(exp_dir) / 'experiment.json'
    if marker.exists() and read(marker).get('format') is None:
        yield  # v1 experiment: read-only, and v2 never writes into its directory, not even a lock
        return
    with (Path(exp_dir) / '.controller.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
