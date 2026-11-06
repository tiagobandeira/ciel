"""
tests/test_core/test_uploads.py

Anexos do chat: gravação em data/user/uploads, extração de texto (PDF/DOCX/
texto), prévia de 2k, índice e limpeza (sessão e órfãos).
"""

import sys
import types

import pytest

import uploads


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "PASTA", tmp_path / "uploads")
    monkeypatch.setattr(uploads, "INDICE", tmp_path / "uploads" / "uploads.json")
    monkeypatch.setattr(uploads, "ROOT", tmp_path)
    return tmp_path / "uploads"


def _pdf_falso(monkeypatch, paginas):
    class Pagina:
        def __init__(self, texto):
            self._texto = texto

        def extract_text(self):
            return self._texto

    class Leitor:
        def __init__(self, stream):
            self.pages = [Pagina(t) for t in paginas]

    monkeypatch.setitem(sys.modules, "PyPDF2", types.SimpleNamespace(PdfReader=Leitor))


class TestSalvarTexto:
    def test_texto_gera_previa_e_caminho(self, pasta):
        info = uploads.salvar("notas.md", "# título\nconteúdo", sessao=7)

        assert info["tipo"] == "md"
        assert info["nome"] == "notas.md"
        assert info["chars"] == len("# título\nconteúdo")
        assert info["previa"].startswith("# título")
        assert info["sessao"] == "7"
        assert (pasta / info["id"] / "notas.md").exists()
        assert uploads.obter(info["id"])["nome"] == "notas.md"

    def test_previa_limita_a_2000(self, pasta):
        info = uploads.salvar("grande.txt", "x" * 5_000)

        assert len(info["previa"]) == uploads.PREVIA_CHARS
        assert info["chars"] == 5_000

    def test_nome_e_sanitizado(self, pasta):
        info = uploads.salvar("../../etc/passwd", "a")

        assert "/" not in info["nome"] and "\\" not in info["nome"]
        assert info["nome"]

    def test_vazio_falha(self, pasta):
        with pytest.raises(ValueError):
            uploads.salvar("vazio.txt", b"")

    def test_binario_como_texto_falha(self, pasta):
        with pytest.raises(ValueError):
            uploads.salvar("bin.txt", b"\x00\x01\x02\x03")


class TestSalvarPdf:
    def test_pdf_extrai_texto_e_paginas(self, pasta, monkeypatch):
        _pdf_falso(monkeypatch, ["teoria matemática", "segunda página"])

        info = uploads.salvar("artigo.pdf", b"%PDF-1.4 fake")

        assert info["tipo"] == "pdf"
        assert info["paginas"] == 2
        assert "teoria matemática" in info["previa"]
        assert "segunda página" in info["previa"]

    def test_pdf_sem_texto_falha(self, pasta, monkeypatch):
        _pdf_falso(monkeypatch, ["", "  "])

        with pytest.raises(ValueError, match="sem texto"):
            uploads.salvar("scan.pdf", b"%PDF-1.4 fake")


class TestLimpeza:
    def test_limpar_sessao_remove_so_a_dela(self, pasta):
        a = uploads.salvar("a.txt", "a", sessao=7)
        b = uploads.salvar("b.txt", "b", sessao=8)

        assert uploads.limpar_sessao(7) == 1

        assert uploads.obter(a["id"]) is None
        assert uploads.obter(b["id"]) is not None
        assert not (pasta / a["id"]).exists()
        assert (pasta / b["id"] / "b.txt").exists()

    def test_orfaos_antigos_somem(self, pasta):
        info = uploads.salvar("orfa.txt", "x")
        indice = uploads._ler_indice()
        indice[info["id"]]["criado"] = "2020-01-01T00:00:00"
        uploads._gravar_indice(indice)

        assert uploads.limpar_orfaos(dias=7) == 1
        assert uploads.obter(info["id"]) is None

    def test_orfaos_recentes_ficam(self, pasta):
        info = uploads.salvar("novo.txt", "x")

        assert uploads.limpar_orfaos(dias=7) == 0
        assert uploads.obter(info["id"]) is not None

    def test_vincular_marca_sessao(self, pasta):
        info = uploads.salvar("a.txt", "a")

        uploads.vincular(info["id"], 42)

        assert uploads.obter(info["id"])["sessao"] == "42"
