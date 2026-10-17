"""Varredura LGPD: bloqueia CPF não mascarado em arquivos de texto versionados.

Só acusa CPF com dígitos verificadores válidos (formatado ou 11 dígitos isolados),
o que evita falso positivo com CNPJ, valores e identificadores. Máscaras como
***.123.456-** não são acusadas. Binários (XLSX, PDF, SQLite) são ignorados.

    python tools/lgpd_scan.py                 # arquivos versionados (git ls-files)
    python tools/lgpd_scan.py --staged        # só o que está no índice
    python tools/lgpd_scan.py ARQ [ARQ ...]   # arquivos indicados
    python tools/lgpd_scan.py --hook          # PreToolUse do Claude Code: lê JSON do stdin

Linha legítima (ex.: CPF fictício em teste) é liberada com o comentário `lgpd-ok` na mesma linha.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 20 * 1024 * 1024
ALLOW_MARK = 'lgpd-ok'
_CPF = re.compile(r'(?<![\w.\-/])(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?![\w.\-/])')
# CPF fictício de uso didático, usado pelos testes para provar o mascaramento.
FICTICIOS = frozenset({'12345678909'})


def cpf_valido(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit() or len(set(digits)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1)))
        if (total * 10 % 11) % 10 != int(digits[size]):
            return False
    return True


def varrer_texto(text: str) -> list[tuple[int, str]]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARK in line:
            continue
        for match in _CPF.finditer(line):
            digits = ''.join(match.groups())
            if cpf_valido(digits) and digits not in FICTICIOS:
                found.append((number, digits[:3] + '.***.***-' + digits[-2:]))
    return found


def varrer_arquivo(path: Path) -> list[tuple[int, str]]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if len(data) > MAX_BYTES or b'\0' in data[:8192]:
        return []
    try:
        return varrer_texto(data.decode('utf-8'))
    except UnicodeDecodeError:
        return []


def _git_files(staged: bool) -> list[Path]:
    args = ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR'] if staged else ['git', 'ls-files']
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / name for name in out.splitlines() if name]


def relatorio(paths: list[Path]) -> list[str]:
    problems = []
    for path in paths:
        for line, masked in varrer_arquivo(path):
            shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
            problems.append(f'{shown}:{line}: CPF válido não mascarado ({masked})')
    return problems


def _hook() -> int:
    """Bloqueia `git commit` com CPF no índice. Código 2 = Claude Code cancela a chamada."""
    try:
        command = json.load(sys.stdin).get('tool_input', {}).get('command', '')
    except (json.JSONDecodeError, AttributeError):
        return 0
    if not re.search(r'\bgit\b[^;&|]*\bcommit\b', command):
        return 0
    problems = relatorio(_git_files(staged=True))
    if not problems:
        return 0
    print('guardiao-lgpd: commit bloqueado.\n' + '\n'.join(problems) +
          f'\nMascare o CPF ou, se for fictício, marque a linha com "{ALLOW_MARK}".', file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('arquivos', nargs='*', type=Path)
    parser.add_argument('--staged', action='store_true')
    parser.add_argument('--hook', action='store_true')
    args = parser.parse_args(argv)
    if args.hook:
        return _hook()
    paths = [p.resolve() for p in args.arquivos] if args.arquivos else _git_files(args.staged)
    problems = relatorio(paths)
    print('\n'.join(problems) if problems else f'nenhum CPF não mascarado em {len(paths)} arquivo(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
