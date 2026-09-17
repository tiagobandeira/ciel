"""
Contratos de dados da camada de proveniência.

InputEnvelope  — representa todo input antes de ser verificado.
                 Criado pelo componente que recebe a entrada
                 (harness de terminal, futuramente web/mobile).

VerifiedInput  — resultado após verificação. É isso que o agente recebe.
                 O envelope completo (source_id, signature, session_id)
                 fica no runtime e nunca vai pro LLM.

Regra: o usuário fornece apenas `payload`.
       source_type, source_id, signature e capabilities são
       atribuídos pelo runtime, nunca pelo conteúdo do texto.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class InputEnvelope:
    payload:     str
    source_type: str
    source_id:   str
    session_id:  str
    signature:   str | None = None


@dataclass
class VerifiedInput:
    payload:      str
    source_type:  str
    source_id:    str
    trusted:      bool
    capabilities: set[str] = field(default_factory=set)

    def can(self, capability: str) -> bool:
        """Verifica se essa entrada possui uma capability específica."""
        return capability in self.capabilities

    def is_user_instruction(self) -> bool:
        from trust.capabilities import USER_INSTRUCTION
        return self.trusted and USER_INSTRUCTION in self.capabilities
