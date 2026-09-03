#!/usr/bin/env python
"""
ciel_tui.py — Interface gráfica de terminal (TUI) do Ciel.

Primeira versão da TUI integrada ao projeto, construída com Textual.
Equivalente funcional da CLI (cli.py), com layout visual persistente
e navegação inteiramente por teclado.

Layout
------
  Sidebar (esquerda)
    AgentCard      — nome e descrição do agente ativo
    Botões         — atalhos visuais para /tool, /task, /skill, /agente
    SessionList    — histórico de sessões recentes (DataTable com scroll)

  Chat (centro)
    RichLog        — histórico da conversa com suporte a markdown e Rich markup
    CmdSuggest     — autocomplete de comandos /
    CielInput      — campo de entrada principal

  InfoPanel (direita)
    Sessão         — id, modo safe
    Orquestrador   — modelo, tok↑↓, steps por turno
    Secundário     — modelo lido de ciel_config.json, tok↑↓ via token_tracker
    SysMonitor     — CPU, RAM e VRAM (requer psutil / pynvml)

Comandos suportados
-------------------
  /agente [nome]   troca de agente
  /task [nome]     executa task (abre modal se sem argumento)
  /skill [nome]    executa skill com modelo secundário
  /tool            lista tools ativas (modal)
  /source          indexa arquivos e URLs no knowledge base
  /history         gerencia sessões salvas (salvar, exportar, branch)
  /novo            nova sessão
  /tokens          uso de tokens da sessão
  /copiar          copia última resposta do agente
  /limpar          limpa o chat
  /limpar-temp     remove tools temporárias
  /promover        promove tool temp → permanente

Atalhos de teclado
------------------
  Ctrl+Q  sair          Ctrl+N  nova sessão     Ctrl+S  salvar
  Ctrl+L  limpar        Ctrl+B  toggle sidebar  Ctrl+Y  modal de cópia
  F1      tools         F2      tasks           F3      skills
  F4      agentes       /       foca input      Tab     cicla painéis

Dependências
------------
  textual, rich, prompt_toolkit
  agent_loop, tools_registry, agent_loader
  history_store, token_tracker
"""

from __future__ import annotations

from datetime import datetime
import json
import re

from rich.text import Text
from rich.markdown import Markdown as RichMarkdown
from rich.console import Group
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    OptionList,
    RichLog,
    Sparkline,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

# ── integração com o loop agêntico ───────────────────────────────────────────
from agent_loop import run_agent, AgentResult
from tools_registry import load_tools, tools_schema
from agent_loader import load_agent, filter_tools, filter_mcp_tools, list_agents
from history_store import HistoryStore, DB_PATH
from mcp.manager import MCPManager


# ─── helpers de task (espelhados de cli.py) ───────────────────────────────────

def load_task(path) -> dict | None:
    from pathlib import Path
    path = Path(path)
    if not path.exists():
        return None
    text  = path.read_text(encoding="utf-8")
    nome = objetivo = resultado = ""
    acoes: list[str] = []
    section = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## task:"):
            nome = s.split(":", 1)[1].strip()
        elif s.startswith("objetivo:"):
            objetivo = s.split(":", 1)[1].strip(); section = None
        elif s in ("ações:", "acoes:"):
            section = "acoes"
        elif s.startswith("resultado esperado:"):
            resultado = s.split(":", 1)[1].strip(); section = None
        elif section == "acoes" and s.startswith("-"):
            acoes.append(s[1:].strip())
    if not nome or not acoes:
        return None
    return {"nome": nome, "objetivo": objetivo, "acoes": acoes, "resultado": resultado}


def find_tasks(query: str, tasks_dir) -> list:
    from pathlib import Path
    tasks_dir = Path(tasks_dir)
    if not tasks_dir.exists():
        return []
    q = query.lower().replace(" ", "-")
    matches = [p for p in tasks_dir.glob("*.md") if q in p.stem.lower()]
    matches.sort(key=lambda p: (0 if p.stem.lower() == q else 1, p.stem))
    return matches


def build_task_prompt(task: dict) -> str:
    acoes_fmt = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(task["acoes"]))
    return (
        f"Execute a seguinte task: {task['nome']}\n\n"
        f"Objetivo: {task['objetivo']}\n\n"
        f"Ações a executar em ordem:\n{acoes_fmt}\n\n"
        f"Resultado esperado: {task['resultado']}\n\n"
        f"Siga as ações na ordem indicada. Se uma ação especificar [tool: nome], "
        f"use essa tool. Caso contrário, escolha a tool mais adequada disponível."
    )


MAX_STEPS_TASK = 9  # +3 vs padrão, igual à CLI


# monitor de sistema — opcionais
try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    import pynvml as _pynvml
    _pynvml.nvmlInit()
    _HAS_NVML = True
except Exception:
    _HAS_NVML = False

# ─── Paleta ───────────────────────────────────────────────────────────────────

P = {
    "bg":      "#0f111a",
    "surface": "#13151f",
    "panel":   "#181b27",
    "border":  "#1e2235",
    "dim":     "#252840",
    "muted":   "#4a4f6a",
    "silver":  "#7a85a8",
    "text":    "#c5cfe8",
    "accent":  "#4c8bf5",
    "accent2": "#2d6be4",
    "gold":    "#e8c84a",
    "green":   "#4ec994",
    "crimson": "#e05270",
    "orange":  "#e8943a",
    "cyan":    "#38d4e0",
    "hi":      "#1e2a4a",   # highlight seleção
}

ASCII_LOGO = """\
  ╭──────────────╮
  │  ◈  c i e l  │
  ╰──────────────╯"""

# ─── Helpers de mensagem ─────────────────────────────────────────────────────

_WEEKDAY_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

def ts() -> str:
    now = datetime.now()
    day = _WEEKDAY_PT[now.weekday()]
    return f"{day} {now.strftime('%H:%M')}"

def msg_user(text: str) -> Text:
    t = Text()
    t.append("  você", style=f"bold {P['gold']}")
    t.append(f"  {text}", style=P["text"])
    return t

_PILL_PREVIEW_LINES = 3   # quantas linhas do pill exibir antes de truncar

def msg_user_pill(pill_content: str, prompt: str) -> Text:
    """Exibe mensagem com pill truncado + prompt do usuário."""
    lines = pill_content.splitlines()
    n_total = len(lines)
    indent = "      "   # alinha com o texto após "você  "

    t = Text()
    t.append("  você", style=f"bold {P['gold']}")
    t.append(f"  ", style="")

    # badge do pill
    t.append(f"[Colado ~{n_total} linhas]", style=f"bold {P['gold']}")
    t.append("\n", style="")

    # preview das primeiras N linhas
    preview = lines[:_PILL_PREVIEW_LINES]
    for line in preview:
        t.append(indent, style="")
        t.append(line, style=f"dim {P['silver']}")
        t.append("\n", style="")

    # rodapé: +N linhas · prompt
    hidden = n_total - _PILL_PREVIEW_LINES
    if hidden > 0:
        t.append(indent, style="")
        t.append(f"+{hidden} linhas", style=f"dim {P['muted']}")
        if prompt:
            t.append(f"  \u00b7  ", style=f"dim {P['border']}")
            t.append(prompt, style=P["text"])
    elif prompt:
        t.append(indent, style="")
        t.append(prompt, style=P["text"])

    return t

def msg_agent(agent: str, text: str, tok_in: int = 0, tok_out: int = 0) -> Group:
    header = Text()
    header.append(f"  {agent}", style=f"bold {P['accent']}")
    if tok_in or tok_out:
        header.append(f"  ↑{tok_in:,} ↓{tok_out:,}", style=f"dim {P['muted']}")
    body = RichMarkdown(text)
    return Group(header, body)

def msg_tool(tool: str, result: str, step: int = 0) -> Text:
    t = Text()
    prefix = f"step {step}" if step else "    "
    t.append(f"  {prefix}  ", style=f"dim {P['muted']}")
    t.append(tool, style=f"bold {P['cyan']}")
    indent = " " * (2 + len(prefix) + 2)
    t.append(f"\n{indent}", style="")
    t.append("└─ ", style=f"dim {P['muted']}")
    t.append(result[:100], style=f"dim {P['silver']}")
    return t

def msg_system(text: str, kind: str = "info") -> Text:
    clr  = {"info": P["silver"], "ok": P["green"], "warn": P["orange"], "err": P["crimson"]}
    icon = {"info": "─", "ok": "✓", "warn": "!", "err": "✗"}
    t = Text()
    t.append(f"  {icon[kind]} ", style=f"bold {clr[kind]}")
    t.append(text, style=clr[kind])
    return t

def msg_sep() -> Text:
    return Text("  " + "─" * 72, style=f"dim {P['dim']}")

# ─── Fake data ────────────────────────────────────────────────────────────────

FAKE_AGENTS = [
    ("general",    "Agente de propósito geral"),
    ("dev_helper", "Auxílio em desenvolvimento"),
    ("researcher", "Pesquisa e síntese de fontes"),
    ("enem_tutor", "Preparação ENEM e vestibular"),
    ("rpg_master", "Mestre de RPG narrativo"),
]
FAKE_TASKS = [
    ("noticias",     "Coleta e resume notícias do dia"),
    ("backup_docs",  "Cópia de segurança de documentos"),
    ("analise_csv",  "Análise estatística de CSV"),
    ("resumo_pdf",   "Resumo de arquivo PDF"),
]
FAKE_SKILLS = [
    ("revisao_texto",  "Revisão gramatical e estilística"),
    ("gerador_teste",  "Gera testes unitários"),
    ("tradutor",       "Tradução pt/en/es"),
]


# ─── Modal de seleção interativo ─────────────────────────────────────────────

# ─── Autocomplete de comandos ─────────────────────────────────────────────────

COMMANDS: list[tuple[str, str]] = [
    ("/tool",              "lista/inspeciona ferramentas  [F1]"),
    ("/task",              "escolhe e executa task        [F2]"),
    ("/task <nome>",       "executa task diretamente"),
    ("/skill",             "ativa skill disponível        [F3]"),
    ("/agente",            "troca persona interativo      [F4]"),
    ("/agente <nome>",     "troca persona diretamente"),
    ("/model <nome>",      "troca modelo Ollama"),
    ("/model2 <nome>",     "define modelo secundário"),
    ("/novo",              "nova sessão"),
    ("/limpar",            "limpa display"),
    ("/history",           "lista sessões salvas"),
    ("/history salvar",    "salva sessão atual"),
    ("/history exportar",  "exporta como .md"),
    ("/history <agente>",  "filtra sessões por agente"),
    ("/source <arquivo>",  "indexa na base de conhecimento"),
    ("/source --listar",   "lista fontes"),
    ("/source --global",   "fonte compartilhada"),
    ("/source --remover",  "remove fonte por id"),
    ("/source --limpar-orfas", "remove fontes órfãs"),
    ("/tokens",            "uso de tokens desta sessão"),
    ("/copiar",            "copia última resposta"),
    ("/safe",              "toggle modo seguro"),
    ("/limpar-temp",       "remove tools temporárias"),
    ("/promover <nome>",   "promove tool temp a permanente"),
    ("/mcp",               "lista servidores MCP e status"),
    ("/mcp -v",            "lista MCP com tools de cada servidor"),
    ("/ajuda",             "lista todos os comandos"),
    ("/sair",              "encerra"),
]


# ─── Input customizado — intercepta paste multilinha ─────────────────────────

_PASTE_THRESHOLD = 4   # linhas mínimas para ativar o colapso

class CielInput(Input):
    """
    Subclasse de Input que substitui _on_paste para capturar texto
    colado com múltiplas linhas antes que o Input nativo o trunce.
    Texto curto (< _PASTE_THRESHOLD linhas) segue o comportamento padrão.
    """

    def on_paste(self, event: events.Paste) -> None:
        text = event.text or ""
        lines = text.splitlines()
        event.prevent_default()  # impede o Input nativo de inserir o texto também
        if len(lines) >= _PASTE_THRESHOLD:
            # redireciona para o app tratar como PastePill
            event.stop()
            self.app._handle_long_paste(text)
        else:
            # insere manualmente no cursor (comportamento equivalente ao padrão)
            self.insert_text_at_cursor(text.splitlines()[0] if lines else text)


class CmdSuggest(Static):
    """Autocomplete flutuante — aparece acima do input quando texto comeca com /."""

    PAGE = 8  # itens visiveis por vez

    def __init__(self, **kw):
        super().__init__("", **kw)
        self._items: list[tuple[str, str]] = []
        self._cursor: int = 0
        self._offset: int = 0  # primeiro item visivel

    def refresh_suggestions(self, query: str) -> None:
        q = query.lower()
        self._items = [(c, d) for c, d in COMMANDS if c.startswith(q)]
        self._cursor = 0
        self._offset = 0
        self._redraw()
        self.display = bool(self._items)

    def hide(self) -> None:
        self._items = []
        self.display = False

    def move(self, delta: int) -> None:
        if not self._items:
            return
        self._cursor = (self._cursor + delta) % len(self._items)
        # ajusta janela para manter cursor visivel
        if self._cursor < self._offset:
            self._offset = self._cursor
        elif self._cursor >= self._offset + self.PAGE:
            self._offset = self._cursor - self.PAGE + 1
        self._redraw()

    def current_cmd(self) -> str | None:
        if not self._items:
            return None
        return self._items[self._cursor][0]

    def _redraw(self) -> None:
        t = Text()
        total   = len(self._items)
        visible = self._items[self._offset : self._offset + self.PAGE]
        for rel, (cmd, desc) in enumerate(visible):
            i = self._offset + rel
            if i == self._cursor:
                t.append(f" {cmd:<22}", style=f"bold reverse {P['accent']}")
                t.append(f" {desc} \n", style=f"reverse {P['silver']}")
            else:
                t.append(f" {cmd:<22}", style=f"bold {P['gold']}")
                t.append(f" {desc}\n",  style=f"dim {P['silver']}")
        # indicador de scroll
        if total > self.PAGE:
            showing = f"{self._offset + 1}-{min(self._offset + self.PAGE, total)}/{total}"
            t.append(f" {'':22} {showing:>10}\n", style=f"dim {P['muted']}")
        self.update(t)


