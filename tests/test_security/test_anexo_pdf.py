"""
tests/test_security/test_anexo_pdf.py

Cobre o anexo de arquivo no chat:

  - anexo binário (PDF decodificado como texto) não entra no histórico
  - o bloco <arquivo> que o server injeta não reaparece inteiro na tela
  - /api/file/extrair devolve o texto do PDF (e falha com mensagem clara)
"""

import io

import pytest


@pytest.fixture
def amb(monkeypatch):
    """Server com login sempre válido; `state` fica None de propósito."""
    import server

    monkeypatch.setattr(server, "_is_authenticated", lambda: True)
    monkeypatch.setattr(server, "state", None)
    server.app.config.update(TESTING=True)
    return server, server.app.test_client()


def _pdf(nome="a.pdf", conteudo=b"%PDF-1.4 conteudo"):
    return {"file": (io.BytesIO(conteudo), nome)}


# ── heurística de binário ───────────────────────────────────────────────────

class TestPareceBinario:
    def test_pdf_decodificado_como_texto(self, amb):
        servidor, _ = amb
        assert servidor._parece_binario("texto\n\x00\x01\x02 resto") is True

    def test_texto_normal(self, amb):
        servidor, _ = amb
        assert servidor._parece_binario("linha um\nlinha dois\tcom tab") is False
        assert servidor._parece_binario("") is False


# ── bloco <arquivo> injetado ────────────────────────────────────────────────

class TestSepararArquivoInjetado:
    def test_so_bloco(self, amb):
        servidor, _ = amb
        texto, anexo = servidor._separar_arquivo_injetado(
            '<arquivo nome="a.pdf">\nconteudo\n</arquivo>'
        )
        assert texto == ""
        assert anexo == "a.pdf"

    def test_mensagem_mais_bloco(self, amb):
        servidor, _ = amb
        texto, anexo = servidor._separar_arquivo_injetado(
            'analise isso\n\n<arquivo nome="a.pdf">\nconteudo\ndo pdf\n</arquivo>\n'
        )
        assert texto == "analise isso"
        assert anexo == "a.pdf"

    def test_sem_anexo(self, amb):
        servidor, _ = amb
        assert servidor._separar_arquivo_injetado("só texto") == ("só texto", None)

    def test_turn_json_limpa_para_a_tela(self, amb):
        servidor, _ = amb
        turno = {
            "id": 1, "role": "user", "ts": "x", "trace": None,
            "content": 'oi\n\n<arquivo nome="a.pdf">\nbytes\n</arquivo>',
        }

        dados = servidor._turn_json(turno)

        assert dados["content"] == "oi"
        assert dados["arquivo"] == "a.pdf"


# ── /api/file/extrair ───────────────────────────────────────────────────────

class TestExtrairApi:
    def test_401_sem_login(self, amb, monkeypatch):
        servidor, cliente = amb
        monkeypatch.setattr(servidor, "_is_authenticated", lambda: False)

        assert cliente.post("/api/file/extrair", data=_pdf(),
                            content_type="multipart/form-data").status_code == 401

    def test_400_sem_arquivo(self, amb):
        _, cliente = amb

        r = cliente.post("/api/file/extrair", data={},
                         content_type="multipart/form-data")

        assert r.status_code == 400

    def test_415_extensao_nao_suportada(self, amb):
        _, cliente = amb

        r = cliente.post("/api/file/extrair", data=_pdf("a.txt"),
                         content_type="multipart/form-data")

        assert r.status_code == 415
        assert "não suportada" in r.get_json()["error"]

    def test_200_devolve_texto(self, amb, monkeypatch):
        servidor, cliente = amb
        monkeypatch.setattr(servidor, "_extrair_texto_pdf",
                            lambda dados, max_chars=12000: "texto do pdf")

        r = cliente.post("/api/file/extrair", data=_pdf(),
                         content_type="multipart/form-data")

        assert r.status_code == 200
        assert r.get_json()["texto"] == "texto do pdf"

    def test_422_pdf_sem_texto(self, amb, monkeypatch):
        servidor, cliente = amb
        monkeypatch.setattr(servidor, "_extrair_texto_pdf",
                            lambda dados, max_chars=12000: "   \n")

        r = cliente.post("/api/file/extrair", data=_pdf(),
                         content_type="multipart/form-data")

        assert r.status_code == 422
        assert "sem texto" in r.get_json()["error"]

    def test_422_pdf_corrompido(self, amb, monkeypatch):
        servidor, cliente = amb

        def explode(dados, max_chars=12000):
            raise RuntimeError("pdf corrompido")

        monkeypatch.setattr(servidor, "_extrair_texto_pdf", explode)

        r = cliente.post("/api/file/extrair", data=_pdf(),
                         content_type="multipart/form-data")

        assert r.status_code == 422
        assert "corrompido" in r.get_json()["error"]


# ── guarda no /api/chat ─────────────────────────────────────────────────────

class TestChatRecusaBinario:
    def test_binario_no_file_text_vira_400(self, amb):
        _, cliente = amb

        r = cliente.post("/api/chat", json={
            "message": "analise",
            "file_text": "\x00\x01\x02PDF-1.4 lixo binário",
        })

        assert r.status_code == 400
        assert "binário" in r.get_json()["error"]
