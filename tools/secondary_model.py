"""Consulta o modelo secundário para tarefas que exigem raciocínio complexo ou contexto extenso."""

REQUIREMENTS = ["requests", "rich"]

import json
import os
import re
import sys
import time
import threading
import queue
from pathlib import Path
from datetime import datetime
import requests
from rich.console import Console, Group
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich.syntax import Syntax
from rich.rule import Rule

# ── config padrão (sobrescrita por ciel_config.json se existir) ───────────────
_DEFAULT_CONFIG = {
    "base_url":              "https://integrate.api.nvidia.com/v1",
    "model":                 "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "api_key_env":           "SECONDARY_MODEL_API_KEY",
    "timeout":               180,
    "max_chars_per_session": 40000,
    "max_response_chars":    8000,
}

_CONFIG_PATH  = Path(__file__).parent.parent / "ciel_config.json"
_QUOTA_PATH   = Path(__file__).parent.parent / "data" / "secondary_quota.json"
_RESPONSE_DIR = Path(__file__).parent.parent / "data" / "user"
_SKILLS_DIR   = Path(__file__).parent.parent / "skills"
_MOCK_DIR     = Path(__file__).parent.parent / "data" / "mock"
_MOCK_FILE    = _MOCK_DIR / "mock_responses.json"

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



# Console dedicado pro stderr — não interfere no stdout do orquestrador
_err = Console(stderr=True, highlight=False)

# Sentinel para sinalizar fim do stream ao consumidor
_STREAM_DONE = object()


class _Spinner:
    """
    Spinner rich para a fase de handshake HTTP (antes do primeiro token).
    Usa estado explícito (.done() / .fail()) — `return` dentro de `with`
    não propaga exc_type, então __exit__ receberia sempre None.
    """

    def __init__(self, model: str, max_retries: int = 0):
        self._model      = model.split("/")[-1]
        self._max_tries  = max_retries + 1
        self._attempt    = 1
        self._status     = ""
        self._success    = None
        self._fail_reason = ""
        self._start      = time.monotonic()
        self._live       = Live(console=_err, refresh_per_second=12)

    def __enter__(self):
        self._live.start()
        self._live.update(self._render())
        return self

    def __exit__(self, exc_type, *_):
        self._live.stop()
        elapsed = int(time.monotonic() - self._start)
        if self._success is True:
            _err.print(
                f"  [green]✓[/green] [bright_black]modelo secundário · "
                f"conectado em {elapsed}s[/bright_black]"
            )
        else:
            reason = f" · {self._fail_reason}" if self._fail_reason else ""
            _err.print(
                f"  [red]✗[/red] [bright_black]modelo secundário · "
                f"falhou após {elapsed}s{reason}[/bright_black]"
            )

    def _render(self) -> Text:
        attempt = (
            f" · tentativa {self._attempt}/{self._max_tries}"
            if self._max_tries > 1 else ""
        )
        status = f" [{self._status}]" if self._status else ""
        elapsed = int(time.monotonic() - self._start)
        t = Text()
        t.append("  ")
        t.append(Spinner("dots").render(time.monotonic()).plain + " ", style="yellow")
        t.append(f"modelo secundário · {self._model}", style="bright_black")
        t.append(f"{attempt}", style="bright_black")
        t.append(f" · conectando...{status} {elapsed}s", style="bright_black")
        return t

    def _refresh(self):
        if self._live.is_started:
            self._live.update(self._render())

    def done(self):
        self._success = True

    def fail(self, reason: str = ""):
        self._success     = False
        self._fail_reason = reason

    def set_attempt(self, n: int):
        self._attempt = n
        self._status  = ""
        self._refresh()

    def set_status(self, msg: str):
        self._status = msg
        self._refresh()



def _ext_to_lexer(filename: str) -> str:
    """Mapeia extensão de arquivo para lexer do Pygments/rich."""
    ext = Path(filename).suffix.lower()
    return {
        ".html": "html",
        ".css":  "css",
        ".js":   "javascript",
        ".py":   "python",
        ".ts":   "typescript",
        ".json": "json",
        ".md":   "markdown",
        ".sh":   "bash",
        ".ipynb":"json",
    }.get(ext, "text")


def _print_file_preview(filename: str, content: str, max_lines: int = 40):
    lines   = content.splitlines()
    preview = "\n".join(lines[:max_lines])
    truncated = len(lines) > max_lines
    _err.print(Rule(f"[bold cyan]{filename}[/bold cyan]", style="bright_black"))
    _err.print(Syntax(preview, _ext_to_lexer(filename), theme="monokai", line_numbers=True, word_wrap=False))
    if truncated:
        _err.print(f"  [bright_black]… +{len(lines) - max_lines} linhas omitidas[/bright_black]")
    _err.print()


