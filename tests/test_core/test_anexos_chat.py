"""
tests/test_core/test_anexos_chat.py

Anexos do chat: bloco no prompt (prévia + caminho), parsing da bolha do
usuário e rota de upload. O arquivo completo nunca entra no contexto.
"""

import io

import pytest

import uploads


@pytest.fixture
def amb(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(uploads, "PASTA", tmp_path / "uploads")
    monkeypatch.setattr(uploads, "INDICE", tmp_path / "uploads" / "uploads.json")
    monkeypatch.setattr(uploads, "ROOT", tmp_path)
    monkeypatch.setattr(server, "_is_authenticated", lambda: True)
    server.app.config.update(TESTING=True)
    return server, server.app.test_client()


class TestBloco:
    def test_previa_e_caminho_sem_conteudo_inteiro(self, amb):
        servidor, _ = amb
        info = uploads.salvar("notas.md", "x" * 5_000)

        texto, anexos = servidor._aplicar_anexos("resuma", [info["id"]])

        assert anexos[0]["id"] == info["id"]
        assert '<arquivo nome="notas.md">' in texto
        assert "[anexo salvo em uploads/" in texto
        assert "x" * 2_000 in texto
        assert "x" * 2_001 not in texto          # só a prévia, não o arquivo
        assert "read_file" in texto
        assert "secondary_model(files=" in texto

    def test_separar_arquivo_volta_so_a_mensagem(self, amb):
        servidor, _ = amb
        info = uploads.salvar("notas.md", "conteudo")

        texto, _ = servidor._aplicar_anexos("resuma", [info["id"]])
        mensagem, nome = servidor._separar_arquivo_injetado(texto)

        assert mensagem == "resuma"
        assert nome == "notas.md"

    def test_id_desconhecido_e_ignorado(self, amb):
        servidor, _ = amb

        texto, anexos = servidor._aplicar_anexos("oi", ["nao-existe"])

        assert texto == "oi"
        assert anexos == []

    def test_limite_de_anexos_por_mensagem(self, amb):
        servidor, _ = amb
        ids = [uploads.salvar(f"a{i}.txt", f"c{i}")["id"] for i in range(7)]

        _, anexos = servidor._aplicar_anexos("oi", ids)

        assert len(anexos) == uploads.MAX_POR_MENSAGEM


class TestRotaUpload:
    def test_salva_e_devolve_previa(self, amb):
        _, cliente = amb

        r = cliente.post("/api/file/upload", data={
            "file": (io.BytesIO(b"conteudo do arquivo"), "notas.txt"),
        }, content_type="multipart/form-data")

        dados = r.get_json()
        assert r.status_code == 200
        assert dados["nome"] == "notas.txt"
        assert dados["previa"] == "conteudo do arquivo"
        assert dados["chars"] == len("conteudo do arquivo")
        assert uploads.obter(dados["id"]) is not None

    def test_binario_devolve_400(self, amb):
        _, cliente = amb

        r = cliente.post("/api/file/upload", data={
            "file": (io.BytesIO(b"\x00\x01\x02"), "bin.txt"),
        }, content_type="multipart/form-data")

        assert r.status_code == 400
        assert "binário" in r.get_json()["error"]

    def test_exige_login(self, amb, monkeypatch):
        servidor, cliente = amb
        monkeypatch.setattr(servidor, "_is_authenticated", lambda: False)

        r = cliente.post("/api/file/upload", data={
            "file": (io.BytesIO(b"oi"), "a.txt"),
        }, content_type="multipart/form-data")

        assert r.status_code == 401

    def test_sem_arquivo_400(self, amb):
        _, cliente = amb

        assert cliente.post("/api/file/upload", data={},
                            content_type="multipart/form-data").status_code == 400
