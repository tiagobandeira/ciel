"""Testes do AuthManager (senha do server web).

O `SECRETS_PATH` é um global do módulo (o arquivo real fica em ~/.ciel), então
cada teste redireciona ele para um tmp_path antes de instanciar — nada toca a
senha ou as chaves de provider da máquina que roda a suíte.
"""

import json
from pathlib import Path

import pytest

import auth.manager as am


@pytest.fixture
def secrets_path(tmp_path, monkeypatch):
    path = tmp_path / "secrets.json"
    monkeypatch.setattr(am, "SECRETS_PATH", path)
    return path


@pytest.fixture
def auth(secrets_path):
    instancia = am.AuthManager()
    instancia.ensure_configured()   # __init__ não grava mais (ver TestPrimeiraExecucao)
    return instancia


class TestPrimeiraExecucao:
    def test_init_nao_grava_em_disco(self, secrets_path):
        # construir não pode ter efeito colateral: o --reset-password precisa
        # rodar mesmo com a pasta sem permissão de escrita
        am.AuthManager()

        assert not secrets_path.exists()

    def test_ensure_gera_a_senha_uma_vez(self, secrets_path):
        primeira = am.AuthManager()
        senha = primeira.ensure_configured()

        assert senha
        assert primeira.login(senha) is not None
        assert am.AuthManager().ensure_configured() is None


class TestResetPassword:
    def test_senha_nova_serve_para_login(self, auth):
        nova = auth.reset_password()

        assert nova and len(nova) >= am.DEFAULT_PASSWORD_LEN
        assert auth.login(nova) is not None

    def test_marca_senha_como_padrao(self, auth):
        nova = auth.reset_password()

        status = auth.status()
        assert status["is_default"] is True
        assert status["default_password"] == nova

    def test_hash_nao_guarda_a_senha_em_texto(self, auth, secrets_path):
        nova = auth.reset_password()

        guardado = json.loads(secrets_path.read_text(encoding="utf-8"))
        assert nova not in guardado["ciel_auth"]["hash"]

    def test_senha_temporaria_some_apos_a_troca(self, auth, secrets_path):
        # reset deixa a senha em texto (como na primeira execução) só até o
        # usuário trocar; depois disso nem a temporária fica no arquivo.
        nova = auth.reset_password()
        token = auth.login(nova)

        auth.change_password(token, "senha-definitiva")

        guardado = json.loads(secrets_path.read_text(encoding="utf-8"))
        assert "default_password" not in guardado["ciel_auth"]
        assert nova not in json.dumps(guardado["ciel_auth"])

    def test_preserva_chaves_de_provider(self, secrets_path):
        # é o motivo de não se apagar o arquivo para recuperar a senha
        secrets_path.write_text(
            json.dumps({"providers": {"nvidia": {"api_key": "KEEP-ME"}}}),
            encoding="utf-8",
        )
        auth = am.AuthManager()

        auth.reset_password()

        guardado = json.loads(secrets_path.read_text(encoding="utf-8"))
        assert guardado["providers"]["nvidia"]["api_key"] == "KEEP-ME"
        assert guardado["ciel_auth"]["is_default"] is True

    def test_invalida_tokens_antigos(self, auth):
        velho = auth.login(auth.status()["default_password"])
        assert auth.verify_token(velho)

        auth.reset_password()

        # a chave HMAC deriva do hash: senha nova ⇒ tokens antigos mortos
        assert not auth.verify_token(velho)


class TestChangePassword:
    def test_exige_token_valido(self, auth):
        assert auth.change_password("token-invalido", "outra-senha")["ok"] is False

    def test_token_novo_funciona_e_desliga_is_default(self, auth):
        token = auth.login(auth.status()["default_password"])

        result = auth.change_password(token, "senha-definitiva")

        assert result["ok"] is True
        assert auth.status()["is_default"] is False
        assert auth.status()["default_password"] is None
        assert auth.login("senha-definitiva") is not None


class TestArquivoDeSegredos:
    """O arquivo é editável à mão; um erro de leitura não pode custar as chaves."""

    def test_aceita_bom(self, secrets_path):
        # Bloco de Notas (e o Set-Content do PowerShell) gravam BOM: sem
        # utf-8-sig o arquivo "some" e o reset apagaria os providers.
        secrets_path.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps({"providers": {"nvidia": {"api_key": "KEEP"}}}).encode()
        )
        auth = am.AuthManager()

        auth.reset_password()

        guardado = json.loads(secrets_path.read_text(encoding="utf-8"))
        assert guardado["providers"]["nvidia"]["api_key"] == "KEEP"

    def test_json_invalido_falha_sem_apagar(self, secrets_path):
        original = "{ isso nao e json"
        secrets_path.write_text(original, encoding="utf-8")

        with pytest.raises(ValueError, match="inválido"):
            am.AuthManager()

        assert secrets_path.read_text(encoding="utf-8") == original

    def test_reset_rele_providers_escritos_depois(self, secrets_path):
        auth = am.AuthManager()   # instância carregada antes do arquivo mudar

        secrets_path.write_text(
            json.dumps({"providers": {"x": {"api_key": "NOVO"}}}),
            encoding="utf-8",
        )
        auth.reset_password()

        guardado = json.loads(secrets_path.read_text(encoding="utf-8"))
        assert guardado["providers"]["x"]["api_key"] == "NOVO"


