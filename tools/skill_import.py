"""Absorve e replica uma skill externa como primitivas nativas do Ciel (tasks, tools, contexto)."""

REQUIREMENTS = ["requests"]

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── paths base (relativo ao projeto Ciel) ─────────────────────────────────────
_ROOT        = Path(__file__).parent.parent
_SKILLS_DIR  = _ROOT / "skills"
_TASKS_DIR   = _ROOT / "tasks"
_TOOLS_DIR   = _ROOT / "tools"
_SYSTEM_DIR  = _ROOT / "system"
_CONFIG_PATH = _ROOT / "ciel_config.json"

# extensões de texto que valem a pena ler da skill externa
_TEXT_EXTS = {
    ".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".toml", ".sh", ".bash", ".rst", ".html", ".css",
}
# arquivos a ignorar sempre
_IGNORE_NAMES = {
    "__pycache__", ".git", ".env", "node_modules", ".DS_Store",
    "*.pyc", "*.pyo",
}
# tamanho máximo por arquivo injetado no prompt (chars)
_MAX_FILE_CHARS = 8000


# ── leitura da skill externa ──────────────────────────────────────────────────

def _read_skill_files(path: Path) -> list[dict]:
    """
    Lê todos os arquivos de texto relevantes da skill externa.
    Retorna lista de {path, content} ordenada: manifest > README > skill.md > resto.
    """
    if path.is_file():
        # skill simples: arquivo único
        try:
            return [{"path": str(path), "content": path.read_text(encoding="utf-8")}]
        except Exception as e:
            return [{"path": str(path), "content": f"[erro ao ler: {e}]"}]

    if not path.is_dir():
        return []

    files = []
    priority = {"manifest.yaml": 0, "manifest.yml": 0, "skill.json": 0,
                "README.md": 1, "readme.md": 1, "skill.md": 2}

    for f in sorted(path.rglob("*")):
        if not f.is_file():
            continue
        if any(ig in f.parts for ig in _IGNORE_NAMES):
            continue
        if f.suffix.lower() not in _TEXT_EXTS:
            continue

        try:
            content = f.read_text(encoding="utf-8")
        except Exception as e:
            content = f"[erro ao ler: {e}]"

        # trunca arquivos muito grandes
        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + f"\n... [truncado — {len(content):,} chars total]"

        rel = str(f.relative_to(path))
        order = priority.get(f.name, 3)
        files.append({"path": rel, "content": content, "order": order})

    files.sort(key=lambda x: (x["order"], x["path"]))
    return [{"path": f["path"], "content": f["content"]} for f in files]


def _build_context_block(files: list[dict]) -> str:
    """Monta o bloco de contexto com os arquivos da skill."""
    if not files:
        return ""
    blocks = []
    for f in files:
        blocks.append(f"### {f['path']}\n```\n{f['content']}\n```")
    return "## Arquivos da skill externa\n\n" + "\n\n".join(blocks)


# ── carrega referências do Ciel pra injetar no prompt ─────────────────────────

def _load_tool_template() -> str:
    path = _SYSTEM_DIR / "tool_template.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    # fallback mínimo caso o arquivo não exista
    return """
Uma tool Ciel é um arquivo Python com esta estrutura EXATA (nesta ordem):

```python
\"\"\"Descrição curta do que a tool faz.\"\"\"

REQUIREMENTS = []  # pacotes pip necessários (lista vazia se nenhum)

# imports aqui

def run(param1: str, param2: str = "default") -> str:
    \"\"\"
    param1: descrição do parâmetro 1
    param2: descrição do parâmetro 2
    \"\"\"
    try:
        # implementação
        return "resultado"
    except Exception as e:
        return f"Erro: {e}"
```

Regras críticas:
- módulo-docstring SEMPRE na primeira linha
- REQUIREMENTS = [] SEMPRE após a docstring (mesmo vazio)
- def run() SEMPRE presente, é o ponto de entrada
- parâmetros SEMPRE anotados com tipo
- SEMPRE retorna str
- NUNCA propaga exceções — trata internamente
""".strip()


