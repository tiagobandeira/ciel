"""Grava o whatsapp_channels.json (canal WhatsApp do Ciel) com os dados da entrevista.
Valida o agente e os números, parte do whatsapp_channels.example.json e preenche só os campos informados.
Se já existir uma configuração, recusa e mostra o que existe, a menos que overwrite=true."""

import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# garante que mcp/whatsapp/channels.py seja encontrado mesmo quando a tool
# é chamada de dentro do loop do agente (cwd pode variar)
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

OUTPUT = "internal"

_EXAMPLE_NAME = "whatsapp_channels.example.json"

# aceita separadores comuns de telefone; o que sobra tem que ser "+" e dígitos.
# 8–20 dígitos cobre telefone E.164 (até 15) e LIDs do WhatsApp (~15).
_SEPARATORS = re.compile(r"[\s\-().]")
_NUMBER_RE = re.compile(r"^\+\d{8,20}$")

_TRUE = {"1", "true", "sim", "yes", "y", "s"}
_FALSE = {"0", "false", "nao", "não", "no", "n", ""}

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _as_bool(value, name: str) -> bool:
    """Aceita bool de verdade e as formas que modelos costumam mandar ('true', 'sim')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUE:
            return True
        if v in _FALSE:
            return False
    raise ValueError(f"'{name}' deve ser true ou false (recebi {value!r}).")


def _split_numbers(raw) -> list[str]:
    """
    Transforma o argumento allow_from em lista de strings.
    Aceita string separada por vírgula/ponto e vírgula/quebra de linha,
    lista, ou string com um array JSON (alguns modelos locais mandam assim).
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(x) for x in raw]
    else:
        text = str(raw).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return _split_numbers(parsed)
            except ValueError:
                pass
        items = re.split(r"[,;\n]+", text)
    return [" ".join(i.split()) for i in items if i.strip()]


def _validate_numbers(items: list[str], normalize) -> tuple[list[str], list[str]]:
    """Devolve (válidos sem duplicatas, inválidos). Duplicata = mesmo número normalizado."""
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not _NUMBER_RE.match(_SEPARATORS.sub("", item)):
            invalid.append(item)
            continue
        key = normalize(item)
        if key in seen:
            continue
        seen.add(key)
        valid.append(item)
    return valid, invalid


