"""
server.py — Ciel web server
Compatível com cli.py atualizado. Expõe /api/* para o frontend.

Rotas:
  GET  /                    → index.html
  GET  /static/<path>       → arquivos estáticos
  GET  /api/info            → agente, modelo, tools, versão
  POST /api/chat            → executa turno do agente
  POST /api/clear           → limpa histórico
  GET  /api/agents          → lista agentes disponíveis
  POST /api/agent           → troca de agente
  GET  /api/tasks           → lista tasks disponíveis
  GET  /api/sessions        → histórico de sessões salvas
  GET  /api/session/<id>    → turnos de uma sessão
  POST /api/session/save    → salva sessão atual
  POST /api/source          → indexa arquivo/URL como fonte
  GET  /api/sources         → lista fontes da sessão atual
  DELETE /api/source/<id>   → remove fonte
  GET  /download            → download de arquivo gerado

Uso:
  python server.py
  python server.py --agent dev_helper --model gemma4:cloud --port 5000
"""

import sys
import json
import base64
import argparse
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, send_file, abort

# ── garante que o root do projeto está no path ─────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from tools_registry import load_tools, tools_schema
from agent_loader   import load_agent, filter_tools, list_agents
from history_store  import HistoryStore, DB_PATH
from history_ui     import build_context_injection

# ── config ──────────────────────────────────────────────────────────────────
DEFAULT_MODEL  = "gemma4:cloud"
DEFAULT_AGENT  = "general"
VERSION        = "2.0.0"
UNSAFE_TOOLS   = {"run_script"}

# Estes são importados do cli.py para reaproveitar toda a lógica
from cli import (
    run_agent, load_task, find_tasks, build_task_prompt,
    _reload_tools, _handle_auto_tool, _save_session,
    MAX_STEPS, MAX_STEPS_TASK,
)

# ── flask app ────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    static_folder=str(ROOT / "web" / "static"),
    template_folder=str(ROOT / "web" / "templates"),
)

# ── estado de sessão (in-memory, por processo) ───────────────────────────────
class AppState:
    def __init__(self, agent_id: str, model: str, safe: bool = False):
        self.model      = model
        self.safe       = safe
        self.history    = []          # list[dict]
        self.store      = HistoryStore(DB_PATH)
        self.session_id: int | None = None
        self.context_injection = None
        self.tokens_in  = 0
        self.tokens_out = 0
        # ── branch ───────────────────────────────────────────────────────────
        # Quando o usuário abre uma sessão existente, ficamos em modo leitura.
        # No primeiro input do usuário, criamos a branch automaticamente.
        self.branch_pending: int | None = None   # id da sessão pai (None = não pendente)
        self._load_agent(agent_id)

    def _load_agent(self, agent_id: str):
        self.agent_id   = agent_id
        self.agent_info = load_agent(agent_id)
        all_tools       = load_tools()
        self.tools      = filter_tools(all_tools, self.agent_info["allowed_tools"])
        if self.safe:
            self.tools = {k: v for k, v in self.tools.items() if k not in UNSAFE_TOOLS}
        self.schema = tools_schema(self.tools)

    def switch_agent(self, agent_id: str):
        self.history.clear()
        self.session_id        = None
        self.context_injection = None
        self.branch_pending    = None
        self.tokens_in         = 0
        self.tokens_out        = 0
        self._load_agent(agent_id)

    def new_session(self):
        self.history.clear()
        self.session_id        = None
        self.context_injection = None
        self.branch_pending    = None
        self.tokens_in         = 0
        self.tokens_out        = 0

    def enter_view_mode(self, parent_session_id: int):
        """
        Prepara o estado para visualização de uma sessão existente.
        O history em memória fica vazio — será populado pela branch
        no primeiro input do usuário.
        """
        self.history.clear()
        self.session_id        = None
        self.context_injection = None
        self.branch_pending    = parent_session_id
        self.tokens_in         = 0
        self.tokens_out        = 0

    def create_branch(self) -> tuple[int, str]:
        """
        Cria a branch da sessão pai e prepara o context_injection.
        Retorna (novo_session_id, aviso_para_o_chat).
        """
        parent_id   = self.branch_pending
        self.branch_pending = None

        parent = self.store.get_session(parent_id)
        if not parent:
            # sessão pai sumiu — abre sessão nova normalmente
            return None, None

        # cria sessão filha
        branch_id = self.store.branch_session(parent_id, self.agent_id)
        self.session_id = branch_id

        # injeta contexto: usa resumo se existir, senão avisa que não há
        summary = parent["summary"] or ""
        if summary:
            self.context_injection = build_context_injection(
                summary       = summary,
                session_title = parent["title"] or f"sessão #{parent_id}",
                agent_id      = parent["agent_id"],
            )

        notice = (
            f"↪ branch criada a partir de **#{parent_id}** "
            f"— {parent['title'] or 'sem título'}"
            + (" · contexto injetado" if summary else " · sem resumo disponível")
        )
        return branch_id, notice

    @property
    def base_url(self):
        return request.host_url.rstrip('/')

    def tools_as_list(self):
        return [
            {
                "name": name,
                "desc": meta.get("description", "").split("\n")[0][:80],
                "cat":  meta.get("categoria", "permanente"),
            }
            for name, meta in sorted(self.tools.items())
        ]