# ─── Detecção de URL ──────────────────────────────────────────────────────────

_URL_RE = re.compile(
    r'https?://[^\s]+'          # http(s)://...
    r'|www\.[^\s]+'             # www....
    r'|[^\s]+\.(com|org|net|io|dev|br|ai|app|md|pdf|txt)/[^\s]*',  # domain/path
    re.IGNORECASE,
)

def _extract_urls(text: str) -> tuple[list[str], str]:
    """Retorna (lista de URLs encontradas, texto sem as URLs)."""
    urls = _URL_RE.findall(text) if isinstance(_URL_RE.findall(text), list) else []
    # findall retorna strings quando não há grupos — garantir lista de str
    urls = [m if isinstance(m, str) else m[0] for m in _URL_RE.finditer(text)]
    urls = [m.group() for m in _URL_RE.finditer(text)]
    remainder = _URL_RE.sub("", text).strip()
    return urls, remainder


# ─── Link Chip — tag visual para URLs no input ───────────────────────────────

class LinkChip(Static):
    """
    Chip compacto exibido antes do Input quando uma URL é detectada.
    Clicável para remover. Cada instância representa uma URL.
    """

    DEFAULT_CSS = f"""
    LinkChip {{
        height: 1;
        width: auto;
        background: {P['hi']};
        color: {P['cyan']};
        padding: 0 1;
        margin: 0 1 0 0;
    }}
    LinkChip:hover {{
        background: {P['dim']};
        color: {P['crimson']};
    }}
    """

    def __init__(self, url: str, **kw) -> None:
        super().__init__(**kw)
        self.url = url
        # exibe só o domínio + "×" para não tomar espaço
        try:
            domain = url.split("//")[-1].split("/")[0]
        except Exception:
            domain = url[:24]
        self._label = f"⬡ {domain}  ×"

    def render(self) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(self._label, style=f"bold {P['cyan']}")
        return t

    def on_click(self) -> None:
        """Remove o chip e devolve a URL para o input."""
        self.app._remove_link_chip(self)


# ─── Paste Pill — recolhe textos longos colados ──────────────────────────────

class PastePill(Static):
    """
    Pill que substitui texto longo colado no input.
    Exibe '[Colado ~N linhas]'; clique para expandir de volta.
    """

    DEFAULT_CSS = f"""
    PastePill {{
        height: 1;
        width: auto;
        background: {P['dim']};
        color: {P['gold']};
        padding: 0 1;
        margin: 0 1 0 0;
    }}
    PastePill:hover {{
        background: {P['hi']};
        color: {P['orange']};
    }}
    """

    def __init__(self, content: str, **kw) -> None:
        super().__init__(**kw)
        self._content = content
        n = len(content.splitlines())
        self._label = f"[Colado ~{n} linhas]  ×"

    @property
    def content(self) -> str:
        return self._content

    def render(self) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(self._label, style=f"bold {P['gold']}")
        return t

    def on_click(self) -> None:
        """Abre modal de edição do conteúdo colado."""
        self.app._open_paste_editor(self)


# ─── Modal de edição do conteúdo colado ──────────────────────────────────────

class PasteEditModal(ModalScreen):
    """
    Modal com TextArea para visualizar e editar o conteúdo colado
    antes de confirmar. Confirmar atualiza o pill; Esc cancela.
    """

    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("ctrl+g", "confirm", show=False, description="confirmar"),
        Binding("ctrl+d", "delete",  show=False, description="deletar"),
    ]

    CSS = f"""
    PasteEditModal {{
        align: center middle;
    }}
    #paste-modal-box {{
        width: 80%;
        max-width: 100;
        height: 60%;
        max-height: 40;
        background: {P['panel']};
        border: solid {P['gold']};
        layout: vertical;
        padding: 0;
    }}
    #paste-modal-header {{
        height: 2;
        background: {P['surface']};
        border-bottom: solid {P['border']};
        color: {P['gold']};
        text-style: bold;
        content-align: left middle;
        padding: 0 2;
    }}
    #paste-modal-area {{
        height: 1fr;
        background: {P['bg']};
        border: none;
        padding: 1 2;
    }}
    #paste-modal-footer {{
        height: 3;
        background: {P['surface']};
        border-top: solid {P['border']};
        layout: horizontal;
        align: right middle;
        padding: 0 2;
    }}
    #paste-btn-confirm {{
        background: {P['accent']};
        color: {P['bg']};
        border: none;
        margin: 0 1;
        min-width: 14;
    }}
    #paste-btn-confirm:hover {{
        background: {P['cyan']};
    }}
    #paste-btn-cancel {{
        background: {P['dim']};
        color: {P['silver']};
        border: none;
        margin: 0 1;
        min-width: 10;
    }}
    #paste-btn-cancel:hover {{
        background: {P['muted']};
        color: {P['text']};
    }}
    #paste-btn-delete {{
        background: {P['surface']};
        color: {P['crimson']};
        border: none;
        margin: 0 1;
        min-width: 10;
    }}
    #paste-btn-delete:hover {{
        background: {P['crimson']};
        color: {P['bg']};
    }}
    """

    def __init__(self, content: str, **kw) -> None:
        super().__init__(**kw)
        self._original = content

    def compose(self) -> ComposeResult:
        n = len(self._original.splitlines())
        with Vertical(id="paste-modal-box"):
            yield Static(
                f"  ✎  conteúdo colado  ·  {n} linhas  ·  edite e confirme",
                id="paste-modal-header",
            )
            yield TextArea(self._original, id="paste-modal-area", soft_wrap=False)
            with Horizontal(id="paste-modal-footer"):
                yield Button("Ctrl+G  confirmar", id="paste-btn-confirm", variant="primary")
                yield Button("Esc  cancelar", id="paste-btn-cancel")
                yield Button("Ctrl+D  deletar", id="paste-btn-delete")

    def on_mount(self) -> None:
        self.query_one("#paste-modal-area", TextArea).focus()

    def on_key(self, event: events.Key) -> None:
        if event.key == "ctrl+g":
            event.stop()
            self.action_confirm()
        elif event.key == "ctrl+d":
            event.stop()
            self.dismiss(("delete", ""))
        elif event.key in ("ctrl+up", "ctrl+down"):
            event.stop()
            area = self.query_one("#paste-modal-area", TextArea)
            row, col = area.cursor_location
            if event.key == "ctrl+up":
                area.cursor_location = (max(0, row - 1), col)
            else:
                last = len(area.text.splitlines()) - 1
                area.cursor_location = (min(last, row + 1), col)

    def action_confirm(self) -> None:
        text = self.query_one("#paste-modal-area", TextArea).text
        self.dismiss(("keep", text))

    def action_delete(self) -> None:
        self.dismiss(("delete", ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "paste-btn-confirm":
            text = self.query_one("#paste-modal-area", TextArea).text
            self.dismiss(("keep", text))
        elif event.button.id == "paste-btn-delete":
            self.dismiss(("delete", ""))
        else:
            self.dismiss(None)


class CopyModal(ModalScreen):
    """Modal de visualização do chat para seleção e cópia de texto."""

    BINDINGS = [
        Binding("ctrl+y", "dismiss", show=False),
        Binding("escape", "dismiss", show=False),
    ]

    CSS = f"""
    CopyModal {{
        background: {P['bg']};
    }}
    #copy-modal-box {{
        width: 100%;
        height: 100%;
        background: {P['bg']};
        layout: vertical;
    }}
    #copy-modal-header {{
        height: 2;
        background: {P['surface']};
        border-bottom: solid {P['gold']};
        color: {P['gold']};
        text-style: bold;
        content-align: center middle;
    }}
    #copy-modal-log {{
        width: 100%;
        height: 1fr;
        background: {P['bg']};
        padding: 1 3;
    }}
    #copy-modal-footer {{
        height: 2;
        background: {P['surface']};
        border-top: solid {P['border']};
        color: {P['muted']};
        content-align: center middle;
    }}
    """

    def __init__(self, lines: list, **kw):
        super().__init__(**kw)
        self._lines = lines

    def compose(self) -> ComposeResult:
        with Vertical(id="copy-modal-box"):
            yield Static(
                "✂  MODO SELEÇÃO — Shift+arrastar para copiar",
                id="copy-modal-header"
            )
            yield RichLog(id="copy-modal-log", highlight=False,
                         markup=False, wrap=True)
            yield Static(
                "Ctrl+Y ou Esc para voltar",
                id="copy-modal-footer"
            )

    def on_mount(self) -> None:
        log = self.query_one("#copy-modal-log", RichLog)
        for line in self._lines:
            log.write(line)


class SelectionModal(ModalScreen):
    """
    Overlay de seleção com ↑↓ Enter — usa OptionList nativo do Textual.
    Usado por /agente, /task, /skill sem argumentos.
    """

    CSS = f"""
    SelectionModal {{
        align: center middle;
    }}
    #modal-box {{
        width: 62;
        height: auto;
        max-height: 26;
        background: {P['panel']};
        border: solid {P['accent']};
        padding: 1 2;
    }}
    #modal-title {{
        height: 2;
        color: {P['accent']};
        text-style: bold;
        content-align: left middle;
        border-bottom: solid {P['border']};
        margin-bottom: 1;
    }}
    #modal-list {{
        height: auto;
        max-height: 16;
        background: {P['panel']};
        border: none;
        padding: 0;
    }}
    #modal-list > .option-list--option {{
        color: {P['silver']};
        padding: 0 1;
    }}
    #modal-list > .option-list--option-highlighted {{
        background: {P['hi']};
        color: {P['accent']};
    }}
    #modal-list > .option-list--option:hover {{
        background: {P['dim']};
        color: {P['text']};
    }}
    #modal-hint {{
        height: 1;
        color: {P['muted']};
        content-align: center middle;
        margin-top: 1;
        border-top: solid {P['border']};
    }}
    """

    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("q",      "dismiss", show=False),
    ]

    def __init__(self, title: str, items: list[tuple[str, str]], **kw):
        super().__init__(**kw)
        self._title = title
        self._items = items   # [(key, description), ...]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Label(self._title, id="modal-title")
            options = [
                Option(f"{key:<22} {desc}", id=key)
                for key, desc in self._items
            ]
            yield OptionList(*options, id="modal-list")
            yield Label("↑↓ navegar   Enter selecionar   Esc cancelar", id="modal-hint")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class SessionModal(ModalScreen):
    """Modal ao clicar numa sessão — preview + opções."""

    CSS = f"""
    SessionModal {{
        align: center middle;
    }}
    #sess-modal-box {{
        width: 68;
        height: auto;
        max-height: 36;
        background: {P['panel']};
        border: solid {P['accent']};
        padding: 1 2;
    }}
    #sess-modal-title {{
        height: 2;
        color: {P['accent']};
        text-style: bold;
        content-align: left middle;
        border-bottom: solid {P['border']};
        margin-bottom: 1;
    }}
    #sess-preview {{
        height: auto;
        max-height: 14;
        background: {P['surface']};
        border: solid {P['border']};
        padding: 1 2;
        margin-bottom: 1;
        color: {P['silver']};
    }}
    #sess-options {{
        height: auto;
        background: {P['panel']};
        border: none;
        padding: 0;
        margin-top: 1;
    }}
    #sess-options > .option-list--option {{
        color: {P['silver']};
        padding: 0 1;
    }}
    #sess-options > .option-list--option-highlighted {{
        background: {P['hi']};
        color: {P['accent']};
    }}
    #sess-options > .option-list--option:hover {{
        background: {P['dim']};
        color: {P['text']};
    }}
    #sess-modal-hint {{
        height: 1;
        color: {P['muted']};
        content-align: center middle;
        margin-top: 1;
        border-top: solid {P['border']};
    }}
    """

    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("q",      "dismiss", show=False),
    ]

    # Ações disponíveis: (id, label)
    _ACTIONS = [
        ("view",       "visualizar   carregar conversa no chat"),
        ("branch",     "branch       fork a partir desta sessão"),
        ("export",     "exportar     salvar como .md"),
        ("delete",     "deletar      remover sessão"),
        ("delete_back","deletar e voltar  remove e abre sessão anterior"),
    ]

    def __init__(self, sess_id: str, title: str, agent: str, date: str, **kw):
        super().__init__(**kw)
        self._sess_id = sess_id
        self._title   = title
        self._agent   = agent
        self._date    = date

    def compose(self) -> ComposeResult:
        with Vertical(id="sess-modal-box"):
            yield Label(
                f"sessão {self._sess_id}  ·  {self._agent}  ·  {self._date}",
                id="sess-modal-title"
            )
            # preview real: primeiras linhas do summary ou dos turns
            preview = Text()
            try:
                store = self.app._store
                sess  = store.get_session(int(self._sess_id))
                if sess and sess.get("summary"):
                    for line in sess["summary"].splitlines()[:6]:
                        preview.append(f"  {line}\n", style=f"dim {P['silver']}")
                else:
                    turns = store.get_turns(int(self._sess_id))
                    shown = 0
                    for turn in turns[:8]:
                        label = "você" if turn["role"] == "user" else self._agent
                        clr   = P["gold"] if turn["role"] == "user" else P["accent"]
                        preview.append(f"  {label}  ", style=f"bold {clr}")
                        snippet = (turn["content"] or "")[:60].replace("\n", " ")
                        preview.append(f"{snippet}\n", style=f"dim {P['silver']}")
                        shown += 1
                        if shown >= 4:
                            break
            except Exception:
                preview.append("  (sem preview disponível)\n", style=f"dim {P['muted']}")
            yield Static(preview, id="sess-preview")
            options = [
                Option(f"{label}", id=oid)
                for oid, label in self._ACTIONS
            ]
            yield OptionList(*options, id="sess-options")
            yield Label("↑↓ navegar   Enter executar   Esc cancelar", id="sess-modal-hint")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss((self._sess_id, event.option.id))


