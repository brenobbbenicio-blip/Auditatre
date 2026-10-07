"""Corpus e transporte fictícios: nenhum teste acessa o Drive real."""

import hashlib
import io
import json
import socket
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from openpyxl import Workbook

from auditatre.cli import main
from auditatre.drive_api import DriveAPI, DriveError, FOLDER_MIME
from auditatre.drive_import import EXPORTS, MANAGED, ImportLimits, importar
from auditatre.run import executar
from tests.pdfutil import pdf_texto


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A suíte Drive deve usar somente transporte fictício")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def folder(file_id, name="Corpus", parent=None):
    return {"id": file_id, "name": name, "mimeType": FOLDER_MIME,
            **({"parents": [parent]} if parent else {})}


def file(file_id, name="doc.txt", data=b"Ata de reuniao.", parent="root", mime="text/plain", version="1"):
    return {"id": file_id, "name": name, "mimeType": mime,
            "modifiedTime": f"2026-10-0{version}T12:00:00Z", "version": version,
            "parents": [parent], "size": str(len(data)),
            "md5Checksum": hashlib.md5(data, usedforsecurity=False).hexdigest()}


class FakeDrive:
    def __init__(self, entries, contents=None):
        self.entries = {entry["id"]: entry for entry in entries}
        self.contents = contents or {}
        self.fail_files = set()
        self.fail_folders = set()
        self.calls = []
        self.changed_on_download = None
        self.closed = False

    def metadata(self, file_id):
        if file_id not in self.entries:
            raise DriveError("http_404")
        return dict(self.entries[file_id])

    def children(self, folder_id):
        if folder_id in self.fail_folders:
            raise DriveError("http_403")
        yield from (dict(entry) for entry in self.entries.values() if folder_id in entry.get("parents", []))

    def content(self, file_id, export_mime):
        self.calls.append((file_id, export_mime))
        data = self.contents.get(file_id, b"Ata de reuniao.")
        yield data[:3]
        if file_id in self.fail_files:
            raise DriveError("download_interrompido")
        yield data[3:]
        if self.changed_on_download == file_id:
            self.entries[file_id]["version"] = "99"

    def close(self):
        self.closed = True


def records(manifest):
    return {item["drive_id"]: item for item in manifest["arquivos"]}


def material_path(inbox, record):
    return inbox / record["materializado"]["caminho"]


def test_recursao_dedup_nomes_hostis_e_proveniencia(tmp_path):
    inbox = tmp_path / "inbox"
    data = b"Contrato n 41/2025."
    drive = FakeDrive([
        folder("root"), folder("sub", "Orcamento", "root"),
        folder("deep", "2026", "sub"),
        file("a", "mesmo.txt", data), file("b", "../../mesmo.txt", data, "deep"),
        file("c", "mesmo.txt", b"Ata de reuniao.", "sub"),
    ], {"a": data, "b": data})
    manifest = importar(drive, "root", inbox)
    assert manifest["completo"]
    items = records(manifest)
    assert items["b"]["caminho_drive"] == "Corpus/Orcamento/2026/../../mesmo.txt"
    assert items["a"]["materializado"]["caminho"] == items["b"]["materializado"]["caminho"]
    assert items["b"]["duplicata_de"] == "a"
    assert len(list((inbox / MANAGED / "objects").iterdir())) == 2
    assert not (tmp_path / "mesmo.txt").exists()
    result = executar(inbox, tmp_path / "out")
    assert len(result["inventario"]) == 2
    entry = next(entry for entry in result["inventario"] if len(entry["drive"]) == 2)
    assert {origin["drive_id"] for origin in entry["drive"]} == {"a", "b"}
    output = json.loads((tmp_path / "out" / "manifesto.json").read_text())
    assert output["importacao_drive"] == manifest
    assert output["entradas"][0]["drive"]
    assert not any("manifesto.json" in entry["caminho"] for entry in result["inventario"])


