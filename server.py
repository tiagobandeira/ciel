"""
Servidor web local do agente — acesso via browser/celular na rede local.

Uso:
  python server.py
  python server.py --agent general --model gemma4:cloud --port 5000
"""

import argparse
import base64
import mimetypes
import socket
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS

from agent_loader import filter_tools, list_agents, load_agent
from cli import _build_create_instruction, _reload_tools, run_agent
from tools_registry import load_tools, tools_schema

DEFAULT_MODEL = "gemma4:cloud"#"gemma4:e2b-it-qat"
DEFAULT_AGENT = "general"
DEFAULT_PORT  = 5000
UNSAFE_TOOLS  = {"run_script"}
PROJECT_ROOT  = Path(__file__).parent.resolve()

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
CORS(app)
state: dict = {}


def init_state(agent_name: str, model: str, safe: bool):
    agent_info = load_agent(agent_name)
    all_tools  = load_tools()
    tools      = filter_tools(all_tools, agent_info["allowed_tools"])
    if safe:
        tools = {k: v for k, v in tools.items() if k not in UNSAFE_TOOLS}
    (PROJECT_ROOT / "data" / "user").mkdir(parents=True, exist_ok=True)
    state.update({
        "agent_info":       agent_info,
        "model":            model,
        "safe":             safe,
        "tools":            tools,
        "schema":           tools_schema(tools),
        "history":          [],
        "pending_proposal": None,
    })


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/info")
def info():
    return jsonify({
        "agent": state["agent_info"]["name"],
        "model": state["model"],
        "tools": [
            {"name": k, "desc": v["description"].split("\n")[0][:60], "cat": v.get("categoria", "permanente")}
            for k, v in state["tools"].items()
        ],
    })


@app.route("/chat", methods=["POST"])
def chat():
    data       = request.get_json(force=True)
    user_input = (data.get("message") or "").strip()
    image_b64  = data.get("image_b64")
    file_text  = data.get("file_text")
    filename   = data.get("filename", "arquivo")

    if not user_input and not image_b64 and not file_text:
        return jsonify({"error": "mensagem vazia"}), 400

    tools      = state["tools"]
    schema     = state["schema"]
    model      = state["model"]
    agent_info = state["agent_info"]
    history    = state["history"]

    # confirmacao de auto tool pendente
    if state["pending_proposal"]:
        proposal = state["pending_proposal"]
        resp = user_input.lower().strip()
        if resp in ("s", "sim", "yes"):
            choice = "s"
        elif resp in ("t", "temp", "temporária", "temporaria"):
            choice = "t"
        else:
            state["pending_proposal"] = None
            return jsonify({"reply": "Ok, tarefa encerrada sem criar a tool.", "status": "done"})

        result, new_tools, new_schema = _handle_auto_tool_web(
            proposal, choice, tools, schema, model, agent_info, history, state["safe"]
        )
        state["tools"]            = new_tools
        state["schema"]           = new_schema
        state["pending_proposal"] = None
        history.append({"role": "agent", "content": result})
        return jsonify({"reply": result, "status": "done"})

    # monta input efetivo
    effective_input = user_input
    img_b64_clean   = None

    if image_b64:
        # salva copia no disco
        img_path = PROJECT_ROOT / "uploads" / filename
        img_path.parent.mkdir(exist_ok=True)
        img_path.write_bytes(base64.b64decode(image_b64))
        # passa b64 direto ao modelo
        img_b64_clean   = image_b64
        effective_input = user_input or "Descreva e analise esta imagem."

    if file_text:
        effective_input = (
            f"{user_input}\n\n"
            f"Conteudo do arquivo '{filename}':\n```\n{file_text[:6000]}\n```"
        )

    history.append({"role": "user", "content": effective_input})
    web_url = state.get("web_base_url", "")
    result = run_agent(
        effective_input, tools, schema, model, agent_info,
        history=history[:-1], image_b64=img_b64_clean, web_base_url=web_url,
    )

    if isinstance(result, dict) and result.get("status") == "needs_tool":
        proposal = result["proposal"]
        state["pending_proposal"] = proposal
        params = ", ".join(
            f"{p['nome']} ({p.get('tipo','str')})" for p in proposal.get("parametros", [])
        )
        msg = (
            f"Nao consegui completar a tarefa com as tools disponiveis.\n\n"
            f"Posso criar uma nova tool:\n"
            f"**{proposal['nome']}** - {proposal['descricao']}\n"
            f"Parametros: {params or 'nenhum'}\n\n"
            f"Responda:\n"
            f"- **s** - criar e salvar permanente\n"
            f"- **t** - criar como temporaria\n"
            f"- qualquer outra coisa - cancelar"
        )
        return jsonify({"reply": msg, "status": "needs_tool"})

    history.append({"role": "agent", "content": result})
    return jsonify({"reply": result, "status": "done"})


