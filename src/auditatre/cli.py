"""Linha de comando. Para se o inbox nao existir. Nao acessa a rede."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from auditatre.run import executar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auditatre")
    parser.add_argument("--inbox", default="inbox/drive")
    parser.add_argument("--out", default="out")
    args = parser.parse_args(argv)
    inbox = Path(args.inbox)
    if not inbox.is_dir():
        print("inbox ausente. O ingestor para aqui e nao busca documentos na rede.", file=sys.stderr)
        return 2
    executar(inbox, Path(args.out))
    return 0
