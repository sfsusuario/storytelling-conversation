"""TikTok Content Posting API: OAuth login + subida del video final.

Dos modos:
- draft (default): el video llega a la bandeja de la app de TikTok y el
  usuario lo publica desde el teléfono. Funciona sin pasar la auditoría de
  contenido de TikTok. El endpoint de inbox no acepta caption: se imprime
  al final para pegarla en la app.
- --direct: publica sin paso manual (scope video.publish). OJO: mientras la
  app no pase la auditoría de TikTok, la visibilidad queda forzada a
  SELF_ONLY (privado, solo lo ve el dueño de la cuenta).

El login abre el navegador; como la Redirect URI registrada no tiene por
qué ser una página real, el usuario pega de vuelta la URL a la que TikTok
lo redirige y de ahí se extrae el authorization code. El token (con su
refresh_token, ~1 año) se guarda en .tiktok_token.json y se renueva solo.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import secrets
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from . import config  # noqa: F401  -- carga .env al importar

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
DIRECT_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

TOKEN_FILE = Path(".tiktok_token.json")

# Un solo chunk hasta 64 MB (los videos de <1 min salen muy por debajo);
# archivos mayores van en chunks de 64 MB, el último absorbe el resto
# (TikTok admite hasta 128 MB en el chunk final).
_MB = 1024 * 1024
MAX_SINGLE_CHUNK = 64 * _MB

PRIVACY_LEVELS = ["SELF_ONLY", "PUBLIC_TO_EVERYONE",
                  "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"]


class TikTokError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

def _credentials() -> tuple[str, str]:
    key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    secret_ = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not key or not secret_:
        raise TikTokError(
            "Faltan TIKTOK_CLIENT_KEY y/o TIKTOK_CLIENT_SECRET en .env "
            "(los da tu app en developers.tiktok.com)")
    return key, secret_


def _token_request(fields: dict) -> dict:
    key, secret_ = _credentials()
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"client_key": key, "client_secret": secret_, **fields},
        timeout=30)
    payload = resp.json()
    if "access_token" not in payload:
        raise TikTokError(
            f"TikTok OAuth ({payload.get('error', resp.status_code)}): "
            f"{payload.get('error_description', payload)}")
    now = time.time()
    payload["expires_at"] = now + payload.get("expires_in", 86400)
    payload["refresh_expires_at"] = now + payload.get("refresh_expires_in", 0)
    return payload


def login(scope: str) -> dict:
    """Authorization-code flow con pegado manual de la URL de redirección."""
    key, _ = _credentials()
    redirect_uri = os.environ.get("TIKTOK_REDIRECT_URI", "")
    if not redirect_uri:
        raise TikTokError(
            "Define TIKTOK_REDIRECT_URI en .env: exactamente la misma "
            "Redirect URI registrada en tu app de developers.tiktok.com "
            "(Login Kit). La página no tiene que existir: tras autorizar, "
            "copia la URL a la que te redirige TikTok y pégala aquí.")
    state = secrets.token_hex(16)
    url = AUTH_URL + "?" + urlencode({
        "client_key": key, "response_type": "code", "scope": scope,
        "redirect_uri": redirect_uri, "state": state})
    print("\nAbre esta URL, inicia sesión en TikTok y autoriza la app:\n\n"
          f"  {url}\n")
    webbrowser.open(url)
    pasted = input("Pega la URL completa a la que te redirigió TikTok: ").strip()
    qs = parse_qs(urlparse(pasted).query)
    if qs.get("state", [state])[0] != state:
        raise TikTokError("El parámetro state no coincide; repite el login.")
    code = (qs.get("code") or [""])[0]
    if not code:
        raise TikTokError("La URL pegada no contiene ?code=... — asegúrate "
                          "de copiar la URL de redirección completa.")
    token = _token_request({"grant_type": "authorization_code", "code": code,
                            "redirect_uri": redirect_uri})
    TOKEN_FILE.write_text(json.dumps(token, indent=2), encoding="utf-8")
    print(f"Login OK (scope: {token.get('scope', scope)}). "
          f"Token guardado en {TOKEN_FILE}")
    return token


def get_token(scope: str, force_login: bool = False,
              interactive: bool = True) -> dict:
    """Token vigente: cache -> refresh -> login interactivo. Con
    interactive=False (la UI, sin terminal) falla en vez de pedir input."""
    if not force_login and TOKEN_FILE.is_file():
        token = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        if time.time() < token.get("expires_at", 0) - 60:
            return token
        try:
            token = _token_request({
                "grant_type": "refresh_token",
                "refresh_token": token.get("refresh_token", "")})
            TOKEN_FILE.write_text(json.dumps(token, indent=2),
                                  encoding="utf-8")
            return token
        except TikTokError:
            pass  # refresh token vencido o revocado -> login completo
    if not interactive:
        raise TikTokError(
            "No hay sesión de TikTok válida (.tiktok_token.json). Corre una "
            "vez en la terminal: python -m charla.tiktok --login")
    return login(scope)


# ---------------------------------------------------------------------------
# Content Posting API
# ---------------------------------------------------------------------------

def _api(url: str, token: dict, body: dict) -> dict:
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token['access_token']}",
                 "Content-Type": "application/json; charset=UTF-8"},
        json=body, timeout=60)
    try:
        payload = resp.json()
    except ValueError:
        raise TikTokError(f"TikTok API HTTP {resp.status_code}: "
                          f"{resp.text[:200]}")
    err = payload.get("error") or {}
    if err.get("code", "ok") != "ok":
        raise TikTokError(f"TikTok API ({err.get('code')}): "
                          f"{err.get('message')}")
    return payload.get("data") or {}


def _chunk_plan(size: int) -> tuple[int, int]:
    if size <= MAX_SINGLE_CHUNK:
        return size, 1
    return MAX_SINGLE_CHUNK, size // MAX_SINGLE_CHUNK


class _ProgressReader:
    """File-like sobre un chunk en memoria: requests lo streamea en bloques
    y cada read() reporta bytes enviados (para barras de progreso)."""

    def __init__(self, blob: bytes, on_read):
        self._io = io.BytesIO(blob)
        self._size = len(blob)
        self._on_read = on_read

    def __len__(self) -> int:
        return self._size

    def read(self, n: int = -1) -> bytes:
        chunk = self._io.read(n)
        if chunk:
            self._on_read(len(chunk))
        return chunk


def _upload_file(upload_url: str, video: Path, chunk_size: int,
                 total_chunks: int, log=print, on_bytes=None) -> None:
    """PUT de los chunks; on_bytes(enviados, total) va reportando avance."""
    size = video.stat().st_size
    sent = 0

    def _tick(n: int) -> None:
        nonlocal sent
        sent += n
        on_bytes(sent, size)

    with video.open("rb") as f:
        for i in range(total_chunks):
            start = i * chunk_size
            end = size - 1 if i == total_chunks - 1 else start + chunk_size - 1
            f.seek(start)
            blob = f.read(end - start + 1)
            resp = requests.put(
                upload_url,
                data=_ProgressReader(blob, _tick) if on_bytes else blob,
                headers={"Content-Type": "video/mp4",
                         "Content-Range": f"bytes {start}-{end}/{size}"},
                timeout=600)
            if resp.status_code not in (200, 201, 206):
                raise TikTokError(f"Subida fallida (HTTP {resp.status_code}): "
                                  f"{resp.text[:200]}")
            log(f"  chunk {i + 1}/{total_chunks}: "
                f"{(end - start + 1) / _MB:.1f} MB subidos")


def upload_draft(token: dict, video: Path, log=print, on_bytes=None) -> str:
    """Sube el video a la bandeja de TikTok del usuario. Returns publish_id."""
    size = video.stat().st_size
    chunk, count = _chunk_plan(size)
    data = _api(INBOX_INIT_URL, token, {"source_info": {
        "source": "FILE_UPLOAD", "video_size": size,
        "chunk_size": chunk, "total_chunk_count": count}})
    log(f"subiendo {video} ({size / _MB:.1f} MB) a la bandeja de TikTok...")
    _upload_file(data["upload_url"], video, chunk, count, log, on_bytes)
    return data["publish_id"]


def upload_direct(token: dict, video: Path, caption: str, privacy: str,
                  log=print, on_bytes=None) -> str:
    """Publica directo en la cuenta (SELF_ONLY hasta pasar la auditoría)."""
    if "video.publish" not in token.get("scope", ""):
        raise TikTokError(
            "El token guardado no tiene el scope video.publish. Pon "
            "CHARLA_TIKTOK_SCOPE=video.upload,video.publish en .env y "
            "vuelve a correr: charla-upload --login")
    size = video.stat().st_size
    chunk, count = _chunk_plan(size)
    data = _api(DIRECT_INIT_URL, token, {
        "post_info": {"title": caption[:2200], "privacy_level": privacy},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk, "total_chunk_count": count}})
    log(f"subiendo {video} ({size / _MB:.1f} MB) como publicación directa...")
    _upload_file(data["upload_url"], video, chunk, count, log, on_bytes)
    return data["publish_id"]


def wait_publish(token: dict, publish_id: str, log=print,
                 timeout: float = 300.0) -> str:
    """Espera el estado terminal del publish: SEND_TO_USER_INBOX (draft
    entregado), PUBLISH_COMPLETE (post directo publicado) o error."""
    deadline = time.monotonic() + timeout
    while True:
        data = _api(STATUS_URL, token, {"publish_id": publish_id})
        status = data.get("status", "UNKNOWN")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return status
        if status == "FAILED":
            raise TikTokError("TikTok rechazó el video: "
                              f"{data.get('fail_reason', data)}")
        if time.monotonic() > deadline:
            raise TikTokError(f"Timeout esperando el estado ({status})")
        log(f"  estado: {status}...")
        time.sleep(3)


# ---------------------------------------------------------------------------
# CLI: charla-upload
# ---------------------------------------------------------------------------

def _resolve_video_and_caption(target: Path,
                               caption: str | None) -> tuple[Path, str]:
    """final.mp4 + caption: acepta el mp4 o el directorio del run; sin
    --caption usa el social.txt que el pipeline deja junto al video."""
    if target.is_dir():
        video, social = target / "final.mp4", target / "social.txt"
    else:
        video, social = target, target.with_name("social.txt")
    if not video.is_file():
        raise TikTokError(f"No existe el video: {video}")
    if caption is None and social.is_file():
        caption = " ".join(social.read_text(encoding="utf-8").split())
    return video, (caption or "").strip()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="charla-upload",
        description="Sube el final.mp4 de un run a TikTok (Content Posting "
                    "API). Default: modo draft — el video llega a tu bandeja "
                    "de TikTok y lo publicas desde la app.")
    p.add_argument("video", nargs="?", type=Path,
                   help="final.mp4 o el directorio de salida del run "
                        "(usa su final.mp4 y su social.txt)")
    p.add_argument("--caption", default=None,
                   help="Caption del post (default: el social.txt del run). "
                        "Solo aplica con --direct; en draft se imprime para "
                        "pegarla en la app")
    p.add_argument("--direct", action="store_true",
                   help="Publicación directa sin paso manual (requiere scope "
                        "video.publish; SELF_ONLY hasta pasar la auditoría "
                        "de TikTok)")
    p.add_argument("--privacy", default="SELF_ONLY", choices=PRIVACY_LEVELS,
                   help="Visibilidad con --direct (default SELF_ONLY; las "
                        "apps sin auditar solo pueden SELF_ONLY)")
    p.add_argument("--login", action="store_true",
                   help="Fuerza un nuevo login OAuth (sin video, solo hace "
                        "el login y termina)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.video and not args.login:
        build_parser().error("indica el final.mp4 o el directorio del run "
                             "(o usa --login)")
    scope = os.environ.get("CHARLA_TIKTOK_SCOPE") or (
        "video.upload,video.publish" if args.direct else "video.upload")
    try:
        token = get_token(scope, force_login=args.login)
        if not args.video:
            return 0
        video, caption = _resolve_video_and_caption(args.video, args.caption)
        if args.direct:
            publish_id = upload_direct(token, video, caption, args.privacy)
            status = wait_publish(token, publish_id)
            print(f"\nPublicado ({status}, {args.privacy}). "
                  f"publish_id: {publish_id}")
        else:
            publish_id = upload_draft(token, video)
            status = wait_publish(token, publish_id)
            print(f"\nListo ({status}): abre TikTok en el teléfono — el "
                  "video está en tus notificaciones/bandeja para publicar.")
            if caption:
                print(f"\nCaption sugerida (pégala en la app):\n{caption}")
    except TikTokError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
