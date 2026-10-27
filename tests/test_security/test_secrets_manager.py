"""Testes do trust/secrets.py: escrita segura, JSON corrompido, fallback, env."""
import importlib, json, os, tempfile
from pathlib import Path
import trust.secrets as m

d = Path(tempfile.mkdtemp()); p = d / "secrets.json"
sm = m.SecretsManager(p)

# 1 criar + atômico (sem .tmp sobrando)
sm.save_provider("nvidia", base_url="u", model="m", api_key="k")
assert sm.get_api_key("nvidia", "m") == "k"
assert not (d / "secrets.tmp").exists()

# 2 preserva ciel_auth
data = json.loads(p.read_text()); data["ciel_auth"] = {"hash": "x"}; p.write_text(json.dumps(data))
sm.save_provider("or", base_url="u2", model="", api_key="k2")
assert json.loads(p.read_text())["ciel_auth"] == {"hash": "x"}

# 3 BOM ok
p.write_text(p.read_text(), encoding="utf-8-sig")
sm.save_provider("x", base_url="u", model="", api_key="k3")
assert "ciel_auth" in json.loads(p.read_text())

# 4 JSON corrompido: leitura tolerante, escrita levanta e NÃO altera
p.write_text('{"providers": {"a": {}},, }')
before = p.read_text()
assert sm.list_providers() == []
for fn in (lambda: sm.save_provider("n", base_url="u", model="", api_key="k"),
           lambda: sm.delete_provider("a")):
    try: fn(); raise SystemExit("deveria levantar")
    except ValueError: pass
assert p.read_text() == before

# 5 raiz não-objeto
p.write_text("[1,2]")
try: sm.save_provider("n", base_url="u", model="", api_key="k"); raise SystemExit("x")
except ValueError: pass

# 6 fallback: criar .tmp bloqueado, escrever no existente ok
p.write_text(json.dumps({"providers": {}, "ciel_auth": {"hash": "h"}}))
orig = Path.write_text
def blocked(self, *a, **k):
    if self.suffix == ".tmp": raise PermissionError(13, "bloqueado", str(self))
    return orig(self, *a, **k)
Path.write_text = blocked
sm.save_provider("fb", base_url="u", model="", api_key="kk")
Path.write_text = orig
j = json.loads(p.read_text()); assert j["providers"]["fb"]["api_key"] == "kk" and j["ciel_auth"]["hash"] == "h"

# 7 tudo bloqueado -> mensagem clara, arquivo intacto
before = p.read_text()
def blocked_all(self, *a, **k): raise PermissionError(13, "bloqueado", str(self))
Path.write_text = blocked_all
try: sm.save_provider("z", base_url="u", model="", api_key="k"); raise SystemExit("x")
except PermissionError as e: assert "Nada foi alterado" in str(e)
Path.write_text = orig
assert p.read_text() == before

# 8 CIEL_SECRETS_PATH
os.environ["CIEL_SECRETS_PATH"] = str(d / "outro.json")
importlib.reload(m)
assert m.SecretsManager()._path == d / "outro.json"
print("todos os testes ok")
