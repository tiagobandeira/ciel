"""
test_fase1_confirmacao.py — teste manual do patch da Fase 1
(confirmação de tool sensível generalizada via needs_confirmation()).

Por que mockar a chamada ao modelo em vez de usar o Ollama de verdade:
o que mudou no patch é a LÓGICA DE CONFIRMAÇÃO, não o jeito que o modelo
decide o que chamar. Se o teste depender do modelo escolher chamar
create_temp_tool por conta própria, ele fica lento e não-determinístico —
às vezes o modelo responde diferente e o teste não prova nada. Aqui a
gente substitui só a resposta do modelo por um roteiro fixo, e deixa
tool_dispatch.needs_confirmation, workspace etc. tudo rodando de verdade
(são os módulos reais do seu projeto).

Uso:
    copie este arquivo pra raiz do projeto (onde estão tool_dispatch.py,
    workspace.py, tools_registry.py, agent_loader.py) e rode:

        python test_fase1_confirmacao.py

    Precisa que o agent_loop.py já com o patch aplicado esteja no mesmo
    lugar de sempre (import agent_loop tem que pegar a versão nova).

Aviso: os cenários 1 e 3 usam "create_temp_tool" de propósito — isso
dispara o bloco de reload automático do registry dentro do loop (recarrega
tools_registry.load_tools() de verdade). É esperado, é o mesmo caminho que
roda em produção. Se o seu projeto não tiver tools_registry/agent_loader
disponíveis no ambiente onde você rodar isso, esse reload pode falhar —
nesse caso rode a partir da raiz do projeto mesmo.
"""

import agent_loop  # deve ser a versão já com o patch da Fase 1

ORIGINAL_CALL_MODEL = agent_loop._call_model
AGENT_INFO = {"id": "test", "system_prompt": "Você é um agente de teste."}


def _fake_tools():
    return {
        "create_temp_tool": {"fn": lambda **kw: "tool criada (fake)"},
        "list_sources":     {"fn": lambda **kw: "fontes: [] (fake)"},
    }


def _mock_call_model(respostas):
    """Troca agent_loop._call_model por uma fila de respostas fixas."""
    fila = list(respostas)

    def fake(messages, model, ollama_url):
        return fila.pop(0), 0, 0  # tokens não importam pro teste

    agent_loop._call_model = fake


def _capturing_on_step():
    """on_step que guarda os eventos pra dar pra fazer assert neles."""
    eventos = []

    def on_step(step, label, content, status):
        eventos.append((label, content, status))
        print(f"  [{status}] step {step} · {label} · {content[:80]}")

    return eventos, on_step


# ── cenário 1: tool sensível + on_confirm_tool aprova ───────────────────────
def teste_confirma_aprovado():
    print("\n[1] tool sensível, callback aprova")
    _mock_call_model([
        '{"tool": "create_temp_tool", "args": {"tool_code": "print(1)"}}',
        '{"done": true, "message": "criei a tool"}',
    ])
    eventos, on_step = _capturing_on_step()
    chamou = []

    def on_confirm_tool(tool_name, tool_code):
        chamou.append(tool_name)
        return True

    result = agent_loop.run_agent(
        "cria uma tool de teste",
        _fake_tools(), [], "modelo-fake", AGENT_INFO,
        on_confirm_tool=on_confirm_tool, on_step=on_step,
    )

    assert chamou == ["create_temp_tool"], "callback de confirmação não foi chamado"
    assert any(l == "resultado" for l, _, _ in eventos), "tool não parece ter executado"
    assert result.status == "done"
    print("  ✓ OK —", result.message)


# ── cenário 2: tool sensível + on_confirm_tool recusa ───────────────────────
def teste_confirma_recusado():
    print("\n[2] tool sensível, callback recusa")
    _mock_call_model([
        '{"tool": "create_temp_tool", "args": {"tool_code": "print(1)"}}',
        '{"done": true, "message": "ok, não criei nada"}',
    ])
    eventos, on_step = _capturing_on_step()

    result = agent_loop.run_agent(
        "cria uma tool de teste",
        _fake_tools(), [], "modelo-fake", AGENT_INFO,
        on_confirm_tool=lambda t, c: False, on_step=on_step,
    )

    recusas = [c for (l, c, s) in eventos if s == "error" and "recusada" in c]
    assert recusas, "esperava um evento de recusa, não achei"
    assert result.status == "done"
    print("  ✓ OK — recusou de verdade:", recusas[0])


# ── cenário 3: tool sensível + on_confirm_tool=None → deve BLOQUEAR ─────────
# Este é o comportamento novo. Antes do patch, on_confirm_tool=None deixava
# a tool passar direto sem perguntar nada.
def teste_bloqueia_sem_callback():
    print("\n[3] tool sensível, SEM callback (comportamento novo)")
    _mock_call_model([
        '{"tool": "create_temp_tool", "args": {"tool_code": "print(1)"}}',
        '{"done": true, "message": "terminou"}',
    ])
    eventos, on_step = _capturing_on_step()

    result = agent_loop.run_agent(
        "cria uma tool de teste",
        _fake_tools(), [], "modelo-fake", AGENT_INFO,
        on_confirm_tool=None, on_step=on_step,
    )

    bloqueios = [c for (l, c, s) in eventos if s == "error" and "bloqueada" in c]
    assert bloqueios, "esperava bloqueio por falta de callback, não achei — GAP AINDA ABERTO"
    assert result.status == "done"
    print("  ✓ OK — bloqueou de verdade:", bloqueios[0])


# ── cenário 4: tool NÃO sensível → não deve nem chamar o callback ───────────
def teste_tool_normal_nao_pede_confirmacao():
    print("\n[4] tool não-sensível — não deve pedir confirmação")
    _mock_call_model([
        '{"tool": "list_sources", "args": {}}',
        '{"done": true, "message": "ok"}',
    ])
    eventos, on_step = _capturing_on_step()
    chamou = []

    result = agent_loop.run_agent(
        "lista as fontes",
        _fake_tools(), [], "modelo-fake", AGENT_INFO,
        on_confirm_tool=lambda t, c: chamou.append(t) or True, on_step=on_step,
    )

    assert not chamou, f"callback foi chamado pra tool que não deveria ser sensível: {chamou}"
    assert result.status == "done"
    print("  ✓ OK — não pediu confirmação")


if __name__ == "__main__":
    try:
        teste_confirma_aprovado()
        teste_confirma_recusado()
        teste_bloqueia_sem_callback()
        teste_tool_normal_nao_pede_confirmacao()
        print("\ntudo passou.")
    finally:
        agent_loop._call_model = ORIGINAL_CALL_MODEL
