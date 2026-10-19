"""tests/test_tools/test_create_directory.py"""

from pathlib import Path

from tools.create_directory import PERMISSIONS, run


def test_cria_pasta_simples(tmp_path):
    alvo = tmp_path / "projeto"
    result = run(str(alvo))
    assert alvo.is_dir()
    assert "criada" in result


def test_cria_pasta_aninhada(tmp_path):
    alvo = tmp_path / "a" / "b" / "c"
    result = run(str(alvo))
    assert alvo.is_dir()
    assert "criada" in result


def test_pasta_ja_existe(tmp_path):
    alvo = tmp_path / "existente"
    alvo.mkdir()
    result = run(str(alvo))
    assert "já existe" in result


def test_arquivo_no_caminho(tmp_path):
    alvo = tmp_path / "arquivo.txt"
    alvo.write_text("x", encoding="utf-8")
    result = run(str(alvo))
    assert "não é uma pasta" in result
    assert alvo.is_file()


def test_path_vazio():
    assert "vazio" in run("")


def test_declara_permissao_de_escrita():
    assert PERMISSIONS == {"path": "write"}
