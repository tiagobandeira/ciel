"""Reset da senha do Ciel web pela linha de comando (nível de sistema).

Quem executa já é o usuário do SO dono de ~/.ciel/secrets.json (0600). Não há
token a exigir — a senha esquecida não pode autenticar o próprio reset. O que
dá para exigir é intenção explícita:

  - confirmação interativa (digitar 'resetar');
  - `--sim` para automação, e sem TTY o comando recusa sem ele;
  - não existe rota HTTP nem tool equivalente — só linha de comando.

O que o reset garante: preserva `providers` (as chaves de API moram no mesmo
arquivo), invalida todas as sessões do navegador (a chave HMAC deriva do hash)
e não altera nada quando não consegue gravar.

Uso:
    python ciel.py --reset-password
    python ciel.py --reset-password --sim
    python server.py --reset-password
"""

from __future__ import annotations

import argparse
import sys

from . import AuthManager
from .manager import SECRETS_PATH

_CONFIRMACAO = "resetar"


def exibir_senha(senha: str) -> None:
    """Caixa da senha provisória (usada aqui e no banner de start do server)."""
    largura = 52
    topo    = "─ senha padrão ativa "
    print("  ┌" + topo + "─" * (largura - len(topo)) + "┐")
    print("  │" + f"  senha: {senha}".ljust(largura) + "│")
    print("  │" + "  troque em: cadeado no topo da página".ljust(largura) + "│")
    print("  └" + "─" * largura + "┘")


def _confirmado() -> bool:
    try:
        resposta = input(f"  digite '{_CONFIRMACAO}' para confirmar: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return resposta.strip().lower() == _CONFIRMACAO


def main(argv: list[str] | None = None, *, tty: bool | None = None) -> int:
    """Executa o reset. Retorna o código de saída (0 ok, 1 falhou, 2 sem TTY)."""
    parser = argparse.ArgumentParser(
        prog="ciel --reset-password",
        description="gera uma nova senha para a interface web do Ciel",
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help="não pede confirmação (usa em script/automação)",
    )
    args = parser.parse_args(argv)

    interativo = sys.stdin.isatty() if tty is None else tty

    print("\n  ◈ reset da senha do Ciel web")
    print(f"  arquivo: {SECRETS_PATH}")

    if not args.sim:
        if not interativo:
            print(
                "  ✗ sem terminal interativo — rode no terminal ou confirme "
                "de propósito com --sim.",
                file=sys.stderr,
            )
            return 2
        print("  a senha atual deixa de valer e as sessões abertas caem.")
        if not _confirmado():
            print("  cancelado — nada foi alterado.")
            return 1

    try:
        senha = AuthManager().reset_password()
    except (ValueError, OSError) as e:
        print(f"  ✗ {e}", file=sys.stderr)
        return 1

    print()
    exibir_senha(senha)
    print("\n  as chaves de provider no mesmo arquivo foram preservadas.")
    print("  se o server estiver rodando, reinicie para a nova senha valer.\n")
    return 0
