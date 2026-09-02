"""
mcp/google/auth.py
==================
Gerencia o fluxo OAuth 2.0 do Google sem dependências externas.

Fluxo:
  1. Lê client_secret.json (gerado no Google Cloud Console)
  2. Se token.json existir e for válido, usa direto
  3. Se o access_token expirou mas há refresh_token, renova automaticamente
  4. Se não há token, abre o browser pro consentimento e salva o token

Env vars reconhecidas:
  GOOGLE_CLIENT_SECRET  — caminho para client_secret.json (obrigatório)
  GOOGLE_TOKEN_STORE    — caminho para salvar token.json
                          (padrão: ~/.ciel/google_token.json)

Uso:
    from mcp.google.auth import GoogleAuth
    auth = GoogleAuth(scopes=[...])
    headers = auth.auth_headers()   # {"Authorization": "Bearer <token>"}
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

# ── Constantes OAuth ───────────────────────────────────────────────────────────

_AUTH_URL    = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL   = "https://oauth2.googleapis.com/token"
_REVOKE_URL  = "https://oauth2.googleapis.com/revoke"
_REDIRECT    = "http://localhost:9874/oauth/callback"
_LOCAL_PORT  = 9874


class GoogleAuthError(Exception):
    pass


# ── Servidor local para capturar o callback OAuth ─────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.code = params.get("code", [None])[0]

        body = b"<h2>Autenticado! Pode fechar esta aba.</h2>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass  # silencia logs do servidor HTTP


def _capture_auth_code(auth_url: str) -> str:
    """
    Abre o browser pro consentimento OAuth e aguarda o redirect local.
    Retorna o authorization code.
    """
    _CallbackHandler.code = None

    server = HTTPServer(("localhost", _LOCAL_PORT), _CallbackHandler)

    print(f"\n[google auth] Abrindo navegador para autenticação...", file=sys.stderr)
    print(f"[google auth] Se não abrir automaticamente, acesse:\n  {auth_url}\n", file=sys.stderr)
    webbrowser.open(auth_url)

    # aguarda o callback em thread separada (timeout: 120s)
    def _serve():
        server.handle_request()

    t = Thread(target=_serve, daemon=True)
    t.start()
    t.join(timeout=120)

    if not _CallbackHandler.code:
        raise GoogleAuthError(
            "Timeout aguardando autenticação. "
            "Acesse a URL manualmente e tente novamente."
        )

    return _CallbackHandler.code


# ── Classe principal ───────────────────────────────────────────────────────────

class GoogleAuth:
    """
    Gerencia tokens OAuth 2.0 do Google sem libs externas.

    Parâmetros:
        scopes      — lista de scopes OAuth necessários
        secret_path — caminho para client_secret.json (ou usa env var)
        token_path  — caminho para salvar/ler token.json (ou usa env var)
    """

    def __init__(
        self,
        scopes:      list[str],
        secret_path: str | None = None,
        token_path:  str | None = None,
    ):
        self.scopes = scopes

        # resolve caminhos
        self._secret_path = Path(
            secret_path
            or os.environ.get("GOOGLE_CLIENT_SECRET", "")
        )
        self._token_path = Path(
            token_path
            or os.environ.get("GOOGLE_TOKEN_STORE", "")
            or Path.home() / ".ciel" / "google_token.json"
        )

        if not self._secret_path or not self._secret_path.exists():
            raise GoogleAuthError(
                "client_secret.json não encontrado.\n"
                "Defina GOOGLE_CLIENT_SECRET=/caminho/para/client_secret.json\n"
                "ou passe secret_path= no construtor."
            )

        self._client_id:     str = ""
        self._client_secret: str = ""
        self._token:         dict = {}

        self._load_secret()
        self._load_token()

    # ── Configuração ───────────────────────────────────────────────────────────

    def _load_secret(self) -> None:
        try:
            raw = json.loads(self._secret_path.read_text(encoding="utf-8"))
            # client_secret.json pode ter chave "installed" ou "web"
            data = raw.get("installed") or raw.get("web") or {}
            self._client_id     = data["client_id"]
            self._client_secret = data["client_secret"]
        except (KeyError, json.JSONDecodeError) as e:
            raise GoogleAuthError(f"client_secret.json inválido: {e}")

    def _load_token(self) -> None:
        if self._token_path.exists():
            try:
                self._token = json.loads(self._token_path.read_text(encoding="utf-8"))
            except Exception:
                self._token = {}

    def _save_token(self) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(
            json.dumps(self._token, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Lógica de token ────────────────────────────────────────────────────────

    def _is_valid(self) -> bool:
        """Token existe e não expirou (com margem de 60s)."""
        if not self._token.get("access_token"):
            return False
        expires_at = self._token.get("expires_at", 0)
        return time.time() < expires_at - 60

    def _refresh(self) -> None:
        refresh_token = self._token.get("refresh_token")
        if not refresh_token:
            raise GoogleAuthError("Sem refresh_token — é necessário autenticar novamente.")

        payload = urllib.parse.urlencode({
            "client_id":     self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        }).encode()

        req  = urllib.request.Request(_TOKEN_URL, data=payload, method="POST")
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())

        if "error" in data:
            raise GoogleAuthError(f"Falha no refresh: {data['error']} — {data.get('error_description', '')}")

        self._token["access_token"] = data["access_token"]
        self._token["expires_at"]   = time.time() + int(data.get("expires_in", 3600))
        # refresh_token rotativo: atualiza se vier um novo
        if "refresh_token" in data:
            self._token["refresh_token"] = data["refresh_token"]
        self._save_token()

    def _full_auth(self) -> None:
        """Fluxo completo: abre browser, captura code, troca por token."""
        params = {
            "client_id":             self._client_id,
            "redirect_uri":          _REDIRECT,
            "response_type":         "code",
            "scope":                 " ".join(self.scopes),
            "access_type":           "offline",
            "prompt":                "consent",   # garante refresh_token sempre
        }
        auth_url = f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"
        code     = _capture_auth_code(auth_url)

        # troca o code pelo token
        payload = urllib.parse.urlencode({
            "client_id":     self._client_id,
            "client_secret": self._client_secret,
            "code":          code,
            "redirect_uri":  _REDIRECT,
            "grant_type":    "authorization_code",
        }).encode()

        req  = urllib.request.Request(_TOKEN_URL, data=payload, method="POST")
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())

        if "error" in data:
            raise GoogleAuthError(f"Falha ao obter token: {data['error']}")

        self._token = {
            "access_token":  data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_at":    time.time() + int(data.get("expires_in", 3600)),
            "scope":         data.get("scope", ""),
        }
        self._save_token()
        print("[google auth] Autenticação concluída e token salvo.", file=sys.stderr)

    # ── API pública ────────────────────────────────────────────────────────────

    def ensure_valid(self) -> None:
        """Garante que há um access_token válido. Chama refresh ou full_auth se necessário."""
        if self._is_valid():
            return
        if self._token.get("refresh_token"):
            try:
                self._refresh()
                return
            except GoogleAuthError:
                pass  # refresh falhou → full auth
        self._full_auth()

    def access_token(self) -> str:
        """Retorna o access_token válido, renovando se necessário."""
        self.ensure_valid()
        return self._token["access_token"]

    def auth_headers(self) -> dict:
        """Retorna headers prontos para requests autenticados."""
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "Content-Type":  "application/json",
        }

    def revoke(self) -> None:
        """Revoga o token e remove o arquivo local."""
        token = self._token.get("access_token") or self._token.get("refresh_token")
        if token:
            try:
                url = f"{_REVOKE_URL}?token={urllib.parse.quote(token)}"
                urllib.request.urlopen(url, timeout=10)
            except Exception:
                pass  # melhor esforço — remove local de qualquer forma
        if self._token_path.exists():
            self._token_path.unlink()
        self._token = {}
        print("[google auth] Token revogado e removido.", file=sys.stderr)
