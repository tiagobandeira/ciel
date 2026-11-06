"""
contexto.py — orçamento de contexto por perfil e por modelo.

Medição real (2026-11, perfil local com `gemma4:cloud`): um "oi" custa
~13.082 tokens de entrada (system prompt + schema de 50+ tools) e uma task de
2 steps ~27k. O prompt fixo come o orçamento antes da conversa começar — por
isso o default local é 32k tokens (16k é piso) e o da nuvem é 128k.

O teto é a janela útil do modelo, não um número inventado: os valores ficam em
`ciel_config.json` (bloco `contexto`), com override por modelo. `chars_por_token`
é só para os pontos que ainda medem em caracteres (estimativa conservadora para
PT/EN: 3).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "ciel_config.json"

DEFAULTS: dict = {
    "teto_tokens":       {"local": 32000, "nuvem": 128000},
    "por_modelo":        {},
    "chars_por_token":   3,
    "anexo": {
        "previa_chars":  2000,
        "teto_tokens":   8000,
    },
    "history_keep_last": {"local": 4, "nuvem": 6},
    # Cota da SESSÃO: soma de tokens de entrada enviados (system + histórico +
    # anexo + tools a cada chamada). Não é a janela do turno — é o último
    # recurso contra loop/leitura gigante. 1M ≈ 50–70 mensagens curtas.
    "cota_sessao_tokens": {"local": 1_000_000, "nuvem": 2_000_000},
    "avisos":            [0.8, 0.95],
    "avisar_truncamento": True,
}

_PERFIS_NUVEM = {"nuvem", "cloud", "build"}


def _perfil(perfil: str | None) -> str:
    """Normaliza para a chave usada no config: `local` ou `nuvem`."""
    return "nuvem" if str(perfil or "").strip().lower() in _PERFIS_NUVEM else "local"


def _mesclar(base: dict, extra: dict) -> dict:
    """Mescla `extra` sobre `base` (um nível de dict, resto substitui)."""
    saida = dict(base)
    for chave, valor in (extra or {}).items():
        if isinstance(valor, dict) and isinstance(saida.get(chave), dict):
            saida[chave] = {**saida[chave], **valor}
        elif valor is not None:
            saida[chave] = valor
    return saida


def carregar(caminho: Path | str | None = None) -> dict:
    """
    Config de contexto já com os defaults aplicados.

    Config ausente/corrompida não quebra nada: vale o default.
    """
    alvo = Path(caminho) if caminho else CONFIG_PATH
    try:
        bruto = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    bloco = bruto.get("contexto") if isinstance(bruto, dict) else None
    if not isinstance(bloco, dict):
        return dict(DEFAULTS)
    return _mesclar(DEFAULTS, bloco)


def _num(valor, padrao: int, minimo: int = 1) -> int:
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return padrao
    return numero if numero >= minimo else padrao


def teto_tokens(perfil: str | None = None, modelo: str | None = None,
                cfg: dict | None = None) -> int:
    """
    Janela útil em tokens: override do modelo > perfil > default.

    O override casa pelo nome exato ou pela família (sem a tag depois de `:`),
    então `gemma4:cloud` no config vale para `gemma4` e vice-versa.
    """
    cfg = cfg or carregar()
    padrao = _num((cfg.get("teto_tokens") or {}).get(_perfil(perfil)),
                  DEFAULTS["teto_tokens"][_perfil(perfil)])

    por_modelo = cfg.get("por_modelo") or {}
    if modelo and isinstance(por_modelo, dict):
        alvo = str(modelo).strip().lower()
        familia = alvo.split(":")[0]
        for chave, valor in por_modelo.items():
            nome = str(chave).strip().lower()
            if nome in (alvo, familia) or nome.split(":")[0] == familia:
                return _num(valor, padrao)

    return padrao


def chars_por_token(cfg: dict | None = None) -> int:
    cfg = cfg or carregar()
    return _num(cfg.get("chars_por_token"), DEFAULTS["chars_por_token"])


def teto_chars(perfil: str | None = None, modelo: str | None = None,
               cfg: dict | None = None) -> int:
    """Mesma janela, convertida para a unidade usada pelos cortes em chars."""
    cfg = cfg or carregar()
    return teto_tokens(perfil, modelo, cfg) * chars_por_token(cfg)


def keep_last(perfil: str | None = None, cfg: dict | None = None) -> int:
    """Quantas mensagens recentes a compactação preserva."""
    cfg = cfg or carregar()
    tabela = cfg.get("history_keep_last") or {}
    return _num(tabela.get(_perfil(perfil)), DEFAULTS["history_keep_last"][_perfil(perfil)])


def cota_sessao_tokens(perfil: str | None = None, cfg: dict | None = None) -> int:
    """
    Cota acumulada da sessão, em tokens de **entrada**.

    Diferente do teto do turno: aqui é o orçamento total que a sessão pode
    enviar ao orquestrador (system + histórico + anexo, a cada chamada). Serve
    de último recurso contra um loop que consome tudo de uma vez.
    """
    cfg = cfg or carregar()
    tabela = cfg.get("cota_sessao_tokens") or {}
    padrao = DEFAULTS["cota_sessao_tokens"][_perfil(perfil)]
    return _num(tabela.get(_perfil(perfil)), padrao)


def avisos(cfg: dict | None = None) -> list[float]:
    """Frações em que a UI avisa sobre a cota (ex.: 0.8 e 0.95)."""
    cfg = cfg or carregar()
    brutos = cfg.get("avisos")
    if not isinstance(brutos, (list, tuple)):
        return list(DEFAULTS["avisos"])
    saida = []
    for bruto in brutos:
        try:
            fracao = float(bruto)
        except (TypeError, ValueError):
            continue
        if 0 < fracao < 1:
            saida.append(fracao)
    return sorted(saida) or list(DEFAULTS["avisos"])


def fracao(usado: int, teto: int) -> float:
    """Fração usada (0..1+), tolerante a teto zero."""
    try:
        teto = int(teto)
        usado = int(usado)
    except (TypeError, ValueError):
        return 0.0
    return (usado / teto) if teto > 0 else 0.0


def anexo(cfg: dict | None = None) -> dict:
    """Orçamento do anexo: prévia que entra no contexto e teto da leitura."""
    cfg = cfg or carregar()
    atual = cfg.get("anexo") or {}
    return {
        "previa_chars": _num(atual.get("previa_chars"), DEFAULTS["anexo"]["previa_chars"]),
        "teto_tokens":  _num(atual.get("teto_tokens"), DEFAULTS["anexo"]["teto_tokens"]),
    }


def avisar_truncamento(cfg: dict | None = None) -> bool:
    cfg = cfg or carregar()
    return bool(cfg.get("avisar_truncamento", DEFAULTS["avisar_truncamento"]))