def _load_task_example() -> str:
    """Carrega um exemplo de task real do projeto."""
    for name in ["noticias_do_dia.md", "iniciar_rpg.md"]:
        p = _TASKS_DIR / name
        if p.exists():
            return p.read_text(encoding="utf-8")
    # fallback mínimo
    return """
## task: exemplo-de-task

objetivo: descrição curta do que a task faz

ações:
- ação em linguagem natural
- ação com tool específica [tool: nome_da_tool]
- outra ação descritiva

resultado esperado: o que deve ser entregue ao final
""".strip()


# ── monta prompt pro Grande Sábio ─────────────────────────────────────────────

def _build_prompt(skill_name: str, context_block: str) -> str:
    tool_template = _load_tool_template()
    task_example  = _load_task_example()

    return f"""Você é o Grande Sábio do Ciel. Sua função é analisar habilidades externas e replicá-las como primitivas nativas do sistema Ciel.

## Sistema Ciel — formato de tool

{tool_template}

## Sistema Ciel — formato de task

Uma task Ciel segue EXATAMENTE este formato:

```
{task_example}
```

Regras de task:
- Começa com `## task: nome-em-kebab-case`
- `objetivo:` em uma linha
- `ações:` lista com `-`; tools sugeridas entre `[tool: nome]`
- `resultado esperado:` em uma linha
- Ações devem ser atômicas — cada uma cabe num step do agente

## Skill a analisar

{context_block}

## Sua tarefa

Analise a skill acima e classifique-a em um dos três tipos:
- **plugin**: traz capacidades independentes (tools reutilizáveis, sem ordem obrigatória)
- **pipeline**: processo sequencial onde cada etapa depende da conclusão da anterior
- **context**: instrução pura sem código executável — só prompt/guia

Depois retorne APENAS um objeto JSON puro, sem markdown, sem texto antes ou depois:

{{
  "skill_name": "{skill_name}",
  "type": "plugin | pipeline | context",
  "description": "o que a skill faz em uma linha",
  "tasks": [
    {{
      "filename": "tasks/{skill_name}_etapa1.md",
      "content": "conteúdo completo da task no formato Ciel"
    }}
  ],
  "tools": [
    {{
      "filename": "tools/{skill_name}_ferramenta.py",
      "content": "código Python completo no formato Ciel"
    }}
  ],
  "requirements": ["pacote1", "pacote2"],
  "residual_prompt": "instruções que não viraram tasks nem tools (vazio se não houver)",
  "entry_task": "nome-da-primeira-task-sem-extensao (só pra tipo pipeline)",
  "summary": "o que foi compilado, quantas tasks e tools geradas, o que ficou como contexto"
}}

Regras importantes:
- `tasks` vazio se tipo plugin ou context
- `tools` vazio se tipo context
- `requirements` só pacotes pip externos — não inclua stdlib do Python
- Se a skill for context, coloque todo o conteúdo útil em `residual_prompt`
- Tools geradas devem seguir EXATAMENTE o formato de tool Ciel acima
- Tasks geradas devem seguir EXATAMENTE o formato de task Ciel acima
- `entry_task` só presente em pipeline — primeira task da fila em ordem de execução
- Retorne JSON puro — sem ```json, sem texto explicativo fora do JSON
"""


# ── chama o modelo secundário diretamente ─────────────────────────────────────