def test_atualizacao_reutiliza_e_nao_ingere_versao_antiga(tmp_path):
    inbox = tmp_path / "inbox"
    first = b"Contrato n 1/2025."
    second = b"Contrato n 2/2025."
    drive = FakeDrive([folder("root"), file("a", data=first)], {"a": first})
    old = records(importar(drive, "root", inbox))["a"]
    assert records(importar(drive, "root", inbox))["a"]["status"] == "reutilizado"
    assert len(drive.calls) == 1
    drive.entries["a"] = file("a", "Renomeado.txt", second, version="2")
    drive.contents["a"] = second
    new = records(importar(drive, "root", inbox))["a"]
    assert material_path(inbox, old).read_bytes() == first
    assert material_path(inbox, new).read_bytes() == second
    assert new["materializado"]["sha256"] != old["materializado"]["sha256"]
    assert new["caminho_drive"] == "Corpus/Renomeado.txt"
    result = executar(inbox, tmp_path / "out")
    assert len(result["inventario"]) == 1
    assert result["inventario"][0]["sha256"] == new["materializado"]["sha256"]


def test_falha_parcial_preserva_bytes_e_data_da_copia_anterior(tmp_path):
    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), file("a")])
    old = records(importar(drive, "root", inbox))["a"]
    drive.entries["a"] = file("a", data=b"Novo contrato", version="2")
    drive.contents["a"] = b"Novo contrato"
    drive.entries["b"] = file("b")
    drive.fail_files.add("a")
    manifest = importar(drive, "root", inbox)
    assert not manifest["completo"]
    items = records(manifest)
    assert items["a"]["status"] == "falha"
    assert items["a"]["modified_time"] != items["a"]["materializado"]["modified_time"]
    assert items["a"]["materializado"] == old["materializado"]
    assert material_path(inbox, old).read_bytes() == b"Ata de reuniao."
    assert items["b"]["status"] == "baixado"
    assert not list((inbox / MANAGED).glob(".download-*"))
    result = executar(inbox, tmp_path / "out")
    assert any(item["fase"] == "importacao" for item in result["lacunas"])


def test_listagem_parcial_preserva_subpasta_e_exclusao_confirmada_desativa(tmp_path):
    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), folder("sub", parent="root"), file("a", parent="sub")])
    original = records(importar(drive, "root", inbox))["a"]
    drive.fail_folders.add("sub")
    partial = importar(drive, "root", inbox)
    assert not partial["completo"]
    assert records(partial)["a"]["ativo"]
    assert records(partial)["a"]["status"] == "nao_observado"
    drive.fail_folders.clear()
    del drive.entries["a"]
    complete = importar(drive, "root", inbox)
    assert complete["completo"]
    assert not records(complete)["a"]["ativo"]
    assert material_path(inbox, original).is_file()
    assert executar(inbox, tmp_path / "out")["inventario"] == []
    drive.fail_folders.add("sub")
    partial = importar(drive, "root", inbox)
    assert not partial["completo"]
    assert not records(partial)["a"]["ativo"]
    assert executar(inbox, tmp_path / "out")["inventario"] == []


