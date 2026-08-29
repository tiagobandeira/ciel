#!/usr/bin/env python
"""
ciel.py — Ponto de entrada unificado do Ciel.

Detecta automaticamente se o Textual está instalado e abre a TUI ou a CLI.
Flags explícitas sempre têm prioridade.

Uso:
    python ciel.py              # TUI se disponível, senão CLI
    python ciel.py --tui        # força TUI (erro se Textual não instalado)
    python ciel.py --cli        # força CLI
    python ciel.py --agent dev_helper
    python ciel.py --model gemma4:cloud
    python ciel.py --safe
    python ciel.py --list-agents
"""

import sys
import argparse


# ── parser de argumentos ──────────────────────────────────────────────────────
# Apenas --tui/--cli são próprios deste arquivo. Todos os outros são
# repassados ao entrypoint escolhido via sys.argv, sem re-parsear.

def _parse_mode() -> tuple[str, list[str]]:
    """
    Retorna (modo, argv_restante).
    modo: "auto" | "tui" | "cli"
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--tui",  action="store_true", default=False)
    parser.add_argument("--cli",  action="store_true", default=False)
    known, rest = parser.parse_known_args()

    if known.tui and known.cli:
        print("ciel: --tui e --cli são mutuamente exclusivos.", file=sys.stderr)
        sys.exit(1)

    if known.tui:
        return "tui", rest
    if known.cli:
        return "cli", rest
    return "auto", rest


def _has_textual() -> bool:
    try:
        import textual  # noqa: F401
        return True
    except ImportError:
        return False


# ── launchers ─────────────────────────────────────────────────────────────────

def _launch_tui(extra_argv: list[str]) -> None:
    """Inicia a TUI. Passa argumentos restantes como configuração inicial."""
    try:
        from textual.app import App  # noqa: F401
    except ImportError:
        print(
            "ciel: Textual não encontrado.\n"
            "  Instale com:  pip install textual\n"
            "  Ou use:       python ciel.py --cli",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parseia os args que a TUI aceita
    p = argparse.ArgumentParser(prog="ciel --tui", add_help=True)
    p.add_argument("--agent",  default="general",      metavar="NOME")
    p.add_argument("--model",  default="gemma4:cloud", metavar="MODELO")
    p.add_argument("--safe",   action="store_true",    default=False)
    args = p.parse_args(extra_argv)

    from ciel_tui import CielTUI
    app = CielTUI(
        initial_agent=args.agent,
        initial_model=args.model,
        safe_mode=args.safe,
    )
    app.run()


def _launch_cli(extra_argv: list[str]) -> None:
    """Inicia a CLI. Reconstrói sys.argv com os args restantes."""
    sys.argv = ["cli.py"] + extra_argv
    from cli import main
    main()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    mode, rest = _parse_mode()

    if mode == "tui":
        _launch_tui(rest)
    elif mode == "cli":
        _launch_cli(rest)
    else:  # auto
        if _has_textual():
            _launch_tui(rest)
        else:
            _launch_cli(rest)


if __name__ == "__main__":
    main()
