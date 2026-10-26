"""Regressão: constantes usadas pelo build da TUI existem no agent_loop."""

from agent_loop import MAX_STEPS_TASK, MAX_STEPS_TASK_NUVEM


def test_constantes_de_steps_do_build():
    assert MAX_STEPS_TASK == 9
    assert MAX_STEPS_TASK_NUVEM == 12
