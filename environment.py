"""
environment.py — Verificação de ambiente do Ciel.

Chamado no início do main() antes de qualquer outra inicialização.
Checks bloqueantes (Ollama) encerram com sys.exit(1).
Checks informativos (modelo secundário) apenas exibem aviso e continuam.

Uso:
    from environment import check_environment
    warnings = check_environment(model="gemma4:cloud")
    # warnings é uma lista de strings para exibir após o header principal
"""

import json
import os
import sys
from pathlib import Path

import requests
from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme

# ── tema idêntico ao cli.py ───────────────────────────────────────────────────
_THEME = Theme({
    "border": "bright_black",
    "muted":  "bright_black",
    "ok":     "green",
    "err":    "red",
    "warn":   "yellow",
})
_console = Console(theme=_THEME)

OLLAMA_BASE      = "http://localhost:11434"
OLLAMA_TAGS_URL  = f"{OLLAMA_BASE}/api/tags"
CONFIG_PATH      = Path("ciel_config.json")
CONFIG_EXAMPLE   = Path("ciel_config.example.json")
ENV_KEY_NAME     = "SECONDARY_MODEL_API_KEY"
PLACEHOLDER_KEY  = "SUA_CHAVE_AQUI"
TIMEOUT          = 3   # segundos — check rápido, não deve travar o startup


# ── helpers internos ──────────────────────────────────────────────────────────

def _check_ollama_running() -> tuple[bool, list[str]]:
    """
    Tenta acessar /api/tags do Ollama.
    Retorna (rodando, lista_de_modelos).
    """
    try:
        resp = requests.get(OLLAMA_TAGS_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        data   = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        return True, models
    except requests.ConnectionError:
        return False, []
    except requests.Timeout:
        return False, []
    except Exception:
        return False, []


def _model_base(name: str) -> str:
    """Retorna o nome base do modelo sem tag de versão para comparação flexível."""
    return name.split(":")[0].lower()


def _model_exists(requested: str, available: list[str]) -> bool:
    """
    Verifica se o modelo solicitado está disponível.
    Aceita match exato ('gemma4:cloud') ou por base ('gemma4').
    """
    if requested in available:
        return True
    req_base = _model_base(requested)
    return any(_model_base(m) == req_base for m in available)


def _check_secondary_config() -> list[str]:
    """
    Verifica configuração do modelo secundário.
    Retorna lista de avisos (vazia = configurado ou não necessário).

    Ordem de verificação:
      1. env var SECONDARY_MODEL_API_KEY → ok, sem aviso
      2. secrets.json (via /connect) com provider ativo → ok
      3. ciel_config.json com api_key inline (legado) → ok
      4. Nada configurado → aviso informativo (não bloqueante)
    """
    # 1. env var tem prioridade
    if os.environ.get(ENV_KEY_NAME, "").strip():
        return []

    # 2. secrets.json via model_manager
    try:
        from trust.model_manager import get_secondary_status
        status = get_secondary_status()
        if status.configured and status.has_key:
            return []
        if status.configured and not status.has_key:
            # provider ativo mas sem chave — aviso mais específico
            return [
                f"[warn]~[/warn]  [muted]modelo secundário sem chave"
                f"  ·  /connect para configurar[/muted]"
            ]
    except Exception:
        pass

    # 4. nada configurado — aviso genérico e informativo
    return [
        "[warn]~[/warn]  [muted]sem modelo secundário"
        "  ·  /connect para configurar[/muted]"
    ]


# ── função principal ──────────────────────────────────────────────────────────

def check_environment(model: str = "gemma4:cloud") -> list[str]:
    """
    Verifica o ambiente antes de iniciar o Ciel.

    Bloqueante (sys.exit) se:
      - Ollama não está acessível
      - Nenhum modelo disponível no Ollama
      - O modelo solicitado não existe

    Retorna lista de strings de aviso (modelo secundário) para
    o chamador exibir após o header principal. Lista vazia = sem avisos.
    Cada string é uma linha única — sem quebras internas.
    """

    # ── 1. Ollama acessível? ──────────────────────────────────────────────────
    running, available_models = _check_ollama_running()

    if not running:
        _console.print(Panel(
            "[err]✗[/err] Ollama não acessível em [muted]localhost:11434[/muted]\n"
            "\n"
            "  Se já instalado, inicie o serviço:\n"
            "  [muted]Windows/macOS[/muted]  procure o ícone do Ollama na bandeja do sistema\n"
            "  [muted]Linux       [/muted]  ollama serve\n"
            "\n"
            "  Se não instalado: [muted]https://ollama.com/download[/muted]",
            border_style="err",
            padding=(0, 2),
        ))
        sys.exit(1)

    # ── 2. Algum modelo disponível? ───────────────────────────────────────────
    if not available_models:
        _console.print(Panel(
            "[err]✗[/err] Nenhum modelo encontrado no Ollama\n"
            "\n"
            "  Baixe o modelo padrão (requer cadastro em ollama.com):\n"
            "  [muted]ollama pull gemma4:cloud[/muted]\n"
            "\n"
            "  Ou um modelo local (~3.5 GB, roda offline):\n"
            "  [muted]ollama pull gemma4:e2b-it-qat[/muted]",
            border_style="err",
            padding=(0, 2),
        ))
        sys.exit(1)

    # ── 3. Modelo solicitado existe? ──────────────────────────────────────────
    if not _model_exists(model, available_models):
        models_fmt = "  ".join(available_models) or "nenhum"
        _console.print(Panel(
            f"[err]✗[/err] Modelo [warn]{model}[/warn] não encontrado no Ollama\n"
            "\n"
            f"  Disponíveis: [muted]{models_fmt}[/muted]\n"
            "\n"
            f"  Baixe com:  [muted]ollama pull {model}[/muted]\n"
            f"  Ou use:     [muted]python ciel.py --model {available_models[0]}[/muted]",
            border_style="err",
            padding=(0, 2),
        ))
        sys.exit(1)

    # ── 4. Modelo secundário configurado? (não bloqueante) ────────────────────
    return _check_secondary_config()