# Inicializado no startup
state: AppState = None


# ── rotas estáticas ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)

@app.route("/download")
def download():
    path = request.args.get("path", "")
    if not path:
        abort(400)
    full = ROOT / path
    if not full.exists() or not full.is_file():
        abort(404)
    # segurança: só permite paths dentro do ROOT
    try:
        full.relative_to(ROOT)
    except ValueError:
        abort(403)
    return send_file(str(full), as_attachment=True, download_name=full.name)


# ── /api/info ─────────────────────────────────────────────────────────────────
@app.route("/api/info")
def api_info():
    return jsonify({
        "agent":      state.agent_id,
        "agent_full": state.agent_info.get("name", state.agent_id),
        "agent_desc": state.agent_info.get("description", ""),
        "model":      state.model,
        "version":    VERSION,
        "tools":      state.tools_as_list(),
    })


# ── /api/chat ─────────────────────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data        = request.get_json(force=True)
    user_input  = data.get("message", "").strip()
    image_b64   = data.get("image_b64")
    file_text   = data.get("file_text")
    filename    = data.get("filename", "arquivo")

    if not user_input and not image_b64 and not file_text:
        return jsonify({"error": "mensagem vazia"}), 400

    # monta entrada real
    if file_text:
        user_input = (
            f"{user_input}\n\n"
            f"<arquivo nome=\"{filename}\">\n{file_text[:12000]}\n</arquivo>"
        ) if user_input else f"<arquivo nome=\"{filename}\">\n{file_text[:12000]}\n</arquivo>"

    # ── comandos especiais (/task, /tools, /tokens, /history ...) ────────────
    if user_input.startswith("/"):
        reply, changed = handle_command(user_input)
        return jsonify({
            "status":       "done",
            "reply":        reply,
            "tools_changed": changed,
            "session_id":   state.session_id,
        })

    # ── branch automática no primeiro input após visualização ────────────────
    branch_notice = None
    if state.branch_pending is not None:
        parent_id_for_sources = state.branch_pending   # captura antes do create_branch zerar
        _, branch_notice = state.create_branch()
        _copy_session_sources(parent_id_for_sources, str(state.session_id))

    # ── turno normal ──────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%a %H:%M")
    state.history.append({"role": "user", "content": user_input, "ts": ts})

    # salva turno user em tempo real
    if state.session_id is None:
        state.session_id = state.store.new_session(
            agent_id=state.agent_id,
            title="",
        )
    state.store.append_turn(state.session_id, "user", user_input, ts)

    # auto-título
    sess = state.store.get_session(state.session_id)
    if sess and not sess["title"]:
        auto_title = " ".join(user_input.split()[:8])
        state.store.update_title(state.session_id, auto_title)

    result, t_in, t_out = run_agent(
        user_input,
        state.tools,
        state.schema,
        state.model,
        state.agent_info,
        history=state.history[:-1],
        image_b64=image_b64,
        web_base_url=state.base_url,
        context_injection=state.context_injection,
        session_id=str(state.session_id) if state.session_id else None,
    )

    state.tokens_in  += t_in
    state.tokens_out += t_out
    state.context_injection = None  # limpa após primeiro uso

    tools_changed = False

    # auto tool
    if isinstance(result, dict) and result.get("status") == "needs_tool":
        proposal = result.get("proposal", {})
        reply    = (
            f"⚡ **Auto Tool**\n\n"
            f"O agente precisa de uma nova tool para concluir esta tarefa:\n\n"
            f"- **nome:** `{proposal.get('nome','?')}`\n"
            f"- **função:** {proposal.get('descricao','?')}\n\n"
            f"Use `/criar-tool {proposal.get('nome','')}` para criar permanente "
            f"ou `/criar-tool-temp {proposal.get('nome','')}` para temporária."
        )
        return jsonify({
            "status":   "needs_tool",
            "reply":    reply,
            "proposal": proposal,
            "tokens_in":  t_in,
            "tokens_out": t_out,
            "session_id": state.session_id,
        })

    final_reply = result if isinstance(result, str) else str(result)

    ts = datetime.now().strftime("%a %H:%M")
    state.history.append({"role": "agent", "content": final_reply, "ts": ts})
    state.store.append_turn(state.session_id, "agent", final_reply, ts)

    return jsonify({
        "status":        "done",
        "reply":         final_reply,
        "branch_notice": branch_notice,
        "tokens_in":     t_in,
        "tokens_out":    t_out,
        "tools_changed": tools_changed,
        "session_id":    state.session_id,
    })


