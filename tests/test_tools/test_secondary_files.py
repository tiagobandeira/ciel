"""
tests/test_tools/test_secondary_files.py

`files` do secondary_model: extração por tipo (PDF/texto), orçamento de
chars e avisos inline. O caminho do anexo do chat chega aqui sem passar pelo
orquestrador.
"""

import sys
import types

from tools import secondary_model as sm


class TestInject:
    def test_texto_entra_no_prompt(self, tmp_path):
        arq = tmp_path / "notas.md"
        arq.write_text("# título\nconteúdo", encoding="utf-8")

        saida = sm._inject_files("Explique", [str(arq)])

        assert "Explique" in saida
        assert "conteúdo" in saida
        assert "texto," in saida

    def test_orcamento_trunca_e_avisa(self, tmp_path):
        arq = tmp_path / "a.txt"
        arq.write_text("x" * 100, encoding="utf-8")

        saida = sm._inject_files("p", [str(arq)], max_chars=10)

        assert "exibindo 10 de 100" in saida
        assert "x" * 10 in saida
        assert "x" * 11 not in saida

    def test_inexistente_nao_aborta(self, tmp_path):
        saida = sm._inject_files("p", [str(tmp_path / "nao.txt")])

        assert "não encontrado" in saida
        assert "p" in saida

    def test_pdf_extrai_texto(self, tmp_path, monkeypatch):
        class Pagina:
            def extract_text(self):
                return "teoria matemática"

        class Leitor:
            def __init__(self, caminho):
                self.pages = [Pagina(), Pagina()]

        monkeypatch.setitem(sys.modules, "PyPDF2",
                            types.SimpleNamespace(PdfReader=Leitor))
        arq = tmp_path / "artigo.pdf"
        arq.write_bytes(b"%PDF-1.4 fake")

        saida = sm._inject_files("p", [str(arq)])

        assert "teoria matemática" in saida
        assert "pdf, 2 páginas" in saida

    def test_pdf_sem_texto_vira_aviso(self, tmp_path, monkeypatch):
        class Pagina:
            def extract_text(self):
                return ""

        class Leitor:
            def __init__(self, caminho):
                self.pages = [Pagina()]

        monkeypatch.setitem(sys.modules, "PyPDF2",
                            types.SimpleNamespace(PdfReader=Leitor))
        arq = tmp_path / "scan.pdf"
        arq.write_bytes(b"%PDF-1.4 fake")

        saida = sm._inject_files("p", [str(arq)])

        assert "erro ao ler" in saida
        assert "sem texto" in saida

    def test_sem_files_devolve_prompt(self):
        assert sm._inject_files("p", []) == "p"
