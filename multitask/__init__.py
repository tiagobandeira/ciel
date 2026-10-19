"""Modo multitask do Ciel: fluxos, quadro, runner e relatório.

Pacote livre de UI — CLI, TUI, server e bots consomem as mesmas peças.

    from multitask.flow import load_flow, build_board
    from multitask.runner import run_board
    from multitask.report import build_report

    flow  = load_flow("exemplo_site")
    board = build_board(flow)
    result = run_board(board, tools, schema, agent_info)
    print(result.message)
"""

from multitask.flow import Flow, FlowError, build_board, list_flows, load_flow
from multitask.report import build_report
from multitask.runner import RunResult, run_board

__all__ = [
    "Flow",
    "FlowError",
    "load_flow",
    "list_flows",
    "build_board",
    "RunResult",
    "run_board",
    "build_report",
]
