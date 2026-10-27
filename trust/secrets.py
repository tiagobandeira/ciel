"""
SecretsManager — armazenamento de credenciais do Ciel.

Salva em ~/.ciel/secrets.json, separado do workspace e do ciel_config.json.
O modelo NUNCA recebe valores — só confirmações ("configurado com sucesso").

Estrutura do arquivo:
{
  "providers": {
    "nvidia": {
      "base_url": "https://integrate.api.nvidia.com/v1",
      "model":    "deepseek-ai/deepseek-v4-flash-0731",
      "api_key":  "nvapi-..."   ← só aqui, nunca no histórico
    }
  }
}

Uso:
    from trust.secrets import SecretsManager
    sm = SecretsManager()

    sm.save_provider("nvidia", base_url=..., model=..., api_key=...)
    cfg = sm.load_provider("nvidia")   # {"base_url": ..., "model": ..., "api_key": ...}
    names = sm.list_providers()        # ["nvidia", "openrouter"]
    sm.delete_provider("nvidia")
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _default_path() -> Path:
    """Mesmo arquivo do auth/manager.py: CIEL_SECRETS_PATH tem prioridade.

    Os dois módulos escrevem no mesmo secrets.json (providers + ciel_auth).
    Se resolverem caminhos diferentes, cada um grava num arquivo e o reset de
    senha deixa de preservar as chaves de provider.
    """
    override = os.environ.get("CIEL_SECRETS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ciel" / "secrets.json"


_SECRETS_FILE = _default_path()


class SecretsManager:

    def __init__(self, path: Path | None = None):
        self._path = path if path is not None else _SECRETS_FILE

    # ── leitura ──────────────────────────────────────────────────────────────

    def _load(self, *, strict: bool = False) -> dict:
        """
        Lê o arquivo de segredos.

        strict=False (leituras): arquivo ausente ou inválido vira
        {"providers": {}} — o agente não cai por causa de um JSON quebrado.
        strict=True (antes de gravar): JSON inválido LEVANTA ValueError.
        Nunca devolver {} num caminho de escrita: a gravação seguinte
        sobrescreveria o arquivo e apagaria `ciel_auth` (senha web) e os
        outros providers em silêncio.
        """
        if not self._path.exists():
            return {"providers": {}}
        try:
            # utf-8-sig: Bloco de Notas grava BOM; sem isso o arquivo inteiro
            # "some" e a próxima gravação apagaria o bloco ciel_auth (senha web)
            dados = json.loads(self._path.read_text(encoding="utf-8-sig"))
            if not isinstance(dados, dict):
                raise ValueError("esperava um objeto JSON")
            return dados
        except (ValueError, OSError) as e:   # JSONDecodeError é ValueError
            if strict:
                raise ValueError(
                    f"arquivo de segredos inválido ({self._path}): {e}. "
                    "Corrija o JSON ou renomeie o arquivo — nada foi alterado."
                ) from e
            return {"providers": {}}

    def list_providers(self) -> list[str]:
        """Lista as entradas configuradas (no formato 'provider:model' ou 'provider')."""
        return sorted(self._load().get("providers", {}).keys())

    def get_api_key(self, name: str, model: str = "") -> str:
        """Retorna só a api_key de um provedor+modelo ou string vazia."""
        cfg = self.load_provider(name, model)
        return (cfg or {}).get("api_key", "")

    # ── escrita ──────────────────────────────────────────────────────────────

    def _save(self, data: dict) -> None:
        """
        Grava de forma atômica (tmp + replace), no mesmo padrão do
        AuthManager._save_secrets: um crash no meio não deixa o arquivo pela
        metade. Se o ambiente bloquear CRIAR arquivo na pasta (antivírus,
        ACL parcial, sandbox) mas deixar escrever no existente, cai para
        gravação direta.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(data, indent=2, ensure_ascii=False)
        tmp = self._path.with_suffix(".tmp")

        def _limpa_tmp() -> None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

        _limpa_tmp()   # sobra somente-leitura de tentativa anterior
        erro_atomico = None
        try:
            tmp.write_text(conteudo, encoding="utf-8")
            try:
                tmp.chmod(0o600)   # só o dono lê/escreve (Unix)
            except OSError:
                pass               # Windows não suporta chmod, ignora
            tmp.replace(self._path)
            return
        except PermissionError as e:
            erro_atomico = e
            _limpa_tmp()

        try:
            self._path.write_text(conteudo, encoding="utf-8")
        except PermissionError:
            raise PermissionError(
                f"sem permissão para gravar {self._path}. Causas comuns: "
                "pasta somente-leitura, Windows Defender (Controlled Folder "
                "Access) ou terminal dentro de sandbox. Nada foi alterado."
            ) from erro_atomico
        try:
            self._path.chmod(0o600)
        except OSError:
            pass

    def save_provider(
        self,
        name: str,
        *,
        base_url: str,
        model: str,
        api_key: str,
    ) -> None:
        """
        Salva ou atualiza as credenciais de um provedor+modelo.
        Usa 'provider_id:model' como chave — o mesmo provedor pode ter
        vários modelos com chaves diferentes (ex: NVIDIA gera chave por modelo).
        Campos em branco mantêm o valor anterior.
        """
        data  = self._load(strict=True)
        # chave composta: garante que nvidia/llama e nvidia/deepseek coexistam
        key   = f"{name}:{model}" if model else name
        existing = data.setdefault("providers", {}).get(key, {})
        data["providers"][key] = {
            "base_url": base_url or existing.get("base_url", ""),
            "model":    model    or existing.get("model",    ""),
            "api_key":  api_key  or existing.get("api_key",  ""),
        }
        self._save(data)

    def load_provider(self, name: str, model: str = "") -> dict | None:
        key = f"{name}:{model}" if model else name
        data = self._load().get("providers", {})
        # 1. chave exata (provider:model ou só provider)
        if key in data:
            return data[key]
        # 2. só o nome sem sufixo (retrocompat)
        if name in data:
            return data[name]
        # 3. qualquer entrada do provider, independente do modelo
        for k, v in data.items():
            if k.startswith(f"{name}:"):
                return v
        return None

    def delete_provider(self, name: str, model: str = "") -> bool:
        key = f"{name}:{model}" if model else name
        data = self._load(strict=True)
        providers = data.get("providers", {})

        # tenta chave exata primeiro
        if key in providers:
            del providers[key]
            self._save(data)
            return True

        # fallback: deleta qualquer entrada do provider com sufixo :model
        if not model:
            keys_to_delete = [k for k in providers if k.startswith(f"{name}:")]
            if keys_to_delete:
                for k in keys_to_delete:
                    del providers[k]
                self._save(data)
                return True

        return False

    # ── resolução de api_key (usado por secondary_model) ─────────────────────

    def resolve_api_key(self, provider_name: str, model: str = "", env_var: str = "") -> str:
        """
        Resolve a api_key na seguinte ordem de prioridade:
          1. variável de ambiente (se env_var for fornecida)
          2. secrets.json por provider:model (chave específica do modelo)
          3. secrets.json por provider (chave genérica do provedor)
          4. ciel_config.json (retrocompatibilidade)
        Retorna string vazia se nenhuma fonte tiver o valor.
        """
        import os
        if env_var and os.environ.get(env_var, "").strip():
            return os.environ[env_var].strip()

        key = self.get_api_key(provider_name, model)
        if key:
            return key

        # retrocompatibilidade: tenta ciel_config.json direto
        try:
            from pathlib import Path as P
            cfg_path = P("ciel_config.json")
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                return cfg.get("api_key", "").strip()
        except Exception:
            pass

        return ""


# instância global — importada por secondary_model e pelos harnesses
secrets = SecretsManager()