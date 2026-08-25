"""Consulta o modelo secundário para tarefas que exigem raciocínio complexo ou contexto extenso."""

REQUIREMENTS = ["requests"]

import json
import os
import re
from pathlib import Path
from datetime import datetime
import requests

# ── config padrão (sobrescrita por ciel_config.json se existir) ───────────────
_DEFAULT_CONFIG = {
    "base_url":              "https://integrate.api.nvidia.com/v1",
    "model":                 "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "api_key_env":           "SECONDARY_MODEL_API_KEY",
    "timeout":               120,
    "max_chars_per_session": 40000,
    "max_response_chars":    8000,
}

_CONFIG_PATH  = Path(__file__).parent.parent / "ciel_config.json"
_QUOTA_PATH   = Path(__file__).parent.parent / "data" / "secondary_quota.json"
_RESPONSE_DIR = Path(__file__).parent.parent / "data" / "user"
_SKILLS_DIR   = Path(__file__).parent.parent / "skills"

# ── system prompts por modo ───────────────────────────────────────────────────
_SYSTEM_TEXT = "Você é um assistente especialista. Responda de forma precisa e completa em Markdown."

_SYSTEM_CODE = """Você é um desenvolvedor especialista. Responda APENAS com um objeto JSON puro, sem texto adicional, sem markdown, sem explicações fora do JSON.

Formato obrigatório:
{
  "folder": "nome-do-projeto",
  "files": [
    { "filename": "index.html", "content": "conteúdo completo aqui" },
    { "filename": "style.css",  "content": "conteúdo completo aqui" },
    { "filename": "script.js",  "content": "conteúdo completo aqui" }
  ],
  "summary": "descrição do artefato gerado: quais arquivos foram criados, o que cada um contém e como usá-los"
}

Regras:
- filename deve ter a extensão correta (.html, .css, .js, .py, .ipynb, .txt, etc.)
- content deve ser o código completo e funcional
- folder deve ser um nome em kebab-case sem espaços
- Nunca coloque markdown ou texto fora do JSON
- O campo summary descreve o que foi GERADO (arquivos e seu conteúdo), nunca resultados de execução — o código não foi executado
"""


def _load_skill(skill: str) -> str | None:
    """
    Lê o conteúdo de uma skill em skills/<skill>.md.
    Retorna o texto da skill ou None se não encontrada.
    """
    path = _SKILLS_DIR / f"{skill}.md"
    if not path.exists():
        # tenta sem extensão caso o usuário já tenha passado o nome com .md
        path = _SKILLS_DIR / skill
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


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


def _save_text_response(content: str) -> str:
    """Salva resposta longa em .md e retorna o caminho relativo."""
    _RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _RESPONSE_DIR / f"secondary_response_{ts}.md"
    path.write_text(content, encoding="utf-8")
    return str(path.relative_to(Path(__file__).parent.parent))


def _save_code_project(data: dict) -> tuple[str, list[str]]:
    """
    Salva os arquivos do projeto em data/user/<folder>/.
    Retorna (caminho_da_pasta, lista_de_arquivos_criados).
    """
    folder    = re.sub(r"[^\w\-]", "-", data.get("folder", "projeto")).strip("-")
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    proj_dir  = _RESPONSE_DIR / f"{folder}_{ts}"
    proj_dir.mkdir(parents=True, exist_ok=True)

    created = []
    for f in data.get("files", []):
        filename = f.get("filename", "file.txt")
        content  = f.get("content", "")
        filepath = proj_dir / filename
        filepath.write_text(content, encoding="utf-8")
        created.append(filename)

    rel_path = str(proj_dir.relative_to(Path(__file__).parent.parent))
    return rel_path, created


def _extract_json(text: str) -> dict | None:
    """Tenta extrair JSON da resposta — remove markdown fences se necessário."""
    text = text.strip()
    # remove ```json ... ``` se o modelo insistir em usar
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        # tenta achar o primeiro { ... } válido na resposta
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return None


def run(
    prompt: str,
    mode: str = "text",
    session_id: str = "_nosession",
    system: str = "",
    save_response: bool = False,
    skill: str = "",
) -> str:
    """
    prompt: descrição completa do problema para o modelo secundário
    mode: 'text' para respostas em markdown | 'code' para projeto com arquivos separados
    session_id: ID da sessão atual (controle de cota — injetado automaticamente)
    system: instrução de sistema opcional (sobrescreve o padrão do modo)
    save_response: se True, força salvar em arquivo mesmo que resposta seja curta (só no modo text)
    skill: nome da skill em skills/ a ser injetada no system prompt (ex: 'django-api')
    """
    cfg = _load_config()

    # ── verifica cota ─────────────────────────────────────────────────────────
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
    api_key     = os.environ.get(api_key_env, "") or cfg.get("api_key", "")

    if not api_key:
        return (
            f"API key não encontrada. "
            f"Defina a variável de ambiente '{api_key_env}' "
            f"ou adicione 'api_key' em ciel_config.json."
        )

    # ── define system prompt ──────────────────────────────────────────────────
    if not system:
        system = _SYSTEM_CODE if mode == "code" else _SYSTEM_TEXT

    # ── injeta skill no system prompt (se fornecida) ──────────────────────────
    if skill:
        skill_content = _load_skill(skill)
        if skill_content:
            system = f"{system}\n\n---\n\n## Skill ativa: {skill}\n\n{skill_content}"
        else:
            # informa no prompt que a skill não foi encontrada, mas não bloqueia
            prompt = f"[aviso: skill '{skill}' não encontrada em skills/]\n\n{prompt}"

    # ── chamada à API ─────────────────────────────────────────────────────────
    base_url = cfg.get("base_url", _DEFAULT_CONFIG["base_url"]).rstrip("/")
    model    = cfg.get("model",    _DEFAULT_CONFIG["model"])
    timeout  = cfg.get("timeout",  _DEFAULT_CONFIG["timeout"])

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": cfg.get("max_tokens", 16384),
    }

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except requests.Timeout:
        return f"Erro: timeout após {timeout}s aguardando resposta do modelo secundário."
    except requests.HTTPError:
        return f"Erro HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        return f"Erro ao chamar modelo secundário: {e}"

    # ── atualiza cota ─────────────────────────────────────────────────────────
    _save_quota(session_id, used + prompt_chars)

    # ── mode: code ────────────────────────────────────────────────────────────
    if mode == "code":
        project = _extract_json(content)
        if project and "files" in project:
            folder_path, files = _save_code_project(project)
            summary = project.get("summary", "")
            files_list = "\n".join(f"  - {f}" for f in files)
            return (
                f"Projeto criado em: {folder_path}\n\n"
                f"Arquivos:\n{files_list}\n\n"
                f"{summary}"
            )
        else:
            # fallback: modelo não retornou JSON válido → salva como .md
            path = _save_text_response(content)
            return (
                f"[aviso] Modelo não retornou JSON estruturado. "
                f"Resposta salva como texto em: {path}\n\n"
                f"Prévia:\n{content[:400].strip()}\n…"
            )

    # ── mode: text ────────────────────────────────────────────────────────────
    max_resp = cfg.get("max_response_chars", 8000)
    if save_response or len(content) > max_resp:
        path = _save_text_response(content)
        return (
            f"Resposta completa salva em: {path}\n\n"
            f"Prévia:\n{content[:400].strip()}\n…\n\n"
            f"Use read_file com o caminho acima para ler a resposta completa."
        )

    return content