def test_exportacao_google_para_formatos_suportados(tmp_path):
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", "<document><p>Ata de reuniao.</p></document>")
    workbook = Workbook()
    workbook.active.append(["CNPJ", "Empenhado"])
    workbook.active.append(["11.222.333/0001-81", "R$ 100,00"])
    workbook.create_sheet("Segunda aba").append(["Contrato", "41/2025"])
    sheet = io.BytesIO()
    workbook.save(sheet)
    workbook.close()
    contents = {"doc": docx.getvalue(), "sheet": sheet.getvalue(),
                "slides": pdf_texto("Ata de reuniao."), "drawing": pdf_texto("Ata de reuniao.")}
    kinds = dict(zip(contents, EXPORTS))
    entries = [folder("root")]
    for file_id, mime in kinds.items():
        meta = file(file_id, file_id, contents[file_id], mime=mime)
        # Formatos Google não têm hash/tamanho dos bytes exportados no Drive.
        meta.pop("size")
        meta.pop("md5Checksum")
        entries.append(meta)
    drive = FakeDrive(entries, contents)
    manifest = importar(drive, "root", tmp_path / "inbox")
    assert manifest["completo"]
    assert set(drive.calls) == {(file_id, EXPORTS[mime][0]) for file_id, mime in kinds.items()}
    for item in manifest["arquivos"]:
        assert item["materializado"]["caminho"].endswith(EXPORTS[item["mime_type"]][1])
    result = executar(tmp_path / "inbox", tmp_path / "out")
    assert all(item["status"] == "extraido" for item in result["inventario"])
    sheet_act = next(act for act in result["matriz"]["atos"] if act["hipoteses"])
    assert not sheet_act["hipoteses"][0]["confirmada"]


def test_zip_importado_continua_sujeito_as_regras_de_seguranca(tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "Nao")
    data = archive.getvalue()
    drive = FakeDrive([folder("root"), file("zip", "documentos.zip", data)], {"zip": data})
    importar(drive, "root", tmp_path / "inbox")
    result = executar(tmp_path / "inbox", tmp_path / "out")
    assert result["inventario"][0]["status"] == "zip_recusado"
    assert result["inventario"][0]["drive"][0]["drive_id"] == "zip"


@pytest.mark.parametrize("fault", ["size", "hash", "during_download"])
def test_download_inconsistente_nao_e_publicado(tmp_path, fault):
    drive = FakeDrive([folder("root"), file("a")])
    if fault == "size":
        drive.entries["a"]["size"] = "999"
    elif fault == "hash":
        drive.entries["a"]["md5Checksum"] = "0" * 32
    else:
        drive.changed_on_download = "a"
    manifest = importar(drive, "root", tmp_path / "inbox")
    assert not manifest["completo"]
    assert records(manifest)["a"]["materializado"] is None
    assert not list((tmp_path / "inbox" / MANAGED / "objects").iterdir())


@pytest.mark.parametrize("limits,error", [
    (ImportLimits(max_file_bytes=5), "limite_por_arquivo"),
    (ImportLimits(max_total_bytes=5), "limite_total_download"),
    (ImportLimits(max_items=1), "limite_itens"),
    (ImportLimits(max_depth=1), "limite_profundidade"),
])
def test_limites(tmp_path, limits, error):
    drive = FakeDrive([folder("root"), folder("sub", parent="root"),
                      folder("deep", parent="sub"), file("a", parent="deep")])
    manifest = importar(drive, "root", tmp_path / "inbox", limits=limits)
    assert not manifest["completo"]
    assert error in json.dumps(manifest)


def test_atalho_nao_expande_escopo_e_formato_google_desconhecido_fica_pendente(tmp_path):
    drive = FakeDrive([folder("root"),
                      file("a", mime="application/vnd.google-apps.shortcut"),
                      file("b", mime="application/vnd.google-apps.form")])
    manifest = importar(drive, "root", tmp_path / "inbox")
    assert not manifest["completo"]
    assert all(item["status"] == "nao_suportado" for item in manifest["arquivos"])
    assert drive.calls == []