def _read_json_dict(path: Path):
    """Lê um JSON de objeto. Devolve None se não existir, for ilegível ou não for objeto."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _describe(cfg: dict) -> str:
    bot = cfg.get("bot", {}) if isinstance(cfg.get("bot"), dict) else {}
    mcp = cfg.get("mcp", {}) if isinstance(cfg.get("mcp"), dict) else {}
    allow = bot.get("allow_from") or []
    return (
        f"bot={'ligado' if bot.get('enabled') else 'desligado'}, "
        f"agente={bot.get('agent', '?')}, "
        f"allow_from={', '.join(allow) if allow else '(vazia)'}, "
        f"mcp={'ligado' if mcp.get('enabled') else 'desligado'}, "
        f"bridge_url={cfg.get('bridge_url', '?')}"
    )


def _strip_comments(cfg: dict) -> dict:
    """Remove chaves '_comentario' & cia do topo — existem só no arquivo de exemplo."""
    return {k: v for k, v in cfg.items() if not k.startswith("_")}


# ── tool ──────────────────────────────────────────────────────────────────────

def run(
    agent: str = None,
    allow_from: str = None,
    bot: bool = True,
    mcp: bool = False,
    bridge_url: str = None,
    overwrite: bool = False,
) -> str:
    """
    agent: nome do agente que vai atender o bot, igual a um arquivo de agents/ sem o .md (obrigatório se bot=true)
    allow_from: números que podem falar com o bot, separados por vírgula, cada um começando com + e o código do país (obrigatório se bot=true)
    bot: true para ativar o Modo Bot (o Ciel responde mensagens em tempo real)
    mcp: true para ativar o Modo MCP (o modelo usa o WhatsApp como tool dentro de tasks)
    bridge_url: URL do bridge; omitir mantém o padrão http://127.0.0.1:8765
    overwrite: true só depois que o usuário confirmar que quer substituir uma configuração já existente
    """
    try:
        from mcp.whatsapp import channels
        from agent_loader import list_agents
    except Exception as e:
        return f"Erro: não consegui carregar o módulo do WhatsApp: {e}"

    # ── flags ────────────────────────────────────────────────────────────────
    try:
        bot = _as_bool(bot, "bot")
        mcp = _as_bool(mcp, "mcp")
        overwrite = _as_bool(overwrite, "overwrite")
    except ValueError as e:
        return f"Erro: {e}"

    if not bot and not mcp:
        return "Erro: ative pelo menos um modo (bot=true e/ou mcp=true)."

    # ── validação (tudo antes de tocar no disco) ─────────────────────────────
    agent_name = (agent or "").strip()
    if agent_name.endswith(".md"):
        agent_name = agent_name[:-3]

    if bot:
        if not agent_name:
            return "Erro: informe o agente que vai atender o bot (argumento 'agent')."
        available = list_agents()
        if agent_name not in available:
            return (
                f"Erro: agente '{agent_name}' não existe em agents/. "
                f"Disponíveis: {', '.join(available) or '(nenhum)'}."
            )

    numbers, invalid = _validate_numbers(_split_numbers(allow_from), channels._normalize)
    if invalid:
        return (
            "Erro: número(s) inválido(s): " + ", ".join(invalid) + ". "
            "Use o formato internacional começando com +, com código do país "
            "(ex: +55 11 99999-9999). Nada foi gravado."
        )
    if bot and not numbers:
        return (
            "Erro: informe pelo menos um número em 'allow_from'. "
            "Sem allowlist o bot ignora todas as mensagens. Nada foi gravado."
        )

    url = None
    if bridge_url is not None and str(bridge_url).strip():
        url = str(bridge_url).strip().rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return (
                f"Erro: bridge_url inválida ({url!r}). "
                "Use algo como http://127.0.0.1:8765. Nada foi gravado."
            )

    # ── config já existe? ────────────────────────────────────────────────────
    config_file = Path(channels.CONFIG_FILE)
    existing = None
    if config_file.exists():
        existing = _read_json_dict(config_file)
        if not overwrite:
            current = _describe(existing) if existing is not None else "arquivo inválido (JSON quebrado)"
            return (
                f"Já existe {config_file.name} nesta instalação ({current}). "
                "Nada foi alterado. Mostre isso ao usuário e pergunte se quer substituir; "
                "só se ele confirmar, chame de novo com overwrite=true."
            )

    # ── monta a config ───────────────────────────────────────────────────────
    if existing is not None:
        # atualização: preserva o que a entrevista não cobre (groups, dm_policy…)
        base, source = existing, "existente"
    else:
        example = _read_json_dict(config_file.with_name(_EXAMPLE_NAME))
        if example is not None:
            base, source = example, "exemplo"
        else:
            base, source = {}, "padrão"

    cfg = channels._merge(channels._DEFAULTS, _strip_comments(base))

    if url:
        cfg["bridge_url"] = url
    cfg["bot"]["enabled"] = bot
    cfg["mcp"]["enabled"] = mcp
    if agent_name:
        cfg["bot"]["agent"] = agent_name
    if numbers:
        cfg["bot"]["allow_from"] = numbers
    elif source != "existente":
        # os números do exemplo são só ilustração — nunca herdar de lá
        cfg["bot"]["allow_from"] = []

    try:
        channels.save(cfg)
    except OSError as e:
        return f"Erro ao gravar {config_file.name}: {e}"

    # ── resultado ────────────────────────────────────────────────────────────
    lines = [
        f"{config_file.name} salvo na raiz do projeto "
        f"({'atualizado a partir do existente' if source == 'existente' else 'criado a partir de ' + source}).",
        f"  Modo Bot: {'ligado · agente ' + cfg['bot']['agent'] if bot else 'desligado'}",
    ]
    if bot:
        lines.append(f"  Números permitidos: {', '.join(cfg['bot']['allow_from'])}")
    lines.append(f"  Modo MCP: {'ligado' if mcp else 'desligado'}")
    lines.append(f"  bridge_url: {cfg['bridge_url']}")
    if source == "existente":
        lines.append("  Mantidos como estavam: groups e dm_policy.")
    host = urlparse(cfg["bridge_url"]).hostname
    if host not in _LOCAL_HOSTS:
        lines.append(
            f"  Atenção: bridge_url aponta para '{host}', fora desta máquina. "
            "O bridge do Ciel foi feito para rodar em 127.0.0.1."
        )
    return "\n".join(lines)