def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _call_secondary(prompt: str) -> str | None:
    """
    Chama a API do modelo secundário diretamente (sem passar pelo orquestrador).
    Retorna o conteúdo bruto ou None em caso de erro.
    """
    import requests as _req

    cfg         = _load_config()
    base_url    = cfg.get("base_url", "").rstrip("/")
    model       = cfg.get("model", "")
    api_key_env = cfg.get("api_key_env", "SECONDARY_MODEL_API_KEY")
    api_key     = os.environ.get(api_key_env, "") or cfg.get("api_key", "")
    timeout     = cfg.get("timeout", 180)
    max_tokens  = cfg.get("max_tokens", 16384)

    if not base_url or not model:
        return None
    if not api_key:
        return None

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Você é o Grande Sábio do Ciel — analista e replicador de habilidades. "
                    "Responda APENAS com JSON puro, sem markdown, sem texto adicional."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,  # baixo: queremos output estruturado e consistente
        "max_tokens": max_tokens,
        "stream": False,
    }

    try:
        resp = _req.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(timeout, None),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"__erro__: {e}"


# ── extrai JSON da resposta ───────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    if start == -1:
        return None
    for end in reversed([m.start() for m in re.finditer(r"\}", text)]):
        if end <= start:
            continue
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            continue
    return None


# ── salva as primitivas geradas ───────────────────────────────────────────────

def _save_primitives(data: dict, skill_name: str) -> dict:
    """
    Salva tasks, tools e contexto residual nos lugares certos.
    Retorna relatório do que foi salvo.
    """
    saved   = {"tasks": [], "tools": [], "residual": None, "errors": []}
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── tasks ──────────────────────────────────────────────────────────────────
    _TASKS_DIR.mkdir(parents=True, exist_ok=True)
    for t in data.get("tasks", []):
        filename = Path(t.get("filename", f"tasks/{skill_name}_task.md")).name
        dest     = _TASKS_DIR / filename
        try:
            dest.write_text(t["content"], encoding="utf-8")
            saved["tasks"].append(str(dest.relative_to(_ROOT)))
        except Exception as e:
            saved["errors"].append(f"task {filename}: {e}")

    # ── tools ──────────────────────────────────────────────────────────────────
    _TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    for t in data.get("tools", []):
        filename = Path(t.get("filename", f"tools/{skill_name}_tool.py")).name
        dest     = _TOOLS_DIR / filename
        try:
            dest.write_text(t["content"], encoding="utf-8")
            saved["tools"].append(str(dest.relative_to(_ROOT)))
        except Exception as e:
            saved["errors"].append(f"tool {filename}: {e}")

    # ── contexto residual → skills/<nome>.md ──────────────────────────────────
    residual = data.get("residual_prompt", "").strip()
    if residual:
        _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        dest = _SKILLS_DIR / f"{skill_name}.md"
        try:
            dest.write_text(residual, encoding="utf-8")
            saved["residual"] = str(dest.relative_to(_ROOT))
        except Exception as e:
            saved["errors"].append(f"residual {skill_name}.md: {e}")

    # ── manifesto local → skills/<nome>_meta.json ─────────────────────────────
    meta = {
        "skill_name":  skill_name,
        "type":        data.get("type", "context"),
        "description": data.get("description", ""),
        "entry_task":  data.get("entry_task", ""),
        "tasks":       [Path(t.get("filename", "")).name for t in data.get("tasks", [])],
        "tools":       [Path(t.get("filename", "")).name for t in data.get("tools", [])],
        "residual":    saved["residual"] or "",
        "absorbed_at": ts,
    }
    meta_dest = _SKILLS_DIR / f"{skill_name}_meta.json"
    try:
        _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        meta_dest.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        saved["errors"].append(f"meta {skill_name}_meta.json: {e}")

    return saved


def _install_requirements(reqs: list[str]) -> list[str]:
    """Instala pacotes pip necessários. Retorna lista de erros."""
    errors = []
    for pkg in reqs:
        pkg = pkg.strip()
        if not pkg:
            continue
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                errors.append(f"{pkg}: {result.stderr[:200]}")
        except Exception as e:
            errors.append(f"{pkg}: {e}")
    return errors


# ── ponto de entrada ──────────────────────────────────────────────────────────