def test_corrupcao_externa_recusada_e_recuperada_por_importacao(tmp_path):
    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), file("a")])
    item = records(importar(drive, "root", inbox))["a"]
    material_path(inbox, item).write_bytes(b"modificado")
    with pytest.raises(DriveError, match="corrompido"):
        executar(inbox, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert importar(drive, "root", inbox)["completo"]
    assert len(drive.calls) == 2


def test_symlink_manifesto_malicioso_e_lock_recusados(tmp_path):
    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), file("a")])
    importar(drive, "root", inbox)
    lock = inbox / MANAGED / ".import.lock"
    lock.touch()
    with pytest.raises(DriveError, match="lock"):
        importar(drive, "root", inbox)
    lock.unlink()
    manifest_path = inbox / MANAGED / "manifesto.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["arquivos"][0]["materializado"]["caminho"] = "../../escape.txt"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DriveError, match="manifesto"):
        executar(inbox, tmp_path / "out")
    manifest_path.unlink()
    outside = tmp_path / "outside"
    outside.mkdir()
    (inbox / MANAGED / "objects").rename(inbox / MANAGED / "old-objects")
    (inbox / MANAGED / "objects").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DriveError, match="symlink"):
        importar(drive, "root", inbox)
    assert list(outside.iterdir()) == []


def test_git_recusa_inbox_versionavel_e_aceita_ignorado(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    drive = FakeDrive([folder("root"), file("a")])
    with pytest.raises(DriveError, match="ignorado"):
        importar(drive, "root", tmp_path / "corpus")
    (tmp_path / ".gitignore").write_text("inbox/\n")
    assert importar(drive, "root", tmp_path / "inbox")["completo"]
    (tmp_path / "inbox" / "tracked.txt").write_text("ficticio")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", "inbox/tracked.txt"], check=True)
    with pytest.raises(DriveError, match="ignorado"):
        importar(drive, "root", tmp_path / "inbox")


def test_raiz_invalida_ou_indisponivel_nao_muda_manifesto(tmp_path):
    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), file("a")])
    importar(drive, "root", inbox)
    path = inbox / MANAGED / "manifesto.json"
    original = path.read_bytes()
    del drive.entries["root"]
    with pytest.raises(DriveError, match="404"):
        importar(drive, "root", inbox)
    assert path.read_bytes() == original
    with pytest.raises(DriveError, match="outra_pasta"):
        importar(drive, "different", inbox)
    assert path.read_bytes() == original


def test_cli_importa_antes_de_ingerir_e_para_em_falha_parcial(tmp_path, monkeypatch):
    drive = FakeDrive([folder("root"), file("a")])
    monkeypatch.setattr(DriveAPI, "from_default_credentials", lambda: drive)
    inbox, out = tmp_path / "inbox", tmp_path / "out"
    args = ["--inbox", str(inbox), "--out", str(out), "--drive-folder", "root"]
    assert main(args + ["--import-only"]) == 0
    assert not out.exists()
    assert drive.closed
    assert main(args) == 0
    original = (out / "manifesto.json").read_bytes()
    drive.entries["a"] = file("a", version="2")
    drive.fail_files.add("a")
    assert main(args) == 3
    assert (out / "manifesto.json").read_bytes() == original


def test_cli_offline_nao_instancia_cliente(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail("Modo offline tentou abrir um cliente de rede")
    monkeypatch.setattr(DriveAPI, "from_default_credentials", forbidden)
    assert main(["--inbox", str(tmp_path / "missing")]) == 2
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "ata.txt").write_text("Ata de reuniao.")
    assert main(["--inbox", str(inbox), "--out", str(tmp_path / "out")]) == 0


def test_falha_ao_gravar_manifesto_preserva_snapshot_e_ignora_objeto_orfao(tmp_path, monkeypatch):
    import auditatre.drive_import as module

    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), file("a")])
    old = importar(drive, "root", inbox)
    manifest_path = inbox / MANAGED / "manifesto.json"
    original = manifest_path.read_bytes()
    drive.entries["a"] = file("a", data=b"Novo contrato", version="2")
    drive.contents["a"] = b"Novo contrato"
    real_replace = module.os.replace

    def fail_manifest(source, target):
        if Path(target) == manifest_path:
            raise OSError("falha ficticia de disco")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", fail_manifest)
    with pytest.raises(OSError):
        importar(drive, "root", inbox)
    assert manifest_path.read_bytes() == original
    assert not (inbox / MANAGED / ".import.lock").exists()
    assert not list((inbox / MANAGED).glob(".manifest-*"))
    assert len(list((inbox / MANAGED / "objects").iterdir())) == 2
    result = executar(inbox, tmp_path / "out")
    assert len(result["inventario"]) == 1
    assert result["inventario"][0]["sha256"] == records(old)["a"]["materializado"]["sha256"]