# ─── Widgets da sidebar ───────────────────────────────────────────────────────

# Ícones por tipo de agente — fallback para ◈
_AGENT_ICON: dict[str, str] = {
    "general":    "◈",
    "dev_helper": "⟨/⟩",
    "researcher": "⊕",
    "enem_tutor": "✦",
    "rpg_master": "⚔",
}

class AgentCard(Static):
    """Card do agente ativo: ícone, nome em destaque e descrição curta."""

    def __init__(self, agent: str, desc: str, **kw):
        super().__init__(**kw)
        self._agent = agent
        self._desc  = desc

    def render(self) -> Text:
        #icon  = _AGENT_ICON.get(self._agent, "◈")
        icon = ""
        t = Text(overflow="ellipsis", no_wrap=False)
        # linha de rótulo da seção
        t.append("  AGENTE\n", style=f"bold {P['muted']}")
        # ícone + nome
        t.append(f" {icon} ", style=f"bold {P['accent']}")
        t.append(f"{self._agent}\n", style=f"bold {P['text']}")
        # descrição quebrada em até 2 linhas de ~20 chars
        words = self._desc.split()
        lines, cur = [], ""
        for w in words:
            if len(cur) + len(w) + 1 > 18:
                lines.append(cur.strip())
                cur = w
            else:
                cur += (" " if cur else "") + w
        if cur:
            lines.append(cur.strip())
        for ln in lines[:2]:
            t.append(f"  {ln}\n", style=f"dim {P['muted']}")
        return t

    def update(self, agent: str, desc: str = "") -> None:
        self._agent = agent
        self._desc  = desc
        self.refresh()


class CmdButton(Static):
    """Botão de comando na sidebar — exibe /cmd e descrição."""

    DEFAULT_CSS = f"""
    CmdButton {{
        height: 1;
        padding: 0 2;
        color: {P['silver']};
    }}
    CmdButton:hover {{
        background: {P['dim']};
        color: {P['text']};
    }}
    CmdButton.active {{
        color: {P['accent']};
        text-style: bold;
    }}
    """

    def __init__(self, cmd: str, hint: str, shortcut: str = "", **kw):
        super().__init__(**kw)
        self._cmd  = cmd
        self._hint = hint

    def on_click(self) -> None:
        getattr(self.app, f"action_cmd_{self._cmd}")()

    def render(self) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(f"/{self._cmd:<8}", style=f"bold {P['accent']}")
        t.append(self._hint, style=f"dim {P['muted']}")
        return t


class SessionList(Widget):
    """Lista de sessões recentes com DataTable — dados reais do HistoryStore."""

    def compose(self) -> ComposeResult:
        yield Static("SESSÕES", id="sessions-hdr")
        yield DataTable(id="sessions-table", cursor_type="row", show_header=False)

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        tbl = self.query_one("#sessions-table", DataTable)
        tbl.clear()
        if not tbl.columns:
            tbl.add_columns("entry")
        try:
            store = self.app._store
            if store is None:
                return
            sessions = store.list_sessions()
            current  = str(self.app._session_id) if self.app._session_id else None
            _DAYS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
            for row in sessions[:20]:
                sid   = str(row["id"])
                title = (row["title"] or "(sem título)")
                icon  = "◉" if sid == current else "○"
                branch = "↪ " if row["parent_session_id"] else ""
                # remove prefixo "[branch] " que o history_store adiciona
                clean_title = title.removeprefix("[branch] ") if branch else title
                raw_date = (row["updated_at"] or "")
                try:
                    from datetime import datetime as _dt
                    d = _dt.fromisoformat(raw_date[:19])
                    date_str = f"{_DAYS_PT[d.weekday()]} {d.day:02d}/{d.month:02d}"
                except Exception:
                    date_str = raw_date[:10]
                TITLE_W = 20
                avail   = TITLE_W - len(branch)
                short   = clean_title[:avail] + "…" if len(clean_title) > avail else clean_title
                entry   = f"{icon} {branch}{short}"
                tbl.add_row(entry, key=sid)
        except Exception:
            pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        sid_str = str(event.row_key.value)
        try:
            store = self.app._store
            sess  = store.get_session(int(sid_str))
            if not sess:
                return
            title  = sess["title"] or f"sessão #{sid_str}"
            agent  = sess["agent_id"] or ""
            date   = (sess["updated_at"] or "")[:16]
            self.app.push_screen(
                SessionModal(sid_str, title, agent, date),
                callback=self._on_session_action,
            )
        except Exception:
            pass

    def _on_session_action(self, result) -> None:
        if result is None:
            return
        sess_id_str, action = result
        self.app._handle_session_action(int(sess_id_str), action, self)


class Sidebar(Widget):
    """Sidebar esquerda completa."""

    def compose(self) -> ComposeResult:
        yield AgentCard("general", "Agente de propósito geral", id="logo-card")
        yield Static("RECURSOS", id="sidebar-cmds-hdr")
        yield CmdButton("tool",   "", id="btn-tool")
        yield CmdButton("task",   "", id="btn-task")
        yield CmdButton("skill",  "", id="btn-skill")
        yield CmdButton("agente", "", id="btn-agente")
        yield SessionList(id="session-list")


# ─── Monitor de sistema ──────────────────────────────────────────────────────

class SysMonitor(Widget):
    """Monitora CPU (Sparkline) e RAM (barra de progresso). Atualiza a cada 2s."""

    _HIST  = 20   # pontos no sparkline
    _WIDTH = 16   # largura da barra de RAM em chars

    def __init__(self, **kw):
        super().__init__(**kw)
        self._cpu_hist:  list[float] = [0.0] * self._HIST

    def compose(self) -> ComposeResult:
        yield Static("", id="sys-cpu-label")
        yield Sparkline(self._cpu_hist, id="sys-cpu-spark")
        yield Static("", id="sys-ram-label")
        yield Static("", id="sys-ram-bar")
        if _HAS_NVML:
            yield Static("", id="sys-vram-label")
            yield Static("", id="sys-vram-bar")

    def on_mount(self) -> None:
        self._poll()
        self.set_interval(2.0, self._poll)

    def _make_bar(self, pct: float, clr: str) -> Text:
        fill  = round(pct / 100 * self._WIDTH)
        empty = self._WIDTH - fill
        t = Text()
        t.append("  ", style="")
        t.append("█" * fill,  style=f"bold {clr}")
        t.append("░" * empty, style=f"dim {clr}")
        return t

    def _poll(self) -> None:
        if not _HAS_PSUTIL:
            return
        # CPU — sparkline
        cpu = _psutil.cpu_percent(interval=None)
        self._cpu_hist = self._cpu_hist[1:] + [cpu]
        self.query_one("#sys-cpu-spark", Sparkline).data = self._cpu_hist
        cpu_clr = P["crimson"] if cpu >= 90 else P["orange"] if cpu >= 70 else P["green"]
        t = Text()
        t.append("  CPU  ", style=f"dim {P['silver']}")
        t.append(f"{cpu:5.1f}%", style=f"bold {cpu_clr}")
        self.query_one("#sys-cpu-label", Static).update(t)
        # RAM — label + barra
        mem     = _psutil.virtual_memory()
        used_gb = mem.used  / 1024**3
        tot_gb  = mem.total / 1024**3
        ram_clr = P["crimson"] if mem.percent >= 90 else P["orange"] if mem.percent >= 70 else P["cyan"]
        t = Text()
        t.append("  RAM  ", style=f"dim {P['silver']}")
        t.append(f"{mem.percent:5.1f}%  ", style=f"bold {ram_clr}")
        t.append(f"{used_gb:.1f}/{tot_gb:.0f}GB", style=f"dim {P['silver']}")
        self.query_one("#sys-ram-label", Static).update(t)
        self.query_one("#sys-ram-bar",   Static).update(self._make_bar(mem.percent, ram_clr))
        # VRAM (NVIDIA) — label + barra
        if _HAS_NVML:
            try:
                h    = _pynvml.nvmlDeviceGetHandleByIndex(0)
                info = _pynvml.nvmlDeviceGetMemoryInfo(h)
                used  = info.used  / 1024**3
                total = info.total / 1024**3
                pct   = used / total * 100
                vram_clr = P["crimson"] if pct >= 90 else P["orange"] if pct >= 70 else P["gold"]
                t = Text()
                t.append("  VRAM ", style=f"dim {P['silver']}")
                t.append(f"{pct:5.1f}%  ", style=f"bold {vram_clr}")
                t.append(f"{used:.1f}/{total:.0f}GB", style=f"dim {P['silver']}")
                self.query_one("#sys-vram-label", Static).update(t)
                self.query_one("#sys-vram-bar",   Static).update(self._make_bar(pct, vram_clr))
            except Exception:
                pass


# ─── Painel direito — informações de sessão e atalhos ────────────────────────

