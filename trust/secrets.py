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
from pathlib import Path

_CIEL_DIR    = Path.home() / ".ciel"
_SECRETS_FILE = _CIEL_DIR / "secrets.json"


class SecretsManager:

    def __init__(self, path: Path = _SECRETS_FILE):
        self._path = path

    # ── leitura ──────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self._path.exists():
            return {"providers": {}}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # permissão restrita — só o dono lê/escreve (Unix)
        try:
            self._path.chmod(0o600)
        except Exception:
            pass  # Windows não suporta chmod, ignora

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
        data  = self._load()
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
        data = self._load()
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