class TestFormatoDeHash:
    """O login escolhe o verificador pelo hash guardado, não pela lib do venv."""

    def test_aceita_hash_pbkdf2(self, secrets_path):
        secrets_path.write_text(
            json.dumps({"ciel_auth": {"hash": am._pbkdf2_hash("senha"), "is_default": False}}),
            encoding="utf-8",
        )

        auth = am.AuthManager()

        assert auth.login("senha") is not None
        assert auth.login("errada") is None

    def test_hash_desconhecido_nao_explode(self, secrets_path):
        secrets_path.write_text(
            json.dumps({"ciel_auth": {"hash": "lixo", "is_default": False}}),
            encoding="utf-8",
        )

        auth = am.AuthManager()

        assert auth.login("qualquer") is None


class TestGravacao:
    """Ambiente que bloqueia criar arquivo na pasta ainda pode gravar o existente."""

    def test_cai_para_gravar_no_lugar_quando_replace_falha(self, auth, secrets_path, monkeypatch):
        import os as os_mod

        def bloqueado(src, dst):
            raise PermissionError(13, "Permission denied", str(dst))

        monkeypatch.setattr(os_mod, "replace", bloqueado)

        auth.reset_password()

        guardado = json.loads(secrets_path.read_text(encoding="utf-8"))
        assert guardado["ciel_auth"]["is_default"] is True
        assert not secrets_path.with_suffix(".tmp").exists()

    def test_erro_claro_quando_nada_pode_ser_gravado(self, auth, secrets_path, monkeypatch):
        antes = secrets_path.read_text(encoding="utf-8")

        def nega(*args, **kwargs):
            raise PermissionError(13, "Permission denied", "secrets")

        monkeypatch.setattr(Path, "write_text", nega)

        with pytest.raises(PermissionError, match="sem permissão"):
            auth.reset_password()

        # falhou alto e não mexeu no que estava lá
        assert secrets_path.read_text(encoding="utf-8") == antes


class TestNivelDeSistema:
    """O reset é ação do usuário do SO: não pede token e não passa pelo guard."""

    def test_caminho_padrao_fica_fora_da_raiz_do_projeto(self, monkeypatch):
        # não usa o tmp_path do pytest: quando o %TEMP% da máquina está
        # bloqueado, o pytest cai para uma pasta DENTRO do projeto e a
        # asserção mentiria. Aqui interessa o caminho padrão (~/.ciel).
        monkeypatch.delenv("CIEL_SECRETS_PATH", raising=False)
        raiz = Path(__file__).resolve().parents[2]

        assert not am._secrets_path().is_relative_to(raiz)

    def test_reset_grava_sem_passar_pelo_guard(self, auth, secrets_path):
        nova = auth.reset_password()

        assert auth.login(nova) is not None
        assert secrets_path.is_file()

    def test_env_define_o_caminho(self, tmp_path, monkeypatch):
        alvo = tmp_path / "outro" / "segredos.json"
        monkeypatch.setenv("CIEL_SECRETS_PATH", str(alvo))

        assert am._secrets_path() == alvo


class TestFronteiraComOWorkspace:
    """O outro lado: o agente continua sem alcançar o arquivo de segredos."""

    def _cenario(self, tmp_path):
        projeto = tmp_path / "projeto"
        projeto.mkdir()
        segredo = tmp_path / "home" / ".ciel" / "secrets.json"
        segredo.parent.mkdir(parents=True)
        segredo.write_text('{"providers": {}}', encoding="utf-8")
        return projeto, segredo

    def test_guard_nega_secrets_fora_do_workspace(self, tmp_path):
        from workspace import Workspace

        projeto, segredo = self._cenario(tmp_path)

        _, erro = Workspace(projeto).check(str(segredo), need_write=False)

        assert erro is not None
        assert "fora do workspace" in erro

    def test_grant_explicito_do_usuario_libera(self, tmp_path):
        # se o humano conceder o caminho, o agente alcança — decisão humana,
        # não do modelo. É o único jeito de a tool chegar no arquivo.
        from workspace import Workspace

        projeto, segredo = self._cenario(tmp_path)
        ws = Workspace(projeto)

        ws.add_grant(segredo, write=False)

        _, erro = ws.check(str(segredo), need_write=False)
        assert erro is None

    def test_guard_nega_credenciais_dentro_do_workspace(self, tmp_path, monkeypatch):
        # contorno de ambiente: CIEL_SECRETS_PATH apontando para dentro do
        # projeto deixaria as chaves ao alcance do read_file do modelo
        from workspace import Workspace

        projeto = tmp_path / "projeto"
        projeto.mkdir()
        segredo = projeto / ".ciel-secrets.json"
        segredo.write_text('{"providers": {}}', encoding="utf-8")
        monkeypatch.setenv("CIEL_SECRETS_PATH", str(segredo))

        ws = Workspace(projeto)
        ws.add_grant(segredo, write=False)   # nem com grant explícito

        _, erro = ws.check(str(segredo), need_write=False)

        assert erro is not None
        assert "credenciais" in erro

    def test_resolvedores_de_caminho_concordam(self, tmp_path, monkeypatch):
        # auth, trust e o guard precisam concordar, senão um grava onde o
        # outro não lê — e a senha deixa de preservar os providers
        from auth.manager import _secrets_path
        from trust.secrets import _default_path
        from workspace import _caminhos_de_credenciais

        alvo = tmp_path / "s.json"
        monkeypatch.setenv("CIEL_SECRETS_PATH", str(alvo))

        assert _secrets_path() == alvo
        assert _default_path() == alvo
        assert alvo.resolve() in _caminhos_de_credenciais()

