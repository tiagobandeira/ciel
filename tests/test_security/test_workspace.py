"""
tests/test_security/test_workspace.py

Cobre: workspace padrão (cwd), path traversal via ../, symlinks,
grants de leitura/escrita, persistência e remoção de grants.
"""

import json
import pytest
from pathlib import Path


@pytest.fixture
def ws(tmp_path):
    """Workspace isolado em diretório temporário."""
    import workspace as _ws_mod
    w = _ws_mod.Workspace(tmp_path)
    return w


@pytest.fixture
def workspace_com_subdir(tmp_path):
    """Workspace com um subdiretório interno e um diretório externo."""
    interno = tmp_path / "projeto"
    interno.mkdir()
    externo = tmp_path / "outro"
    externo.mkdir()
    (interno / "arquivo.txt").write_text("conteúdo")
    (externo / "secreto.txt").write_text("segredo")
    import workspace as _ws_mod
    w = _ws_mod.Workspace(interno)
    return w, interno, externo


# ── acesso dentro do workspace ────────────────────────────────────────────────

class TestDentroDoWorkspace:
    def test_leitura_permitida(self, workspace_com_subdir):
        w, interno, _ = workspace_com_subdir
        resolved, err = w.check(str(interno / "arquivo.txt"), need_write=False)
        assert err is None
        assert resolved is not None

    def test_escrita_permitida(self, workspace_com_subdir):
        w, interno, _ = workspace_com_subdir
        resolved, err = w.check(str(interno / "novo.txt"), need_write=True)
        assert err is None

    def test_arquivo_relativo(self, workspace_com_subdir):
        """Path relativo que resolve pra dentro do workspace."""
        import os
        w, interno, _ = workspace_com_subdir
        os.chdir(interno)
        resolved, err = w.check("arquivo.txt", need_write=False)
        assert err is None


# ── bloqueio fora do workspace ────────────────────────────────────────────────

class TestForaDoWorkspace:
    def test_leitura_bloqueada(self, workspace_com_subdir):
        w, _, externo = workspace_com_subdir
        resolved, err = w.check(str(externo / "secreto.txt"), need_write=False)
        assert err is not None
        assert resolved is None

    def test_escrita_bloqueada(self, workspace_com_subdir):
        w, _, externo = workspace_com_subdir
        resolved, err = w.check(str(externo / "novo.txt"), need_write=True)
        assert err is not None

    def test_path_traversal_pontos(self, workspace_com_subdir):
        """../externo/secreto.txt não deve escapar do workspace."""
        w, interno, externo = workspace_com_subdir
        payload = str(interno / ".." / "outro" / "secreto.txt")
        resolved, err = w.check(payload, need_write=False)
        assert err is not None

    def test_path_absoluto_externo(self, workspace_com_subdir):
        w, _, externo = workspace_com_subdir
        resolved, err = w.check(str(Path("/etc/passwd")), need_write=False)
        assert err is not None

    def test_path_vazio(self, ws):
        resolved, err = ws.check("", need_write=False)
        assert err is not None


# ── grants ────────────────────────────────────────────────────────────────────

class TestGrants:
    def test_grant_leitura_permite_ler(self, workspace_com_subdir):
        w, _, externo = workspace_com_subdir
        w.add_grant(externo, write=False)
        resolved, err = w.check(str(externo / "secreto.txt"), need_write=False)
        assert err is None

    def test_grant_leitura_bloqueia_escrita(self, workspace_com_subdir):
        w, _, externo = workspace_com_subdir
        w.add_grant(externo, write=False)
        resolved, err = w.check(str(externo / "secreto.txt"), need_write=True)
        assert err is not None

    def test_grant_escrita_permite_escrever(self, workspace_com_subdir):
        w, _, externo = workspace_com_subdir
        w.add_grant(externo, write=True)
        resolved, err = w.check(str(externo / "secreto.txt"), need_write=True)
        assert err is None

    def test_grant_persistido(self, workspace_com_subdir):
        """Grant salvo em .ciel_workspace.json sobrevive a uma nova instância."""
        import workspace as _ws_mod
        w, interno, externo = workspace_com_subdir
        w.add_grant(externo, write=False)

        w2 = _ws_mod.Workspace(interno)
        resolved, err = w2.check(str(externo / "secreto.txt"), need_write=False)
        assert err is None

    def test_grant_removido(self, workspace_com_subdir):
        w, _, externo = workspace_com_subdir
        w.add_grant(externo, write=True)
        w.remove_grant(externo)
        resolved, err = w.check(str(externo / "secreto.txt"), need_write=False)
        assert err is not None

    def test_grant_nao_duplica(self, workspace_com_subdir):
        """Adicionar o mesmo grant duas vezes não cria duplicata."""
        w, _, externo = workspace_com_subdir
        w.add_grant(externo, write=False)
        w.add_grant(externo, write=True)
        assert len(w.grants) == 1
        assert w.grants[0].write is True