# ── handler de comandos internos ──────────────────────────────────────────────
def handle_command(cmd: str) -> tuple[str, bool]:
    """
    Processa /comandos do frontend.
    Retorna (reply_str, tools_changed_bool).
    """
    changed = False

    # /task
    if cmd.startswith("/task"):
        parts = cmd.split(None, 1)
        arg   = parts[1].strip() if len(parts) > 1 else ""

        if not arg:
            tasks = list(Path("tasks").glob("*.md")) if Path("tasks").exists() else []
            if not tasks:
                return "nenhuma task em `tasks/`", False
            lines = ["**tasks disponíveis:**\n"]
            for t in sorted(tasks):
                td  = load_task(t)
                obj = td["objetivo"][:60] if td else "formato inválido"
                lines.append(f"- `{t.stem}` — {obj}")
            return "\n".join(lines), False

        task_path = Path(arg) if arg.endswith(".md") else Path("tasks") / f"{arg}.md"
        if not task_path.exists():
            candidates = find_tasks(arg, Path("tasks"))
            if not candidates:
                return f"task `{arg}` não encontrada.", False
            task_path = candidates[0]

        task = load_task(task_path)
        if not task:
            return f"arquivo `{task_path.name}` não segue o formato de task.", False

        task_prompt = build_task_prompt(task)
        ts = datetime.now().strftime("%a %H:%M")
        state.history.append({"role": "user", "content": f"/task {task['nome']}", "ts": ts})

        result, t_in, t_out = run_agent(
            task_prompt,
            state.tools,
            state.schema,
            state.model,
            state.agent_info,
            history=state.history[:-1],
            web_base_url=state.base_url,
            session_id=str(state.session_id) if state.session_id else None,
            max_steps=MAX_STEPS_TASK,
        )
        state.tokens_in  += t_in
        state.tokens_out += t_out

        if isinstance(result, dict) and result.get("status") == "needs_tool":
            return "⚠ A task requer uma tool que ainda não existe.", False

        final = result if isinstance(result, str) else str(result)
        ts = datetime.now().strftime("%a %H:%M")
        state.history.append({"role": "agent", "content": final, "ts": ts})
        if state.session_id:
            state.store.append_turn(state.session_id, "agent", final, ts)
        return final, changed

    # /tools
    if cmd == "/tools":
        lines = ["**tools ativas:**\n"]
        for name, meta in sorted(state.tools.items()):
            cat  = meta.get("categoria", "permanente")
            desc = meta.get("description", "").split("\n")[0][:60]
            badge = " `[temp]`" if cat == "temp" else ""
            lines.append(f"- `{name}`{badge} — {desc}")
        return "\n".join(lines), False

    # /tokens
    if cmd == "/tokens":
        total = state.tokens_in + state.tokens_out
        return (
            f"**tokens desta sessão:**\n\n"
            f"- entrada: `{state.tokens_in:,}`\n"
            f"- saída: `{state.tokens_out:,}`\n"
            f"- total: `{total:,}`"
        ), False

    # /history salvar
    if cmd == "/history salvar":
        if not state.history:
            return "nenhuma conversa para salvar.", False
        # importa Console dummy para _save_session
        class _DummyConsole:
            def print(self, *a, **kw): pass
        import types
        dummy = _DummyConsole()
        sid = _save_session(
            state.store, state.history, state.agent_info,
            state.model, state.agent_id, dummy,
            existing_session_id=state.session_id,
        )
        state.session_id = sid
        return f"sessão #{sid} salva.", False

    # /history exportar
    if cmd == "/history exportar":
        if not state.session_id:
            return "salve a conversa primeiro com `/history salvar`", False
        try:
            out = state.store.export_markdown(state.session_id)
            return f"exportado: `{out}`", False
        except Exception as e:
            return f"erro ao exportar: {e}", False

    # /novo
    if cmd == "/novo":
        state.new_session()
        return "nova sessão iniciada.", False

    # /limpar-temp
    if cmd == "/limpar-temp":
        temp_dir = Path("tools/temp")
        removidas = []
        for f in temp_dir.glob("*.py"):
            if f.name != "__init__.py":
                f.unlink()
                removidas.append(f.stem)
        if removidas:
            state.tools, state.schema = _reload_tools(state.agent_info, state.safe)
            changed = True
            return f"tools temp removidas: {', '.join(removidas)}", True
        return "nenhuma tool temporária encontrada.", False

    # /source --listar
    if cmd == "/source --listar":
        try:
            from knowledge.db import list_sources
            sources = list_sources(
                agent_id=state.agent_id,
                session_id=str(state.session_id) if state.session_id else None,
            )
            if not sources:
                return "nenhuma fonte indexada.", False
            lines = [f"**{len(sources)} fonte(s):**\n"]
            for s in sources:
                scope = "global" if s["session_id"] == "_shared" else f"sessão {s['session_id']}"
                lines.append(f"- `{s['filename']}` ({s['n_chunks']} chunks · {scope})")
            return "\n".join(lines), False
        except Exception as e:
            return f"erro: {e}", False

    return f"comando `{cmd}` não reconhecido pelo servidor.", False