def _print_build_phase(project, content, cfg):
    max_tokens = cfg.get("max_tokens", 16384)
    if project is None or "files" not in project:
        _err.print()
        _err.print("  [yellow]⚠ resposta incompleta[/yellow] [bright_black]— o modelo pode ter atingido o limite de tokens[/bright_black]")
        _err.print(f"  [bright_black]dica: aumente [cyan]max_tokens[/cyan] em ciel_config.json (atual: {max_tokens:,})[/bright_black]")
        _err.print()
        return
    _err.print()
    _err.print(Rule("[bold]construindo projeto[/bold]", style="bright_black"))
    _err.print()
    for f in project.get("files", []):
        _print_file_preview(f.get("filename", "arquivo"), f.get("content", ""))
    files = [f.get("filename", "") for f in project.get("files", [])]
    sizes = [len(f.get("content", "")) for f in project.get("files", [])]
    files_fmt = "  ".join(
        f"[cyan]{fn}[/cyan] [bright_black]({sz:,}c)[/bright_black]"
        for fn, sz in zip(files, sizes)
    )
    _err.print(Rule(style="bright_black"))
    _err.print(f"  {files_fmt}")
    _err.print()


def _format_token_usage(usage: dict, cfg: dict) -> str:
    """
    Formata o bloco de uso de tokens para exibição no terminal.
    Inclui custo estimado se 'token_cost_per_1k' estiver em ciel_config.json.
    """
    prompt_tok     = usage.get("prompt_tokens", 0)
    completion_tok = usage.get("completion_tokens", 0)
    total_tok      = usage.get("total_tokens", 0)

    # custo estimado — opcional, definido em ciel_config.json
    # ex: "token_cost_per_1k": {"input": 0.0004, "output": 0.0016}
    cost_cfg  = cfg.get("token_cost_per_1k", {})
    cost_line = ""
    if cost_cfg:
        cost_in    = (prompt_tok     / 1000) * cost_cfg.get("input",  0)
        cost_out   = (completion_tok / 1000) * cost_cfg.get("output", 0)
        cost_total = cost_in + cost_out
        cost_line  = f" · [yellow]~${cost_total:.4f}[/yellow]"

    return (
        f"  [bright_black]tokens:[/bright_black] "
        f"[cyan]prompt {prompt_tok:,}[/cyan] "
        f"[bright_black]+[/bright_black] "
        f"[green]saída {completion_tok:,}[/green] "
        f"[bright_black]= total {total_tok:,}[/bright_black]"
        f"{cost_line}"
    )


