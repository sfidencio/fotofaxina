"""Cliente mínimo da Google Photos Library API (upload + álbuns criados pelo app).

Desde 31/03/2025 a API só enxerga o que o próprio app enviou. Por isso o controle
de duplicatas e de "já enviado" é todo feito no banco local.
"""
from __future__ import annotations

import os
import shutil
import time

from . import secure_store
from .config import CLIENT_SECRET_PATH, TOKEN_PATH, resource
from .i18n import _

SCOPES = [
    "https://www.googleapis.com/auth/photoslibrary.appendonly",
    "https://www.googleapis.com/auth/photoslibrary.edit.appcreateddata",
]
API = "https://photoslibrary.googleapis.com/v1"
BATCH_LIMIT = 50


class GooglePhotosError(Exception):
    pass


class NotConnected(GooglePhotosError):
    pass


class QuotaExceeded(GooglePhotosError):
    pass


def bundled_secret_path():
    """Credencial embutida no instalador (gerada no build a partir de um secret do GitHub)."""
    p = resource("client_secret.json")
    return p if p.exists() else None


def secret_path():
    if CLIENT_SECRET_PATH.exists():
        return CLIENT_SECRET_PATH
    return bundled_secret_path()


def has_client_secret() -> bool:
    return secret_path() is not None


def install_client_secret(src: str) -> None:
    CLIENT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, CLIENT_SECRET_PATH)


def disconnect() -> None:
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


def EXPIRED_MSG() -> str:  # função: o idioma é escolhido depois do import
    return _("O login no Google expirou (enquanto o app está em modo de teste no Google Cloud, isso "
             "acontece a cada 7 dias). Clique em “Conectar conta Google” na aba Configurações.")


def load_credentials():
    """Lê o login salvo (protegido pela criptografia do Windows quando disponível)."""
    import json

    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.exists():
        return None
    data = TOKEN_PATH.read_bytes()
    try:
        info = json.loads(secure_store.unprotect(data).decode("utf-8"))
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    except Exception:
        return None  # arquivo corrompido ou de outro usuário do Windows: pede login de novo
    if secure_store.needs_upgrade(data):
        save_credentials(creds)  # token de versão antiga, em texto: protege agora
    return creds


def save_credentials(creds) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    secure_store.write_private(TOKEN_PATH, secure_store.protect(creds.to_json().encode("utf-8")))


class GooglePhotos:
    def __init__(self):
        self.session = None

    # ---------- autenticação ----------
    def connect(self, interactive: bool = True) -> None:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import AuthorizedSession, Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = load_credentials()
        expired = False
        if creds and not creds.valid and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # app em modo "Teste" no Google Cloud: o login vale 7 dias. Apaga o token para a
                # tela não continuar dizendo "conectada".
                creds, expired = None, True
                disconnect()
        if not creds or not creds.valid:
            if not interactive:
                raise NotConnected(EXPIRED_MSG() if expired else _("Conecte sua conta Google na aba Configurações."))
            if not has_client_secret():
                raise NotConnected(_("Selecione o arquivo client_secret.json na aba Configurações."))
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path()), SCOPES)
            creds = flow.run_local_server(
                port=0, open_browser=True,
                authorization_prompt_message=_("Abrindo o navegador para login no Google…"),
                success_message=_("Pronto! Pode fechar esta aba e voltar ao FotoFaxina."),
            )
        save_credentials(creds)
        self.session = AuthorizedSession(creds)

    # ---------- HTTP com retentativa ----------
    def _request(self, method: str, url: str, *, body_path: str | None = None, **kw):
        if self.session is None:
            raise NotConnected(_("Conta Google não conectada."))
        import requests
        from google.auth.exceptions import RefreshError

        delay = 2.0
        resp = None
        for attempt in range(7):
            try:
                if body_path is not None:
                    with open(body_path, "rb") as fh:
                        resp = self.session.request(method, url, data=fh, timeout=600, **kw)
                else:
                    resp = self.session.request(method, url, timeout=120, **kw)
            except RefreshError as e:  # o login expirou no meio do envio
                disconnect()
                raise NotConnected(EXPIRED_MSG()) from e
            except (requests.ConnectionError, requests.Timeout) as e:
                # internet caiu ou oscilou: espera e tenta de novo
                if attempt == 6:
                    raise GooglePhotosError(_("Sem conexão com o Google Fotos: {erro}").format(erro=e)) from e
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            if resp.status_code < 400:
                return resp
            if resp.status_code == 429:
                text = resp.text.lower()
                if "per day" in text or attempt >= 4:
                    raise QuotaExceeded(_(
                        "Limite diário da API do Google Fotos atingido. Continue amanhã — "
                        "o que já foi enviado fica registrado."
                    ))
            elif resp.status_code < 500:
                raise GooglePhotosError(f"{resp.status_code}: {resp.text[:300]}")
            time.sleep(delay)
            delay = min(delay * 2, 60)
        raise GooglePhotosError(_("Falha após várias tentativas ({codigo}): {texto}").format(
            codigo=resp.status_code, texto=resp.text[:300]))

    # ---------- operações ----------
    def upload_bytes(self, path: str, mime: str | None) -> str:
        headers = {
            "Content-type": "application/octet-stream",
            "X-Goog-Upload-Protocol": "raw",
            "X-Goog-Upload-File-Name": os.path.basename(path).encode("ascii", "ignore").decode() or "foto",
        }
        if mime:
            headers["X-Goog-Upload-Content-Type"] = mime
        resp = self._request("POST", f"{API}/uploads", body_path=path, headers=headers)
        return resp.text.strip()

    def create_album(self, title: str) -> tuple[str, str | None]:
        """Cria o álbum e devolve (id, link para abrir no Google Fotos)."""
        resp = self._request("POST", f"{API}/albums", json={"album": {"title": title[:500]}})
        data = resp.json()
        return data["id"], data.get("productUrl")

    def rename_album(self, album_id: str, title: str) -> None:
        self._request(
            "PATCH", f"{API}/albums/{album_id}", params={"updateMask": "title"},
            json={"title": title[:500]},
        )

    def batch_create(self, album_id: str | None, items: list[tuple[str, str]]) -> dict[str, tuple[bool, str]]:
        """items: (upload_token, nome_arquivo). Retorna {token: (ok, media_id_ou_erro)}."""
        body = {
            "newMediaItems": [
                {"simpleMediaItem": {"uploadToken": tok, "fileName": name}} for tok, name in items
            ]
        }
        if album_id:
            body["albumId"] = album_id
        resp = self._request("POST", f"{API}/mediaItems:batchCreate", json=body)
        out = {}
        for res in resp.json().get("newMediaItemResults", []):
            tok = res.get("uploadToken")
            status = res.get("status", {})
            media = res.get("mediaItem")
            if media and status.get("code", 0) == 0:
                out[tok] = (True, media["id"])
            else:
                out[tok] = (False, status.get("message", "erro desconhecido"))
        return out