def test_atualizacao_de_duplicata_nao_altera_a_outra_copia(tmp_path):
    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), file("a"), file("b")])
    old = records(importar(drive, "root", inbox))
    drive.entries["a"] = file("a", data=b"Contrato atualizado.", version="2")
    drive.contents["a"] = b"Contrato atualizado."
    current = records(importar(drive, "root", inbox))
    assert current["b"]["materializado"] == old["b"]["materializado"]
    assert material_path(inbox, current["b"]).read_bytes() == b"Ata de reuniao."
    assert material_path(inbox, current["a"]).read_bytes() == b"Contrato atualizado."
    assert len(executar(inbox, tmp_path / "out")["inventario"]) == 2


def test_renomear_extensao_atualiza_formato_local(tmp_path):
    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), file("a")])
    importar(drive, "root", inbox)
    drive.entries["a"]["name"] = "planilha.csv"
    new = records(importar(drive, "root", inbox))["a"]
    assert new["materializado"]["caminho"].endswith(".csv")


def test_ciclo_de_pastas_e_item_fora_da_raiz_ficam_pendentes(tmp_path):
    drive = FakeDrive([folder("root"), folder("sub", parent="root")])
    drive.entries["root"]["parents"] = ["sub"]
    assert not importar(drive, "root", tmp_path / "cycle")["completo"]

    class WrongParent(FakeDrive):
        def children(self, folder_id):
            yield file("outside", parent="outside-folder")

    drive = WrongParent([folder("root")])
    manifest = importar(drive, "root", tmp_path / "outside")
    assert not manifest["completo"]
    assert manifest["erros"][0]["codigo"] == "item_fora_da_pasta"
    assert drive.calls == []


def test_download_proibido_e_limite_total_interrompem_novas_transferencias(tmp_path):
    drive = FakeDrive([folder("root"), file("a"), file("b"), file("c")])
    drive.entries["a"]["capabilities"] = {"canDownload": False}
    manifest = importar(drive, "root", tmp_path / "inbox", limits=ImportLimits(max_total_bytes=2))
    assert not manifest["completo"]
    assert records(manifest)["a"]["erro"] == "download_nao_permitido"
    assert drive.calls == [("b", None)]


def test_exportacao_vazia_nao_informa_sucesso(tmp_path):
    mime = "application/vnd.google-apps.spreadsheet"
    drive = FakeDrive([folder("root"), file("a", data=b"", mime=mime)], {"a": b""})
    manifest = importar(drive, "root", tmp_path / "inbox")
    assert not manifest["completo"]
    assert records(manifest)["a"]["erro"] == "exportacao_vazia"
    assert records(manifest)["a"]["materializado"] is None


@pytest.mark.parametrize("key", ["schema", "completo", "ativo", "bytes"])
def test_manifesto_incompleto_ou_malformado_para_antes_da_saida(tmp_path, key):
    inbox = tmp_path / "inbox"
    drive = FakeDrive([folder("root"), file("a")])
    manifest = importar(drive, "root", inbox)
    if key in {"schema", "completo"}:
        del manifest[key]
    elif key == "ativo":
        del manifest["arquivos"][0][key]
    else:
        manifest["arquivos"][0]["materializado"][key] = "invalid"
    (inbox / MANAGED / "manifesto.json").write_text(json.dumps(manifest))
    with pytest.raises(DriveError, match="manifesto"):
        executar(inbox, tmp_path / "out")
    assert not (tmp_path / "out").exists()


