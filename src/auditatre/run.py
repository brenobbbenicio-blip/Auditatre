"""Percorre o inbox local e grava inventario, matriz, lacunas e manifesto."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

from auditatre.crosswalk import cruzar
from auditatre.extract import extrair
from auditatre.leitura import ler_texto
from auditatre.limits import MAX_BYTES
from auditatre.report import renderizar
from auditatre.zipsafe import LimitesZip, abrir_zip

EXT_ZIP = (".zip",)


def _sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _sha256_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as handle:
        for bloco in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _json(dados: object) -> str:
    return json.dumps(dados, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def executar(inbox: Path, saida: Path, *, max_bytes: int = MAX_BYTES, limites_zip: LimitesZip | None = None) -> dict[str, object]:
    if not inbox.is_dir():
        raise FileNotFoundError(inbox)
    saida.mkdir(parents=True, exist_ok=True)
    sal_path = saida / ".pessoa_sal"
    if sal_path.exists():
        sal = sal_path.read_bytes()
    else:
        sal = secrets.token_bytes(16)
        sal_path.write_bytes(sal)

    inventario: list[dict[str, object]] = []
    documentos = []
    lacunas_arquivo: list[dict[str, object]] = []
    vistos: dict[str, str] = {}
    limites = limites_zip or LimitesZip(catalog_bytes=max_bytes)

    def registrar(caminho: str, dados: bytes | None, status: str, motivo: str | None, tamanho: int, digest: str | None) -> None:
        if digest and digest in vistos and status == "extraido":
            inventario.append(
                {
                    "bytes": tamanho,
                    "caminho": caminho,
                    "duplicata_de": vistos[digest],
                    "motivo": "sha256 repetido",
                    "sha256": digest,
                    "status": "duplicado",
                    "tipo": None,
                }
            )
            return
        if digest and status == "extraido":
            vistos[digest] = caminho
        tipo = None
        if status == "extraido" and dados is not None:
            texto, leitura = ler_texto(caminho, dados)
            if leitura == "sem_texto":
                status = "sem_texto"
                motivo = "pdf sem texto"
                lacunas_arquivo.append(
                    {"grupo": caminho, "fase": "leitura", "motivo": "pdf sem texto", "valor": None}
                )
            elif leitura == "extraido" and texto.strip():
                documento = extrair(caminho, texto, sal=sal)
                tipo = documento.tipo
                if documento.achados or documento.tipo != "outro":
                    documentos.append(documento)
            elif leitura == "nao_lido":
                status = "catalogado"
                motivo = "tipo nao lido"
                tipo = "outro"
        inventario.append(
            {
                "bytes": tamanho,
                "caminho": caminho,
                "duplicata_de": None,
                "motivo": motivo,
                "sha256": digest,
                "status": status,
                "tipo": tipo,
            }
        )

    arquivos = sorted(caminho for caminho in inbox.rglob("*") if caminho.is_file() and caminho.name != ".gitkeep")
    for caminho in arquivos:
        relativo = caminho.relative_to(inbox).as_posix()
        tamanho = caminho.stat().st_size
        digest = _sha256_arquivo(caminho)
        if tamanho > max_bytes:
            inventario.append(
                {
                    "bytes": tamanho,
                    "caminho": relativo,
                    "duplicata_de": None,
                    "motivo": "acima de 20 MB",
                    "sha256": digest,
                    "status": "catalogado",
                    "tipo": None,
                }
            )
            lacunas_arquivo.append(
                {"grupo": relativo, "fase": "leitura", "motivo": "arquivo acima de 20 MB so catalogado", "valor": None}
            )
            continue
        dados = caminho.read_bytes()
        if relativo.lower().endswith(EXT_ZIP):
            membros = abrir_zip(dados, relativo, limites=limites)
            if len(membros) == 1 and membros[0].status == "zip_recusado" and membros[0].caminho == relativo:
                registrar(relativo, None, "zip_recusado", membros[0].motivo, tamanho, digest)
                continue
            inventario.append(
                {
                    "bytes": tamanho,
                    "caminho": relativo,
                    "duplicata_de": None,
                    "motivo": None,
                    "sha256": digest,
                    "status": "extraido",
                    "tipo": "zip",
                }
            )
            vistos[digest] = relativo
            for membro in membros:
                if membro.status != "extraido" or membro.dados is None:
                    inventario.append(
                        {
                            "bytes": membro.bytes_declarados,
                            "caminho": membro.caminho,
                            "duplicata_de": None,
                            "motivo": membro.motivo,
                            "sha256": _sha256(membro.dados) if membro.dados else None,
                            "status": membro.status,
                            "tipo": None,
                        }
                    )
                    continue
                registrar(membro.caminho, membro.dados, "extraido", None, len(membro.dados), _sha256(membro.dados))
            continue
        registrar(relativo, dados, "extraido", None, tamanho, digest)

    matriz, lacunas = cruzar(documentos)
    lacunas = lacunas_arquivo + lacunas
    inventario.sort(key=lambda item: str(item["caminho"]))
    relatorio = renderizar(inventario, matriz, lacunas)
    _gravar(saida, inventario, matriz, lacunas, relatorio)
    return {"inventario": inventario, "matriz": matriz, "lacunas": lacunas, "relatorio": relatorio}


def _gravar(
    saida: Path,
    inventario: list[dict[str, object]],
    matriz: list[dict[str, object]],
    lacunas: list[dict[str, object]],
    relatorio: str,
) -> None:
    arquivos = {
        "inventario.json": _json(inventario),
        "matriz.json": _json({"grupos": matriz}),
        "lacunas.json": _json(lacunas),
        "relatorio.md": relatorio if relatorio.endswith("\n") else relatorio + "\n",
    }
    for nome, conteudo in arquivos.items():
        (saida / nome).write_text(conteudo, encoding="utf-8")
    manifesto = {
        "algoritmo": "sha256",
        "saidas": {
            nome: {"bytes": len(conteudo.encode()), "sha256": _sha256(conteudo.encode())}
            for nome, conteudo in arquivos.items()
        },
        "entradas": [
            {"bytes": item["bytes"], "caminho": item["caminho"], "sha256": item["sha256"]}
            for item in inventario
            if item["sha256"] and "!/" not in str(item["caminho"])
        ],
    }
    (saida / "manifesto.json").write_text(_json(manifesto), encoding="utf-8")
