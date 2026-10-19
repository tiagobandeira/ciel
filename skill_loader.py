"""
skill_loader.py — leitura centralizada de `skills/*.md`.

Antes deste módulo, cada consumidor lia a pasta do seu jeito:

    tools/secondary_model.py  →  injeta o texto cru no system prompt
    tools/list_skills.py      →  extrai description/mode com regex própria
    cli.py / ciel_tui.py      →  varre a pasta para listar e exibir

Isso impedia o modo build de usar a mesma skill como system prompt do
orquestrador, e fazia o front-matter (`--- mode: code ---`) ser ignorado
na injeção. Aqui fica a fonte única.

Formato aceito (o mesmo dos arquivos atuais):

    ---
    mode: code
    description: Uma linha sobre a skill
    requer: secundario          # opcional (roadmap: secundario | nenhum)
    tools: calculator, read_file
    ---
    # Título da skill
    ...

O front-matter é opcional; sem ele, `extract_metadata()` mantém exatamente
o fallback histórico (chave `description:` no corpo ou primeiro parágrafo
após o título).

Nada aqui importa Rich/Textual; serve CLI, TUI, server, bots e o runner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

SKILL_LEVELS = ("obrigatoria", "sugerida", "opcional")
DEFAULT_SKILL_LEVEL = "opcional"

_FRONT_MATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*$")


# ── front-matter ──────────────────────────────────────────────────────────

def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """
    Separa o front-matter do corpo.

    Retorna (meta, body). Sem front-matter, meta={} e body=text.
    Chaves são normalizadas para minúsculas.
    """
    if not text:
        return {}, ""
    raw = text.lstrip("\ufeff")

    match = _FRONT_MATTER_RE.match(raw)
    if not match:
        return {}, raw

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip().lower()
        if not _KEY_RE.match(key):
            continue
        meta[key] = _strip_quotes(value)

    return meta, raw[match.end():]


def extract_metadata(text: str) -> dict:
    """
    Compatível com o antigo `tools/list_skills._extract_metadata`.

    Retorna {'description': str, 'mode': str}. A descrição vem do
    front-matter, senão de uma linha `description:` no corpo, senão do
    primeiro parágrafo após o título (truncado em 120 chars).
    """
    meta, _ = parse_front_matter(text)
    description = meta.get("description", "")
    mode = meta.get("mode", "")

    if not description:
        match = re.search(
            r"^description:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE
        )
        if match:
            description = match.group(1).strip()
        else:
            past_title = False
            for line in text.splitlines():
                stripped = line.strip()
                if not past_title:
                    if stripped.startswith("#"):
                        past_title = True
                    continue
                if stripped and not stripped.startswith("---"):
                    description = stripped[:120]
                    break

    return {"description": description, "mode": mode}


# ── modelo de skill ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class Skill:
    """Uma skill carregada do disco."""

    name: str
    path: Path
    text: str = ""
    body: str = ""
    meta: dict = field(default_factory=dict)
    description: str = ""
    mode: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def requires(self) -> str:
        """`requer:` do front-matter (`secundario` | `nenhum`)."""
        return (
            self.meta.get("requer")
            or self.meta.get("requires")
            or "nenhum"
        ).strip().lower()

    @property
    def tools(self) -> list[str]:
        raw = self.meta.get("tools", "")
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def label(self) -> str:
        mode = f"  [mode: {self.mode}]" if self.mode else ""
        return f"{self.name}{mode}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "description": self.description,
            "mode": self.mode,
            "requires": self.requires,
            "tools": self.tools,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class SkillBinding:
    """Skill vinculada a uma persona, com o nível declarado no agente."""

    skill: Skill
    level: str = DEFAULT_SKILL_LEVEL


# ── paths ─────────────────────────────────────────────────────────────────

def _skills_dir(skills_dir: str | Path | None) -> Path:
    return Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR


def _resolve_path(name: str, base: Path) -> Path | None:
    """
    Resolve `name` dentro de `base`, aceitando com ou sem `.md` e
    recusando traversal para fora da pasta de skills.
    """
    name = (name or "").strip()
    if not name:
        return None

    candidates = [name] if name.endswith(".md") else [f"{name}.md", name]
    base_resolved = base.resolve()

    for candidate in candidates:
        path = (base / candidate)
        try:
            resolved = path.resolve()
        except OSError:
            continue
        # precisa ficar dentro de base (inclusive arquivo direto em base)
        if resolved == base_resolved or base_resolved in resolved.parents:
            return path
    return None


# ── leitura ───────────────────────────────────────────────────────────────

def load_skill(
    name: str,
    skills_dir: str | Path | None = None,
) -> Skill | None:
    """Carrega uma skill pelo nome; None se não existir."""
    base = _skills_dir(skills_dir)
    path = _resolve_path(name, base)
    if path is None or not path.exists() or not path.is_file():
        return None

    stem = path.stem
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return Skill(name=stem, path=path, error=str(exc))

    meta, body = parse_front_matter(text)
    info = extract_metadata(text)
    return Skill(
        name=stem,
        path=path,
        text=text,
        body=body,
        meta=meta,
        description=info["description"],
        mode=info["mode"],
    )


def load_text(
    name: str,
    skills_dir: str | Path | None = None,
) -> str | None:
    """
    Texto completo da skill, exatamente como está no disco (com front-matter).

    É o comportamento histórico de `secondary_model._load_skill`, mantido
    para não alterar o prompt enviado ao modelo secundário.
    """
    skill = load_skill(name, skills_dir=skills_dir)
    if skill is None or not skill.ok:
        return None
    return skill.text


def list_skills(skills_dir: str | Path | None = None) -> list[Skill]:
    """Lista as skills `.md` da pasta, em ordem alfabética."""
    base = _skills_dir(skills_dir)
    if not base.exists() or not base.is_dir():
        return []

    skills: list[Skill] = []
    for path in sorted(base.glob("*.md")):
        skill = load_skill(path.stem, skills_dir=base)
        if skill is not None:
            skills.append(skill)
    return skills


def skills_for_agent(
    agent_info: dict,
    *,
    skills_dir: str | Path | None = None,
    levels: tuple[str, ...] | None = None,
) -> list[SkillBinding]:
    """
    Resolve a seção `## Skills` de uma persona (`agent_info["skills"]`).

    Mantém a ordem declarada, ignora skills ausentes e normaliza níveis
    desconhecidos para `opcional` — o mesmo default de `agent_loader`.
    """
    entries = (agent_info or {}).get("skills") or []
    bindings: list[SkillBinding] = []
    seen: set[str] = set()

    for entry in entries:
        if isinstance(entry, str):
            name, level = entry, DEFAULT_SKILL_LEVEL
        elif isinstance(entry, dict):
            name = str(entry.get("name") or "")
            level = str(entry.get("level") or DEFAULT_SKILL_LEVEL).lower()
        else:
            continue

        name = name.strip()
        if not name or name in seen:
            continue
        if level not in SKILL_LEVELS:
            level = DEFAULT_SKILL_LEVEL
        if levels is not None and level not in levels:
            continue

        skill = load_skill(name, skills_dir=skills_dir)
        if skill is None:
            continue

        seen.add(name)
        bindings.append(SkillBinding(skill=skill, level=level))

    return bindings


__all__ = [
    "DEFAULT_SKILLS_DIR",
    "SKILL_LEVELS",
    "DEFAULT_SKILL_LEVEL",
    "Skill",
    "SkillBinding",
    "parse_front_matter",
    "extract_metadata",
    "load_skill",
    "load_text",
    "list_skills",
    "skills_for_agent",
]
