"""Materialização transacional local. Transporte injetável; sem rede neste módulo."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from auditatre.drive_api import DriveError, FOLDER_MIME, validar_id

MANAGED = ".auditatre-drive"
MANIFEST = "manifesto.json"
EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}


class Client(Protocol):
    def metadata(self, file_id: str) -> dict: ...
    def children(self, folder_id: str) -> Iterator[dict]: ...
    def content(self, file_id: str, export_mime: str | None) -> Iterator[bytes]: ...


@dataclass(frozen=True)
class ImportLimits:
    max_file_bytes: int = 200 * 1024 * 1024
    max_total_bytes: int = 1024 * 1024 * 1024
    max_items: int = 10_000
    max_depth: int = 50


def _sem_symlink(path: Path) -> None:
    if any(p.is_symlink() for p in (path.absolute(), *path.absolute().parents)):
        raise DriveError("symlink_recusado")


def _destino_seguro(inbox: Path) -> None:
    _sem_symlink(inbox)
    # Um inbox customizado dentro de um checkout também precisa estar ignorado.
    for parent in (inbox.absolute(), *inbox.absolute().parents):
        if (parent / ".git").exists():
            relative = inbox.absolute().relative_to(parent).as_posix()
            tracked = subprocess.run(
                ["git", "-C", str(parent), "ls-files", "--", relative],
                capture_output=True, check=True, text=True,
            )
            ignored = subprocess.run(
                ["git", "-C", str(parent), "check-ignore", "-q", "--", relative + "/__corpus__"],
                capture_output=True,
            )
            if tracked.stdout or ignored.returncode != 0:
                raise DriveError("inbox_deve_estar_fora_do_git_ou_ignorado")
            break


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _objeto(inbox: Path, item: dict) -> Path:
    material = item["materializado"]
    sha = material["sha256"]
    relative = material["caminho"]
    if not re.fullmatch(r"[0-9a-f]{64}", sha) or not re.fullmatch(
        re.escape(MANAGED) + r"/objects/" + sha + r"\.[a-z0-9]{1,12}", relative
    ):
        raise DriveError("manifesto_drive_invalido")
    path = inbox / relative
    _sem_symlink(path)
    return path


def ler_manifesto(inbox: Path) -> dict | None:
    path = inbox / MANAGED / MANIFEST
    _sem_symlink(path)
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (manifest["schema"] != 1 or not isinstance(manifest["arquivos"], list)
                or not isinstance(manifest["completo"], bool)
                or not isinstance(manifest["erros"], list)):
            raise ValueError
        validar_id(manifest["raiz_id"])
        ids = set()
        for item in manifest["arquivos"]:
            file_id = validar_id(item["drive_id"])
            if (file_id in ids or not isinstance(item["ativo"], bool)
                    or not isinstance(item["caminho_drive"], str)
                    or not isinstance(item["caminhos_drive"], list)
                    or not isinstance(item["modified_time"], str)
                    or item["status"] not in {"baixado", "reutilizado", "falha", "nao_suportado", "nao_observado"}):
                raise ValueError
            ids.add(file_id)
            if item.get("materializado"):
                material = item["materializado"]
                if (type(material["bytes"]) is not int or material["bytes"] < 0
                        or not isinstance(material["modified_time"], str)
                        or not isinstance(material["mime_type_origem"], str)
                        or material["mime_type_exportacao"] is not None
                        and not isinstance(material["mime_type_exportacao"], str)):
                    raise ValueError
                _objeto(inbox, item)
        return manifest
    except (KeyError, TypeError, ValueError, OSError):
        raise DriveError("manifesto_drive_invalido") from None


def entradas_importadas(inbox: Path) -> tuple[dict[str, list[dict]], dict | None]:
    """Somente objetos referenciados pelo manifesto atual participam da ingestão."""
    manifest = ler_manifesto(inbox)
    bindings: dict[str, list[dict]] = {}
    verified: dict[str, tuple[str, int]] = {}
    if not manifest:
        return bindings, None
    for item in manifest["arquivos"]:
        if not item.get("ativo", True) or not item.get("materializado"):
            continue
        path = _objeto(inbox, item)
        material = item["materializado"]
        relative = material["caminho"]
        expected = (material["sha256"], material["bytes"])
        if relative in verified:
            if verified[relative] != expected:
                raise DriveError("manifesto_drive_invalido")
        else:
            if not path.is_file() or path.stat().st_size != material["bytes"] or _hash(path) != material["sha256"]:
                raise DriveError("objeto_drive_ausente_ou_corrompido")
            verified[relative] = expected
        bindings.setdefault(relative, []).append(item)
    return bindings, manifest


def _validar_metadata(meta: dict, expected_id: str | None = None) -> None:
    try:
        validar_id(meta["id"])
        if expected_id and meta["id"] != expected_id:
            raise ValueError
        if not isinstance(meta["name"], str) or not isinstance(meta["mimeType"], str) or meta.get("trashed"):
            raise ValueError
        if meta["mimeType"] != FOLDER_MIME and not isinstance(meta.get("modifiedTime"), str):
            raise ValueError
        if "parents" in meta and (not isinstance(meta["parents"], list)
                                  or not all(isinstance(parent, str) for parent in meta["parents"])):
            raise ValueError
        if "capabilities" in meta and not isinstance(meta["capabilities"], dict):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise DriveError("metadata_invalida") from None


def _versao(meta: dict) -> tuple:
    return tuple(meta.get(key) for key in ("modifiedTime", "version", "mimeType", "size", "md5Checksum"))


def _gravar_manifesto(path: Path, manifest: dict) -> None:
    _sem_symlink(path)
    fd, name = tempfile.mkstemp(prefix=".manifest-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def importar(client: Client, folder_id: str, inbox: Path, *, limits: ImportLimits | None = None) -> dict:
    limits = limits or ImportLimits()
    if min(limits.max_file_bytes, limits.max_total_bytes, limits.max_items, limits.max_depth) <= 0:
        raise DriveError("limites_invalidos")
    validar_id(folder_id)
    _destino_seguro(inbox)
    previous = ler_manifesto(inbox)
    if previous and previous["raiz_id"] != folder_id:
        raise DriveError("outra_pasta_drive_use_outro_inbox")
    root = client.metadata(folder_id)
    _validar_metadata(root, folder_id)
    if root["mimeType"] != FOLDER_MIME:
        raise DriveError("raiz_nao_e_pasta")
    managed = inbox / MANAGED
    _sem_symlink(managed / "objects")
    (managed / "objects").mkdir(parents=True, exist_ok=True)
    lock = managed / ".import.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise DriveError("importacao_em_andamento_ou_lock_pendente") from None
    os.close(fd)
    try:
        # Releitura sob o lock impede usar estado antigo entre importadores.
        previous = ler_manifesto(inbox)
        if previous and previous["raiz_id"] != folder_id:
            raise DriveError("outra_pasta_drive_use_outro_inbox")
        return _importar(client, folder_id, inbox, root, previous, limits)
    finally:
        lock.unlink(missing_ok=True)


def _importar(client: Client, folder_id: str, inbox: Path, root: dict, previous: dict | None, limits: ImportLimits) -> dict:
    old = {item["drive_id"]: item for item in (previous or {}).get("arquivos", [])}
    records: dict[str, dict] = {}
    errors: list[dict] = []
    seen_folders: set[str] = set()
    items = 0
    downloaded = 0
    listing_complete = True
    managed = inbox / MANAGED

    def download(meta: dict, suffix: str, export_mime: str | None) -> dict:
        nonlocal downloaded
        if downloaded >= limits.max_total_bytes:
            raise DriveError("limite_total_download")
        if not export_mime and int(meta.get("size", 0)) > limits.max_file_bytes:
            raise DriveError("limite_por_arquivo")
        digest = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False)
        size = 0
        fd, name = tempfile.mkstemp(prefix=".download-", dir=managed)
        try:
            with os.fdopen(fd, "wb") as handle:
                stream = client.content(meta["id"], export_mime)
                try:
                    for chunk in stream:
                        size += len(chunk)
                        downloaded += len(chunk)
                        if size > limits.max_file_bytes:
                            raise DriveError("limite_por_arquivo")
                        if downloaded > limits.max_total_bytes:
                            raise DriveError("limite_total_download")
                        digest.update(chunk)
                        md5.update(chunk)
                        handle.write(chunk)
                finally:
                    close = getattr(stream, "close", None)
                    if close is not None:
                        close()
                handle.flush()
                os.fsync(handle.fileno())
            if export_mime and not size:
                raise DriveError("exportacao_vazia")
            if not export_mime:
                if "size" in meta and size != int(meta["size"]):
                    raise DriveError("download_tamanho_divergente")
                if meta.get("md5Checksum") and md5.hexdigest() != meta["md5Checksum"]:
                    raise DriveError("download_hash_divergente")
            after = client.metadata(meta["id"])
            _validar_metadata(after, meta["id"])
            if _versao(after) != _versao(meta):
                raise DriveError("arquivo_alterado_durante_download")
            sha = digest.hexdigest()
            relative = f"{MANAGED}/objects/{sha}{suffix}"
            material = {
                "caminho": relative, "sha256": sha, "bytes": size,
                "modified_time": meta["modifiedTime"], "version": meta.get("version"),
                "mime_type_origem": meta["mimeType"], "mime_type_exportacao": export_mime,
            }
            target = _objeto(inbox, {"materializado": material})
            if target.exists() and _hash(target) == sha:
                Path(name).unlink()
            else:
                os.replace(name, target)
            return material
        finally:
            Path(name).unlink(missing_ok=True)

    def visit(meta: dict, remote_path: str, depth: int) -> None:
        nonlocal items, listing_complete
        _validar_metadata(meta)
        if meta["mimeType"] == FOLDER_MIME:
            if meta["id"] in seen_folders:
                errors.append({"drive_id": meta["id"], "caminho_drive": remote_path, "codigo": "pasta_repetida_ou_ciclo"})
                listing_complete = False
                return
            seen_folders.add(meta["id"])
            try:
                if depth > limits.max_depth:
                    raise DriveError("limite_profundidade")
                for child in client.children(meta["id"]):
                    items += 1
                    if items > limits.max_items:
                        raise DriveError("limite_itens")
                    _validar_metadata(child)
                    if "parents" in child and meta["id"] not in child["parents"]:
                        raise DriveError("item_fora_da_pasta")
                    visit(child, remote_path + "/" + child["name"], depth + 1)
            except (DriveError, OSError, ValueError) as exc:
                listing_complete = False
                errors.append({"drive_id": meta["id"], "caminho_drive": remote_path, "codigo": str(exc) if isinstance(exc, DriveError) else "falha_local"})
            return
        file_id = meta["id"]
        if file_id in records:
            # O mesmo ID não deve ser baixado novamente em uma listagem repetida.
            if remote_path not in records[file_id]["caminhos_drive"]:
                records[file_id]["caminhos_drive"].append(remote_path)
            return
        previous = old.get(file_id, {})
        record = {
            "drive_id": file_id, "caminho_drive": remote_path, "caminhos_drive": [remote_path],
            "modified_time": meta["modifiedTime"], "version": meta.get("version"),
            "mime_type": meta["mimeType"], "ativo": True,
            "materializado": previous.get("materializado"), "status": "falha", "erro": None,
        }
        records[file_id] = record
        mime = meta["mimeType"]
        export_mime, suffix = EXPORTS.get(mime, (None, Path(meta["name"]).suffix.lower()))
        if mime.startswith("application/vnd.google-apps.") and mime not in EXPORTS:
            record.update(status="nao_suportado", erro="formato_google_ou_atalho_nao_suportado")
            return
        if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
            suffix = ".bin"
        try:
            if meta.get("capabilities", {}).get("canDownload") is False:
                raise DriveError("download_nao_permitido")
            material = previous.get("materializado")
            if material and material["caminho"].endswith(suffix) and (
                material["modified_time"], material.get("version"),
                material["mime_type_origem"], material["mime_type_exportacao"]
            ) == (meta["modifiedTime"], meta.get("version"), mime, export_mime):
                path = _objeto(inbox, previous)
                if path.is_file() and path.stat().st_size == material["bytes"] and _hash(path) == material["sha256"]:
                    record["status"] = "reutilizado"
                    return
            record["materializado"] = download(meta, suffix, export_mime)
            record["status"] = "baixado"
        except (DriveError, OSError, ValueError) as exc:
            record["erro"] = str(exc) if isinstance(exc, DriveError) else "falha_local"

    visit(root, root["name"], 0)
    for file_id, previous in old.items():
        if file_id not in records:
            # Uma falha de listagem não reativa remoção já confirmada.
            records[file_id] = dict(previous, ativo=previous["ativo"] and not listing_complete,
                                    status="nao_observado", erro=None)
    canonical: dict[str, str] = {}
    for file_id, record in sorted(records.items()):
        material = record.get("materializado")
        record["duplicata_de"] = None
        if material and record["ativo"]:
            path = material["caminho"]
            record["duplicata_de"] = canonical.get(path)
            canonical.setdefault(path, file_id)
    manifest = {
        "schema": 1, "raiz_id": folder_id, "raiz_nome": root["name"],
        "importado_em": datetime.now(timezone.utc).isoformat(), "algoritmo": "sha256",
        "completo": listing_complete and all(r["status"] not in {"falha", "nao_suportado"} for r in records.values()),
        "erros": errors, "arquivos": [record for _, record in sorted(records.items())],
    }
    _gravar_manifesto(managed / MANIFEST, manifest)
    return manifest
