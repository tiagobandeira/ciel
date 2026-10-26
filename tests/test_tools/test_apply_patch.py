"""Testes da tool apply_patch (atômica)."""

from tools.apply_patch import run as apply_patch


def test_aplica_multiplos_hunks(tmp_path):
    p = tmp_path / "app.js"
    p.write_text("const a = 1;\nconst b = 2;\n", encoding="utf-8")

    result = apply_patch(str(p), [
        {"old": "const a = 1;", "new": "const a = 10;"},
        {"old": "const b = 2;", "new": "const b = 20;"},
    ])

    assert "2 hunk(s)" in result
    assert p.read_text(encoding="utf-8") == "const a = 10;\nconst b = 20;\n"


def test_falha_e_nao_escreve_nada(tmp_path):
    p = tmp_path / "app.js"
    original = "const a = 1;\nconst b = 2;\n"
    p.write_text(original, encoding="utf-8")

    result = apply_patch(str(p), [
        {"old": "const a = 1;", "new": "const a = 10;"},
        {"old": "nao existe", "new": "x"},
    ])

    assert "hunk 2" in result
    assert "Nada foi escrito" in result
    assert p.read_text(encoding="utf-8") == original


def test_trecho_ambiguo_falha(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x\nx\n", encoding="utf-8")

    result = apply_patch(str(p), [{"old": "x", "new": "y"}])

    assert "2 ocorrência" in result
    assert p.read_text(encoding="utf-8") == "x\nx\n"


def test_hunk_com_old_vazio(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    assert "vazio" in apply_patch(str(p), [{"old": "", "new": "y"}])


def test_arquivo_inexistente(tmp_path):
    result = apply_patch(str(tmp_path / "nao_existe.txt"), [{"old": "a", "new": "b"}])
    assert "não encontrado" in result


def test_hunks_vazio(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    assert "não vazia" in apply_patch(str(p), [])


def test_metadata_de_permissao():
    from tools_registry import load_tools

    tools = load_tools()
    assert "apply_patch" in tools
    assert tools["apply_patch"]["permissions"] == {"path": "write"}
