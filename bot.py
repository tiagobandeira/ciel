"""
bot.py — Entry point do Modo Bot WhatsApp.

Uso:
    python bot.py
    python bot.py --model gemma4:cloud
    python bot.py --safe
    python bot.py --agent dev_helper   # sobrescreve o agente do whatsapp_channels.json

Mantém o terminal aberto exibindo o banner de status e o log de execuções
em tempo real (mesmo formato de steps do CLI).

Encerrar: Ctrl+C
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.markup import escape
from rich.theme import Theme

# ── setup de path ─────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from mcp.whatsapp import channels as ch
from mcp.whatsapp.bot import run_bot, bridge_status, WEBHOOK_PORT

# ── tema (mesmo do cli.py) ────────────────────────────────────────────────────
CIEL_THEME = Theme({
    "border": "bright_black",
    "user":   "cyan",
    "agent":  "green",
    "tool":   "yellow",
    "muted":  "bright_black",
    "ok":     "green",
    "err":    "red",
    "warn":   "yellow",
})

console = Console(theme=CIEL_THEME)

NAME    = "Ciel CLI"
VERSION = "1.0.0"


# ── display ───────────────────────────────────────────────────────────────────

def _status_badge(status: str) -> str:
    badges = {
        "connected":    "[ok]● conectado[/ok]",
        "waiting_qr":  "[warn]◌ aguardando QR[/warn]",
        "disconnected": "[err]○ desconectado[/err]",
    }
    return badges.get(status, f"[muted]{status}[/muted]")


def _print_banner(model: str, agent_name: str, safe: bool) -> None:
    """Exibe o cabeçalho fixo do modo bot."""
    console.clear()

    status      = bridge_status()
    status_line = _status_badge(status)
    safe_badge  = "  [tool]⚠ modo seguro[/tool]\n" if safe else ""

    cfg         = ch.load()
    allow_from  = cfg.get("bot", {}).get("allow_from", [])
    allow_line  = (
        "  " + "  ".join(f"[user]{n}[/user]" for n in allow_from)
        if allow_from
        else "  [warn](allowlist vazia — nenhuma mensagem será processada)[/warn]"
    )

    mcp_line = (
        "[ok]habilitado[/ok]"
        if cfg.get("mcp", {}).get("enabled")
        else "[muted]desabilitado[/muted]"
    )

    content = (
        f"  [bold white]{NAME}[/bold white] [muted](V{VERSION})[/muted]"
        f"  [muted]·[/muted]  [bold]Modo Bot[/bold]\n"
        f"\n"
        f"{safe_badge}"
        f"  [muted]canal:[/muted]   WhatsApp  {status_line}\n"
        f"  [muted]agente:[/muted]  [agent]{agent_name}[/agent]"
        f"   [muted]model:[/muted] [white]{model}[/white]\n"
        f"  [muted]MCP:[/muted]    {mcp_line}\n"
        f"  [muted]webhook:[/muted] 127.0.0.1:{WEBHOOK_PORT}/webhook\n"
        f"\n"
        f"  [muted]permitidos:[/muted]\n"
        f"{allow_line}\n"
        f"\n"
        f"  [muted]Ctrl+C para encerrar[/muted]\n"
    )

    console.print(Panel(content, border_style="border", padding=(0, 1), expand=False))
    console.print()


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ── callbacks de log ──────────────────────────────────────────────────────────

def _on_event(chat_id: str, sender: str, text: str) -> None:
    console.print(
        f"  [muted]{_ts()}[/muted]  "
        f"[user][whatsapp][/user]  "
        f"[muted]{sender}[/muted]  "
        f"{escape(text[:120])}"
    )
    console.print(Rule(style="border"))


def _on_step(step: int, label: str, content: str, status: str) -> None:
    color = "tool" if status == "tool" else "muted"
    console.print(
        f"  [muted]{_ts()}[/muted]  "
        f"[{color}]step {step} › {label}[/{color}]  "
        f"[muted]{escape(content[:100])}[/muted]"
    )


def _on_done(message: str, steps: int, tok_in: int, tok_out: int) -> None:
    console.print(
        f"  [muted]{_ts()}[/muted]  "
        f"[ok]✓ done[/ok]  "
        f"[muted]{steps} steps · {tok_in}↑ {tok_out}↓ tokens[/muted]"
    )
    console.print()


def _on_error(kind: str, message: str) -> None:
    console.print(
        f"  [muted]{_ts()}[/muted]  "
        f"[err]✗ erro ({kind})[/err]  "
        f"[muted]{escape(message[:200])}[/muted]"
    )
    console.print()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bot",
        description="Ciel — Modo Bot WhatsApp",
    )
    parser.add_argument(
        "--model",
        default="gemma4:cloud",
        metavar="MODELO",
        help="modelo Ollama (padrão: gemma4:cloud)",
    )
    parser.add_argument(
        "--agent",
        default=None,
        metavar="AGENTE",
        help="sobrescreve o agente configurado em whatsapp_channels.json",
    )
    parser.add_argument(
        "--safe",
        action="store_true",
        default=False,
        help="desabilita tools de execução arbitrária (run_script, create_tool)",
    )
    args = parser.parse_args()

    # --agent sobrescreve temporariamente a config (sem salvar)
    if args.agent:
        cfg = ch.load()
        cfg["bot"]["enabled"] = True
        cfg["bot"]["agent"]   = args.agent
        ch.save(cfg)

    agent_name = ch.bot_agent()

    def _on_ready():
        _print_banner(args.model, agent_name, args.safe)
        console.print(
            f"  [ok]Servidor de webhook iniciado.[/ok]  "
            f"[muted]Aguardando mensagens…[/muted]\n"
        )

    run_bot(
        model     = args.model,
        safe      = args.safe,
        on_event  = _on_event,
        on_step   = _on_step,
        on_done   = _on_done,
        on_error  = _on_error,
        on_ready  = _on_ready,
    )

    console.print("\n  [muted]Modo bot encerrado.[/muted]\n")


if __name__ == "__main__":
    main()
