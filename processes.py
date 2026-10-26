"""
processes.py — processos nativos do Ciel.

Um processo é uma receita de alto nível (app_web, landing_page, jogo_web…)
que aponta para um fluxo do motor multitask. O usuário fala em linguagem
natural; o modo build escolhe o processo e o motor executa com spec/checks.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Process:
    id: str
    titulo: str
    descricao: str
    flow: str
    keywords: tuple[str, ...] = field(default_factory=tuple)
    precisa_spec: bool = False


PROCESSES: tuple[Process, ...] = (
    Process(
        id="web_projeto",
        titulo="Projeto web com entrevista",
        descricao="app web com briefing entrevistado, spec, implementação e preview",
        flow="web_projeto",
        keywords=("entrevista", "briefing", "projeto web", "requisitos"),
        precisa_spec=True,
    ),
    Process(
        id="app_web",
        titulo="App web",
        descricao="app local com interface, persistência e critérios de aceite",
        flow="app_web",
        keywords=(
            "app", "aplicativo", "editor", "notas", "notion",
            "todo", "kanban", "crud",
        ),
        precisa_spec=True,
    ),
    Process(
        id="landing_page",
        titulo="Landing page",
        descricao="página de apresentação responsiva com hero, features e CTA",
        flow="landing_page",
        keywords=("landing", "pagina", "site", "website", "hero", "cta"),
    ),
    Process(
        id="jogo_web",
        titulo="Jogo web",
        descricao="jogo simples em HTML/canvas/JavaScript",
        flow="jogo_snake",
        keywords=("jogo", "game", "cobrinha", "snake", "canvas"),
    ),
    Process(
        id="gerar_testes",
        titulo="Gerar testes",
        descricao="escreve e executa testes para um módulo, sem alterar o código-fonte",
        flow="gerar_testes",
        keywords=("gerar testes", "criar testes", "escrever testes", "pytest", "cobertura"),
    ),
    Process(
        id="auditar_repo",
        titulo="Auditar repositório",
        descricao="mapeia estrutura, riscos e próximos passos sem alterar o código",
        flow="auditar_repo",
        keywords=("auditar", "auditoria", "seguranca", "code review", "revisar repo", "riscos"),
    ),
    Process(
        id="analise_dados",
        titulo="Análise de dados",
        descricao="perfila, limpa e analisa um dataset com relatório reproduzível",
        flow="analise_dados",
        keywords=("analise de dados", "análise de dados", "dataset", "csv", "planilha", "pandas", "estatistica"),
    ),
    Process(
        id="artigo_matematica",
        titulo="Artigo de matemática",
        descricao="artigo em Markdown com definições, teoremas e referências",
        flow="artigo_matematica",
        keywords=("artigo", "paper", "cientifico", "matematic"),
    ),
    Process(
        id="notebook_matematica",
        titulo="Notebook",
        descricao="notebook Jupyter sobre um tema matemático",
        flow="notebook_matematica",
        keywords=("notebook", "colab", "jupyter"),
    ),
    Process(
        id="corrigir_bug",
        titulo="Corrigir bug",
        descricao="corrige uma falha reproduzível com correção mínima e check",
        flow="corrigir_bug",
        keywords=("bug", "corrigir", "corrija", "falha", "erro", "teste falhando"),
    ),
)


def list_processes() -> list[Process]:
    return list(PROCESSES)


def get_process(name: str) -> Process | None:
    key = _fold(name)
    for process in PROCESSES:
        if key in (_fold(process.id), _fold(process.titulo)):
            return process
    return None


def _fold(text: str) -> str:
    """Minúsculas e sem acentos, para casar 'análise' com 'analise'."""
    raw = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in raw if not unicodedata.combining(ch))


def detect_process(text: str) -> Process | None:
    """Heurística simples de intenção; o build pode confirmar com o usuário."""
    folded = _fold(text)
    best: Process | None = None
    best_hits = 0
    for process in PROCESSES:
        hits = sum(1 for kw in process.keywords if _fold(kw) in folded)
        if hits > best_hits:
            best = process
            best_hits = hits
    return best
