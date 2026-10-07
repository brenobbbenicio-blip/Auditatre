"""Adaptador opcional da API Drive v3. Apenas GET e escopo de leitura."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator

FOLDER_MIME = "application/vnd.google-apps.folder"
FIELDS = "id,name,mimeType,modifiedTime,version,size,md5Checksum,trashed,parents,capabilities(canDownload)"
READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class DriveError(Exception):
    """Código seguro: não expõe URL, corpo HTTP ou credenciais."""


def validar_id(file_id: str) -> str:
    if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", file_id):
        raise DriveError("id_drive_invalido")
    return file_id


class DriveAPI:
    def __init__(self, session: object):
        self.session = session

    @classmethod
    def from_default_credentials(cls) -> DriveAPI:
        # Importação tardia: o modo offline não precisa do extra [drive].
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
        except ImportError:
            raise DriveError("instale_o_extra_drive") from None
        try:
            credentials, _ = google.auth.default(scopes=[READONLY_SCOPE])
            return cls(AuthorizedSession(credentials))
        except Exception:
            raise DriveError("credenciais_adc_indisponiveis") from None

    def _get(self, endpoint: str, params: dict[str, object], *, stream: bool = False):
        for tentativa in range(3):
            try:
                response = self.session.get(
                    "https://www.googleapis.com/drive/v3/files" + endpoint,
                    params=params, timeout=(10, 60), stream=stream,
                    allow_redirects=False,
                )
            except Exception:
                raise DriveError("falha_transporte") from None
            if response.status_code in {429, 500, 502, 503, 504} and tentativa < 2:
                response.close()
                time.sleep(tentativa + 1)
                continue
            if response.status_code != 200:
                code = response.status_code
                response.close()
                raise DriveError(f"http_{code}")
            return response
        raise DriveError("falha_transporte")

    def _json(self, endpoint: str, params: dict[str, object]) -> dict:
        response = self._get(endpoint, params)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except Exception:
            raise DriveError("resposta_json_invalida") from None
        finally:
            response.close()

    def metadata(self, file_id: str) -> dict:
        return self._json("/" + validar_id(file_id), {"fields": FIELDS, "supportsAllDrives": "true"})

    def children(self, folder_id: str) -> Iterator[dict]:
        params: dict[str, object] = {
            "q": f"'{validar_id(folder_id)}' in parents and trashed = false",
            "fields": f"nextPageToken,incompleteSearch,files({FIELDS})",
            "pageSize": 1000, "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        tokens: set[str] = set()
        while True:
            page = self._json("", params)
            if page.get("incompleteSearch"):
                raise DriveError("busca_incompleta")
            if not isinstance(page.get("files"), list):
                raise DriveError("listagem_invalida")
            yield from page["files"]
            token = page.get("nextPageToken")
            if not token:
                return
            if not isinstance(token, str) or token in tokens:
                raise DriveError("paginacao_invalida")
            tokens.add(token)
            params["pageToken"] = token

    def content(self, file_id: str, export_mime: str | None) -> Iterator[bytes]:
        endpoint = "/" + validar_id(file_id)
        params = {"alt": "media", "supportsAllDrives": "true"}
        if export_mime:
            endpoint += "/export"
            params = {"mimeType": export_mime}
        response = self._get(endpoint, params, stream=True)
        try:
            yield from response.iter_content(chunk_size=1024 * 1024)
        except Exception:
            # Nunca recomeça um stream parcial concatenando cópias dos bytes.
            raise DriveError("download_interrompido") from None
        finally:
            response.close()

    def close(self) -> None:
        self.session.close()
