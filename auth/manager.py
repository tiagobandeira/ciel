"""
auth/manager.py — Gerenciador de autenticação do Ciel.

Responsabilidades:
  - Armazenar e verificar a senha (hash bcrypt em ~/.ciel/secrets.json,
    mesma estrutura já usada pelo projeto para chaves de provider).
  - Emitir tokens de sessão assinados (HMAC-SHA256) sem dependência nova.
  - Validar tokens e controlar expiração.
  - Gerar a senha padrão na primeira execução.

Sem banco de dados, sem JWT, sem dependência além da stdlib + bcrypt
(bcrypt já é instalado pelo requirements do projeto via passlib ou direto).
Se bcrypt não estiver disponível, faz fallback para PBKDF2-HMAC-SHA256
da stdlib — seguro o suficiente para uso local em rede doméstica.

Uso:
    from auth import AuthManager
    auth = AuthManager()

    # verificar senha e obter token
    token = auth.login("minha_senha")   # None se errada
    if token:
        resp.set_cookie("ciel_auth", token, httponly=True, samesite="Lax")

    # validar token numa request
    auth.verify_token(request.cookies.get("ciel_auth"))  # True / False

    # trocar senha (requer token válido)
    auth.change_password(token, "nova_senha")

    # status público (para o frontend saber o que mostrar)
    auth.status()  # { "configured": bool, "default_password": bool }
"""

import os
import json
import hmac
import hashlib
import secrets
import time
from pathlib import Path
from typing import Optional

# ── constantes ────────────────────────────────────────────────────────────────
SECRETS_PATH    = Path.home() / ".ciel" / "secrets.json"
TOKEN_BYTE_SIZE = 32          # 256 bits → suficiente para uso local
SESSION_TTL     = 12 * 3600  # 12 horas em segundos
DEFAULT_PASSWORD_LEN = 12     # senha gerada automaticamente

# chave HMAC derivada do próprio hash de senha (nunca exposta)
# se o usuário trocar a senha, todos os tokens antigos expiram — comportamento intencional
_HMAC_INFO = "ciel-auth-token-v1"


# ── helpers de hash ───────────────────────────────────────────────────────────
def _try_bcrypt():
    """Retorna (hash_fn, verify_fn) usando bcrypt se disponível."""
    try:
        import bcrypt
        def _hash(pw: str) -> str:
            return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()
        def _verify(pw: str, hashed: str) -> bool:
            return bcrypt.checkpw(pw.encode(), hashed.encode())
        return _hash, _verify
    except ImportError:
        return None, None


