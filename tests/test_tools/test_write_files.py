"""Testes da tool write_files (lote atômico)."""

from tools.write_files import run as write_files


def test_escreve_varios_arquivos(tmp_path):
    result = write_files(str(tmp_path), [
        {"path": "a.txt", "content": "A"},
        {"path": "sub/b.txt", "content": "B"},
    ])

    assert "2 arquivo(s)" in result
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "A"
    assert (tmp_path / "sub/b.txt").read_text(encoding="utf-8") == "B"


def test_preserva_existente_quando_overwrite_false(tmp_path):
    (tmp_path / "a.txt").write_text("antigo", encoding="utf-8")

    result = write_files(str(tmp_path), [
        {"path": "a.txt", "content": "novo"},
        {"path": "b.txt", "content": "B"},
    ], overwrite=False)

    assert "1 preservado" in result
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "antigo"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "B"


def test_rejeita_path_traversal(tmp_path):
    result = write_files(str(tmp_path), [{"path": "../fora.txt", "content": "x"}])
    assert "inválido" in result
    assert not (tmp_path.parent / "fora.txt").exists()


def test_rejeita_absoluto(tmp_path):
    result = write_files(str(tmp_path), [{"path": str(tmp_path / "x.txt"), "content": "x"}])
    assert "inválido" in result


def test_rejeita_duplicado(tmp_path):
    result = write_files(str(tmp_path), [
        {"path": "a.txt", "content": "1"},
        {"path": "a.txt", "content": "2"},
    ])
    assert "duplicado" in result


def test_rollback_em_falha(tmp_path, monkeypatch):
    (tmp_path / "existente.txt").write_text("original", encoding="utf-8")
    original_write = type(tmp_path).write_text

    def falha(self, *args, **kwargs):
        if self.name == "b.txt":
            raise OSError("disco cheio")
        return original_write(self, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "write_text", falha)

    result = write_files(str(tmp_path), [
        {"path": "existente.txt", "content": "alterado"},
        {"path": "b.txt", "content": "B"},
    ])

    assert "revertidas" in result
    assert (tmp_path / "existente.txt").read_text(encoding="utf-8") == "original"
    assert not (tmp_path / "b.txt").exists()


def test_metadata_de_permissao():
    from tools_registry import load_tools

    tools = load_tools()
    assert "write_files" in tools
    assert tools["write_files"]["permissions"] == {"base": "write"}