class InfoPanel(Widget):
    """Painel direito: sessão, orquestrador e modelo secundário."""

    _QUOTA_LIMIT = 100_000  # tokens — virá do config
    _QUOTA_SESS  = 4_820    # fictício por enquanto
    _QUOTA_TOTAL = 38_450   # fictício por enquanto

    def __init__(self, agent: str, model: str, **kw):
        super().__init__(**kw)
        self._agent      = agent
        self._model      = model          # orquestrador
        self._model2     = "gpt-4o-mini"  # secundário — virá do config
        self._sess_no    = "nova"
        self._safe       = False
        # orquestrador
        self._tok_in     = 0
        self._tok_out    = 0
        self._last_steps = 0
        self._max_steps  = 6
        self._cost_usd: float | None = None
        # secundário
        self._tok2_in    = 0
        self._tok2_out   = 0
        self._cost2_usd: float | None = None

    def compose(self) -> ComposeResult:
        yield Label("  SESSÃO",        id="info-sess-title")
        yield Static("",               id="info-sess-body")
        yield Static("",               id="info-orch-title")
        yield Static("",               id="info-orch-body")
        yield Static("",               id="info-mod2-title")
        yield Static("",               id="info-mod2-body")
        if _HAS_PSUTIL:
            yield Static("  SISTEMA", id="info-sys-title")
            yield SysMonitor(id="sys-monitor")

    def on_mount(self) -> None:
        self._refresh()

    def update_state(self, agent: str = "", model: str = "", model2: str = "",
                     sess_no: str = "", tok_in: int = 0, tok_out: int = 0,
                     steps: int = 0, max_steps: int = 0,
                     cost_usd: float | None = None,
                     tok2_in: int = 0, tok2_out: int = 0,
                     cost2_usd: float | None = None,
                     safe: bool | None = None) -> None:
        if agent:            self._agent   = agent
        if model:            self._model   = model
        if model2:           self._model2  = model2
        if sess_no:          self._sess_no = sess_no
        if safe is not None: self._safe    = safe
        if tok_in or tok_out:
            self._tok_in  += tok_in
            self._tok_out += tok_out
        if tok2_in or tok2_out:
            self._tok2_in  += tok2_in
            self._tok2_out += tok2_out
        if steps:     self._last_steps = steps
        if max_steps: self._max_steps  = max_steps
        if cost_usd is not None:
            self._cost_usd = (self._cost_usd or 0) + cost_usd
        if cost2_usd is not None:
            self._cost2_usd = (self._cost2_usd or 0) + cost2_usd
        self._refresh()

    def _progress_bar(self, used: int, limit: int, width: int = 14) -> tuple[str, str]:
        pct  = min(used / max(limit, 1), 1.0)
        fill = round(pct * width)
        bar  = "█" * fill + "░" * (width - fill)
        if pct >= 0.90:   clr = P["crimson"]
        elif pct >= 0.70: clr = P["orange"]
        elif pct >= 0.40: clr = P["gold"]
        else:             clr = P["green"]
        return bar, clr

    def _cost_str(self, cost: float | None) -> tuple[str, str]:
        if cost is None:
            return "— em breve", f"dim {P['muted']}"
        clr = P["green"] if cost < 0.01 else P["orange"]
        return f"~${cost:.4f}", clr

    def _refresh(self) -> None:
        # ── SESSÃO ────────────────────────────────────────────────────────
        safe_str = "ativo" if self._safe else "off"
        safe_clr = P["orange"] if self._safe else f"dim {P['muted']}"
        w = self.query_one("#info-sess-body", Static)
        t = Text()
        t.append(f"  {'id':<8}", style=f"dim {P['silver']}")
        t.append(f" #{self._sess_no}\n", style=P["text"])
        t.append(f"  {'safe':<8}", style=f"dim {P['silver']}")
        t.append(f" {safe_str}\n", style=safe_clr)
        w.update(t)

        # ── ORQUESTRADOR ──────────────────────────────────────────────────
        orch_title = self.query_one("#info-orch-title", Static)
        orch_title.update(f"  {self._model}")

        total1 = self._tok_in + self._tok_out
        steps_str = f"{self._last_steps}/{self._max_steps}" if self._last_steps else "—"
        steps_clr = P["orange"] if self._last_steps >= self._max_steps else f"dim {P['muted']}"
        cost_s, cost_c = self._cost_str(self._cost_usd)

        w = self.query_one("#info-orch-body", Static)
        t = Text()
        t.append(f"  {'tok ↑':<8}", style=f"dim {P['silver']}")
        t.append(f" {self._tok_in:,}\n", style=P["text"])
        t.append(f"  {'tok ↓':<8}", style=f"dim {P['silver']}")
        t.append(f" {self._tok_out:,}\n", style=P["text"])
        t.append(f"  {'total':<8}", style=f"dim {P['silver']}")
        t.append(f" {total1:,}\n", style=f"bold {P['accent']}")
        t.append(f"  {'steps':<8}", style=f"dim {P['silver']}")
        t.append(f" {steps_str}\n", style=steps_clr)
        t.append(f"  {'custo':<8}", style=f"dim {P['silver']}")
        t.append(f" {cost_s}\n", style=cost_c)
        w.update(t)

        # ── MOD SECUNDÁRIO ────────────────────────────────────────────────
        mod2_title = self.query_one("#info-mod2-title", Static)
        mod2_title.update(f"  {self._model2}")

        total2 = self._tok2_in + self._tok2_out
        cost2_s, cost2_c = self._cost_str(self._cost2_usd)
        bar, bar_clr = self._progress_bar(self._QUOTA_TOTAL, self._QUOTA_LIMIT)
        pct_str = f"{self._QUOTA_TOTAL / max(self._QUOTA_LIMIT, 1) * 100:.1f}%"

        w = self.query_one("#info-mod2-body", Static)
        t = Text()
        t.append(f"  {'tok ↑':<8}", style=f"dim {P['silver']}")
        t.append(f" {self._tok2_in:,}\n", style=P["text"])
        t.append(f"  {'tok ↓':<8}", style=f"dim {P['silver']}")
        t.append(f" {self._tok2_out:,}\n", style=P["text"])
        t.append(f"  {'total':<8}", style=f"dim {P['silver']}")
        t.append(f" {total2:,}\n", style=f"bold {P['accent']}")
        t.append(f"  {'custo':<8}", style=f"dim {P['silver']}")
        t.append(f" {cost2_s}\n", style=cost2_c)
        t.append(f"  ── cota\n", style=f"dim {P['muted']}")
        t.append(f"  {'sessão':<8}", style=f"dim {P['silver']}")
        t.append(f" {self._QUOTA_SESS:,}\n", style=P["text"])
        t.append(f"  {'geral':<8}", style=f"dim {P['silver']}")
        t.append(f" {self._QUOTA_TOTAL:,}\n", style=P["text"])
        t.append(f"  {'limite':<8}", style=f"dim {P['silver']}")
        t.append(f" {self._QUOTA_LIMIT:,}\n", style=f"dim {P['muted']}")
        t.append(f"  {'uso':<8}", style=f"dim {P['silver']}")
        t.append(f" {pct_str}\n", style=f"bold {bar_clr}")

        t.append(f"  ")
        t.append(bar, style=bar_clr)
        t.append(f"\n", style="")
        w.update(t)


# ─── Top bar ─────────────────────────────────────────────────────────────────

class TopBar(Static):
    def __init__(self, agent: str, model: str, **kw):
        super().__init__(**kw)
        self._agent  = agent
        self._model  = model
        self._tok_in = 0
        self._tok_out= 0

    def update_state(self, agent: str = "", model: str = "",
                     tok_in: int = 0, tok_out: int = 0) -> None:
        if agent: self._agent = agent
        if model: self._model = model
        self._tok_in  += tok_in
        self._tok_out += tok_out
        self.refresh()

    def render(self) -> Text:
        t = Text(overflow="ellipsis", no_wrap=True)
        t.append("  ◈ ciel", style=f"bold {P['accent']}")
        t.append("  │  ", style=f"dim {P['border']}")
        t.append("● ", style=P["green"])
        t.append(self._agent, style=f"bold {P['text']}")
        t.append(f"   {self._model}", style=f"dim {P['silver']}")
        t.append(f"   ↑{self._tok_in:,} ↓{self._tok_out:,}",
                 style=f"dim {P['muted']}")
        return t



# ─── App ──────────────────────────────────────────────────────────────────────

