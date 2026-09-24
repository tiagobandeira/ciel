"""
tests/test_core/test_task_guard_extended.py

Extensão do test_task_guard.py — cobre find_tasks (cli.py):
busca parcial, case-insensitive, match exato com prioridade,
diretório inexistente e múltiplos resultados ordenados.
"""

import pytest
from pathlib import Path

from cli import find_tasks


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tasks_dir(tmp_path):
    """Cria um diretório temporário com tasks .md de teste."""
    d = tmp_path / "tasks"
    d.mkdir()
    for name in [
        "noticias_do_dia.md",
        "resumo_semanal.md",
        "resumo_mensal.md",
        "backup_dados.md",
    ]:
        (d / name).write_text(f"# {name}", encoding="utf-8")
    return d


# ── busca parcial ─────────────────────────────────────────────────────────────

class TestFindTasksPartial:
    def test_busca_parcial_retorna_matches(self, tasks_dir):
        results = find_tasks("resumo", tasks_dir)
        nomes = [p.stem for p in results]
        assert "resumo_semanal" in nomes
        assert "resumo_mensal" in nomes

    def test_busca_parcial_nao_retorna_outros(self, tasks_dir):
        results = find_tasks("resumo", tasks_dir)
        nomes = [p.stem for p in results]
        assert "noticias_do_dia" not in nomes
        assert "backup_dados" not in nomes

    def test_query_vazio_retorna_todos(self, tasks_dir):
        # query vazio ("") é substring de tudo — retorna todas as tasks
        results = find_tasks("", tasks_dir)
        assert len(results) == 4


# ── case-insensitive ──────────────────────────────────────────────────────────

class TestFindTasksCaseInsensitive:
    def test_uppercase_encontra_task(self, tasks_dir):
        results = find_tasks("BACKUP", tasks_dir)
        assert any(p.stem == "backup_dados" for p in results)

    def test_mixed_case_encontra_task(self, tasks_dir):
        results = find_tasks("Noticias", tasks_dir)
        assert any(p.stem == "noticias_do_dia" for p in results)

    def test_case_nao_afeta_contagem(self, tasks_dir):
        lower = find_tasks("resumo", tasks_dir)
        upper = find_tasks("RESUMO", tasks_dir)
        assert len(lower) == len(upper)


# ── match exato tem prioridade ────────────────────────────────────────────────

class TestFindTasksExactFirst:
    def test_match_exato_vem_primeiro(self, tasks_dir):
        # "resumo_semanal" contém "resumo", mas "resumo_semanal" é match exato
        results = find_tasks("resumo_semanal", tasks_dir)
        assert results[0].stem == "resumo_semanal"

    def test_match_exato_unico_resultado(self, tasks_dir):
        results = find_tasks("backup_dados", tasks_dir)
        assert len(results) == 1
        assert results[0].stem == "backup_dados"

    def test_parcial_sem_exato_retorna_varios(self, tasks_dir):
        results = find_tasks("resumo", tasks_dir)
        # nenhum stem é exatamente "resumo", então os dois parciais voltam
        stems = [p.stem for p in results]
        assert "resumo_mensal" in stems
        assert "resumo_semanal" in stems


# ── diretório inexistente ─────────────────────────────────────────────────────

class TestFindTasksMissingDir:
    def test_dir_inexistente_retorna_lista_vazia(self, tmp_path):
        resultado = find_tasks("qualquer", tmp_path / "nao_existe")
        assert resultado == []

    def test_dir_inexistente_nao_lanca_excecao(self, tmp_path):
        # garante que não explode com FileNotFoundError
        try:
            find_tasks("x", tmp_path / "fantasma")
        except Exception as e:
            pytest.fail(f"find_tasks lançou exceção inesperada: {e}")


# ── múltiplos resultados e ordenação ─────────────────────────────────────────

class TestFindTasksOrdering:
    def test_parciais_ordenados_alfabeticamente(self, tasks_dir):
        results = find_tasks("resumo", tasks_dir)
        stems = [p.stem for p in results]
        assert stems == sorted(stems)

    def test_retorna_pathlib_path(self, tasks_dir):
        results = find_tasks("backup", tasks_dir)
        assert all(isinstance(p, Path) for p in results)

    def test_apenas_arquivos_md(self, tasks_dir):
        # cria um .txt que não deve aparecer
        (tasks_dir / "resumo_anual.txt").write_text("nao eh md")
        results = find_tasks("resumo", tasks_dir)
        assert all(p.suffix == ".md" for p in results)

    def test_query_com_espaco_vira_hifen(self, tmp_path):
        # "noticias do dia" → busca por "noticias-do-dia"
        # só bate em arquivos cujo stem contenha literalmente "noticias-do-dia"
        d = tmp_path / "tasks_hifen"
        d.mkdir()
        (d / "noticias-do-dia.md").write_text("# com hifen")
        (d / "noticias_do_dia.md").write_text("# com underscore")
        results = find_tasks("noticias do dia", d)
        stems = [p.stem for p in results]
        assert "noticias-do-dia" in stems
        assert "noticias_do_dia" not in stems  # underscore não casa com hifen
