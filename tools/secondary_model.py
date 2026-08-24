"""Consulta o modelo secundário para tarefas que exigem raciocínio complexo ou contexto extenso."""

REQUIREMENTS = ["requests"]

import json
import os
from pathlib import Path
from datetime import datetime
import requests

# ── config padrão (sobrescrita por ciel_config.json se existir) ───────────────
_DEFAULT_CONFIG = {
    "base_url": "https://integrate.api.nvidia.com/v1",
    "model":    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "api_key_env": "SECONDARY_MODEL_API_KEY",
    "timeout":  120,
    "max_chars_per_session": 40000,   # cota de entrada por sessão (~10k tokens)
    "max_response_chars":    8000,    # resposta acima disso → salva em arquivo
}

_CONFIG_PATH   = Path(__file__).parent.parent / "ciel_config.json"
_QUOTA_PATH    = Path(__file__).parent.parent / "data" / "secondary_quota.json"
_RESPONSE_DIR  = Path(__file__).parent.parent / "data" / "user"


def _load_config() -> dict:
    cfg = dict(_DEFAULT_CONFIG)
    if _CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(_CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def _load_quota(session_id: str) -> int:
    """Retorna quantos chars já foram enviados nesta sessão."""
    if not _QUOTA_PATH.exists():
        return 0
    try:
        data = json.loads(_QUOTA_PATH.read_text(encoding="utf-8"))
        return data.get(session_id, 0)
    except Exception:
        return 0


def _save_quota(session_id: str, used: int):
    _QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _QUOTA_PATH.exists():
        try:
            data = json.loads(_QUOTA_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data[session_id] = used
    _QUOTA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _save_response(content: str) -> str:
    """Salva resposta longa em arquivo e retorna o caminho."""
    _RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _RESPONSE_DIR / f"secondary_response_{ts}.md"
    path.write_text(content, encoding="utf-8")
    return str(path.relative_to(Path(__file__).parent.parent))


def run(
    prompt: str,
    session_id: str = "_nosession",
    system: str = "Você é um assistente especialista. Responda de forma precisa e completa.",
    save_response: bool = False,
) -> str:
    """
    prompt: descrição completa do problema ou pergunta para o modelo secundário
    session_id: ID da sessão atual (usado para controle de cota)
    system: instrução de sistema opcional para o modelo secundário
    save_response: se True, salva resposta em arquivo mesmo que seja curta
    """
    cfg = _load_config()

    # ── verifica cota da sessão ───────────────────────────────────────────────
    prompt_chars = len(prompt)
    used         = _load_quota(session_id)
    max_chars    = cfg.get("max_chars_per_session", 40000)

    if used + prompt_chars > max_chars:
        restante = max(0, max_chars - used)
        return (
            f"Cota do modelo secundário esgotada para esta sessão. "
            f"Usado: {used:,} chars / Limite: {max_chars:,} chars. "
            f"Restante: {restante:,} chars. "
            f"Tente resumir o problema ou inicie uma nova sessão."
        )

    # ── obtém API key ─────────────────────────────────────────────────────────
    api_key_env = cfg.get("api_key_env", "SECONDARY_MODEL_API_KEY")
    api_key     = os.environ.get(api_key_env, "")

    # fallback: chave inline no config (não recomendado)
    if not api_key:
        api_key = cfg.get("api_key", "")

    if not api_key:
        return (
            f"API key não encontrada. "
            f"Defina a variável de ambiente '{api_key_env}' "
            f"ou adicione 'api_key' em ciel_config.json."
        )

    # ── monta e faz a chamada ─────────────────────────────────────────────────
    base_url = cfg.get("base_url", _DEFAULT_CONFIG["base_url"]).rstrip("/")
    model    = cfg.get("model",    _DEFAULT_CONFIG["model"])
    timeout  = cfg.get("timeout",  _DEFAULT_CONFIG["timeout"])

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system",  "content": system},
            {"role": "user",    "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens":  4096,
    }

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data    = resp.json()
        content = data["choices"][0]["message"]["content"]
    except requests.Timeout:
        return f"Erro: timeout após {timeout}s aguardando resposta do modelo secundário."
    except requests.HTTPError as e:
        return f"Erro HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        return f"Erro ao chamar modelo secundário: {e}"

    # ── atualiza cota ─────────────────────────────────────────────────────────
    _save_quota(session_id, used + prompt_chars)

    # ── decide se salva em arquivo ────────────────────────────────────────────
    max_resp = cfg.get("max_response_chars", 8000)
    if save_response or len(content) > max_resp:
        path = _save_response(content)
        preview = content[:400].strip()
        return (
            f"Resposta completa salva em: {path}\n\n"
            f"Prévia:\n{preview}\n…\n\n"
            f"Use read_file com o caminho acima para ler a resposta completa."
        )

    return content