class CielTUI(App):
    TITLE = "ciel v2"

    CSS = f"""
    Screen {{
        background: {P['bg']};
        layout: vertical;
    }}

    /* ── top bar ── */
    #top-bar {{
        height: 2;
        background: {P['surface']};
        border-bottom: solid {P['border']};
        content-align: left middle;
    }}

    /* ── body ── */
    #body {{
        height: 1fr;
        layout: horizontal;
        overflow: hidden;
    }}

    /* ── sidebar ── */
    Sidebar {{
        width: 24;
        min-width: 24;
        background: {P['panel']};
        border-right: solid {P['border']};
        layout: vertical;
        overflow: hidden;
    }}

    /* agent card */
    #logo-card {{
        height: 7;
        background: {P['surface']};
        border-bottom: solid {P['border']};
        padding: 1 0 0 0;
    }}

    /* label de seção: comandos */
    #sidebar-cmds-hdr {{
        height: 2;
        background: {P['surface']};
        color: {P['muted']};
        text-style: bold;
        padding: 0 2;
        content-align: left middle;
        border-bottom: solid {P['border']};
    }}

    /* sessions */
    SessionList {{
        height: 1fr;
        layout: vertical;
        overflow-y: auto;
    }}
    #sessions-hdr {{
        height: 3;
        background: {P['surface']};
        color: {P['muted']};
        text-style: bold;
        padding: 0 2;
        content-align: left middle;
        border-top: solid {P['border']};
        border-bottom: solid {P['border']};
    }}
    #sessions-table {{
        height: 1fr;
        background: {P['panel']};
        border: none;
        color: {P['muted']};
    }}
    DataTable > .datatable--cursor {{
        background: {P['hi']};
        color: {P['accent']};
    }}

    /* ── chat ── */
    #chat-col {{
        width: 1fr;
        layout: vertical;
        background: {P['surface']};
        overflow: hidden;
    }}

    #view-banner {{
        height: 2;
        background: {P['dim']};
        color: {P['orange']};
        padding: 0 2;
        content-align: left middle;
        display: none;
    }}
    #view-banner.active {{ display: block; }}

    #chat-log {{
        height: 1fr;
        background: {P['surface']};
        padding: 1 3;
        border: none;
    }}

    #thinking {{
        height: 1;
        background: {P['surface']};
        color: {P['accent']};
        padding: 0 3;
        display: none;
    }}
    #thinking.active {{ display: block; }}

    /* ── input area ── */
    #input-wrap {{
        height: auto;
        background: {P['surface']};
        padding: 1 2 0 2;
    }}
    #chips-row {{
        height: auto;
        min-height: 0;
        layout: horizontal;
        background: {P['surface']};
        padding: 0 0 0 1;
        display: none;
    }}
    #chips-row.has-chips {{
        display: block;
        height: 1;
        margin-bottom: 1;
    }}
    CmdSuggest {{
        display: none;
        height: auto;
        background: {P['surface']};
        border: solid {P['border']};
        border-bottom: solid {P['accent']};
        margin: 0 0 1 0;
        max-height: 12;
        overflow-y: auto;
    }}

    #input-row {{
        height: 3;
        background: {P['bg']};
        border: solid {P['accent']};
        layout: horizontal;
        padding: 0 1;
        align: left middle;
    }}
    #input-row:focus-within {{
        border: solid {P['cyan']};
    }}
    #input-prefix {{
        width: auto;
        height: 1;
        background: {P['bg']};
        color: {P['accent']};
        text-style: bold;
        padding: 0 1 0 0;
    }}
    #input-row:focus-within #input-prefix {{
        color: {P['cyan']};
    }}

    Input {{
        width: 1fr;
        height: 3;
        background: {P['bg']};
        color: {P['text']};
        border: none;
        padding: 0;
    }}
    Input:focus {{ border: none; background: {P['bg']}; }}


    /* ── info panel ── */
    InfoPanel {{
        width: 22;
        min-width: 22;
        background: {P['panel']};
        border-left: solid {P['border']};
        layout: vertical;
        overflow-y: auto;
    }}
    #info-sess-title {{
        height: 2;
        width: 1fr;
        background: {P['surface']};
        color: {P['accent']};
        text-style: bold;
        content-align: left middle;
        border-bottom: solid {P['border']};
        padding: 0 2;
    }}
    #info-orch-title,
    #info-mod2-title {{
        height: 1;
        background: {P['dim']};
        color: {P['cyan']};
        text-style: bold;
        content-align: left middle;
        padding: 0 1;
    }}
    #info-sess-body,
    #info-orch-body,
    #info-mod2-body {{
        height: auto;
        padding: 1 0 0 0;
        border-bottom: solid {P['border']};
    }}

    /* ── sys monitor ── */
    #info-sys-title {{
        height: 1;
        background: {P['dim']};
        color: {P['gold']};
        text-style: bold;
        content-align: left middle;
        padding: 0 1;
        margin-top: 1;
    }}
    SysMonitor {{
        height: auto;
        padding: 1 0 1 0;
        border-bottom: solid {P['border']};
    }}
    #sys-cpu-label,
    #sys-ram-label,
    #sys-vram-label {{
        height: 1;
    }}
    #sys-cpu-spark {{
        height: 3;
        margin: 0 2;
        color: {P['green']};
    }}

    /* ── footer ── */
    Footer {{
        background: {P['panel']};
        color: {P['silver']};
    }}
    Footer > .footer--key {{
        background: {P['dim']};
        color: {P['accent']};
        text-style: bold;
    }}

    """

    BINDINGS = [
        Binding("ctrl+q", "quit",           description="sair",        show=True),
        Binding("ctrl+n", "new_session",    description="nova sessão", show=True),
        Binding("ctrl+s", "save_session",   description="salvar",      show=True),
        Binding("ctrl+l", "clear_chat",     description="limpar",      show=True),
        Binding("ctrl+b", "toggle_sidebar", description="sidebar",     show=True),
        Binding("escape", "focus_input",    show=False),
        Binding("f1",     "cmd_tool",       description="tool",        show=True),
        Binding("f2",     "cmd_task",       description="task",        show=True),
        Binding("f3",     "cmd_skill",      description="skill",       show=True),
        Binding("f4",     "cmd_agente",     description="agente",      show=True),
        Binding("/",      "focus_slash",    show=False),
        Binding("tab",    "cycle_focus",    show=False),
        Binding("ctrl+y", "toggle_select",  description="selecionar", show=False),
        Binding("ctrl+k", "edit_pill",       description="editar colado", show=False),
    ]

    # ── estado ────────────────────────────────────────────────────────────────
    current_agent: reactive[str]  = reactive("general")
    current_model: reactive[str]  = reactive("gemma4:cloud")
    safe_mode:     reactive[bool] = reactive(False)
    input_hist:    list[str]      = []
    hist_cursor:   int            = -1
    session_no:    reactive[str]  = reactive("nova")
    tok_in:        int            = 0
    tok_out:       int            = 0
    # ── estado do agente real ─────────────────────────────────────────────────
    _tools:        dict           = {}
    _schema:       list           = []
    _agent_info:   dict           = {}
    _history:      list           = []
    _store:        object         = None
    _session_id:   object         = None
    _focus_cycle:  int            = 0   # 0=chat 1=sidebar 2=info
    _sidebar_pinned: bool | None  = None  # None = auto; True/False = manual override
    _select_mode:   bool            = False  # modo seleção — desativa mouse
    _log_lines:     list            = []       # buffer para o modal de cópia
    _link_chips:    list            = []       # URLs capturadas como chips
    _paste_pill:    "PastePill | None" = None  # pill de texto colado longo
    _mcp_manager:   object          = None     # MCPManager — conecta servidores MCP

    # ── init ──────────────────────────────────────────────────────────────────

    def __init__(
        self,
        initial_agent: str = "general",
        initial_model: str = "gemma4:cloud",
        safe_mode: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.current_agent = initial_agent
        self.current_model = initial_model
        self.safe_mode     = safe_mode

    # ── compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield TopBar("general", self.current_model, id="top-bar")
        with Horizontal(id="body"):
            yield Sidebar(id="sidebar")
            with Vertical(id="chat-col"):
                yield Static("", id="view-banner")
                yield RichLog(id="chat-log", highlight=False,
                              markup=False, auto_scroll=True, wrap=True)
                yield Static("  ● pensando…", id="thinking")
                with Vertical(id="input-wrap"):
                    yield CmdSuggest(id="cmd-suggest")
                    yield Horizontal(id="chips-row")
                    with Horizontal(id="input-row"):
                        yield Static(">", id="input-prefix")
                        yield CielInput(placeholder="mensagem ou /comando…", id="input-box")
            yield InfoPanel("general", self.current_model, id="info-panel")
        yield Footer()

    # ── resize responsivo ─────────────────────────────────────────────────────

    def on_resize(self, event: events.Resize) -> None:
        w = event.size.width
        sb = self.query_one("#sidebar",    Sidebar)
        ip = self.query_one("#info-panel", InfoPanel)

        if self._sidebar_pinned is not None:
            # usuário forçou manualmente — respeita, só ajusta info panel
            if w < 60:
                ip.display = False
            else:
                ip.display = True
            return

        # modo automático
        if w >= 100:          # tudo visível
            sb.display = True
            ip.display = True
        elif w >= 70:         # esconde sidebar, mantém info
            sb.display = False
            ip.display = True
        else:                 # só chat
            sb.display = False
            ip.display = False

    # ── mount ─────────────────────────────────────────────────────────────────

    def _log_write(self, item) -> None:
        """Escreve no chat-log e acumula no buffer para o CopyModal."""
        log = self.query_one("#chat-log", RichLog)
        log.write(item)
        self._log_lines.append(item)

    # ── carregamento de agente e tools ───────────────────────────────────────

    UNSAFE_TOOLS = {"run_script"}

    def _load_agent(self, agent_name: str) -> None:
        """Carrega agent_info, tools e schema. Atualiza estado e widgets."""
        try:
            self._agent_info = load_agent(agent_name)
        except Exception as e:
            self._log_write(msg_system(f"agente '{agent_name}' não encontrado: {e}", "err"))
            return

        all_tools = load_tools()
        tools = filter_tools(all_tools, self._agent_info.get("allowed_tools"))
        if self.safe_mode:
            tools = {k: v for k, v in tools.items() if k not in self.UNSAFE_TOOLS}

        # reinjeta tools MCP se o manager já estiver inicializado
        if self._mcp_manager is not None:
            tools.update(filter_mcp_tools(
                self._mcp_manager.all_tools(),
                self._agent_info.get("allowed_mcp_servers"),
            ))
            # reinjeta referência do manager nas tools administrativas
            _mcp_admin_tools = ("mcp_add_server", "mcp_list_servers", "mcp_remove_server")
            for tn in _mcp_admin_tools:
                if tn in tools:
                    tools[tn]["fn"].__globals__["_manager"] = self._mcp_manager

        self._tools  = tools
        self._schema = tools_schema(tools)

        # atualiza widgets se já montados
        try:
            desc = self._agent_info.get("description", "")
            self.query_one("#logo-card",  AgentCard).update(agent_name, desc)
            self.query_one("#top-bar",    TopBar).update_state(agent=agent_name)
            self.query_one("#info-panel", InfoPanel).update_state(agent=agent_name)
        except Exception:
            pass  # widgets ainda não montados no primeiro on_mount

    def _handle_session_action(self, sess_id: int, action: str, sess_list: "SessionList") -> None:
        """Executa a ação escolhida no SessionModal com dados reais."""
        store = self._store
        if store is None:
            return
        try:
            sess = store.get_session(sess_id)
        except Exception:
            sess = None

        if action == "view":
            # carrega o histórico da sessão no chat
            try:
                turns = store.get_turns(sess_id)
                log   = self.query_one("#chat-log", RichLog)
                log.clear()
                self._log_write(msg_system(
                    f"sessão #{sess_id} — {sess['title'] or 'sem título'}", "info"))
                self._log_write(msg_sep())
                for turn in turns:
                    if turn["role"] == "user":
                        self._log_write(msg_user(turn["content"] or ""))
                    else:
                        self._log_write(msg_agent(
                            sess["agent_id"] or self.current_agent,
                            turn["content"] or "",
                        ))
                self._log_write(msg_sep())
                self._log_write(msg_system("visualização somente leitura — /novo para nova sessão", "info"))
            except Exception as e:
                self._log_write(msg_system(f"erro ao carregar sessão: {e}", "err"))

        elif action == "branch":
            # fork: nova sessão filha com resumo injetado
            try:
                from history_ui import build_context_injection
                summary = sess["summary"] if sess else ""
                title   = sess["title"]   if sess else ""
                agent_id = sess["agent_id"] if sess else self.current_agent

                new_sid = store.branch_session(
                    sess_id, agent_id,
                    title=f"[branch] {title or ''}",
                )
                self._session_id = new_sid
                self._history.clear()
                self.session_no = str(new_sid)
                self.query_one("#info-panel", InfoPanel).update_state(sess_no=str(new_sid))

                # troca agente se necessário
                if agent_id != self.current_agent:
                    try:
                        self._load_agent(agent_id)
                        self.current_agent = agent_id
                    except Exception:
                        pass

                # injeta resumo no próximo turno
                if summary:
                    from history_ui import build_context_injection
                    self._context_injection = build_context_injection(
                        summary, title or "", agent_id)
                    self._log_write(msg_system(
                        f"branch #{new_sid} criado  ·  resumo injetado no contexto", "ok"))
                else:
                    self._context_injection = None
                    self._log_write(msg_system(
                        f"branch #{new_sid} criado  ·  sem resumo disponível", "ok"))

                sess_list._refresh_table()
            except Exception as e:
                self._log_write(msg_system(f"erro ao criar branch: {e}", "err"))

        elif action == "export":
            try:
                out = store.export_markdown(sess_id)
                self._log_write(msg_system(f"exportado: {out}", "ok"))
            except Exception as e:
                self._log_write(msg_system(f"erro ao exportar: {e}", "err"))

        elif action in ("delete", "delete_back"):
            try:
                store.delete_session(sess_id)
                self._log_write(msg_system(f"sessão #{sess_id} deletada", "warn"))
                if action == "delete_back":
                    # volta para a sessão mais recente restante
                    remaining = store.list_sessions()
                    if remaining:
                        self._log_write(msg_system(
                            f"sessão #{remaining[0]['id']} disponível — use /history para retomar", "info"))
                sess_list._refresh_table()
            except Exception as e:
                self._log_write(msg_system(f"erro ao deletar: {e}", "err"))

    @work(thread=True)
    def _save_session_bg(self) -> None:
        """Gera resumo via modelo e salva sessão em background."""
        if not self._history or self._store is None:
            self.call_from_thread(
                self._log_write,
                msg_system("nenhuma conversa para salvar.", "warn"),
            )
            return

        store = self._store
        sid   = self._session_id

        # cria sessão se ainda não existir
        if sid is None:
            first_user = next(
                (e["content"] for e in self._history if e["role"] == "user"), "")
            fallback = " ".join(first_user.split()[:8]) or "sem título"
            try:
                sid = store.new_session(
                    agent_id=self._agent_info.get("id", self.current_agent),
                    title=fallback,
                )
                for entry in self._history:
                    store.append_turn(sid, entry["role"], entry["content"], entry.get("ts", ""))
                self._session_id = sid
                self.call_from_thread(
                    lambda: setattr(self, "session_no", str(sid)))
            except Exception as e:
                self.call_from_thread(
                    self._log_write,
                    msg_system(f"erro ao criar sessão: {e}", "err"),
                )
                return

        self.call_from_thread(self._log_write, msg_system("gerando resumo…", "info"))

        # gera resumo via Ollama
        try:
            import requests as _req
            conv_text = "\n".join(
                f"[{'user' if e['role'] == 'user' else 'agente'}] {e['content']}"
                for e in self._history
            )
            prompt_resumo = (
                "Você é um assistente técnico. Leia a conversa e produza um resumo "
                "estruturado em português com EXATAMENTE estas três seções:\n\n"
                "TÍTULO: (1 linha curta, máx. 60 chars)\n"
                "CONTEXTO: (1-3 frases) — o que estava sendo feito e por quê\n"
                "ESTADO: (bullets) — decisões, tools criadas, arquivos, pendências\n\n"
                f"CONVERSA:\n{conv_text[:6000]}"
            )
            from agent_loop import OLLAMA_URL
            resp = _req.post(OLLAMA_URL, json={
                "model": self.current_model,
                "messages": [
                    {"role": "system",  "content": "Responda apenas com o resumo."},
                    {"role": "user",    "content": prompt_resumo},
                ],
                "stream": False,
            }, timeout=120)
            resp.raise_for_status()
            summary_raw = resp.json()["message"]["content"].strip()

            # extrai TÍTULO
            fallback_title = " ".join(
                next((e["content"] for e in self._history if e["role"] == "user"), "").split()[:8]
            ) or "sem título"
            title_final = fallback_title
            clean_lines = []
            for line in summary_raw.splitlines():
                if line.upper().startswith(("TÍTULO:", "TITULO:")):
                    extracted = line.split(":", 1)[1].strip()
                    if extracted:
                        title_final = extracted[:60]
                else:
                    clean_lines.append(line)
            summary = "\n".join(clean_lines).strip()

            store.update_title(sid, title_final)
            store.save_summary(sid, summary)

            self.call_from_thread(
                self._log_write,
                msg_system(f"sessão #{sid} salva  ·  {title_final}", "ok"),
            )
            # atualiza sidebar
            try:
                self.call_from_thread(
                    self.query_one("#session-list", SessionList)._refresh_table)
            except Exception:
                pass

        except Exception as e:
            self.call_from_thread(
                self._log_write,
                msg_system(f"resumo falhou ({e}), sessão salva sem resumo.", "warn"),
            )

    def on_mount(self) -> None:
        self.query_one("#input-box", CielInput).focus()
        self._store = HistoryStore(DB_PATH)

        # store agora esta pronto - forca o refresh da sidebar
        # (SessionList.on_mount rodou antes do store ser criado)
        try:
            self.query_one("#session-list", SessionList)._refresh_table()
        except Exception:
            pass

        # le modelo secundario do ciel_config.json
        try:
            from pathlib import Path
            cfg = json.loads(Path("ciel_config.json").read_text(encoding="utf-8"))
            model2_name = cfg.get("model", "")
            if model2_name:
                self.query_one("#info-panel", InfoPanel).update_state(model2=model2_name)
        except Exception:
            pass

        # carrega agente e tools reais
        self._load_agent(self.current_agent)
        self._refresh_skill_commands()

        # ── MCP: cria o manager e injeta nas tools admin ──────────────────────
        # IMPORTANTE: connect_all() usa SyncMCPClient que chama
        # loop.run_until_complete() internamente. Isso não pode ser chamado aqui
        # porque on_mount() roda dentro do loop asyncio do Textual — em Python
        # 3.10+ isso levanta "RuntimeError: Cannot run the event loop while
        # another loop is running". A conexão real é feita em _mcp_init_worker()
        # (thread separada), que não tem nenhum loop ativo.
        self._mcp_manager = MCPManager()

        # Injeta o manager nas tools administrativas já agora, antes de conectar,
        # para que mcp_add_server / mcp_list_servers / mcp_remove_server
        # funcionem corretamente mesmo antes do worker terminar.
        _mcp_admin_tools = ("mcp_add_server", "mcp_list_servers", "mcp_remove_server")
        for tn in _mcp_admin_tools:
            if tn in self._tools:
                self._tools[tn]["fn"].__globals__["_manager"] = self._mcp_manager

        # Dispara a conexão em background (não bloqueia o loop do Textual)
        self._mcp_init_worker()

        t = Text()
        t.append("\n  ciel", style=f"bold {P['accent']}")
        t.append("  agentic CLI local", style=f"dim {P['silver']}")
        self._log_write(t)
        self._log_write(msg_sep())
        self._log_write(msg_system(
            f"persona: {self.current_agent}  │  modelo: {self.current_model}", "info"))
        self._log_write(msg_system("Ollama em localhost:11434", "ok"))
        self._log_write(msg_system(
            f"{len(self._tools)} ferramentas ativas — F1 para listar", "info"))
        self._log_write(msg_system(
            "F2 tasks   F3 skills   F4 agentes   / foca input", "info"))
        self._log_write(Text())

    # ── input ─────────────────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        suggest = self.query_one("#cmd-suggest", CmdSuggest)
        val = event.value
        if val.startswith("/") and " " not in val:
            suggest.refresh_suggestions(val)
        else:
            suggest.hide()
        # detecta URLs digitadas/coladas e converte em chips
        if not val.startswith("/"):
            self._try_add_url_chip(event.input)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        suggest = self.query_one("#cmd-suggest", CmdSuggest)
        # Enter com suggest aberto = completar, nao submeter
        if suggest.display:
            cmd = suggest.current_cmd()
            if cmd:
                # se o comando tem subcomando (ex: "/history salvar"), insere completo
                # e adiciona espaço só se for comando base sem argumento fixo
                parts = cmd.split()
                if len(parts) == 1 or parts[-1].startswith("<"):
                    # comando simples ou com placeholder: insere base + espaço
                    event.input.value = parts[0] + " "
                else:
                    # tem subcomando fixo (ex: "salvar", "exportar"): insere completo
                    event.input.value = cmd
                event.input.cursor_position = len(event.input.value)
            suggest.hide()
            return
        text = event.value.strip()
        # monta texto final: pill + chips + texto do input
        pill_content = None
        parts = []
        if self._paste_pill:
            pill_content = self._paste_pill.content
            parts.append(pill_content)
            self._paste_pill = None
        for chip in self._link_chips:
            parts.append(chip.url)
        self._link_chips.clear()
        self._sync_chips_row()
        if text:
            parts.append(text)
        full_text = "\n".join(parts).strip() if parts else ""
        if not full_text:
            return
        event.input.value = ""
        self.input_hist.append(full_text)
        self.hist_cursor = len(self.input_hist)
        self._dispatch(full_text, pill_content=pill_content, prompt=text)

    def on_key(self, event: events.Key) -> None:
        inp     = self.query_one("#input-box",   CielInput)
        suggest = self.query_one("#cmd-suggest", CmdSuggest)
        if not inp.has_focus:
            return
        if suggest.display:
            if event.key == "up":
                suggest.move(-1); event.prevent_default()
            elif event.key == "down":
                suggest.move(1);  event.prevent_default()
            elif event.key == "tab":
                cmd = suggest.current_cmd()
                if cmd:
                    parts = cmd.split()
                    if len(parts) == 1 or parts[-1].startswith("<"):
                        inp.value = parts[0] + " "
                    else:
                        inp.value = cmd
                    inp.cursor_position = len(inp.value)
                suggest.hide(); event.prevent_default()
            elif event.key == "escape":
                suggest.hide(); event.prevent_default()
        else:
            if event.key == "up":
                self._hist_up();   event.prevent_default()
            elif event.key == "down":
                self._hist_down(); event.prevent_default()
            elif event.key == "ctrl+k":
                if self._paste_pill is not None:
                    self._open_paste_editor(self._paste_pill)
                event.prevent_default()

    def _hist_up(self) -> None:
        if not self.input_hist: return
        self.hist_cursor = max(0, self.hist_cursor - 1)
        self.query_one("#input-box", CielInput).value = self.input_hist[self.hist_cursor]

    def _hist_down(self) -> None:
        if not self.input_hist: return
        self.hist_cursor = min(len(self.input_hist), self.hist_cursor + 1)
        inp = self.query_one("#input-box", CielInput)
        inp.value = "" if self.hist_cursor == len(self.input_hist) \
                    else self.input_hist[self.hist_cursor]

    # ── chips / paste pill ────────────────────────────────────────────────────

    def _sync_chips_row(self) -> None:
        """Re-renderiza a chips-row com os chips e pill atuais."""
        row = self.query_one("#chips-row", Horizontal)
        row.remove_children()
        has = bool(self._link_chips) or (self._paste_pill is not None)
        if has:
            if self._paste_pill:
                row.mount(self._paste_pill)
            for chip in self._link_chips:
                row.mount(chip)
            row.add_class("has-chips")
        else:
            row.remove_class("has-chips")

    def _remove_link_chip(self, chip: "LinkChip") -> None:
        """Remove chip e devolve URL para o input."""
        if chip in self._link_chips:
            self._link_chips.remove(chip)
        inp = self.query_one("#input-box", CielInput)
        inp.value = (chip.url + " " + inp.value).strip()
        inp.cursor_position = len(inp.value)
        self._sync_chips_row()

    def _open_paste_editor(self, pill: "PastePill") -> None:
        """Abre o modal de edição do conteúdo do pill."""
        def on_result(result) -> None:
            if result is None:
                return  # cancelou — pill continua intacto
            action, text = result
            if action == "delete":
                # descarta o pill e limpa o input também
                self._paste_pill = None
                self._sync_chips_row()
                self.query_one("#input-box", CielInput).focus()
            else:
                # atualiza o pill com o conteúdo editado
                self._paste_pill = PastePill(text)
                self._sync_chips_row()

        self.push_screen(PasteEditModal(pill.content), on_result)

    def _expand_paste_pill(self, pill: "PastePill") -> None:
        """Legado — mantido para compatibilidade, redireciona para o editor."""
        self._open_paste_editor(pill)

    def _try_add_url_chip(self, inp: Input) -> None:
        """Detecta URLs no valor do input e as converte em chips."""
        val = inp.value
        # só processa se terminar em espaço (URL provavelmente completa)
        if not val.endswith(" "):
            return
        urls, remainder = _extract_urls(val.rstrip())
        if not urls:
            return
        for url in urls:
            self._link_chips.append(LinkChip(url))
        inp.value = remainder + (" " if remainder else "")
        inp.cursor_position = len(inp.value)
        self._sync_chips_row()

    def _handle_long_paste(self, text: str) -> None:
        """Chamado por CielInput quando um paste longo é detectado."""
        if self._paste_pill:
            combined = self._paste_pill.content + "\n" + text
            self._paste_pill = PastePill(combined)
        else:
            self._paste_pill = PastePill(text)
        self._sync_chips_row()
        # Limpa qualquer fragmento que tenha vazado pro input
        # (ocorre quando o terminal não suporta bracketed paste)
        inp = self.query_one("#input-box", CielInput)
        inp.value = ""

    def on_paste(self, event: events.Paste) -> None:
        # Tratamento real está em CielInput._on_paste → _handle_long_paste.
        pass

    # ── dispatcher ────────────────────────────────────────────────────────────

    def _dispatch(self, text: str, pill_content: str | None = None, prompt: str = "") -> None:
        log = self.query_one("#chat-log", RichLog)
        if text.startswith("/"):
            self._cmd(text, log)
        else:
            if pill_content is not None:
                self._log_write(msg_user_pill(pill_content, prompt))
            else:
                self._log_write(msg_user(text))

            # salva turno do usuário no histórico
            ts_str = datetime.now().strftime("%a %H:%M")
            self._history.append({"role": "user", "content": text, "ts": ts_str})

            # cria sessão no store na primeira mensagem real
            if self._session_id is None and self._store is not None:
                self._session_id = self._store.new_session(
                    agent_id=self._agent_info.get("id", self.current_agent),
                    title="",
                )
                auto_title = " ".join(text.split()[:8])
                self._store.update_title(self._session_id, auto_title)
                self.session_no = str(self._session_id)
                self.query_one("#info-panel", InfoPanel).update_state(
                    sess_no=str(self._session_id))
                # atualiza sidebar imediatamente com a nova sessão
                try:
                    self.query_one("#session-list", SessionList)._refresh_table()
                except Exception:
                    pass

            if self._session_id is not None:
                self._store.append_turn(self._session_id, "user", text, ts_str)

            self._agent_turn(text, log)

    # ── modal helpers ─────────────────────────────────────────────────────────

    def _run_task_by_name(self, name: str, log: RichLog) -> None:
        """Resolve o .md, monta o task_prompt estruturado e despacha para _agent_turn."""
        from pathlib import Path
        tasks_dir = Path("tasks")

        # tenta caminho direto primeiro; depois busca por stem
        task_path = Path(name) if name.endswith(".md") else tasks_dir / f"{name}.md"
        if not task_path.exists():
            candidates = find_tasks(name, tasks_dir)
            if not candidates:
                self._log_write(msg_system(
                    f"task '{name}' não encontrada em tasks/", "err"
                ))
                return
            task_path = candidates[0]  # melhor match

        task = load_task(task_path)
        if not task:
            self._log_write(msg_system(
                f"arquivo '{task_path.name}' não segue o formato de task", "err"
            ))
            return

        n_acoes = len(task["acoes"])
        self._log_write(msg_system(
            f"task: {task['nome']}  │  {n_acoes} ações  │  até {MAX_STEPS_TASK} steps",
            "info",
        ))
        task_prompt = build_task_prompt(task)
        self._agent_turn(task_prompt, log, max_steps=MAX_STEPS_TASK)

    def _open_task_modal(self) -> None:
        from pathlib import Path
        tasks_dir = Path("tasks")
        task_items: list[tuple[str, str]] = []
        if tasks_dir.exists():
            for p in sorted(tasks_dir.glob("*.md")):
                # lê objetivo da primeira linha "objetivo: ..." se existir
                try:
                    obj = ""
                    for line in p.read_text(encoding="utf-8").splitlines():
                        if line.strip().startswith("objetivo:"):
                            obj = line.split(":", 1)[1].strip()[:60]
                            break
                except Exception:
                    obj = ""
                task_items.append((p.stem, obj))
        if not task_items:
            task_items = [("(nenhuma task encontrada)", "")]

        def on_result(choice):
            if choice and choice != "(nenhuma task encontrada)":
                log = self.query_one("#chat-log", RichLog)
                self._run_task_by_name(choice, log)

        self.set_focus(None)
        self.push_screen(
            SelectionModal("  /task — escolha uma tarefa", task_items),
            on_result,
        )

    def _open_agent_modal(self) -> None:
        def on_result(choice):
            if choice:
                try:
                    self._load_agent(choice)
                    self.current_agent = choice
                    self._history.clear()
                    self._session_id = None
                    self.session_no  = "nova"
                    self._log_write(msg_system(f"persona trocada para '{choice}'", "ok"))
                    self._log_write(msg_system(f"{len(self._tools)} tools ativas", "info"))
                except Exception as e:
                    self._log_write(msg_system(f"erro ao carregar '{choice}': {e}", "err"))

        try:
            agent_names = list_agents()
            agent_items = []
            for name in agent_names:
                try:
                    info = load_agent(name)
                    desc = info.get("description", "")[:60]
                except Exception:
                    desc = ""
                agent_items.append((name, desc))
        except Exception:
            agent_items = [(self.current_agent, "")]

        self.set_focus(None)
        self.push_screen(
            SelectionModal("  /agente — escolha uma persona", agent_items),
            on_result,
        )

    def _open_skill_modal(self) -> None:
        def on_result(choice):
            if choice:
                log = self.query_one("#chat-log", RichLog)
                self._log_write(msg_system(f"skill '{choice}' ativada", "ok"))
        self.set_focus(None)
        self.push_screen(
            SelectionModal("  /skill — escolha uma habilidade", FAKE_SKILLS),
            on_result,
        )

    def _open_tool_modal(self) -> None:
        items = [
            (name, meta.get("description", "")[:60])
            for name, meta in self._tools.items()
        ]
        if not items:
            items = [("(nenhuma tool carregada)", "")]

        def on_result(choice):
            if choice and choice in self._tools:
                cat = self._tools[choice].get("categoria", "permanente")
                self._log_write(msg_system(f"tool '{choice}' — ativa  ○  {cat}", "ok"))

        self.set_focus(None)
        self.push_screen(
            SelectionModal("  /tool — ferramentas disponíveis", items),
            on_result,
        )

    # ── comandos ─────────────────────────────────────────────────────────────

    def _cmd(self, raw: str, log: RichLog) -> None:
        self._log_write(msg_user(raw))
        parts = raw.split()
        verb  = parts[0].lower()

        if verb in ("/ajuda", "/help"):
            cmds = [
                ("/tool",                 "lista/inspeciona ferramentas  [F1]"),
                ("/task",                 "escolhe e executa task        [F2]"),
                ("/task <nome>",          "executa task diretamente"),
                ("/skill",                "ativa skill disponível        [F3]"),
                ("/agente",               "troca persona interativo      [F4]"),
                ("/agente <nome>",        "troca persona diretamente"),
                ("/model <nome>",         "troca modelo Ollama"),
                ("/model2 <nome>",        "define modelo secundário"),
                ("/novo",                 "nova sessão"),
                ("/limpar",               "limpa display"),
                ("/history",              "lista sessões salvas"),
                ("/history salvar",       "salva sessão atual"),
                ("/history exportar",     "exporta como .md"),
                ("/history <agente>",    "filtra sessões por agente"),
                ("/source <arquivo>",     "indexa na base de conhecimento"),
                ("/source --listar",      "lista fontes"),
                ("/source --global <f>",  "fonte compartilhada"),
                ("/tokens",               "uso de tokens desta sessão"),
                ("/copiar",               "copia última resposta"),
                ("/safe",                 "toggle modo seguro"),
                ("/limpar-temp",          "remove tools temporárias"),
                ("/promover <nome>",      "promove tool temp a permanente"),
                ("/mcp",                  "lista servidores MCP e status"),
                ("/mcp -v",               "lista MCP com tools de cada servidor"),
                ("/sair",                 "encerra"),
            ]
            t = Text()
            t.append("\n  comandos disponíveis\n", style=f"bold {P['accent']}")
            for c, d in cmds:
                t.append(f"  {c:<28}", style=f"bold {P['gold']}")
                t.append(f"{d}\n",     style=f"dim {P['silver']}")
            self._log_write(t)

        elif verb == "/tool":
            # sem argumento: abre modal; com argumento: inspeciona
            if len(parts) < 2:
                self._open_tool_modal()
            else:
                name = parts[1]
                if name in self._tools:
                    cat = self._tools[name].get("categoria", "permanente")
                    self._log_write(msg_system(f"tool '{name}' — ativa  ○  {cat}", "ok"))
                else:
                    self._log_write(msg_system(f"tool '{name}' não encontrada", "err"))

        elif verb == "/tools":
            # alias para compatibilidade com v1
            self._open_tool_modal()

        elif verb == "/task":
            if len(parts) < 2:
                self._open_task_modal()
            else:
                self._run_task_by_name(parts[1], log)

        elif verb == "/skill":
            if len(parts) < 2:
                self._open_skill_modal()
            else:
                # raw.split(None, 2) para separar nome do prompt (que pode ter espaços)
                from pathlib import Path
                raw_parts  = raw.split(None, 2)
                skill_name = raw_parts[1].strip()
                skill_prompt = raw_parts[2].strip() if len(raw_parts) > 2 else ""
                skill_path = Path("skills") / f"{skill_name}.md"

                if not skill_path.exists():
                    self._log_write(msg_system(
                        f"skill '{skill_name}' não encontrada em skills/", "err"
                    ))
                elif not skill_prompt:
                    # /skill <nome> — exibe conteúdo da skill
                    content = skill_path.read_text(encoding="utf-8")
                    preview = content[:800] + ("…" if len(content) > 800 else "")
                    t = Text()
                    t.append(f"\n  skill: {skill_name}\n", style=f"bold {P['accent']}")
                    t.append(f"  {'─' * 60}\n", style=f"dim {P['muted']}")
                    for line in preview.splitlines():
                        t.append(f"  {line}\n", style=P["text"])
                    self._log_write(t)
                else:
                    # /skill <nome> <prompt> — injeta instrução e executa
                    injected = (
                        f"{skill_prompt}\n\n"
                        f"[instrução do sistema: use a tool secondary_model"
                        f" com skill=\"{skill_name}\"]"
                    )
                    self._log_write(msg_system(
                        f"skill: {skill_name}  │  {skill_prompt[:60]}", "info"
                    ))
                    self._agent_turn(injected, log)

        elif verb == "/agente":
            if len(parts) < 2:
                self._open_agent_modal()
            else:
                nome = parts[1]
                try:
                    self._load_agent(nome)
                    self.current_agent = nome
                    self._history.clear()
                    self._session_id = None
                    self.session_no  = "nova"
                    self._log_write(msg_system(f"persona trocada para '{nome}'", "ok"))
                    self._log_write(msg_system(f"{len(self._tools)} tools ativas", "info"))
                except Exception as e:
                    self._log_write(msg_system(f"agente '{nome}' não encontrado: {e}", "err"))

        elif verb == "/model":
            if len(parts) < 2:
                self._log_write(msg_system(f"modelo atual: {self.current_model}", "info"))
            else:
                self.current_model = parts[1]
                self.query_one("#top-bar",    TopBar).update_state(model=parts[1])
                self.query_one("#info-panel", InfoPanel).update_state(model=parts[1])
                self._log_write(msg_system(f"modelo trocado para '{parts[1]}'", "ok"))

        elif verb == "/model2":
            if len(parts) < 2:
                self._log_write(msg_system("uso: /model2 <nome>", "warn"))
            else:
                # modelo secundário ainda não implementado no painel
                self._log_write(msg_system(f"modelo secundário '{parts[1]}' registrado (em breve no painel)", "info"))

        elif verb == "/novo":
            self.session_no  = "nova"
            self._session_id = None
            self._history.clear()
            self.tok_in = self.tok_out = 0
            self.query_one("#info-panel", InfoPanel).update_state(sess_no="nova")
            log.clear()
            self._link_chips.clear()
            self._paste_pill = None
            self._sync_chips_row()
            self._log_write(msg_system(
                f"nova sessão  │  persona: {self.current_agent}  │  modelo: {self.current_model}", "ok"))

        elif verb == "/limpar":
            log.clear()

        elif verb == "/tokens":
            t = Text()
            t.append("\n  tokens desta sessão\n", style=f"bold {P['accent']}")
            t.append(f"  entrada   {self.tok_in:>8,}\n",  style=P["cyan"])
            t.append(f"  saída     {self.tok_out:>8,}\n", style=P["cyan"])
            t.append(f"  total     {self.tok_in + self.tok_out:>8,}\n",
                     style=f"bold {P['text']}")
            self._log_write(t)

        elif verb == "/safe":
            self.safe_mode = not self.safe_mode
            estado = "ativado" if self.safe_mode else "desativado"
            self._log_write(msg_system(f"modo seguro {estado}", "warn"))

        elif verb == "/source":
            sub = parts[1] if len(parts) > 1 else ""

            if not sub:
                self._log_write(msg_system(
                    "uso: /source <arquivo|url> [--global] | --listar | --remover <id> | --limpar-orfas",
                    "warn",
                ))

            elif sub == "--listar":
                aid = self._agent_info.get("id", self.current_agent)
                sid = str(self._session_id) if self._session_id else None
                try:
                    from knowledge.db import list_sources
                    sources = list_sources(agent_id=aid, session_id=sid)
                    if not sources:
                        self._log_write(msg_system("nenhuma fonte indexada", "info"))
                    else:
                        t = Text()
                        t.append(f"\n  {len(sources)} fonte(s) indexada(s)\n",
                                 style=f"bold {P['accent']}")
                        for s in sources:
                            escopo = "compartilhada" if s["session_id"] == "_shared" \
                                     else f"sessão {s['session_id']}"
                            t.append(f"  id={s['id']}  ", style=f"bold {P['cyan']}")
                            t.append(f"{s['filename']}  ", style=P["text"])
                            t.append(f"({s['n_chunks']} chunks · {escopo})\n",
                                     style=f"dim {P['muted']}")
                            if s.get("summary"):
                                resumo = s["summary"][:80].replace("\n", " ")
                                t.append(f"         ↳ {resumo}…\n",
                                         style=f"dim {P['silver']}")
                        self._log_write(t)
                except Exception as e:
                    self._log_write(msg_system(f"erro ao listar fontes: {e}", "err"))

            elif sub == "--limpar-orfas":
                try:
                    from knowledge.db import cleanup_orphan_sources
                    n = cleanup_orphan_sources()
                    if n:
                        self._log_write(msg_system(
                            f"{n} sessão(ões) órfã(s) removida(s) do knowledge.db", "ok"
                        ))
                    else:
                        self._log_write(msg_system("nenhuma fonte órfã encontrada", "info"))
                except Exception as e:
                    self._log_write(msg_system(f"erro ao limpar órfãs: {e}", "err"))

            elif sub == "--remover":
                if len(parts) < 3 or not parts[2].isdigit():
                    self._log_write(msg_system("uso: /source --remover <id>", "warn"))
                else:
                    source_id = int(parts[2])
                    aid = self._agent_info.get("id", self.current_agent)
                    try:
                        from knowledge.db import get_source, delete_source
                        from pathlib import Path as _Path
                        source = get_source(source_id)
                        if not source:
                            self._log_write(msg_system(
                                f"fonte id={source_id} não encontrada", "err"
                            ))
                        elif source["agent_id"] != aid:
                            self._log_write(msg_system(
                                f"fonte id={source_id} não pertence ao agente '{aid}'", "err"
                            ))
                        else:
                            filepath = source.get("filepath", "")
                            cache_path = _Path(filepath)
                            if "cache" in cache_path.parts:
                                try:
                                    cache_path.unlink(missing_ok=True)
                                    if cache_path.parent.exists() and \
                                       not any(cache_path.parent.iterdir()):
                                        cache_path.parent.rmdir()
                                except Exception:
                                    pass
                            delete_source(source_id)
                            self._log_write(msg_system(
                                f"fonte removida (id={source_id} · {source['filename']})", "ok"
                            ))
                    except Exception as e:
                        self._log_write(msg_system(f"erro ao remover fonte: {e}", "err"))

            else:
                # /source <arquivo|url> [--global]
                eh_global = "--global" in parts
                partes_sem_flag = [p for p in parts[1:] if p != "--global"]
                caminho = " ".join(partes_sem_flag)
                self._run_source(caminho, eh_global, log)

        elif verb == "/history":
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "salvar":
                self._save_session_bg()
            elif sub == "exportar":
                if self._session_id is not None and self._store is not None:
                    try:
                        out = self._store.export_markdown(self._session_id)
                        self._log_write(msg_system(f"exportado: {out}", "ok"))
                    except Exception as e:
                        self._log_write(msg_system(f"erro ao exportar: {e}", "err"))
                else:
                    self._log_write(msg_system("nenhuma sessão ativa para exportar", "warn"))
            else:
                # /history <agente> filtra por agente; sem arg lista todos
                agent_filter = sub if sub else None
                try:
                    sessions = self._store.list_sessions(agent_filter) if self._store else []
                    if not sessions:
                        msg = f"nenhuma sessão salva para '{agent_filter}'" if agent_filter else "nenhuma sessão salva ainda"
                        self._log_write(msg_system(msg, "info"))
                    else:
                        titulo = f"histórico — {agent_filter}" if agent_filter else "histórico — todos os agentes"
                        t = Text()
                        t.append(f"\n  {titulo}\n", style=f"bold {P['accent']}")
                        for row in sessions[:15]:
                            date  = (row["updated_at"] or "")[:16]
                            title = (row["title"] or "(sem título)")[:38]
                            agent = row["agent_id"] or ""
                            t.append(f"  {date}  ", style=f"dim {P['muted']}")
                            t.append(f"{title:<38}", style=P["text"])
                            t.append(f"  {agent}\n", style=f"dim {P['silver']}")
                        t.append("\n  use a sidebar para retomar, branch ou deletar\n",
                                 style=f"dim {P['muted']}")
                        self._log_write(t)
                except Exception as e:
                    self._log_write(msg_system(f"erro ao listar sessões: {e}", "err"))

        elif verb == "/copiar":
            agent_entries = [e for e in self._history if e["role"] == "agent"]
            if not agent_entries:
                self._log_write(msg_system("nenhuma resposta para copiar ainda", "warn"))
            else:
                texto = agent_entries[-1]["content"]
                try:
                    import pyperclip
                    pyperclip.copy(texto)
                    preview = texto[:60].replace("\n", " ")
                    self._log_write(msg_system(f"copiado: \"{preview}…\"", "ok"))
                except Exception:
                    self._log_write(msg_system(
                        "clipboard não disponível — instale xclip ou xsel no Linux",
                        "warn",
                    ))

        elif verb in ("/limpar-temp", "/limptemp"):
            from pathlib import Path
            temp_dir = Path("tools/temp")
            removidas = []
            if temp_dir.exists():
                for f in temp_dir.glob("*.py"):
                    if f.name != "__init__.py":
                        f.unlink()
                        removidas.append(f.stem)
            if removidas:
                self._reload_tools(log)
                self._log_write(msg_system(
                    f"tools temp removidas: {', '.join(removidas)}", "ok"
                ))
            else:
                self._log_write(msg_system("nenhuma tool temporária encontrada", "info"))

        elif verb == "/promover":
            if len(parts) < 2:
                self._log_write(msg_system("uso: /promover <nome-tool>", "warn"))
            else:
                from pathlib import Path
                tool_name = parts[1].removesuffix(".py")
                dst = Path("tools") / f"{tool_name}.py"

                # procura em tools/temp/ e no fallback tools/tools/temp/ (bug do agente)
                candidates = [
                    Path("tools/temp")       / f"{tool_name}.py",
                    Path("tools/tools/temp") / f"{tool_name}.py",
                ]
                src = next((p for p in candidates if p.exists()), None)

                if src is None:
                    self._log_write(msg_system(
                        f"tool temp '{tool_name}' não encontrada em tools/temp/", "err"
                    ))
                elif dst.exists():
                    self._log_write(msg_system(
                        f"já existe uma tool permanente com esse nome: '{tool_name}'", "warn"
                    ))
                else:
                    src.rename(dst)
                    self._reload_tools(log)
                    self._log_write(msg_system(
                        f"'{tool_name}' promovida para tools permanentes", "ok"
                    ))

        elif verb == "/mcp":
            verbose = len(parts) > 1 and parts[1] == "-v"
            if self._mcp_manager is None:
                self._log_write(msg_system("MCP manager não inicializado.", "warn"))
            else:
                servers = self._mcp_manager.list_servers()
                if not servers:
                    self._log_write(msg_system(
                        "nenhum servidor MCP configurado  ·  use mcp_add_server para adicionar",
                        "info",
                    ))
                else:
                    allowed_servers = self._agent_info.get("allowed_mcp_servers")  # None = todos
                    def _server_active(name: str) -> bool:
                        return allowed_servers is None or name in allowed_servers

                    t = Text()
                    t.append(f"\n  servidores MCP ({len(servers)})\n",
                             style=f"bold {P['accent']}")
                    for s in servers:
                        icon   = "●" if s["connected"] else "○"
                        color  = P["green"] if s["connected"] else P["crimson"]
                        active = _server_active(s["name"])
                        t.append(f"  {icon} ", style=f"bold {color}")
                        t.append(f"{s['name']}", style=f"bold {P['text']}")
                        t.append(f"  [{s['type']}]", style=f"dim {P['muted']}")
                        if active:
                            t.append(f"  ativo", style=f"bold {P['green']}")
                        else:
                            t.append(
                                f"  desativado ({self._agent_info['id']})",
                                style=f"dim {P['muted']}",
                            )
                        t.append(f"  {s['status']}\n", style=f"dim {P['silver']}")
                        if verbose and s.get("tools"):
                            for tool_name in s["tools"]:
                                if active:
                                    t.append(f"      • {tool_name}\n",
                                             style=f"dim {P['cyan']}")
                                else:
                                    t.append(f"      • {tool_name}  ✗\n",
                                             style=f"dim {P['muted']}")
                        if s.get("error"):
                            t.append(f"    ⚠ {s['error']}\n",
                                     style=f"dim {P['orange']}")
                    self._log_write(t)

        elif verb == "/sair":
            self._log_write(msg_system("encerrando…", "info"))
            if self._mcp_manager is not None:
                self._mcp_manager.disconnect_all()
            self.set_timer(0.4, self.exit)

        else:
            self._log_write(msg_system(
                f"comando desconhecido: '{verb}'.  /ajuda lista os comandos.", "warn"))

    @work(thread=True)
    def _run_source(self, caminho: str, eh_global: bool, log: RichLog) -> None:
        """Indexa um arquivo ou URL em background."""
        from pathlib import Path as _Path
        aid = self._agent_info.get("id", self.current_agent)

        if eh_global:
            sid = "_shared"
        else:
            if self._session_id is None:
                # cria sessão automaticamente se não existir
                if self._store:
                    from datetime import datetime as _dt
                    new_id = self._store.new_session(
                        agent_id=aid,
                        title=f"sessão {_dt.now().strftime('%d/%m %H:%M')}",
                    )
                    self._session_id = new_id
                    self.call_from_thread(
                        self._log_write,
                        msg_system(f"sessão criada (id={new_id})", "info"),
                    )
            sid = str(self._session_id) if self._session_id else "_shared"

        escopo = "compartilhada" if eh_global else f"sessão {sid}"
        eh_url = caminho.startswith(("http://", "https://"))

        self.call_from_thread(
            self._log_write,
            msg_system(f"{'baixando e ' if eh_url else ''}indexando '{caminho}'…", "info"),
        )

        try:
            if eh_url:
                from knowledge.ingest_url import ingest_url
                source_id = ingest_url(url=caminho, agent_id=aid,
                                       session_id=sid, verbose=False)
            else:
                from knowledge.ingest import ingest
                source_id = ingest(filepath=caminho, agent_id=aid,
                                   session_id=sid, verbose=False)

            self.call_from_thread(
                self._log_write,
                msg_system(
                    f"{'URL' if eh_url else 'fonte'} indexada "
                    f"(id={source_id} · {escopo})", "ok"
                ),
            )
        except FileNotFoundError:
            self.call_from_thread(
                self._log_write,
                msg_system(f"arquivo não encontrado: '{caminho}'", "err"),
            )
        except (ValueError, RuntimeError) as e:
            self.call_from_thread(
                self._log_write,
                msg_system(f"erro: {e}", "err"),
            )
        except Exception as e:
            self.call_from_thread(
                self._log_write,
                msg_system(f"erro ao indexar: {e}", "err"),
            )

    def _refresh_skill_commands(self) -> None:
        """Popula COMMANDS com as skills disponíveis em skills/ dinamicamente."""
        from pathlib import Path
        # remove entradas de skill antigas para não duplicar
        global COMMANDS
        COMMANDS[:] = [(c, d) for c, d in COMMANDS if not c.startswith("/skill ")]
        skills_dir = Path("skills")
        if skills_dir.exists():
            for sk in sorted(skills_dir.glob("*.md")):
                COMMANDS.append((f"/skill {sk.stem}", f"skill: {sk.stem}"))

    def _reload_tools(self, log: RichLog) -> None:
        """Recarrega tools do disco e atualiza self._tools / self._schema."""
        new_tools = load_tools()
        filtered  = filter_tools(new_tools, self._agent_info.get("allowed_tools"))
        if self.safe_mode:
            filtered = {k: v for k, v in filtered.items() if k not in self.UNSAFE_TOOLS}
        # reinjeta tools MCP para não perdê-las no reload
        if self._mcp_manager is not None:
            filtered.update(filter_mcp_tools(
                self._mcp_manager.all_tools(),
                self._agent_info.get("allowed_mcp_servers"),
            ))
            _mcp_admin_tools = ("mcp_add_server", "mcp_list_servers", "mcp_remove_server")
            for tn in _mcp_admin_tools:
                if tn in filtered:
                    filtered[tn]["fn"].__globals__["_manager"] = self._mcp_manager
        self._tools  = filtered
        self._schema = tools_schema(filtered)

    # ── workers ───────────────────────────────────────────────────────────────

    @work(thread=True)
    def _mcp_init_worker(self) -> None:
        """
        Conecta servidores MCP persistidos em background.

        Precisa rodar em thread separada (não no loop asyncio do Textual) porque
        SyncMCPClient usa loop.run_until_complete() internamente — o que falha se
        já houver um loop rodando na thread corrente (Python 3.10+).
        """
        mcp_results = self._mcp_manager.connect_all()
        if not mcp_results:
            return

        ok_count   = sum(1 for v in mcp_results.values() if v)
        fail_count = len(mcp_results) - ok_count

        if ok_count:
            # Atualiza tools e schema com o que foi conectado
            self._tools.update(filter_mcp_tools(
                self._mcp_manager.all_tools(),
                self._agent_info.get("allowed_mcp_servers"),
            ))
            self._schema = tools_schema(self._tools)

            # Garante injeção do manager nas tools admin (pode não ter ocorrido
            # em on_mount se a tool ainda não estava no registry)
            _mcp_admin_tools = ("mcp_add_server", "mcp_list_servers", "mcp_remove_server")
            for tn in _mcp_admin_tools:
                if tn in self._tools:
                    self._tools[tn]["fn"].__globals__["_manager"] = self._mcp_manager

            self.call_from_thread(
                self._log_write,
                msg_system(f"MCP: {ok_count} servidor(es) conectado(s)", "ok"),
            )

        if fail_count:
            failed_names = [k for k, v in mcp_results.items() if not v]
            self.call_from_thread(
                self._log_write,
                msg_system(
                    f"MCP: {fail_count} servidor(es) não conectaram: {failed_names}", "warn"
                ),
            )

    @work(thread=True)
    def _agent_turn(self, user_text: str, log: RichLog, max_steps: int = 6) -> None:
        """Worker real: chama run_agent com callbacks thread-safe."""
        self.call_from_thread(self._set_thinking, True)

        # zera contador do secundario para este turno
        try:
            import token_tracker
            token_tracker.reset()
        except Exception:
            pass

        # ── callbacks injetados no run_agent ──────────────────────────────────

        def on_step(step: int, label: str, content: str, status: str) -> None:
            if status in ("tool", "error", "parse_error"):
                # secondary_model: extrai skill= e mostra preview do prompt
                if label == "secondary_model" and "skill=" in content:
                    import re as _re
                    m = _re.search(r'skill=["\']?([^\s"\'},]+)', content)
                    skill_tag = f"  [skill: {m.group(1)}]" if m else ""
                    prompt_preview = content[:80].replace("\n", " ")
                    display_label = f"secondary_model{skill_tag}"
                    self.call_from_thread(log.write, msg_tool(display_label, prompt_preview, step))
                else:
                    self.call_from_thread(log.write, msg_tool(label, content, step))

        def on_done(message: str, steps: int, t_in: int, t_out: int) -> None:
            self.tok_in  += t_in
            self.tok_out += t_out
            self.call_from_thread(self._set_thinking, False)
            self.call_from_thread(
                log.write,
                msg_agent(self.current_agent, message, t_in, t_out),
            )
            self.call_from_thread(log.write, msg_sep())
            self.call_from_thread(log.write, Text())
            self.call_from_thread(
                self.query_one("#info-panel", InfoPanel).update_state,
                tok_in=t_in, tok_out=t_out, steps=steps,
            )
            self.call_from_thread(
                self.query_one("#top-bar", TopBar).update_state,
                tok_in=t_in, tok_out=t_out,
            )
            ts_str = datetime.now().strftime("%a %H:%M")
            self._history.append({"role": "agent", "content": message, "ts": ts_str})
            if self._session_id is not None:
                self._store.append_turn(self._session_id, "agent", message, ts_str)

        def on_limit(steps: int, t_in: int, t_out: int) -> None:
            self.tok_in  += t_in
            self.tok_out += t_out
            self.call_from_thread(self._set_thinking, False)
            self.call_from_thread(
                self.query_one("#info-panel", InfoPanel).update_state,
                tok_in=t_in, tok_out=t_out, steps=steps,
            )
            self.call_from_thread(
                self.query_one("#top-bar", TopBar).update_state,
                tok_in=t_in, tok_out=t_out,
            )
            self.call_from_thread(
                log.write,
                msg_system("⚠ limite de steps atingido sem conclusão.", "warn"),
            )
            self.call_from_thread(log.write, msg_sep())

        def on_error(kind: str, message: str) -> None:
            self.call_from_thread(self._set_thinking, False)
            label = "conexão" if kind == "connection" else "parse"
            self.call_from_thread(
                log.write,
                msg_system(f"erro de {label}: {message}", "err"),
            )

        # ── contexto: exclui o turno atual (já passado via user_text) ─────────
        context = self._history[:-1] if self._history else []

        result: AgentResult = run_agent(
            user_text,
            self._tools,
            self._schema,
            self.current_model,
            self._agent_info,
            history=context,
            session_id=str(self._session_id) if self._session_id else None,
            mcp_manager=self._mcp_manager,
            on_step=on_step,
            on_done=on_done,
            on_limit=on_limit,
            on_error=on_error,
            max_steps=max_steps,
        )

        # le tokens acumulados do modelo secundario neste turno
        try:
            import token_tracker
            t2_in, t2_out = token_tracker.get()
            if t2_in or t2_out:
                self.call_from_thread(
                    self.query_one("#info-panel", InfoPanel).update_state,
                    tok2_in=t2_in, tok2_out=t2_out,
                )
        except Exception:
            pass

        # reload de tools se o agente criou uma nova durante o turno
        if result.status == "done":
            new_tools = load_tools()
            filtered  = filter_tools(new_tools, self._agent_info.get("allowed_tools"))
            if self.safe_mode:
                filtered = {k: v for k, v in filtered.items() if k not in self.UNSAFE_TOOLS}
            # reinjeta tools MCP para não perdê-las no reload automático
            if self._mcp_manager is not None:
                filtered.update(filter_mcp_tools(
                    self._mcp_manager.all_tools(),
                    self._agent_info.get("allowed_mcp_servers"),
                ))
                _mcp_admin_tools = ("mcp_add_server", "mcp_list_servers", "mcp_remove_server")
                for tn in _mcp_admin_tools:
                    if tn in filtered:
                        filtered[tn]["fn"].__globals__["_manager"] = self._mcp_manager
            if set(filtered) != set(self._tools):
                self._tools  = filtered
                self._schema = tools_schema(filtered)
                self.call_from_thread(
                    log.write,
                    msg_system(f"{len(filtered)} tools ativas (recarregadas)", "ok"),
                )

        elif result.status == "needs_tool":
            p     = result.proposal or {}
            nome  = p.get("nome", "?")
            desc  = p.get("descricao", "?")
            params = ", ".join(
                f"{x['nome']} ({x.get('tipo','str')})"
                for x in p.get("parametros", [])
            ) or "nenhum"
            t = Text()
            t.append("\n  ⚡ auto tool — proposta\n", style=f"bold {P['gold']}")
            t.append(f"  nome:   {nome}\n",           style=P["text"])
            t.append(f"  o que:  {desc}\n",           style=P["silver"])
            t.append(f"  params: {params}\n",         style=P["silver"])
            t.append(
                "\n  responda 'criar tool' para confirmar.\n",
                style=f"dim {P['muted']}",
            )
            self.call_from_thread(self._set_thinking, False)
            self.call_from_thread(log.write, t)
            self.call_from_thread(log.write, msg_sep())

    def _set_thinking(self, active: bool) -> None:
        w = self.query_one("#thinking")
        if active: w.add_class("active")
        else:      w.remove_class("active")

    # ── actions ───────────────────────────────────────────────────────────────

    def action_toggle_select(self) -> None:
        """Abre modal de cópia com o conteúdo do chat."""
        self.push_screen(CopyModal(list(self._log_lines)))

    def action_edit_pill(self) -> None:
        """Ctrl+E — abre o editor do paste pill sem precisar clicar nele."""
        if self._paste_pill is not None:
            self._open_paste_editor(self._paste_pill)

    def action_quit(self) -> None:
        if self._mcp_manager is not None:
            self._mcp_manager.disconnect_all()
        self.exit()
    def action_clear_chat(self)  -> None: self.query_one("#chat-log", RichLog).clear()
    def action_focus_input(self) -> None: self.query_one("#input-box", CielInput).focus()

    def action_new_session(self) -> None:
        self._cmd("/novo", self.query_one("#chat-log", RichLog))

    def action_save_session(self) -> None:
        self._cmd("/history salvar", self.query_one("#chat-log", RichLog))

    def action_toggle_sidebar(self) -> None:
        sb = self.query_one("#sidebar", Sidebar)
        if self._sidebar_pinned is None:
            # primeira vez: fixa no estado oposto ao atual
            self._sidebar_pinned = not sb.display
        else:
            # alterna; se chegou ao estado original do auto, volta ao auto
            self._sidebar_pinned = not self._sidebar_pinned
        sb.display = self._sidebar_pinned

    # F1–F4: dispara os modais diretamente pelo teclado
    def action_cmd_tool(self)   -> None: self._open_tool_modal()
    def action_cmd_task(self)   -> None: self._open_task_modal()
    def action_cmd_skill(self)  -> None: self._open_skill_modal()
    def action_cmd_agente(self) -> None: self._open_agent_modal()

    def action_focus_slash(self) -> None:
        """/ foca o input e pré-digita /"""
        inp = self.query_one("#input-box", CielInput)
        inp.focus()
        if not inp.value.startswith("/"):
            inp.value = "/"
            inp.cursor_position = len(inp.value)

    def action_cycle_focus(self) -> None:
        """Tab circula pelos painéis visíveis."""
        sb = self.query_one("#sidebar",    Sidebar)
        ip = self.query_one("#info-panel", InfoPanel)
        inp = self.query_one("#input-box", CielInput)

        # monta lista dos alvos visíveis
        targets = [inp]
        if sb.display:
            targets.append(self.query_one("#sessions-table", DataTable))
        if ip.display:
            targets.append(ip)

        # encontra posição atual e avança
        focused = self.focused
        try:
            idx = targets.index(focused)
        except ValueError:
            idx = -1
        next_widget = targets[(idx + 1) % len(targets)]
        next_widget.focus()


if __name__ == "__main__":
    CielTUI().run()