"""Linha de comando. Offline por padrão; importação de Drive explícita."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from auditatre.run import executar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auditatre")
    parser.add_argument("--inbox", default="inbox/drive")
    parser.add_argument("--out", default="out")
    parser.add_argument("--drive-folder", help="ID da pasta a importar antes da ingestão (ativa rede)")
    parser.add_argument("--import-only", action="store_true", help="Importa sem executar a ingestão")
    parser.add_argument("--drive-max-file-bytes", type=int, default=200 * 1024 * 1024)
    parser.add_argument("--drive-max-total-bytes", type=int, default=1024 * 1024 * 1024)
    args = parser.parse_args(argv)
    if args.import_only and not args.drive_folder:
        parser.error("--import-only exige --drive-folder")
    inbox = Path(args.inbox)
    if args.drive_folder:
        from auditatre.drive_api import DriveAPI, DriveError
        from auditatre.drive_import import ImportLimits, importar

        client = None
        try:
            client = DriveAPI.from_default_credentials()
            manifest = importar(client, args.drive_folder, inbox, limits=ImportLimits(
                max_file_bytes=args.drive_max_file_bytes,
                max_total_bytes=args.drive_max_total_bytes,
            ))
            if not manifest["completo"]:
                print("Importação parcial. Consulte .auditatre-drive/manifesto.json no inbox; ingestão não executada.", file=sys.stderr)
                return 3
            if args.import_only:
                return 0
        except (DriveError, OSError) as exc:
            code = str(exc) if isinstance(exc, DriveError) else "falha_local"
            print(f"Importação não concluída: {code}. Ingestão não executada.", file=sys.stderr)
            return 3
        finally:
            if client is not None:
                client.close()
    if not inbox.is_dir():
        print("inbox ausente. O ingestor para aqui e nao busca documentos na rede.", file=sys.stderr)
        return 2
    # O núcleo continua local, incluindo a conferência de proveniência importada.
    from auditatre.drive_api import DriveError
    try:
        executar(inbox, Path(args.out))
    except DriveError as exc:
        print(f"Proveniência Drive inválida: {exc}. Ingestão não concluída.", file=sys.stderr)
        return 3
    return 0