# ── /api/clear ────────────────────────────────────────────────────────────────
@app.route("/api/clear", methods=["POST"])
def api_clear():
    state.new_session()
    return jsonify({"ok": True})


# ── /api/agents ───────────────────────────────────────────────────────────────
@app.route("/api/agents")
def api_agents():
    agents = []
    for aid in list_agents():
        try:
            info = load_agent(aid)
            agents.append({
                "id":          aid,
                "name":        info.get("name", aid),
                "description": info.get("description", "")[:80],
            })
        except Exception:
            agents.append({"id": aid, "name": aid, "description": ""})
    return jsonify({"agents": agents})


# ── /api/agent (POST) ─────────────────────────────────────────────────────────
@app.route("/api/agent", methods=["POST"])
def api_switch_agent():
    data     = request.get_json(force=True)
    agent_id = data.get("agent", "").strip()
    if not agent_id:
        return jsonify({"error": "agent_id vazio"}), 400
    try:
        state.switch_agent(agent_id)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({
        "ok":         True,
        "agent":      state.agent_id,
        "agent_full": state.agent_info.get("name", state.agent_id),
        "agent_desc": state.agent_info.get("description", ""),
        "tools":      state.tools_as_list(),
    })


# ── /api/tasks ────────────────────────────────────────────────────────────────
@app.route("/api/tasks")
def api_tasks():
    tasks_dir = Path("tasks")
    if not tasks_dir.exists():
        return jsonify({"tasks": []})
    tasks = []
    for p in sorted(tasks_dir.glob("*.md")):
        td = load_task(p)
        if td:
            tasks.append({
                "id":        p.stem,
                "name":      td["nome"],
                "objective": td["objetivo"][:80],
            })
    return jsonify({"tasks": tasks})


