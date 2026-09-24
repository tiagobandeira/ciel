"""
tests/test_core/test_history_store.py

Cobre HistoryStore (history_store.py): sessões, turnos, branch,
redaction, exportação Markdown e format_session_row.

Cada teste recebe um store isolado em banco SQLite em memória —
nenhum teste toca o agent_history.db real do projeto.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from history_store import HistoryStore, _redact, format_session_row


# ── fixture base ──────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """HistoryStore isolado em arquivo temporário, fechado após o teste."""
    s = HistoryStore(db_path=tmp_path / "test_history.db")
    yield s
    s.close()


# ── new_session / get_session ─────────────────────────────────────────────────

class TestNewSession:
    def test_retorna_id_inteiro(self, store):
        sid = store.new_session("geral", "Minha sessão")
        assert isinstance(sid, int)
        assert sid > 0

    def test_ids_incrementais(self, store):
        sid1 = store.new_session("geral", "S1")
        sid2 = store.new_session("geral", "S2")
        assert sid2 > sid1

    def test_get_session_campos(self, store):
        sid = store.new_session("csv_manager", "Análise de dados")
        row = store.get_session(sid)
        assert row["agent_id"] == "csv_manager"
        assert row["title"] == "Análise de dados"
        assert row["summary"] == ""
        assert row["parent_session_id"] is None

    def test_get_session_inexistente_retorna_none(self, store):
        assert store.get_session(9999) is None

    def test_title_vazio_permitido(self, store):
        sid = store.new_session("geral")
        row = store.get_session(sid)
        assert row["title"] == ""

    def test_created_at_preenchido(self, store):
        sid = store.new_session("geral", "teste")
        row = store.get_session(sid)
        assert row["created_at"] is not None
        assert len(row["created_at"]) >= 10  # ao menos YYYY-MM-DD


# ── update_title / save_summary ───────────────────────────────────────────────

class TestUpdateTitleESummary:
    def test_update_title(self, store):
        sid = store.new_session("geral", "título antigo")
        store.update_title(sid, "título novo")
        assert store.get_session(sid)["title"] == "título novo"

    def test_save_summary(self, store):
        sid = store.new_session("geral", "S")
        store.save_summary(sid, "Resumo gerado pelo modelo")
        assert store.get_session(sid)["summary"] == "Resumo gerado pelo modelo"

    def test_save_summary_redacta_chave(self, store):
        sid = store.new_session("geral", "S")
        store.save_summary(sid, "Usamos sk-abc123xyz456abc123xyz456 para autenticar")
        summary = store.get_session(sid)["summary"]
        assert "sk-" not in summary
        assert "[REDACTED]" in summary


# ── list_sessions ─────────────────────────────────────────────────────────────

class TestListSessions:
    def test_lista_todas_sessoes(self, store):
        store.new_session("geral", "S1")
        store.new_session("geral", "S2")
        store.new_session("csv_manager", "S3")
        assert len(store.list_sessions()) == 3

    def test_filtra_por_agente(self, store):
        store.new_session("geral", "S1")
        store.new_session("geral", "S2")
        store.new_session("csv_manager", "S3")
        result = store.list_sessions("geral")
        assert len(result) == 2
        assert all(r["agent_id"] == "geral" for r in result)

    def test_ordenada_mais_recente_primeiro(self, store):
        sid1 = store.new_session("geral", "Primeira")
        sid2 = store.new_session("geral", "Segunda")
        # append_turn atualiza updated_at da sessão
        store.append_turn(sid1, "user", "oi")  # sid1 fica mais recente
        sessions = store.list_sessions()
        assert sessions[0]["id"] == sid1

    def test_banco_vazio_retorna_lista_vazia(self, store):
        assert store.list_sessions() == []

    def test_agente_sem_sessoes_retorna_vazio(self, store):
        store.new_session("outro_agente", "S1")
        assert store.list_sessions("geral") == []

    def test_turn_count_correto(self, store):
        sid = store.new_session("geral", "S")
        store.append_turn(sid, "user", "msg 1")
        store.append_turn(sid, "agent", "resp 1")
        store.append_turn(sid, "user", "msg 2")
        row = store.list_sessions()[0]
        assert row["turn_count"] == 3


# ── append_turn / get_turns ───────────────────────────────────────────────────

class TestTurnos:
    def test_append_e_get_turns(self, store):
        sid = store.new_session("geral", "S")
        store.append_turn(sid, "user", "Olá")
        store.append_turn(sid, "agent", "Oi! Como posso ajudar?")
        turns = store.get_turns(sid)
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[0]["content"] == "Olá"
        assert turns[1]["role"] == "agent"

    def test_turnos_em_ordem(self, store):
        sid = store.new_session("geral", "S")
        for i in range(5):
            store.append_turn(sid, "user", f"msg {i}")
        turns = store.get_turns(sid)
        contents = [t["content"] for t in turns]
        assert contents == [f"msg {i}" for i in range(5)]

    def test_get_turns_sessao_vazia(self, store):
        sid = store.new_session("geral", "S")
        assert store.get_turns(sid) == []

    def test_append_turn_atualiza_updated_at(self, store):
        sid = store.new_session("geral", "S")
        before = store.get_session(sid)["updated_at"]
        import time; time.sleep(0.01)
        store.append_turn(sid, "user", "oi")
        after = store.get_session(sid)["updated_at"]
        # updated_at deve mudar ou ser >= before
        assert after >= before

    def test_turnos_nao_vazam_entre_sessoes(self, store):
        sid1 = store.new_session("geral", "S1")
        sid2 = store.new_session("geral", "S2")
        store.append_turn(sid1, "user", "apenas na S1")
        assert store.get_turns(sid2) == []


# ── redaction em append_turn ──────────────────────────────────────────────────

class TestRedactionEmTurnos:
    def test_api_key_openai_redactada(self, store):
        sid = store.new_session("geral", "S")
        store.append_turn(sid, "user", "minha chave é sk-abc123xyz456abc123xyz456")
        content = store.get_turns(sid)[0]["content"]
        assert "sk-" not in content
        assert "[REDACTED]" in content

    def test_conteudo_normal_preservado(self, store):
        sid = store.new_session("geral", "S")
        store.append_turn(sid, "user", "Calcule 2 + 2 por favor")
        content = store.get_turns(sid)[0]["content"]
        assert content == "Calcule 2 + 2 por favor"

    def test_github_token_redactado(self, store):
        sid = store.new_session("geral", "S")
        token = "ghp_" + "A" * 36
        store.append_turn(sid, "agent", f"token: {token}")
        content = store.get_turns(sid)[0]["content"]
        assert "ghp_" not in content
        assert "[REDACTED]" in content

    def test_connection_string_redactada(self, store):
        sid = store.new_session("geral", "S")
        store.append_turn(sid, "user", "postgres://admin:senha123@localhost/db")
        content = store.get_turns(sid)[0]["content"]
        assert "senha123" not in content


# ── _redact (função isolada) ──────────────────────────────────────────────────

class TestRedactFuncao:
    def test_string_vazia(self):
        assert _redact("") == ""

    def test_none_equivalente(self):
        # _redact recebe str, mas garante que falsy retorna o valor
        assert _redact("") == ""

    def test_sk_key_redactada(self):
        result = _redact("chave: sk-abc123xyz456abc123xyz456")
        assert "sk-" not in result
        assert "[REDACTED]" in result

    def test_nvapi_redactada(self):
        result = _redact("nvapi-" + "x" * 25)
        assert "nvapi-" not in result

    def test_bearer_token_redactado(self):
        result = _redact("Authorization: Bearer meu-token-secreto-longo-aqui")
        assert "meu-token-secreto" not in result

    def test_password_par_redactado(self):
        result = _redact("password=minha_senha_secreta")
        assert "minha_senha_secreta" not in result

    def test_texto_sem_segredo_inalterado(self):
        texto = "Análise de dados de vendas do Q3 2026"
        assert _redact(texto) == texto

    def test_multiplos_segredos_no_mesmo_texto(self):
        texto = "sk-abc123xyz456abc123xyz456 e ghp_" + "B" * 36
        result = _redact(texto)
        assert "sk-" not in result
        assert "ghp_" not in result
        assert result.count("[REDACTED]") == 2


# ── delete_session ────────────────────────────────────────────────────────────

class TestDeleteSession:
    def test_delete_remove_sessao(self, store):
        sid = store.new_session("geral", "S")
        store.delete_session(sid)
        assert store.get_session(sid) is None

    def test_delete_remove_turnos_cascade(self, store):
        sid = store.new_session("geral", "S")
        store.append_turn(sid, "user", "oi")
        store.append_turn(sid, "agent", "olá")
        store.delete_session(sid)
        assert store.get_turns(sid) == []

    def test_delete_nao_afeta_outras_sessoes(self, store):
        sid1 = store.new_session("geral", "S1")
        sid2 = store.new_session("geral", "S2")
        store.append_turn(sid2, "user", "preservada")
        store.delete_session(sid1)
        assert store.get_session(sid2) is not None
        assert len(store.get_turns(sid2)) == 1

    def test_delete_sessao_inexistente_nao_quebra(self, store):
        store.delete_session(9999)  # não deve lançar exceção

    def test_delete_remove_da_listagem(self, store):
        sid = store.new_session("geral", "S")
        store.delete_session(sid)
        assert len(store.list_sessions()) == 0


# ── branch_session ────────────────────────────────────────────────────────────

class TestBranchSession:
    def test_branch_cria_nova_sessao(self, store):
        parent = store.new_session("geral", "Original")
        child = store.branch_session(parent, "geral")
        assert child != parent
        assert store.get_session(child) is not None

    def test_branch_registra_parent_id(self, store):
        parent = store.new_session("geral", "Original")
        child = store.branch_session(parent, "geral")
        row = store.get_session(child)
        assert row["parent_session_id"] == parent

    def test_branch_titulo_automatico(self, store):
        parent = store.new_session("geral", "Conversa Principal")
        child = store.branch_session(parent, "geral")
        title = store.get_session(child)["title"]
        assert "branch" in title.lower() or "Conversa Principal" in title

    def test_branch_titulo_customizado(self, store):
        parent = store.new_session("geral", "Original")
        child = store.branch_session(parent, "geral", title="Meu Branch")
        assert store.get_session(child)["title"] == "Meu Branch"

    def test_branch_pode_ter_agent_diferente(self, store):
        parent = store.new_session("geral", "Original")
        child = store.branch_session(parent, "csv_manager")
        assert store.get_session(child)["agent_id"] == "csv_manager"

    def test_branch_nao_herda_turnos(self, store):
        """Branch começa do zero — turnos não são copiados automaticamente."""
        parent = store.new_session("geral", "Original")
        store.append_turn(parent, "user", "contexto anterior")
        child = store.branch_session(parent, "geral")
        assert store.get_turns(child) == []

    def test_branch_de_parent_inexistente_lanca_erro(self, store):
        """FK constraint do SQLite impede branch de parent que não existe."""
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            store.branch_session(9999, "geral", title="Orfão")


# ── export_markdown ───────────────────────────────────────────────────────────

class TestExportMarkdown:
    def test_cria_arquivo(self, store, tmp_path):
        sid = store.new_session("geral", "Minha Conversa")
        store.append_turn(sid, "user", "Olá!")
        store.append_turn(sid, "agent", "Oi, como posso ajudar?")
        out = store.export_markdown(sid, out_path=tmp_path / "export.md")
        assert out.exists()

    def test_conteudo_tem_titulo(self, store, tmp_path):
        sid = store.new_session("geral", "Análise de Dados")
        out = store.export_markdown(sid, out_path=tmp_path / "export.md")
        content = out.read_text(encoding="utf-8")
        assert "Análise de Dados" in content

    def test_conteudo_tem_turnos(self, store, tmp_path):
        sid = store.new_session("geral", "S")
        store.append_turn(sid, "user", "Pergunta do usuário")
        store.append_turn(sid, "agent", "Resposta do agente")
        out = store.export_markdown(sid, out_path=tmp_path / "export.md")
        content = out.read_text(encoding="utf-8")
        assert "Pergunta do usuário" in content
        assert "Resposta do agente" in content

    def test_conteudo_tem_resumo_se_existir(self, store, tmp_path):
        sid = store.new_session("geral", "S")
        store.save_summary(sid, "Resumo da conversa aqui")
        out = store.export_markdown(sid, out_path=tmp_path / "export.md")
        content = out.read_text(encoding="utf-8")
        assert "Resumo da conversa aqui" in content

    def test_nome_automatico_sem_out_path(self, store, tmp_path, monkeypatch):
        sid = store.new_session("geral", "Minha Sessão")
        monkeypatch.chdir(tmp_path)  # monkeypatch restaura o cwd após o teste
        out = store.export_markdown(sid)
        assert out.exists()
        assert str(sid) in out.name

    def test_sessao_inexistente_lanca_value_error(self, store, tmp_path):
        with pytest.raises(ValueError, match="9999"):
            store.export_markdown(9999, out_path=tmp_path / "x.md")

    def test_sem_turnos_gera_arquivo_valido(self, store, tmp_path):
        sid = store.new_session("geral", "Vazia")
        out = store.export_markdown(sid, out_path=tmp_path / "export.md")
        assert out.exists()
        assert out.read_text()  # não vazio


# ── format_session_row ────────────────────────────────────────────────────────

class TestFormatSessionRow:
    @pytest.fixture
    def row(self, store):
        sid = store.new_session("csv_manager", "Análise de vendas")
        store.save_summary(sid, "Resumo gerado")
        store.append_turn(sid, "user", "oi")
        store.append_turn(sid, "agent", "olá")
        return store.list_sessions()[0]

    def test_contem_agent_id(self, row):
        assert "csv_manager" in format_session_row(row)

    def test_contem_turn_count(self, row):
        formatted = format_session_row(row)
        assert "2" in formatted

    def test_contem_titulo(self, row):
        assert "Análise de vendas" in format_session_row(row)

    def test_estrela_quando_tem_summary(self, row):
        assert "★" in format_session_row(row)

    def test_sem_summary_sem_estrela(self, store):
        sid = store.new_session("geral", "S")
        store.append_turn(sid, "user", "oi")
        row = store.list_sessions()[0]
        assert "★" not in format_session_row(row)

    def test_idx_aparece_quando_passado(self, row):
        formatted = format_session_row(row, idx=3)
        assert "3." in formatted

    def test_sem_idx_sem_numero(self, row):
        formatted = format_session_row(row, idx=None)
        assert "1." not in formatted

    def test_titulo_sem_titulo(self, store):
        sid = store.new_session("geral")
        store.append_turn(sid, "user", "oi")
        row = store.list_sessions()[0]
        formatted = format_session_row(row)
        assert "(sem título)" in formatted