@app.route("/download")
def download():
    rel_path = request.args.get("path", "")
    if not rel_path:
        return jsonify({"error": "path nao informado"}), 400
    try:
        full_path = (PROJECT_ROOT / rel_path).resolve()
        full_path.relative_to(PROJECT_ROOT)
    except (ValueError, Exception):
        return jsonify({"error": "path invalido"}), 400

    if not full_path.exists() or not full_path.is_file():
        return jsonify({"error": f"arquivo nao encontrado: {rel_path}"}), 404

    mime = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
    return send_file(full_path, mimetype=mime, as_attachment=False)


@app.route("/clear", methods=["POST"])
def clear():
    state["history"].clear()
    state["pending_proposal"] = None
    return jsonify({"ok": True})


@app.route("/agents")
def agents():
    result = []
    for a in list_agents():
        try:
            info = load_agent(a)
            result.append({"name": a, "desc": info["description"][:70]})
        except Exception:
            result.append({"name": a, "desc": ""})
    return jsonify(result)


@app.route("/switch", methods=["POST"])
def switch():
    data = request.get_json(force=True)
    try:
        init_state(data.get("agent", DEFAULT_AGENT), state["model"], state["safe"])
        return jsonify({"ok": True, "agent": state["agent_info"]["name"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def _handle_auto_tool_web(proposal, choice, tools, schema, model, agent_info, history, safe):
    tool_name        = proposal["nome"]
    is_temp          = (choice == "t")
    create_tool_name = "create_temp_tool" if is_temp else "create_tool"

    if create_tool_name not in tools:
        return f"Tool '{create_tool_name}' nao disponivel.", tools, schema

    create_instruction = _build_create_instruction(proposal)
    if is_temp:
        create_instruction += " Use a tool 'create_temp_tool' para salvar."

    tools_criacao = {k: v for k, v in tools.items()
                     if k != ("create_tool" if is_temp else "create_temp_tool")}

    create_result = run_agent(
        create_instruction, tools_criacao, tools_schema(tools_criacao),
        model, agent_info, history=None,
    )
    create_msg = create_result if isinstance(create_result, str) else "?"

    tools_antes           = set(tools.keys())
    new_tools, new_schema = _reload_tools(agent_info, safe)
    tools_novas           = set(new_tools.keys()) - tools_antes
    tool_criada           = tool_name if tool_name in new_tools else (
        next(iter(tools_novas)) if len(tools_novas) == 1 else None
    )

    if not tool_criada:
        return f"Criacao da tool falhou. Detalhe: {create_msg}", new_tools, new_schema

    original_input = history[-2]["content"] if len(history) >= 2 else ""
    retry = run_agent(original_input, new_tools, new_schema, model, agent_info, history=history[:-1])

    if isinstance(retry, dict):
        return "Tarefa nao concluida mesmo apos criar a tool.", new_tools, new_schema

    return retry, new_tools, new_schema


def main():
    parser = argparse.ArgumentParser(description="Agent Web Server")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--agent", default=DEFAULT_AGENT)
    parser.add_argument("--port",  default=DEFAULT_PORT, type=int)
    parser.add_argument("--safe",  action="store_true")
    args = parser.parse_args()

    try:
        init_state(args.agent, args.model, args.safe)
    except FileNotFoundError as e:
        print(f"Erro: {e}")
        return

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "127.0.0.1"

    print(f"\n  Agent Web Server")
    print(f"  agente : {state['agent_info']['name']}")
    print(f"  modelo : {args.model}")
    print(f"  tools  : {len(state['tools'])}")
    print(f"\n  local  : http://localhost:{args.port}")
    print(f"  rede   : http://{local_ip}:{args.port}  <- acesse pelo celular\n")

    # guarda URL base pra injetar no system prompt
    state["web_base_url"] = f"http://{local_ip}:{args.port}"

    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=False)


if __name__ == "__main__":
    main()