def _stream_response(
    resp: requests.Response,
    mode: str = "text",
    debug: bool = False,
) -> tuple[str, dict]:
    """
    Consome SSE em thread separada e renderiza com rich.
    mode=text:  spinner -> tokens em cinza -> conclusao
    mode=code:  spinner -> detecta filenames -> conclusao (sem mostrar JSON bruto)

    Retorna (content: str, usage: dict) onde usage pode ser vazio
    se o provider não suportar stream_options.
    """
    raw_lines: list[str] = []
    tok_queue: queue.Queue = queue.Queue()

    # Usage capturado do último chunk SSE (OpenAI-compatible: chunk com choices=[] e usage={})
    _usage_holder: list[dict] = []

    def _reader():
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if debug and len(raw_lines) < 50:
                raw_lines.append(repr(line))
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except Exception:
                continue

            # chunk de usage: choices pode ser [] e usage preenchido
            if obj.get("usage") and not _usage_holder:
                _usage_holder.append(obj["usage"])

            choices = obj.get("choices") or []
            if not choices:
                continue
            token = choices[0].get("delta", {}).get("content") or ""
            if token:
                tok_queue.put(token)
        tok_queue.put(_STREAM_DONE)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    chunks:     list[str] = []
    start       = time.monotonic()
    got_first   = False
    visible     = Text()
    buffer      = ""
    seen_files: list[str] = []
    spinner_obj = Spinner("dots")
    tok_count   = 0  # contador de tokens chegando (aproximação por chunk)

    def _make_renderable():
        spinner_line = Text()
        spinner_line.append("  ")
        spinner_line.append(spinner_obj.render(time.monotonic()).plain + " ", style="yellow")
        elapsed = int(time.monotonic() - start)

        if mode == "code":
            if seen_files:
                spinner_line.append(f"gerando... {seen_files[-1]}", style="bright_black")
            elif got_first:
                spinner_line.append(f"recebendo... ", style="bright_black")
                spinner_line.append(f"~{tok_count} tok", style="cyan")
                spinner_line.append(f" · {elapsed}s", style="bright_black")
            else:
                spinner_line.append(f"aguardando tokens... {elapsed}s", style="bright_black")
            return spinner_line

        # mode=text
        if not got_first:
            spinner_line.append(f"aguardando tokens... {elapsed}s", style="bright_black")
            return Group(spinner_line, visible)

        # got_first=True: mostra contador de tokens ao lado do spinner
        spinner_line.append(f"~{tok_count} tok", style="cyan")
        spinner_line.append(f" · {elapsed}s", style="bright_black")
        return Group(spinner_line, visible)

    with Live(_make_renderable(), console=_err, refresh_per_second=12, vertical_overflow="visible") as live:
        while True:
            try:
                item = tok_queue.get(timeout=0.1)
            except queue.Empty:
                live.update(_make_renderable())
                continue

            if item is _STREAM_DONE:
                break

            got_first = True
            chunks.append(item)
            # estimativa de tokens: cada chunk da API costuma ser 1 token,
            # mas usamos contagem de chunks como proxy visual — corrigido pelo usage real no fim
            tok_count += 1

            if mode == "code":
                buffer += item
                found = re.findall(r'"filename"\s*:\s*"([^"]+)"', buffer)
                for fname in found:
                    if fname not in seen_files:
                        seen_files.append(fname)
                        live.update(_make_renderable())
            else:
                visible.append(item, style="dim white")
                lines = visible.plain.split("\n")
                if len(lines) > 6:
                    trimmed = "\n".join(lines[-6:])
                    visible = Text(trimmed, style="dim white", no_wrap=False)
                live.update(_make_renderable())

    reader.join()
    elapsed_total = int(time.monotonic() - start)
    total_chars   = len("".join(chunks))
    usage         = _usage_holder[0] if _usage_holder else {}

    if chunks:
        _err.print(
            f"  [bright_black]✓ stream concluído · {elapsed_total}s · {total_chars:,} chars[/bright_black]"
        )
    else:
        _err.print(f"  [yellow]⚠ stream concluído sem tokens · {elapsed_total}s[/yellow]")

    if debug and raw_lines:
        debug_path = _RESPONSE_DIR / "sse_debug.txt"
        _RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
        debug_path.write_text("\n".join(raw_lines), encoding="utf-8")
        _err.print(f"  [bright_black][debug] SSE bruto salvo em: {debug_path}[/bright_black]")

    return "".join(chunks), usage


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
    """
    Tenta extrair o primeiro JSON válido da resposta do modelo.

    Estratégias em ordem:
    1. Remove fences de markdown (```json ... ```) onde quer que estejam
    2. Tenta parse direto da string limpa
    3. Localiza o primeiro '{' e tenta parsear até cada '}' do mais externo
       para o mais interno — ignora texto antes e depois do JSON
    """
    text = text.strip()

    # 1. remove todas as fences de markdown
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text).strip()

    # 2. tenta parse direto
    try:
        return json.loads(text)
    except Exception:
        pass

    # 3. busca progressiva: do primeiro { até cada } do mais externo ao mais interno
    start = text.find("{")
    if start == -1:
        return None

    end_positions = [m.start() for m in re.finditer(r"\}", text)]
    for end in reversed(end_positions):
        if end <= start:
            continue
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            continue

    return None


