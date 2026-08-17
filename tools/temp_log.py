"""Registra uso de tool temporária no temp-log.md e sugere promoção se uso frequente."""

import re
from pathlib import Path
from datetime import datetime

TEMP_LOG       = Path(__file__).parent / "tools" / "temp" / "temp-log.md"
PROMOTE_AFTER  = 5  # usos antes de sugerir promoção


def run(tool_name: str) -> str:
    """
    tool_name: nome da tool temporária que foi executada
    """
    if not TEMP_LOG.exists():
        return f"temp-log.md não encontrado. Tool '{tool_name}' não registrada."

    today   = datetime.now().strftime("%Y-%m-%d")
    content = TEMP_LOG.read_text(encoding="utf-8")
    lines   = content.splitlines()

    header_done = False
    new_lines   = []
    updated     = False
    usos_atual  = 0

    for line in lines:
        if line.startswith("| tool ") or line.startswith("|---"):
            new_lines.append(line)
            header_done = True
            continue

        if header_done and line.startswith(f"| {tool_name} |"):
            # atualiza linha existente
            parts = [p.strip() for p in line.split("|")]
            # parts: ['', tool, criada, usos, ultimo_uso, '']
            try:
                usos_atual = int(parts[3]) + 1
            except (ValueError, IndexError):
                usos_atual = 1
            parts[3] = str(usos_atual)
            parts[4] = today
            new_lines.append("| " + " | ".join(parts[1:-1]) + " |")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        # tool não estava no log — adiciona
        new_lines.append(f"| {tool_name} | ? | 1 | {today} |")
        usos_atual = 1

    TEMP_LOG.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    msg = f"Uso registrado: '{tool_name}' ({usos_atual}x)."
    if usos_atual >= PROMOTE_AFTER:
        msg += f" ⚡ Usada {usos_atual}x — considere promover para tools permanentes com /promover {tool_name}."

    return msg
