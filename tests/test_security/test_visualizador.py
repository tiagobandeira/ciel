"""
tests/test_security/test_visualizador.py

Cobre o visualizador de arquivos do site:

  - /preview/<path>  entrega inline, com MIME, só o que está em data/
  - /api/files       lista uma pasta de data/ (login obrigatório)
  - /api/preview_site  servidor estático do projeto (token, origem separada)
  - guardas          path traversal, dotfiles (data/user/.id_secret),
                     symlink para fora, request sem cookie
  - o que o turno gerou (retrato de data/user) e o que fica no histórico
"""

import json
import os
from pathlib import Path

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def amb(monkeypatch, tmp_path):
    """
    Server com ROOT/data redirecionados para tmp_path e login sempre válido.

    ROOT é lido em tempo de chamada nas rotas do visualizador, então trocar o
    global basta para os testes não dependerem do repositório real.
    """
    import server
    import preview_sites

    raiz = (tmp_path / "proj").resolve()
    data = raiz / "data"
    (data / "user" / "app").mkdir(parents=True)
    (data / "user" / "sources").mkdir(parents=True)

    monkeypatch.setattr(server, "ROOT", raiz)
    monkeypatch.setattr(server, "_PUBLIC_ROOT", data)
    monkeypatch.setattr(server, "_is_authenticated", lambda: True)
    server.app.config.update(TESTING=True)

    yield server, server.app.test_client(), raiz

    preview_sites.parar_todos()   # não deixa porta aberta entre testes


# ── /preview ──────────────────────────────────────────────────────────────────

class TestPreviewServe:
    def test_html_inline_com_mime_e_sem_attachment(self, amb):
        _, cliente, raiz = amb
        alvo = raiz / "data" / "user" / "app" / "index.html"
        alvo.write_text("<!doctype html><title>oi</title><link href='style.css'>", encoding="utf-8")

        r = cliente.get("/preview/data/user/app/index.html")

        assert r.status_code == 200
        assert r.mimetype == "text/html"
        assert r.data.startswith(b"<!doctype html")
        disposicao = r.headers.get("Content-Disposition", "")
        assert "attachment" not in disposicao
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["X-Content-Type-Options"] == "nosniff"

    def test_arquivo_irmao_resolve(self, amb):
        """É o que faz html + style.css + script.js gerados rodarem juntos."""
        _, cliente, raiz = amb
        pasta = raiz / "data" / "user" / "app"
        (pasta / "index.html").write_text("<link href='style.css'>", encoding="utf-8")
        (pasta / "style.css").write_text("body{background:#000}", encoding="utf-8")
        (pasta / "script.js").write_text("console.log(1)", encoding="utf-8")

        assert cliente.get("/preview/data/user/app/style.css").mimetype == "text/css"
        assert cliente.get("/preview/data/user/app/script.js").mimetype in (
            "text/javascript", "application/javascript",
        )

    def test_markdown_com_charset(self, amb):
        _, cliente, raiz = amb
        alvo = raiz / "data" / "user" / "tutorial.md"
        alvo.write_text("# olá", encoding="utf-8")

        r = cliente.get("/preview/data/user/tutorial.md")

        assert r.status_code == 200
        assert r.mimetype == "text/markdown"
        assert "charset=utf-8" in r.headers["Content-Type"]
        assert "olá" in r.get_data(as_text=True)

    def test_arquivo_inexistente_404(self, amb):
        _, cliente, _ = amb
        assert cliente.get("/preview/data/user/nao-existe.html").status_code == 404

    def test_exige_login(self, amb, monkeypatch):
        servidor, cliente, raiz = amb
        (raiz / "data" / "user" / "x.txt").write_text("x", encoding="utf-8")
        monkeypatch.setattr(servidor, "_is_authenticated", lambda: False)

        r = cliente.get("/preview/data/user/x.txt")

        assert r.status_code == 401
        assert "login" in r.get_data(as_text=True).lower()