def _pbkdf2_hash(pw: str, salt: Optional[str] = None) -> str:
    """Fallback PBKDF2-HMAC-SHA256 usando apenas a stdlib."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 260_000)
    return f"pbkdf2${salt}${dk.hex()}"


def _pbkdf2_verify(pw: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 3 or parts[0] != "pbkdf2":
        return False
    _, salt, expected = parts
    candidate = _pbkdf2_hash(pw, salt)
    return hmac.compare_digest(candidate, stored)


# ── AuthManager ───────────────────────────────────────────────────────────────
class AuthManager:
    """
    Gerencia autenticação para o Ciel server.

    Thread-safety: operações de leitura são seguras; escritas (change_password,
    _save_secrets) usam o GIL do CPython — suficiente para Flask dev server e
    Gunicorn com workers em thread (não multiprocess).
    """

    def __init__(self):
        self._hash_fn, self._verify_fn = _try_bcrypt()
        if self._hash_fn is None:
            # fallback stdlib
            self._hash_fn   = _pbkdf2_hash
            self._verify_fn = _pbkdf2_verify

        self._data = self._load_secrets()

        # primeira execução: gera senha padrão
        if "ciel_auth" not in self._data:
            default_pw = self._generate_default()
            self._data["ciel_auth"] = {
                "hash":             self._hash_fn(default_pw),
                "default_password": default_pw,   # exibida UMA vez, removida depois
                "is_default":       True,
            }
            self._save_secrets()

    # ── estado público ────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Retorna info de status sem expor nada sensível."""
        auth = self._data.get("ciel_auth", {})
        return {
            "configured":       "hash" in auth,
            "is_default":       auth.get("is_default", False),
            # senha padrão só aparece enquanto nunca foi trocada
            "default_password": auth.get("default_password") if auth.get("is_default") else None,
        }

    # ── login / logout ────────────────────────────────────────────────────────

    def login(self, password: str) -> Optional[str]:
        """
        Verifica a senha. Retorna um token de sessão assinado ou None.
        O token deve ser armazenado num cookie HttpOnly pelo caller.
        """
        auth = self._data.get("ciel_auth", {})
        stored_hash = auth.get("hash", "")
        if not stored_hash:
            return None
        if not self._verify_fn(password, stored_hash):
            return None
        return self._issue_token()

    def verify_token(self, token: Optional[str]) -> bool:
        """Retorna True se o token é válido e não expirou."""
        if not token:
            return False
        return self._validate_token(token)

    # ── troca de senha ────────────────────────────────────────────────────────

    def change_password(self, token: str, new_password: str) -> dict:
        """
        Troca a senha. Requer um token válido.
        Invalida todos os tokens existentes (nova chave HMAC derivada do novo hash).
        Retorna { "ok": bool, "error"?: str, "token"?: str (novo token) }.
        """
        if not self.verify_token(token):
            return {"ok": False, "error": "não autenticado"}

        if len(new_password) < 6:
            return {"ok": False, "error": "senha muito curta (mínimo 6 caracteres)"}

        new_hash = self._hash_fn(new_password)
        self._data["ciel_auth"] = {
            "hash":             new_hash,
            "is_default":       False,
            # remove a senha padrão em texto — ela cumpriu seu papel
        }
        self._save_secrets()

        # emite novo token com a nova chave
        new_token = self._issue_token()
        return {"ok": True, "token": new_token}

    # ── internals: token HMAC ─────────────────────────────────────────────────

    def _signing_key(self) -> bytes:
        """
        Chave HMAC derivada do hash de senha armazenado.
        Trocar a senha → chave diferente → todos os tokens antigos inválidos.
        """
        stored_hash = self._data.get("ciel_auth", {}).get("hash", "")
        return hashlib.sha256(
            f"{_HMAC_INFO}:{stored_hash}".encode()
        ).digest()

    def _issue_token(self) -> str:
        """
        Emite token no formato:  <nonce_hex>.<expires_ts>.<hmac_hex>
        Exemplo:
            a3f9...1b2c.1718123456.e7d0...4f2a
        """
        nonce   = secrets.token_hex(TOKEN_BYTE_SIZE)
        expires = int(time.time()) + SESSION_TTL
        payload = f"{nonce}.{expires}"
        sig     = hmac.new(
            self._signing_key(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{payload}.{sig}"

    def _validate_token(self, token: str) -> bool:
        """Valida assinatura e expiração. Resistente a timing attacks."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return False
            nonce, expires_str, sig = parts
            expires = int(expires_str)
        except (ValueError, AttributeError):
            return False

        if time.time() > expires:
            return False

        payload   = f"{nonce}.{expires_str}"
        expected  = hmac.new(
            self._signing_key(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, sig)

    # ── internals: persistência ───────────────────────────────────────────────

    def _load_secrets(self) -> dict:
        SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not SECRETS_PATH.exists():
            return {}
        try:
            return json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_secrets(self):
        SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        # chmod 600 antes de escrever — só o dono lê
        tmp = SECRETS_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.chmod(0o600)
        tmp.replace(SECRETS_PATH)

    @staticmethod
    def _generate_default() -> str:
        """
        Gera senha padrão legível: 3 grupos de 4 chars separados por hífen.
        Ex: a3k9-z2mp-8fqr
        """
        alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # sem i,l,o,0,1 (confusos)
        raw = "".join(secrets.choice(alphabet) for _ in range(DEFAULT_PASSWORD_LEN))
        return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