class Response:
    def __init__(self, status=200, data=None, chunks=()):
        self.status_code, self.data, self.chunks = status, data, chunks
        self.closed = False

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


class Session:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def get(self, url, **kwargs):
        self.calls.append((url, {**kwargs, "params": dict(kwargs["params"])}))
        return next(self.responses)


def test_api_pagina_filtra_pasta_e_exporta_sem_redirect():
    session = Session([
        Response(data={"files": [{"id": "a"}], "nextPageToken": "next"}),
        Response(data={"files": [{"id": "b"}]}),
        Response(chunks=[b"xlsx"]), Response(chunks=[b"pdf"]),
    ])
    client = DriveAPI(session)
    assert list(client.children("root")) == [{"id": "a"}, {"id": "b"}]
    assert session.calls[1][1]["params"]["pageToken"] == "next"
    assert session.calls[0][1]["params"]["q"] == "'root' in parents and trashed = false"
    assert b"".join(client.content("a", EXPORTS["application/vnd.google-apps.spreadsheet"][0])) == b"xlsx"
    assert session.calls[2][0].endswith("/a/export")
    assert b"".join(client.content("b", None)) == b"pdf"
    assert session.calls[3][1]["params"]["alt"] == "media"
    assert all(call[1]["allow_redirects"] is False for call in session.calls)


@pytest.mark.parametrize("status", [302, 401, 403, 404])
def test_api_erros_nao_expoem_corpo_ou_credenciais(status):
    response = Response(status=status, data={"secret": "TOKEN_FICTICIO"})
    with pytest.raises(DriveError) as exc:
        DriveAPI(Session([response])).metadata("a")
    assert str(exc.value) == f"http_{status}"
    assert response.closed


def test_api_retry_busca_incompleta_e_token_repetido(monkeypatch):
    monkeypatch.setattr("auditatre.drive_api.time.sleep", lambda _: None)
    retry = Response(status=429)
    session = Session([retry, Response(data=folder("root"))])
    assert DriveAPI(session).metadata("root")["id"] == "root"
    assert retry.closed
    with pytest.raises(DriveError, match="busca_incompleta"):
        list(DriveAPI(Session([Response(data={"files": [], "incompleteSearch": True})])).children("root"))
    page = {"files": [], "nextPageToken": "same"}
    with pytest.raises(DriveError, match="paginacao"):
        list(DriveAPI(Session([Response(data=page), Response(data=page)])).children("root"))


def test_adc_pede_somente_escopo_de_leitura_e_nao_expoe_erro(monkeypatch):
    from auditatre.drive_api import READONLY_SCOPE

    google = ModuleType("google")
    auth = ModuleType("google.auth")
    transport = ModuleType("google.auth.transport")
    request_transport = ModuleType("google.auth.transport.requests")
    google.auth = auth
    auth.transport = transport
    transport.requests = request_transport
    for module in (google, auth, transport, request_transport):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    credentials, session = object(), object()
    requested = []

    def default(scopes):
        requested.extend(scopes)
        return credentials, "project-ficticio"

    def authorized_session(value):
        assert value is credentials
        return session

    auth.default = default
    request_transport.AuthorizedSession = authorized_session
    assert DriveAPI.from_default_credentials().session is session
    assert requested == [READONLY_SCOPE]

    def failed(scopes):
        raise ValueError("TOKEN_FICTICIO que nao pode aparecer")

    auth.default = failed
    with pytest.raises(DriveError) as exc:
        DriveAPI.from_default_credentials()
    assert str(exc.value) == "credenciais_adc_indisponiveis"


@pytest.mark.parametrize("file_id", ["../secret", "root' or trashed=true", "https://evil.test", ""])
def test_id_nao_pode_injetar_url_ou_consulta(file_id):
    with pytest.raises(DriveError, match="id_drive"):
        DriveAPI(Session([])).metadata(file_id)