class TestPreviewGuardas:
    def test_fora_de_data_negado(self, amb):
        servidor, cliente, raiz = amb
        (raiz / "ciel_config.json").write_text('{"api_key": "sk-segredo"}', encoding="utf-8")

        assert cliente.get("/preview/ciel_config.json").status_code == 404
        assert servidor._resolver_arquivo_publico("ciel_config.json") is None

    def test_traversal_com_pontos_negado(self, amb):
        servidor, _, raiz = amb
        (raiz / "fora.md").write_text("x", encoding="utf-8")

        assert servidor._resolver_arquivo_publico("data/../fora.md") is None

    def test_dotfile_negado(self, amb):
        """data/user/.id_secret é o segredo HMAC do bot — não pode sair daqui."""
        servidor, cliente, raiz = amb
        segredo = raiz / "data" / "user" / ".id_secret"
        segredo.write_text("cafebabe", encoding="utf-8")

        assert servidor._resolver_arquivo_publico("data/user/.id_secret") is None
        assert cliente.get("/preview/data/user/.id_secret").status_code == 404

    def test_symlink_para_fora_negado(self, amb):
        servidor, _, raiz = amb
        fora = raiz / "fora.txt"
        fora.write_text("segredo", encoding="utf-8")
        link = raiz / "data" / "user" / "link.txt"
        try:
            os.symlink(fora, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlink exige privilégio neste sistema")

        assert servidor._resolver_arquivo_publico("data/user/link.txt") is None

    def test_pasta_nao_e_arquivo(self, amb):
        servidor, _, _ = amb
        assert servidor._resolver_arquivo_publico("data/user/app") is None
        assert servidor._resolver_arquivo_publico("") is None


# ── /api/files ────────────────────────────────────────────────────────────────

class TestApiFiles:
    def test_lista_pasta(self, amb):
        _, cliente, raiz = amb
        (raiz / "data" / "user" / "app" / "index.html").write_text("x", encoding="utf-8")
        (raiz / "data" / "user" / "tutorial.md").write_text("# t", encoding="utf-8")
        (raiz / "data" / "user" / "planilha.xlsx").write_bytes(b"PK")
        (raiz / "data" / "user" / ".id_secret").write_text("x", encoding="utf-8")

        r = cliente.get("/api/files?path=data/user")
        dados = r.get_json()
        nomes = {i["name"]: i for i in dados["items"]}

        assert r.status_code == 200
        assert dados["path"] == "data/user"
        assert dados["parent"] == "data"
        assert nomes["app"]["dir"] is True
        assert nomes["tutorial.md"]["preview"] is True
        assert nomes["tutorial.md"]["size"] == 3
        assert nomes["planilha.xlsx"]["preview"] is False
        assert ".id_secret" not in nomes

    def test_pasta_padrao_e_data_user(self, amb):
        _, cliente, _ = amb
        assert cliente.get("/api/files").get_json()["path"] == "data/user"

    def test_data_user_ausente_cai_em_data(self, amb):
        """Instalação limpa: data/user só nasce no primeiro arquivo gerado."""
        import shutil

        _, cliente, raiz = amb
        shutil.rmtree(raiz / "data" / "user")

        dados = cliente.get("/api/files?path=data/user").get_json()

        assert dados["path"] == "data"

    def test_fora_de_data_403(self, amb):
        _, cliente, _ = amb
        assert cliente.get("/api/files?path=..").status_code == 403
        assert cliente.get("/api/files?path=server.py").status_code == 403

    def test_exige_login(self, amb, monkeypatch):
        servidor, cliente, _ = amb
        monkeypatch.setattr(servidor, "_is_authenticated", lambda: False)
        assert cliente.get("/api/files?path=data/user").status_code == 401

    def test_marca_pasta_com_site(self, amb):
        """Pasta com index.html ganha o atalho "abrir como site" no painel."""
        _, cliente, raiz = amb
        pasta = raiz / "data" / "user" / "comsite"
        pasta.mkdir()
        (pasta / "index.html").write_text("x", encoding="utf-8")

        dados = cliente.get("/api/files?path=data/user").get_json()
        por_nome = {i["name"]: i for i in dados["items"] if i["dir"]}

        assert por_nome["comsite"]["site"] is True
        assert por_nome["app"]["site"] is False
        assert cliente.get("/api/files?path=data/user/comsite").get_json()["site"] is True

    def test_raiz_de_data_sem_parent(self, amb):
        _, cliente, _ = amb
        dados = cliente.get("/api/files?path=data").get_json()
        assert dados["parent"] is None
        assert any(i["name"] == "user" and i["dir"] for i in dados["items"])


# ── caminho de fonte (upload cai em data/user/sources) ───────────────────────

class TestPreviewPathDaFonte:
    def test_arquivo_em_data(self, amb):
        servidor, _, raiz = amb
        arq = raiz / "data" / "user" / "sources" / "manual.md"
        arq.write_text("x", encoding="utf-8")

        assert servidor._preview_path_da_fonte(str(arq)) == "data/user/sources/manual.md"

    def test_arquivo_fora_de_data(self, amb):
        servidor, _, raiz = amb
        arq = raiz / "fora.md"
        arq.write_text("x", encoding="utf-8")

        assert servidor._preview_path_da_fonte(str(arq)) is None

    def test_inexistente_e_vazio(self, amb):
        servidor, _, raiz = amb
        assert servidor._preview_path_da_fonte(str(raiz / "data" / "user" / "sumiu.md")) is None
        assert servidor._preview_path_da_fonte("") is None


# ── o que o turno gerou (retrato de data/user) ───────────────────────────────

class TestArquivosDoTurno:
    def test_arquivo_novo_entra(self, amb):
        servidor, _, raiz = amb
        antes = servidor._foto_data()
        alvo = raiz / "data" / "user" / "tutorial.md"
        alvo.write_text("# oi", encoding="utf-8")

        entradas = servidor._arquivos_do_turno(antes, servidor._foto_data())

        assert [e["path"] for e in entradas] == ["data/user/tutorial.md"]
        assert entradas[0]["ext"] == "md"
        assert entradas[0]["size"] == 4
        assert entradas[0]["preview"] is True

    def test_arquivo_intocado_fica_fora(self, amb):
        servidor, _, raiz = amb
        alvo = raiz / "data" / "user" / "antigo.md"
        alvo.write_text("x", encoding="utf-8")
        os.utime(alvo, (1_000_000, 1_000_000))

        entradas = servidor._arquivos_do_turno(servidor._foto_data(), servidor._foto_data())

        assert entradas == []

    def test_sobrescrito_entra(self, amb):
        """write_files com overwrite=True muda o mtime: foi gerado agora."""
        servidor, _, raiz = amb
        alvo = raiz / "data" / "user" / "site" / "index.html"
        alvo.parent.mkdir(parents=True)
        alvo.write_text("<h1>antigo</h1>", encoding="utf-8")
        os.utime(alvo, (1_000_000, 1_000_000))
        antes = servidor._foto_data()

        alvo.write_text("<h1>novo</h1>", encoding="utf-8")
        entradas = servidor._arquivos_do_turno(antes, servidor._foto_data())

        assert [e["path"] for e in entradas] == ["data/user/site"]

    def test_projeto_vira_uma_entrada_de_pasta(self, amb):
        """
        O caso real: secondary_model grava data/user/calculadora numa chamada.
        Antes de a pasta existir não há o que fotografar — era por isso que o
        bloco "arquivo gerado" não aparecia para página html.
        """
        servidor, _, raiz = amb
        antes = servidor._foto_data()
        pasta = raiz / "data" / "user" / "calculadora"
        pasta.mkdir(parents=True)
        for nome in ("index.html", "style.css", "script.js"):
            (pasta / nome).write_text("x", encoding="utf-8")

        entradas = servidor._arquivos_do_turno(antes, servidor._foto_data())

        assert len(entradas) == 1
        entrada = entradas[0]
        assert entrada["path"] == "data/user/calculadora"
        assert entrada["dir"] is True
        assert entrada["entry"] == "index.html"
        assert entrada["n_files"] == 3

    def test_pasta_sem_index_vira_arquivos(self, amb):
        servidor, _, raiz = amb
        antes = servidor._foto_data()
        pasta = raiz / "data" / "user" / "notas"
        pasta.mkdir(parents=True)
        (pasta / "a.md").write_text("a", encoding="utf-8")
        (pasta / "b.txt").write_text("b", encoding="utf-8")

        entradas = servidor._arquivos_do_turno(antes, servidor._foto_data())

        assert sorted(e["path"] for e in entradas) == [
            "data/user/notas/a.md",
            "data/user/notas/b.txt",
        ]

    def test_editar_css_de_projeto_existente_vira_site(self, amb):
        """Mexer só no style.css de um projeto não deve virar chip de "style.css"."""
        servidor, _, raiz = amb
        pasta = raiz / "data" / "user" / "site"
        pasta.mkdir(parents=True)
        (pasta / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
        css = pasta / "style.css"
        css.write_text("body{}", encoding="utf-8")
        os.utime(css, (1_000_000, 1_000_000))

        antes = servidor._foto_data()
        css.write_text("body{background:#000}", encoding="utf-8")
        entradas = servidor._arquivos_do_turno(antes, servidor._foto_data())

        assert [e["path"] for e in entradas] == ["data/user/site"]
        assert entradas[0]["dir"] is True

    def test_write_files_de_verdade(self, amb):
        """Integração: a tool real, criando o projeto numa pasta nova."""
        servidor, _, raiz = amb
        from tools.write_files import run as write_files

        antes = servidor._foto_data()
        write_files(
            base=str(raiz / "data" / "user" / "calculadora"),
            files=[
                {"path": "index.html", "content": "<h1>calc</h1>"},
                {"path": "app.js", "content": "console.log(1)"},
            ],
        )
        entradas = servidor._arquivos_do_turno(antes, servidor._foto_data())

        assert [e["path"] for e in entradas] == ["data/user/calculadora"]

    def test_sem_mudanca_nenhuma(self, amb):
        servidor, _, _ = amb
        assert servidor._arquivos_do_turno(servidor._foto_data(), servidor._foto_data()) == []


# ── /api/preview_site (servidor estático do projeto) ─────────────────────────

class TestPreviewSite:
    def _projeto(self, raiz):
        pasta = raiz / "data" / "user" / "calc"
        pasta.mkdir(parents=True)
        (pasta / "index.html").write_text(
            "<!doctype html><link rel='stylesheet' href='style.css'>", encoding="utf-8"
        )
        (pasta / "style.css").write_text("body{background:#000}", encoding="utf-8")
        return pasta

    def test_abre_pasta_com_index(self, amb):
        import urllib.request

        _, cliente, raiz = amb
        self._projeto(raiz)

        r = cliente.get("/api/preview_site?path=data/user/calc")
        dados = r.get_json()

        assert r.status_code == 200
        assert dados["entry"] == "index.html"
        assert "/p/" in dados["url"]
        assert dados["url"].endswith("/index.html")
        assert dados["port"] > 0

        # servidor estático de verdade: css irmão tem que vir junto
        base = dados["url"].rsplit("/", 1)[0]
        with urllib.request.urlopen(dados["url"], timeout=5) as resp:
            assert resp.status == 200
            assert "style.css" in resp.read().decode()
        with urllib.request.urlopen(base + "/style.css", timeout=5) as resp:
            assert resp.status == 200
            assert "background" in resp.read().decode()

    def test_abre_html_solto_pela_pasta(self, amb):
        _, cliente, raiz = amb
        self._projeto(raiz)

        dados = cliente.get("/api/preview_site?path=data/user/calc/index.html").get_json()

        assert dados["dir"] is False
        assert dados["entry"] == "index.html"

    def test_404_sem_html(self, amb):
        _, cliente, raiz = amb
        (raiz / "data" / "user" / "vazia").mkdir()
        assert cliente.get("/api/preview_site?path=data/user/vazia").status_code == 404

    def test_403_fora_de_data(self, amb):
        _, cliente, _ = amb
        assert cliente.get("/api/preview_site?path=..").status_code == 403

    def test_401_sem_login(self, amb, monkeypatch):
        servidor, cliente, _ = amb
        monkeypatch.setattr(servidor, "_is_authenticated", lambda: False)
        assert cliente.get("/api/preview_site?path=data/user/calc").status_code == 401

    def test_token_obrigatorio(self, amb):
        import urllib.error
        import urllib.request

        _, cliente, raiz = amb
        self._projeto(raiz)
        dados = cliente.get("/api/preview_site?path=data/user/calc").get_json()

        ruim = dados["url"].replace("/p/", "/p/xxx", 1)
        with pytest.raises(urllib.error.HTTPError) as erro:
            urllib.request.urlopen(ruim, timeout=5)
        assert erro.value.code == 404


# ── chips ao reabrir uma sessão do histórico ────────────────────────────────

class TestArquivosNoHistorico:
    def test_trace_guarda_arquivos(self):
        from server import _trace_json

        bruto = _trace_json([], "done", 2, 1, 2, 0.0,
                            arquivos=[{"path": "data/user/x.html"}])

        assert json.loads(bruto)["arquivos"] == [{"path": "data/user/x.html"}]
        # sem passo e sem arquivo continua None (não grava lixo no histórico)
        assert _trace_json([], "done", 0, 0, 0, 0.0) is None

    def test_turn_json_usa_arquivos_do_trace(self, amb):
        servidor, _, _ = amb
        turno = {
            "id": 1, "role": "agent", "ts": "x", "content": "pronto",
            "trace": json.dumps({
                "passos": [], "fim": {"status": "done"},
                "arquivos": [{"path": "data/user/a.md", "name": "a.md"}],
            }),
        }

        assert servidor._turn_json(turno)["arquivos"] == [
            {"path": "data/user/a.md", "name": "a.md"}
        ]

    def test_sessao_antiga_reconstroi_pela_resposta(self, amb):
        """Turno gravado antes disto: acha a pasta citada (e que existe)."""
        servidor, _, raiz = amb
        pasta = raiz / "data" / "user" / "calc"
        pasta.mkdir(parents=True)
        (pasta / "index.html").write_text("x", encoding="utf-8")
        turno = {
            "id": 2, "role": "agent", "ts": "x", "trace": None,
            "content": (
                "Calculadora científica criada com sucesso! Arquivos salvos em: "
                "data/user/calc (incluindo index.html, style.css e script.js)"
            ),
        }

        arquivos = servidor._turn_json(turno)["arquivos"]

        assert [a["path"] for a in arquivos] == ["data/user/calc"]
        assert arquivos[0]["dir"] is True

    def test_mencao_que_nao_existe_nao_vira_chip(self, amb):
        servidor, _, _ = amb
        assert servidor._arquivos_da_mensagem(
            "salvo em data/user/nao-existe/index.html"
        ) == []

    def test_pasta_vence_arquivo_que_esta_dentro(self, amb):
        servidor, _, raiz = amb
        pasta = raiz / "data" / "user" / "calc"
        pasta.mkdir(parents=True)
        (pasta / "index.html").write_text("x", encoding="utf-8")
        (pasta / "style.css").write_text("x", encoding="utf-8")

        arquivos = servidor._arquivos_da_mensagem(
            "projeto em data/user/calc, css em data/user/calc/style.css"
        )

        assert [a["path"] for a in arquivos] == ["data/user/calc"]

    def test_arquivo_citado_vira_chip_do_projeto(self, amb):
        """Resposta cita o index.html do projeto: o chip é da pasta, não do html."""
        servidor, _, raiz = amb
        pasta = raiz / "data" / "user" / "jogo"
        pasta.mkdir(parents=True)
        (pasta / "index.html").write_text("x", encoding="utf-8")

        arquivos = servidor._arquivos_da_mensagem(
            "É só abrir o arquivo data/user/jogo/index.html no navegador"
        )

        assert [a["path"] for a in arquivos] == ["data/user/jogo"]
        assert arquivos[0]["dir"] is True
# ── fonte registrada fora de data/ (rota /api/source/<id>/preview) ──────────

class TestFontePreview:
    def _registrar(self, monkeypatch, caminho):
        """Faz a rota enxergar `caminho` como a fonte 18 do knowledge.db."""
        import knowledge.db as kdb
        registro = {"id": 18, "filename": caminho.name, "filepath": str(caminho)}
        monkeypatch.setattr(kdb, "get_source", lambda sid: registro if sid == 18 else None)
        return registro

    def _arquivo(self, raiz, nome="cronica.md", conteudo="# A crônica\n"):
        alvo = raiz.parent / "RPG" / nome
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(conteudo, encoding="utf-8")
        return alvo

    def test_fonte_fora_de_data_ganha_url(self, amb):
        servidor, _, raiz = amb
        alvo = self._arquivo(raiz)

        info = servidor._preview_da_fonte({"id": 18, "filepath": str(alvo)})

        assert info["preview_path"] is None
        assert info["preview_url"] == "/api/source/18/preview"
        assert info["preview_motivo"] is None

    def test_fonte_em_data_mantem_path(self, amb):
        servidor, _, raiz = amb
        alvo = raiz / "data" / "user" / "nota.md"
        alvo.write_text("x", encoding="utf-8")

        info = servidor._preview_da_fonte({"id": 7, "filepath": str(alvo)})

        assert info["preview_path"] == "data/user/nota.md"
        assert info["preview_url"] is None

    def test_arquivo_sumido_tem_motivo(self, amb):
        servidor, _, raiz = amb

        info = servidor._preview_da_fonte({"id": 1, "filepath": str(raiz / "sumiu.md")})

        assert info["preview_url"] is None
        assert "não está mais no disco" in info["preview_motivo"]

    def test_serve_md_da_fonte(self, amb, monkeypatch):
        _, cliente, raiz = amb
        self._registrar(monkeypatch, self._arquivo(raiz))

        r = cliente.get("/api/source/18/preview")

        assert r.status_code == 200
        assert r.mimetype == "text/markdown"
        assert "charset=utf-8" in r.headers["Content-Type"]
        assert "crônica" in r.get_data(as_text=True)
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["X-Content-Type-Options"] == "nosniff"

    def test_download_vira_attachment(self, amb, monkeypatch):
        _, cliente, raiz = amb
        self._registrar(monkeypatch, self._arquivo(raiz))

        r = cliente.get("/api/source/18/preview?dl=1")

        assert "attachment" in r.headers.get("Content-Disposition", "")

    def test_html_de_fonte_vira_texto(self, amb, monkeypatch):
        """Página de fonte não roda na origem do Ciel: chega como código."""
        _, cliente, raiz = amb
        self._registrar(monkeypatch, self._arquivo(raiz, "jogo.html", "<h1>oi</h1>"))

        r = cliente.get("/api/source/18/preview")

        assert r.status_code == 200
        assert r.mimetype == "text/plain"
        assert "<h1>oi</h1>" in r.get_data(as_text=True)

    def test_arquivo_sumido_404(self, amb, monkeypatch):
        _, cliente, raiz = amb
        self._registrar(monkeypatch, raiz / "sumiu.md")

        r = cliente.get("/api/source/18/preview")

        assert r.status_code == 404
        assert "não está mais no disco" in r.get_data(as_text=True)

    def test_arquivo_protegido_403(self, amb, monkeypatch):
        _, cliente, raiz = amb
        alvo = raiz.parent / "RPG" / ".segredo"
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text("x", encoding="utf-8")
        self._registrar(monkeypatch, alvo)

        assert cliente.get("/api/source/18/preview").status_code == 403

    def test_fonte_inexistente_404(self, amb, monkeypatch):
        import knowledge.db as kdb
        _, cliente, _ = amb
        monkeypatch.setattr(kdb, "get_source", lambda sid: None)

        assert cliente.get("/api/source/18/preview").status_code == 404

    def test_401_sem_login(self, amb, monkeypatch):
        servidor, cliente, _ = amb
        monkeypatch.setattr(servidor, "_is_authenticated", lambda: False)

        assert cliente.get("/api/source/18/preview").status_code == 401