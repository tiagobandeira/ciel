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

Nível de acesso:
  O arquivo de segredos é credencial do SISTEMA (~/.ciel/secrets.json), fora
  do workspace do Ciel — como ~/.ssh. O agente (modelo) nunca o alcança:
  qualquer tool que receba esse caminho passa pelo workspace guard e é
  negada. Já o reset de senha (reset_password / `server.py --reset-password`)
  é ação do usuário logado no sistema, executada no terminal: não pede token
  e não passa pelo guard, porque quem executa já provou ser o dono do arquivo.
  Esse comando NÃO é exposto por HTTP.

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

    # recuperar senha esquecida (sem token; preserva as chaves de provider)
    senha = auth.reset_password()

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

def _secrets_path() -> Path:
    """
    Caminho do arquivo de segredos do usuário do sistema.

    Fora do workspace do Ciel de propósito: é credencial do sistema, não dado
    do projeto. CIEL_SECRETS_PATH permite apontar para outro arquivo
    (testes, instalação portátil, máquina com mais de um usuário do Ciel).
    """
    override = os.environ.get("CIEL_SECRETS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ciel" / "secrets.json"


SECRETS_PATH    = _secrets_path()
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


def _verify_hash(pw: str, stored: str) -> bool:
    """
    Verifica pelo FORMATO do hash guardado, não pela lib instalada.

    Sem isso, instalar (ou remover) bcrypt no venv tranca o login de um hash
    do outro formato — bcrypt.checkpw levanta ValueError num hash pbkdf2.
    Escolher pelo prefixo mantém o arquivo portátil e o reset manual seguro.
    """
    if stored.startswith("pbkdf2$"):
        return _pbkdf2_verify(pw, stored)
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt
        except ImportError:
            return False
        try:
            return bcrypt.checkpw(pw.encode(), stored.encode())
        except ValueError:
            return False
    return False


# ── AuthManager ───────────────────────────────────────────────────────────────
class AuthManager:
    """
    Gerencia autenticação para o Ciel server.

    Thread-safety: operações de leitura são seguras; escritas (change_password,
    _save_secrets) usam o GIL do CPython — suficiente para Flask dev server e
    Gunicorn com workers em thread (não multiprocess).
    """

    def __init__(self):
        self._hash_fn, _ = _try_bcrypt()
        if self._hash_fn is None:
            self._hash_fn = _pbkdf2_hash   # fallback stdlib
        # a verificação escolhe pelo formato guardado (ver _verify_hash)
        self._verify_fn = _verify_hash

        self._data = self._load_secrets()

    # ── primeira execução / recuperação ───────────────────────────────────────

    def ensure_configured(self) -> Optional[str]:
        """
        Garante que existe uma senha configurada, gerando a padrão se faltar.

        Fica FORA do __init__ de propósito: construir o AuthManager não deve
        gravar em disco. Assim o comando de reset roda mesmo quando o arquivo
        está ausente ou a pasta está sem permissão de escrita — se o __init__
        tentasse gravar, o import derrubaria o processo antes do reset.

        Retorna a senha gerada (para ser exibida uma vez) ou None se já havia.
        """
        if "ciel_auth" in self._data:
            return None
        senha = self._generate_default()
        self._data["ciel_auth"] = {
            "hash":             self._hash_fn(senha),
            "default_password": senha,
            "is_default":       True,
        }
        self._save_secrets()
        return senha

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

    def reset_password(self) -> str:
        """
        Gera uma senha padrão provisória e a grava — sem exigir token.

        Nível de sistema: não passa pelo workspace guard do agente. Quem chama
        já é o usuário do SO dono do arquivo (shell local), e essa é a única
        credencial que faz sentido — a senha esquecida não pode autenticar o
        próprio reset. O modelo continua sem acesso: tools que recebam esse
        caminho são barradas pelo guard.

        É o caminho de recuperação quando a senha foi esquecida: a antiga não
        pode ser derivada (só o hash é guardado), então o reset sobrescreve
        apenas `ciel_auth` e preserva o resto do arquivo — em especial
        `providers`, com as chaves das APIs, que é o motivo de NÃO se apagar
        `~/.ciel/secrets.json` para recuperar a senha.

        Todos os tokens antigos morrem junto, porque a chave HMAC é derivada
        do hash. A senha volta em texto uma única vez, para ser exibida; ela
        fica no arquivo como `default_password` até o usuário trocar — mesmo
        comportamento da primeira execução.
        """
        # relê antes de gravar: o arquivo é compartilhado com o server que
        # estiver rodando e com edições manuais; um `providers` escrito
        # depois desta instância não pode ser perdido no reset.
        atual = self._load_secrets()
        senha = self._generate_default()
        atual["ciel_auth"] = {
            "hash":             self._hash_fn(senha),
            "default_password": senha,
            "is_default":       True,
        }
        self._data = atual
        self._save_secrets()
        return senha

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
        # utf-8-sig: Bloco de Notas e alguns editores gravam BOM. Sem isso o
        # arquivo "some" para o json.loads e as chaves de provider se perdem.
        texto = SECRETS_PATH.read_text(encoding="utf-8-sig")
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError as e:
            # NUNCA devolver {} aqui: a próxima gravação sobrescreveria o
            # arquivo e apagaria providers/senha em silêncio. Falhar alto é
            # o comportamento seguro para um arquivo de credenciais.
            raise ValueError(
                f"arquivo de segredos inválido ({SECRETS_PATH}): {e}. "
                "Corrija o JSON ou renomeie o arquivo — nada foi alterado."
            ) from e
        if not isinstance(dados, dict):
            raise ValueError(
                f"arquivo de segredos inválido ({SECRETS_PATH}): "
                "esperava um objeto JSON."
            )
        return dados

    def _save_secrets(self):
        SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(self._data, indent=2, ensure_ascii=False)
        tmp = SECRETS_PATH.with_suffix(".tmp")

        def _limpa_tmp():
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

        # sobra de tentativa anterior pode estar somente-leitura e travar o
        # write; remover antes é mais confiável que tentar sobrescrever.
        _limpa_tmp()

        erro_atomico = None
        try:
            tmp.write_text(conteudo, encoding="utf-8")
            try:
                tmp.chmod(0o600)   # só o dono lê
            except OSError:
                pass               # FS sem semântica POSIX: segue
            tmp.replace(SECRETS_PATH)
            return
        except PermissionError as e:
            # alguns ambientes bloqueiam CRIAR arquivo na pasta, mas deixam
            # gravar no arquivo que já existe (antivírus, ACL parcial, sandbox)
            erro_atomico = e
            _limpa_tmp()

        try:
            SECRETS_PATH.write_text(conteudo, encoding="utf-8")
        except PermissionError:
            raise PermissionError(
                f"sem permissão para gravar {SECRETS_PATH}. Causas comuns: "
                "pasta somente-leitura, Windows Defender (Controlled Folder "
                "Access) ou terminal dentro de sandbox. Nada foi alterado."
            ) from erro_atomico

    @staticmethod
    def _generate_default() -> str:
        """
        Gera senha padrão legível: 3 grupos de 4 chars separados por hífen.
        Ex: a3k9-z2mp-8fqr
        """
        alphabet = "abcdefghjkmnpqrstuvwxyz23456789"  # sem i,l,o,0,1 (confusos)
        raw = "".join(secrets.choice(alphabet) for _ in range(DEFAULT_PASSWORD_LEN))
        return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
