"""
Capabilities que uma fonte de input pode possuir.

Começamos com duas — conversation e user_instruction — que cobrem
o caso inicial (terminal local). As demais estão listadas como
referência pra quando o Ciel crescer pra web/mobile/server.

Regra fundamental:
    Somente o runtime pode criar ou promover conteúdo a USER_INSTRUCTION.
    O LLM não pode fazer essa promoção a partir de conteúdo externo.
"""

# ── capabilities v0 ────────────────────────────────────────────────────────
CONVERSATION     = "conversation"      # pode enviar conteúdo pro agente
USER_INSTRUCTION = "user_instruction"  # pode originar instrução legítima do usuário

# ── capabilities futuras (referência) ──────────────────────────────────────
# TOOL_EXECUTION   = "tool_execution"
# ADMIN            = "admin"
# CONFIGURATION    = "configuration"
# MEMORY_WRITE     = "memory_write"
# AGENT_MANAGEMENT = "agent_management"

# conjunto mínimo que toda fonte deve ter pra ser útil
MINIMUM = {CONVERSATION}

# conjunto completo que o terminal local possui
TERMINAL_FULL = {CONVERSATION, USER_INSTRUCTION}