def _load_mock_responses() -> dict:
    """
    Carrega respostas customizadas de data/mock/mock_responses.json.
    Retorna dict vazio se o arquivo não existir.
    """
    if not _MOCK_FILE.exists():
        return {}
    try:
        return json.loads(_MOCK_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[MOCK] Erro ao carregar mock_responses.json: {e}")
        return {}


def _run_mock(mock_type: str, mode: str, skill: str, prompt: str = "") -> str:
    """
    Simula a resposta do modelo secundário para testes de fluxo.

    Respostas customizadas em data/mock/mock_responses.json sobrescrevem os defaults.

    mock_type (definido em ciel_config.json → "mock_type"):
      "code"      → JSON válido com files[] — testa salvamento e list_directory
      "text"      → resposta markdown curta — testa mode text
      "text_long" → resposta longa — testa fallback de salvamento em .md
      "invalid"   → JSON malformado — testa fallback do mode code
      "error"     → simula erro HTTP 503 — testa retry/backoff
      "quota"     → simula cota esgotada
    """
    _MOCK_BANNER = "[MOCK]"
    has_files = "## Contexto — arquivos fornecidos" in prompt
    prompt_preview = prompt[:200].replace("\n", " ")
    print(
        f"\n{_MOCK_BANNER} secondary_model chamado\n"
        f"  mode   : {mode}\n"
        f"  skill  : {skill or '(nenhuma)'}\n"
        f"  tipo   : {mock_type}\n"
        f"  files  : {'✓ bloco de contexto injetado' if has_files else '✗ sem arquivos'}\n"
        f"  prompt : {prompt_preview}...\n"
    )

    # carrega customizações do arquivo externo
    custom = _load_mock_responses()

    if mock_type == "error":
        raise requests.HTTPError(
            response=type("R", (), {"status_code": 503, "text": "[MOCK] Servidor indisponível"})()
        )

    if mock_type == "quota":
        return (
            "Cota do modelo secundário esgotada para esta sessão. "
            "Usado: 40,000 chars / Limite: 40,000 chars. "
            "Restante: 0 chars. [MOCK]"
        )

    if mock_type == "invalid":
        content = custom.get("invalid", "Resposta sem JSON válido. [MOCK]")
        if mode == "code":
            path = _save_text_response(content)
            return (
                f"[aviso] Modelo não retornou JSON estruturado. "
                f"Resposta salva como texto em: {path}\n\n"
                f"Prévia:\n{content[:400].strip()}\n… [MOCK]"
            )
        return content

    if mock_type == "text_long":
        content = custom.get(
            "text_long",
            "# Análise Mock\n\n"
            + ("Parágrafo de mock para simular resposta longa. " * 200)
            + "\n\n[MOCK]",
        )
        path = _save_text_response(content)
        return (
            f"Resposta completa salva em: {path}\n\n"
            f"Prévia:\n{content[:400].strip()}\n…\n\n"
            f"Use read_file com o caminho acima para ler a resposta completa. [MOCK]"
        )

    if mock_type == "text":
        return custom.get(
            "text",
            f"# Resposta Mock\n\n"
            f"Resposta simulada em modo `text`.\n\n"
            f"- **mode**: `{mode}`\n"
            f"- **skill**: `{skill or '(nenhuma)'}`\n\n"
            f"[MOCK] Fluxo funcionando corretamente.",
        )

    # padrão: mock_type == "code"
    default_project = {
        "folder": "mock-projeto",
        "files": [
            {
                "filename": "index.html",
                "content": (
                    "<!DOCTYPE html><html lang='pt-BR'><head>"
                    "<meta charset='UTF-8'><title>Mock</title>"
                    "<link rel='stylesheet' href='style.css'></head>"
                    "<body><h1>Mock Project</h1>"
                    "<script src='script.js'></script></body></html>"
                ),
            },
            {
                "filename": "style.css",
                "content": "body { font-family: sans-serif; padding: 2rem; background: #111; color: #eee; }",
            },
            {
                "filename": "script.js",
                "content": f"console.log('[MOCK] mode={mode} skill={skill or 'none'}');",
            },
        ],
        "summary": (
            f"[MOCK] Projeto simulado. mode={mode} | skill={skill or 'nenhuma'} | "
            f"Arquivos: index.html, style.css, script.js"
        ),
    }

    # customização do code: aceita project inteiro ou só files
    mock_project = custom.get("code", default_project)
    # garante folder e summary se o custom não tiver
    if "folder" not in mock_project:
        mock_project["folder"] = default_project["folder"]
    if "summary" not in mock_project:
        mock_project["summary"] = default_project["summary"]

    folder_path, files = _save_code_project(mock_project)
    files_list = "\n".join(f"  - {f}" for f in files)
    return (
        f"Projeto criado em: {folder_path}\n\n"
        f"Arquivos:\n{files_list}\n\n"
        f"{mock_project['summary']}"
    )



def _inject_files(prompt: str, files: list) -> str:
    """
    Lê os arquivos da lista e injeta o conteúdo no prompt como bloco de contexto.

    Arquivos ilegíveis geram um aviso inline em vez de abortar.
    O bloco é inserido antes do prompt original para que o modelo
    receba o contexto antes da instrução.
    """
    if not files:
        return prompt

    blocks = []
    for path_str in files:
        path = Path(path_str)
        if not path.exists():
            blocks.append(f"### {path_str}\n[arquivo não encontrado]")
            continue
        try:
            content = path.read_text(encoding="utf-8")
            blocks.append(f"### {path_str}\n```\n{content}\n```")
        except Exception as e:
            blocks.append(f"### {path_str}\n[erro ao ler: {e}]")

    if not blocks:
        return prompt

    context = "## Contexto — arquivos fornecidos\n\n" + "\n\n".join(blocks)
    return f"{context}\n\n---\n\n{prompt}"


def run(
    prompt: str,
    mode: str = "text",
    session_id: str = "_nosession",
    system: str = "",
    save_response: bool = False,
    skill: str = "",
    files: list = None,
) -> str:
    """
    prompt: descrição completa do problema para o modelo secundário
    mode: 'text' para respostas em markdown | 'code' para projeto com arquivos separados
    session_id: ID da sessão atual (controle de cota — injetado automaticamente)
    system: instrução de sistema opcional (sobrescreve o padrão do modo)
    save_response: se True, força salvar em arquivo mesmo que resposta seja curta (só no modo text)
    skill: nome da skill em skills/ a ser injetada no system prompt (ex: 'django-api')
    files: lista de caminhos de arquivos locais a injetar como contexto no prompt
    """
    cfg = _load_config()

    # ── injeta arquivos no prompt (antes de calcular cota) ────────────────────
    if files:
        prompt = _inject_files(prompt, files)

    # ── mock para testes de fluxo ─────────────────────────────────────────────
    if cfg.get("mock_secondary", False):
        mock_type = cfg.get("mock_type", "code")
        return _run_mock(mock_type, mode, skill, prompt)

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
    model    = cfg.get("model",    _DEFAULT_CONFIG["model"]) or _DEFAULT_CONFIG["model"]
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

    # Erros de servidor (5xx) e rate limit são transitórios — vale tentar de novo.
    # Erros de cliente (4xx) são definitivos — falha imediata.
    _RETRYABLE  = {502, 503, 504, 429}
    max_retries = cfg.get("max_retries", 2)
    stream_debug = cfg.get("stream_debug", False)
    content     = None

    # stream=True: o servidor envia tokens conforme gera — sem timeout de geração.
    # timeout=(N, None): N segundos para o handshake inicial, sem limite para leitura.
    payload["stream"] = True
    # stream_options: solicita usage no último chunk do stream (OpenAI-compatible)
    # Providers que não suportam ignoram silenciosamente o campo.
    payload["stream_options"] = {"include_usage": True}

    _usage      = {}
    with _Spinner(model, max_retries=max_retries) as spinner:
        for attempt in range(1, max_retries + 2):
            spinner.set_attempt(attempt)
            try:
                resp = requests.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type":  "application/json",
                    },
                    json=payload,
                    timeout=(timeout, None),  # connect_timeout, read_timeout=sem limite
                    stream=True,
                )
                resp.raise_for_status()

                # handshake ok — para o spinner e começa a exibir tokens
                spinner.done()
                content, _usage = _stream_response(resp, mode=mode, debug=stream_debug)
                break

            except requests.Timeout:
                if attempt > max_retries:
                    spinner.fail(f"timeout de conexão após {timeout}s")
                    return (
                        f"Erro: timeout de conexão após {timeout}s ({max_retries + 1} tentativas). "
                        f"O servidor não respondeu — tente novamente em alguns minutos."
                    )
                wait = 2 ** attempt
                spinner.set_status(f"timeout, aguardando {wait}s")
                time.sleep(wait)

            except requests.HTTPError:
                status = resp.status_code
                if status not in _RETRYABLE or attempt > max_retries:
                    spinner.fail(f"erro HTTP {status}")
                    return f"Erro HTTP {status}: {resp.text[:300]}"
                wait = 2 ** attempt
                spinner.set_status(f"erro {status}, aguardando {wait}s")
                time.sleep(wait)

            except Exception as e:
                spinner.fail(str(e)[:60])
                return f"Erro ao chamar modelo secundário: {e}"

        if content is None:
            spinner.fail("sem resposta após todas as tentativas")

    # imprime tokens depois do _Spinner fechar — evita conflito com o Live interno
    if _usage:
        _err.print(_format_token_usage(_usage, cfg))

    # ── atualiza cota ─────────────────────────────────────────────────────────
    if content is None:
        return "Erro: todas as tentativas falharam sem resposta do modelo secundário."
    _save_quota(session_id, used + prompt_chars)

    # ── mode: code ────────────────────────────────────────────────────────────
    if mode == "code":
        project = _extract_json(content)
        # fase build — imprime arquivos com syntax highlight ou aviso de JSON cortado
        _print_build_phase(project, content, cfg)
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