def run(path: str, nome: str = "") -> str:
    """
    path: caminho da skill externa (diretório ou arquivo .md)
    nome: nome da skill no Ciel em kebab-case (inferido do path se omitido)
    """
    skill_path = Path(path).expanduser().resolve()

    if not skill_path.exists():
        return f"Erro: caminho não encontrado — {path}"

    # infere nome da skill se não fornecido
    if not nome:
        nome = re.sub(r"[^\w\-]", "-", skill_path.stem).strip("-").lower()
    nome = re.sub(r"[^\w\-]", "-", nome).strip("-").lower()

    # ── lê arquivos da skill ───────────────────────────────────────────────────
    files = _read_skill_files(skill_path)
    if not files:
        return f"Erro: nenhum arquivo de texto encontrado em '{path}'"

    n_files = len(files)
    total_chars = sum(len(f["content"]) for f in files)

    # ── monta contexto e prompt ───────────────────────────────────────────────
    context_block = _build_context_block(files)
    prompt        = _build_prompt(nome, context_block)

    # ── chama o Grande Sábio ──────────────────────────────────────────────────
    raw = _call_secondary(prompt)

    if raw is None:
        return (
            "Erro: modelo secundário não configurado. "
            "Verifique ciel_config.json (base_url, model, api_key)."
        )

    if raw.startswith("__erro__:"):
        return f"Erro ao chamar modelo secundário: {raw[9:].strip()}"

    # ── extrai JSON ───────────────────────────────────────────────────────────
    data = _extract_json(raw)
    if not data:
        # salva resposta bruta pra debug
        debug_path = _ROOT / "data" / "user" / f"skill_import_debug_{nome}.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(raw, encoding="utf-8")
        return (
            f"Erro: Grande Sábio não retornou JSON válido.\n"
            f"Resposta bruta salva em: {debug_path.relative_to(_ROOT)}\n"
            f"Dica: verifique se o modelo está seguindo as instruções e tente novamente."
        )

    skill_type = data.get("type", "context")

    # ── instala requirements se necessário ───────────────────────────────────
    reqs       = data.get("requirements", [])
    req_errors = []
    if reqs:
        req_errors = _install_requirements(reqs)

    # ── salva primitivas ──────────────────────────────────────────────────────
    saved = _save_primitives(data, nome)

    # ── monta relatório ───────────────────────────────────────────────────────
    lines = [
        f"✓ Skill absorvida: {nome} ({skill_type})",
        f"  {n_files} arquivo(s) analisado(s) · {total_chars:,} chars",
        "",
    ]

    if saved["tasks"]:
        lines.append(f"  tasks geradas ({len(saved['tasks'])}):")
        for t in saved["tasks"]:
            lines.append(f"    - {t}")

    if saved["tools"]:
        lines.append(f"  tools geradas ({len(saved['tools'])}):")
        for t in saved["tools"]:
            lines.append(f"    - {t}")

    if saved["residual"]:
        lines.append(f"  contexto residual: {saved['residual']}")

    if reqs and not req_errors:
        lines.append(f"  requirements instalados: {', '.join(reqs)}")
    elif req_errors:
        lines.append(f"  ⚠ erros ao instalar requirements:")
        for e in req_errors:
            lines.append(f"    - {e}")

    if saved["errors"]:
        lines.append(f"  ⚠ erros ao salvar:")
        for e in saved["errors"]:
            lines.append(f"    - {e}")

    lines.append("")
    lines.append(f"  {data.get('summary', '')}")

    if skill_type == "pipeline":
        entry = data.get("entry_task", "")
        if entry:
            lines.append(f"\n  Para executar: /replicar {nome}")
    elif skill_type == "plugin":
        tool_names = [Path(t.get("filename","")).stem for t in data.get("tools",[])]
        if tool_names:
            lines.append(f"\n  Tools disponíveis: {', '.join(tool_names)}")
            lines.append(f"  (recarregue o registry ou reinicie pra usar)")
    elif skill_type == "context":
        lines.append(f"\n  Para usar: /skill {nome} <seu prompt>")

    return "\n".join(lines)
