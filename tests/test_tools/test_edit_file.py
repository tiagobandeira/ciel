"""Testes da tool edit_file."""

from tools.edit_file import run as edit_file


def test_substitui_uma_ocorrencia(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("alpha beta alpha", encoding="utf-8")

    result = edit_file(str(p), "alpha", "gamma")

    assert "1 substituída" in result
    assert p.read_text(encoding="utf-8") == "gamma beta alpha"


def test_substitui_todas_com_count_zero(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("alpha beta alpha", encoding="utf-8")

    edit_file(str(p), "alpha", "gamma", count=0)

    assert p.read_text(encoding="utf-8") == "gamma beta gamma"


def test_trecho_nao_encontrado(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("abc", encoding="utf-8")

    result = edit_file(str(p), "zzz", "x")

    assert "não encontrado" in result
    assert p.read_text(encoding="utf-8") == "abc"


def test_arquivo_inexistente(tmp_path):
    result = edit_file(str(tmp_path / "nao_existe.txt"), "a", "b")
    assert "não encontrado" in result


def test_old_vazio(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("abc", encoding="utf-8")
    assert "não pode ser vazio" in edit_file(str(p), "", "x")


def test_metadata_de_permissao():
    from tools_registry import load_tools

    tools = load_tools()
    assert "edit_file" in tools
    assert tools["edit_file"]["permissions"] == {"path": "write"}