# ── /api/sessions ─────────────────────────────────────────────────────────────
@app.route("/api/sessions")
def api_sessions():
    agent_filter = request.args.get("agent")
    rows = state.store.list_sessions(agent_filter)
    sessions = [
        {
            "id":                row["id"],
            "agent_id":          row["agent_id"],
            "title":             row["title"] or "",
            "summary":           (row["summary"] or "")[:120],
            "created_at":        row["created_at"][:16],
            "updated_at":        row["updated_at"][:16],
            "turn_count":        row["turn_count"],
            "parent_session_id": row["parent_session_id"],
        }
        for row in rows
    ]
    return jsonify({"sessions": sessions})


# ── helper: copia referências de fontes da sessão pai ────────────────────────
def _copy_session_sources(parent_session_id: int | None, new_session_id: str):
    """
    Duplica no knowledge.db as referências de fontes da sessão pai
    para a sessão da branch, sem reindexar os arquivos.
    """
    if parent_session_id is None:
        return
    try:
        from knowledge.db import get_conn
        kconn = get_conn()
        rows = kconn.execute(
            "SELECT * FROM sources WHERE session_id=?",
            (str(parent_session_id),),
        ).fetchall()
        for row in rows:
            # insere com novo session_id; ignora se já existe
            kconn.execute(
                """
                INSERT OR IGNORE INTO sources
                    (filename, filepath, agent_id, session_id, n_chunks, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["filename"], row["filepath"], row["agent_id"],
                    new_session_id,  row["n_chunks"],  row["summary"],
                    row["created_at"],
                ),
            )
        kconn.commit()
        kconn.close()
    except Exception:
        pass   # fontes são melhorias, não impedem a branch de funcionar


# ── /api/session/<id>/load ────────────────────────────────────────────────────
@app.route("/api/session/<int:session_id>/load", methods=["POST"])
def api_load_session(session_id):
    """
    Abre uma sessão existente em modo leitura + prepara branch.
    - Muda o agente se necessário (sem resetar tools desnecessariamente)
    - Seta branch_pending no estado
    - Retorna turns, info do agente e fontes da sessão
    """
    sess = state.store.get_session(session_id)
    if not sess:
        return jsonify({"error": "sessão não encontrada"}), 404

    # troca de agente se necessário (sem limpar branch_pending ainda)
    if sess["agent_id"] != state.agent_id:
        state._load_agent(sess["agent_id"])

    # entra em modo leitura
    state.enter_view_mode(session_id)

    # turnos para exibição
    turn_rows = state.store.get_turns(session_id)
    turns = [
        {"id": t["id"], "role": t["role"], "content": t["content"], "ts": t["ts"]}
        for t in turn_rows
    ]

    # fontes desta sessão
    sources = []
    try:
        from knowledge.db import list_sources
        raw = list_sources(agent_id=sess["agent_id"], session_id=str(session_id))
        sources = [
            {
                "id":       s["id"],
                "filename": s["filename"],
                "n_chunks": s["n_chunks"],
                "scope":    "sessão",
            }
            for s in raw
        ]
    except Exception:
        pass

    # dados da sessão pai (se for branch)
    parent_info = None
    if sess["parent_session_id"]:
        parent_row = state.store.get_session(sess["parent_session_id"])
        if parent_row:
            parent_info = {
                "id":          parent_row["id"],
                "title":       parent_row["title"] or "",
                "summary":     parent_row["summary"] or "",
                "has_summary": bool(parent_row["summary"]),
            }

    return jsonify({
        "ok":           True,
        "session":      {
            "id":                sess["id"],
            "agent_id":          sess["agent_id"],
            "title":             sess["title"] or "",
            "summary":           sess["summary"] or "",
            "created_at":        sess["created_at"][:16],
            "updated_at":        sess["updated_at"][:16],
            "has_summary":       bool(sess["summary"]),
            "parent_session_id": sess["parent_session_id"],
        },
        "parent":       parent_info,
        "turns":        turns,
        "sources":      sources,
        "agent":        state.agent_id,
        "agent_full":   state.agent_info.get("name", state.agent_id),
        "agent_desc":   state.agent_info.get("description", ""),
        "tools":        state.tools_as_list(),
        "branch_pending": session_id,
    })
@app.route("/api/session/<int:session_id>")
def api_get_session(session_id):
    sess_row  = state.store.get_session(session_id)
    turn_rows = state.store.get_turns(session_id)

    if not sess_row:
        return jsonify({"error": "sessão não encontrada"}), 404

    session = {
        "id":         sess_row["id"],
        "agent_id":   sess_row["agent_id"],
        "title":      sess_row["title"] or "",
        "summary":    sess_row["summary"] or "",
        "created_at": sess_row["created_at"][:16],
        "updated_at": sess_row["updated_at"][:16],
    }
    turns = [
        {
            "id":      t["id"],
            "role":    t["role"],
            "content": t["content"],
            "ts":      t["ts"],
        }
        for t in turn_rows
    ]
    return jsonify({"session": session, "turns": turns})


# ── /api/session/<id> DELETE ──────────────────────────────────────────────────
@app.route("/api/session/<int:session_id>", methods=["DELETE"])
def api_delete_session(session_id):
    sess = state.store.get_session(session_id)
    if not sess:
        return jsonify({"error": "sessão não encontrada"}), 404

    state.store.delete_session(session_id)

    # se a sessão deletada era a atual, reseta o estado
    if state.session_id == session_id:
        state.new_session()

    return jsonify({"ok": True, "deleted": session_id})


# ── /api/source/upload (POST) ─────────────────────────────────────────────────
@app.route("/api/source/upload", methods=["POST"])
def api_upload_source():
    """
    Recebe um arquivo via multipart/form-data, salva em data/user/sources/
    e indexa no knowledge.db exatamente como /api/source faria com um caminho local.
    """
    if "file" not in request.files:
        return jsonify({"error": "nenhum arquivo enviado"}), 400

    f         = request.files["file"]
    is_global = request.form.get("global", "false").lower() in ("true", "1", "on")
    aid       = state.agent_id

    # destino: data/user/sources/<filename>
    save_dir = ROOT / "data" / "user" / "sources"
    save_dir.mkdir(parents=True, exist_ok=True)
    dest = save_dir / f.filename
    # evita sobrescrever: adiciona sufixo se já existir
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while dest.exists():
            dest = save_dir / f"{stem}_{i}{suffix}"
            i += 1
    f.save(str(dest))

    # resolve escopo
    if is_global:
        sid = "_shared"
    else:
        if state.session_id is None:
            state.session_id = state.store.new_session(
                agent_id=aid,
                title=f"sessão {datetime.now().strftime('%d/%m %H:%M')}",
            )
        sid = str(state.session_id)

    try:
        from knowledge.ingest import ingest
        source_id = ingest(filepath=str(dest), agent_id=aid, session_id=sid, verbose=False)
        return jsonify({"ok": True, "source_id": source_id, "saved_as": str(dest)})
    except Exception as e:
        # remove arquivo se a indexação falhou
        dest.unlink(missing_ok=True)
        return jsonify({"error": str(e)}), 500


# ── /api/source ───────────────────────────────────────────────────────────────
@app.route("/api/source", methods=["POST"])
def api_add_source():
    data      = request.get_json(force=True)
    path      = data.get("path", "").strip()
    is_global = data.get("global", False)

    if not path:
        return jsonify({"error": "path vazio"}), 400

    aid = state.agent_id
    if is_global:
        sid = "_shared"
    else:
        if state.session_id is None:
            state.session_id = state.store.new_session(
                agent_id=aid,
                title=f"sessão {datetime.now().strftime('%d/%m %H:%M')}",
            )
        sid = str(state.session_id)

    try:
        if path.startswith(("http://", "https://")):
            from knowledge.ingest_url import ingest_url
            source_id = ingest_url(url=path, agent_id=aid, session_id=sid, verbose=False)
        else:
            from knowledge.ingest import ingest
            source_id = ingest(filepath=path, agent_id=aid, session_id=sid, verbose=False)
        return jsonify({"ok": True, "source_id": source_id})
    except FileNotFoundError:
        return jsonify({"error": f"arquivo não encontrado: {path}"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /api/sources ──────────────────────────────────────────────────────────────
@app.route("/api/sources")
def api_list_sources():
    try:
        from knowledge.db import list_sources
        sources = list_sources(
            agent_id=state.agent_id,
            session_id=str(state.session_id) if state.session_id else None,
        )
        result = []
        for s in sources:
            scope = "global" if s["session_id"] == "_shared" else f"sessão {s['session_id']}"
            result.append({
                "id":       s["id"],
                "filename": s["filename"],
                "n_chunks": s["n_chunks"],
                "scope":    scope,
                "summary":  (s.get("summary") or "")[:100],
            })
        return jsonify({"sources": result})
    except Exception as e:
        return jsonify({"sources": [], "error": str(e)})


# ── /api/source/<id> DELETE ───────────────────────────────────────────────────
@app.route("/api/source/<int:source_id>", methods=["DELETE"])
def api_delete_source(source_id):
    try:
        from knowledge.db import get_source, delete_source
        source = get_source(source_id)
        if not source:
            return jsonify({"error": "fonte não encontrada"}), 404
        filepath = source.get("filepath", "")
        cache_path = Path(filepath)
        if "cache" in cache_path.parts:
            try:
                cache_path.unlink(missing_ok=True)
                if cache_path.parent.exists() and not any(cache_path.parent.iterdir()):
                    cache_path.parent.rmdir()
            except Exception:
                pass
        delete_source(source_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    global state

    parser = argparse.ArgumentParser(description="Ciel Web Server")
    parser.add_argument("--agent",  default=DEFAULT_AGENT)
    parser.add_argument("--model",  default=DEFAULT_MODEL)
    parser.add_argument("--port",   default=5000, type=int)
    parser.add_argument("--host",   default="0.0.0.0")
    parser.add_argument("--safe",   action="store_true")
    parser.add_argument("--debug",  action="store_true")
    args = parser.parse_args()

    try:
        state = AppState(args.agent, args.model, safe=args.safe)
    except FileNotFoundError as e:
        print(f"Erro: {e}")
        sys.exit(1)

    print(f"\n  ◈ ciel v{VERSION}")
    print(f"  agente : {state.agent_info.get('name', args.agent)}")
    print(f"  modelo : {args.model}")
    print(f"  tools  : {len(state.tools)}")
    print(f"  endereço: http://{args.host}:{args.port}\n")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()