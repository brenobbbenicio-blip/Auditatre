"""Abre zip com zipfile, até 3 níveis, recusando path traversal e zip bomb."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from auditatre.limits import MAX_BYTES, ZIP_MAX_DEPTH, ZIP_MAX_MEMBERS, ZIP_MAX_RATIO, ZIP_MAX_TOTAL


class ZipRecusado(Exception):
    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class LimitesZip:
    max_depth: int = ZIP_MAX_DEPTH
    max_members: int = ZIP_MAX_MEMBERS
    max_total: int = ZIP_MAX_TOTAL
    max_ratio: int = ZIP_MAX_RATIO
    max_member: int = ZIP_MAX_TOTAL
    catalog_bytes: int = MAX_BYTES


@dataclass(frozen=True)
class MembroZip:
    caminho: str
    dados: bytes | None
    status: str
    motivo: str | None
    bytes_declarados: int


def nome_perigoso(nome: str) -> bool:
    texto = nome.replace("\\", "/")
    if texto.startswith("/") or texto.startswith("//"):
        return True
    if len(texto) >= 2 and texto[1] == ":":
        return True
    partes = PurePosixPath(texto).parts
    return any(parte == ".." for parte in partes)


def _proporcao(info: zipfile.ZipInfo) -> float:
    if info.file_size <= 0:
        return 1.0
    if info.compress_size <= 0:
        return float(info.file_size)
    return info.file_size / info.compress_size


def _inspecionar(zf: zipfile.ZipFile, limites: LimitesZip) -> list[zipfile.ZipInfo]:
    membros: list[zipfile.ZipInfo] = []
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        if nome_perigoso(info.filename):
            raise ZipRecusado("path traversal")
        if info.flag_bits & 0x1:
            raise ZipRecusado("zip criptografado")
        membros.append(info)
        if len(membros) > limites.max_members:
            raise ZipRecusado("zip bomb")
        if info.file_size < 0 or info.file_size > limites.max_member:
            raise ZipRecusado("zip bomb")
        if _proporcao(info) > limites.max_ratio:
            raise ZipRecusado("zip bomb")
        total += info.file_size
        if total > limites.max_total:
            raise ZipRecusado("zip bomb")
    return membros


def abrir_zip(dados: bytes, caminho: str, *, profundidade: int = 1, limites: LimitesZip | None = None) -> list[MembroZip]:
    limites = limites or LimitesZip()
    if profundidade > limites.max_depth:
        return [
            MembroZip(
                caminho=caminho,
                dados=None,
                status="zip_recusado",
                motivo="profundidade",
                bytes_declarados=len(dados),
            )
        ]
    try:
        zf = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        return [
            MembroZip(
                caminho=caminho,
                dados=None,
                status="zip_recusado",
                motivo="zip ilegivel",
                bytes_declarados=len(dados),
            )
        ]
    with zf:
        try:
            membros = _inspecionar(zf, limites)
        except ZipRecusado as exc:
            return [
                MembroZip(
                    caminho=caminho,
                    dados=None,
                    status="zip_recusado",
                    motivo=exc.motivo,
                    bytes_declarados=len(dados),
                )
            ]
        saida: list[MembroZip] = []
        for info in membros:
            interno = f"{caminho}!/{info.filename}"
            with zf.open(info, "r") as handle:
                blob = handle.read(limites.max_member + 1)
            if len(blob) > limites.max_member or (info.file_size and len(blob) > info.file_size):
                return [
                    MembroZip(
                        caminho=caminho,
                        dados=None,
                        status="zip_recusado",
                        motivo="zip bomb",
                        bytes_declarados=len(dados),
                    )
                ]
            if len(blob) > limites.catalog_bytes:
                saida.append(
                    MembroZip(
                        caminho=interno,
                        dados=blob,
                        status="catalogado",
                        motivo="acima de 20 MB",
                        bytes_declarados=len(blob),
                    )
                )
                continue
            if info.filename.lower().endswith(".zip"):
                saida.extend(abrir_zip(blob, interno, profundidade=profundidade + 1, limites=limites))
                continue
            saida.append(
                MembroZip(
                    caminho=interno,
                    dados=blob,
                    status="extraido",
                    motivo=None,
                    bytes_declarados=len(blob),
                )
            )
        return saida
