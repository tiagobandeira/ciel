"""
tests/test_tools/test_list_directory.py

Cobre list_directory.py:
  - listagem básica, filtro por extensão, recursiva
  - diretório inexistente, path que não é diretório
  - alias 'path' via kwargs
  - arquivos ocultos, diretório vazio
"""

import pytest
from pathlib import Path

from tools.list_directory import run as list_directory


# ── fixture base ──────────────────────────────────────────────────────────────

@pytest.fixture
def dir_com_arquivos(tmp_path):
    """Cria estrutura de arquivos para os testes."""
    (tmp_path / "arquivo1.py").write_text("# py")
    (tmp_path / "arquivo2.py").write_text("# py2")
    (tmp_path / "readme.md").write_text("# doc")
    (tmp_path / "dados.txt").write_text("dados")
    (tmp_path / ".oculto").write_text("hidden")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "sub_arquivo.py").write_text("# sub")
    return tmp_path


# ── listagem básica ───────────────────────────────────────────────────────────

class TestListDirectoryBasic:
    def test_lista_arquivos_existentes(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos))
        assert "arquivo1.py" in result
        assert "arquivo2.py" in result
        assert "readme.md" in result

    def test_distingue_arquivo_de_pasta(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos))
        assert "[arq]" in result
        assert "[dir]" in result

    def test_exibe_total_de_itens(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos))
        # deve mencionar o número de itens no cabeçalho
        assert "item" in result.lower()

    def test_diretorio_atual_padrao(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "local.txt").write_text("x")
        result = list_directory()
        assert "local.txt" in result


# ── filtro por extensão ───────────────────────────────────────────────────────

class TestListDirectoryFilter:
    def test_filtra_por_extensao_py(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos), ext=".py")
        assert "arquivo1.py" in result
        assert "arquivo2.py" in result
        assert "readme.md" not in result
        assert "dados.txt" not in result

    def test_filtra_por_extensao_sem_ponto(self, dir_com_arquivos):
        # aceita "py" sem o ponto
        result = list_directory(str(dir_com_arquivos), ext="py")
        assert "arquivo1.py" in result
        assert "readme.md" not in result

    def test_extensao_inexistente_retorna_mensagem(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos), ext=".xyz")
        assert "Nenhum" in result or "nenhum" in result.lower()

    def test_cabecalho_menciona_extensao(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos), ext=".md")
        assert ".md" in result or "ext" in result


# ── listagem recursiva ────────────────────────────────────────────────────────

class TestListDirectoryRecursive:
    def test_recursivo_inclui_subdiretorio(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos), recursive=True)
        assert "sub_arquivo.py" in result

    def test_nao_recursivo_nao_inclui_subdir(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos), recursive=False)
        # o arquivo dentro do subdir não deve aparecer diretamente
        assert "sub_arquivo.py" not in result

    def test_recursivo_menciona_flag(self, dir_com_arquivos):
        result = list_directory(str(dir_com_arquivos), recursive=True)
        assert "recursivo" in result.lower()


# ── erros graciosos ───────────────────────────────────────────────────────────

class TestListDirectoryErrors:
    def test_diretorio_inexistente_retorna_erro(self, tmp_path):
        result = list_directory(str(tmp_path / "fantasma"))
        assert "Erro" in result
        assert "não encontrado" in result

    def test_path_e_arquivo_retorna_erro(self, tmp_path):
        f = tmp_path / "arquivo.txt"
        f.write_text("x")
        result = list_directory(str(f))
        assert "Erro" in result
        assert "diretório" in result.lower() or "não é" in result

    def test_diretorio_vazio_retorna_mensagem(self, tmp_path):
        vazio = tmp_path / "vazio"
        vazio.mkdir()
        result = list_directory(str(vazio))
        assert "Nenhum" in result or "nenhum" in result.lower()


# ── alias 'path' via kwargs ───────────────────────────────────────────────────

class TestListDirectoryPathAlias:
    def test_alias_path_funciona(self, dir_com_arquivos):
        # passa 'path' em vez de 'directory'
        result = list_directory(path=str(dir_com_arquivos))
        assert "arquivo1.py" in result

    def test_directory_tem_prioridade_sobre_path(self, dir_com_arquivos, tmp_path):
        outro = tmp_path / "outro"
        outro.mkdir()
        (outro / "exclusivo.txt").write_text("x")
        # quando directory != ".", o path é ignorado
        result = list_directory(str(dir_com_arquivos), path=str(outro))
        assert "arquivo1.py" in result
        assert "exclusivo.txt" not in result
