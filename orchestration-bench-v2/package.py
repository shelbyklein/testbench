#!/usr/bin/env python3
"""Build outputs/orchestration-bench-v2 and its ZIP from this source tree (tracked files only)."""
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'outputs'
NAME = 'orchestration-bench-v2'
EXAMPLE = 'practical-setups'


def main():
    files = subprocess.check_output(['git', 'ls-files', '.'], cwd=ROOT, text=True).split('\n')
    files = sorted(f for f in files if f and not f.startswith('.runtime/'))
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '.'], cwd=ROOT, text=True).strip()
    if dirty:
        print('Refusing to package uncommitted changes:\n' + dirty, file=sys.stderr)
        return 1
    folder = OUT / NAME
    if folder.exists():
        shutil.rmtree(folder)
    for name in files:
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    # Prepared example: real definition, every run unstarted, not ready until model roles are recorded.
    example = folder / 'experiments' / 'prepared' / EXAMPLE
    subprocess.run([sys.executable, 'bench.py', '--experiment', str(example), 'prepare', '--definition', EXAMPLE],
                   cwd=folder, check=True, capture_output=True, text=True)
    (example.parent / 'README.md').write_text(
        f'# Prepared example: {EXAMPLE}\n\nPrepared by package.py from the packaged definitions. Every run is `prepared`; none has started, '
        'and `start` refuses until the real model roles are recorded. Launch notes inside the workspaces carry the paths of the '
        'machine that built the package; `start` regenerates them for your location.\n\n'
        f'    python3 bench.py --experiment experiments/prepared/{EXAMPLE} status\n'
        f'    python3 bench.py --experiment experiments/prepared/{EXAMPLE} serve --open\n')
    extra = sorted(str(p.relative_to(folder)) for p in example.parent.rglob('*') if p.is_file() and p.name != '.controller.lock')
    archive = OUT / f'{NAME}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in extra:
            bundle.write(folder / name, f'{NAME}/{name}')
        for name in files:
            info = zipfile.ZipInfo(f'{NAME}/{name}', date_time=(2026, 9, 20, 0, 0, 0))  # reproducible archive
            info.external_attr = ((ROOT / name).stat().st_mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, (ROOT / name).read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    (OUT / f'{NAME}.zip.sha256').write_text(f'{digest}  {NAME}.zip\nsource commit {commit}\n')
    print(f'{len(files)} source files + {len(extra)} prepared-example files -> {folder}\n{archive}\nsha256 {digest}\nsource commit {commit}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
