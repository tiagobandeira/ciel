/* ═══════════════════════════════════════════════════════════════
   Ciel — app.js
   Frontend da interface web. Comunica com server.py via /api/*.
   ═══════════════════════════════════════════════════════════════ */

// ── estado global ─────────────────────────────────────────────
let pendingFile      = null;   // { file, dataUrl?, content?, type: 'image'|'text' }
let currentAgent     = null;   // string: id do agente ativo
let currentModel     = null;   // string
let currentSessionId = null;   // int | null — sessão onde o chat está acontecendo
let viewingSessionId = null;   // int | null — sessão destacada na sidebar (inclui modo leitura)
let tokenIn          = 0;
let tokenOut         = 0;
let rightPanelOpen   = true;
let currentTurn      = null;   // turn_id do turno em andamento (trace do SSE)
let turnoAtivo       = false;  // há um POST /api/chat em andamento
let cancelando       = false;  // "parar" já foi pedido, evita duplo clique
let perguntaPendente = null;   // { turnId, el } — pergunta de tool INTERACTIVE aguardando resposta
let _perguntaSeq     = 0;
const turnosFechados = new Set();

const IMAGE_EXTS = new Set(['png','jpg','jpeg','gif','webp','bmp','svg']);

// ── refs DOM ──────────────────────────────────────────────────
const messagesEl  = () => document.getElementById('messages');
const inputEl     = () => document.getElementById('msg-input');
const sendBtn     = () => document.getElementById('send-btn');

// ── init ──────────────────────────────────────────────────────
async function init() {
  try {
    const info = await api('/api/info');
    _infoCache = info;
    currentAgent = info.agent;
    currentModel = info.model;
    // Topbar
    setStatus('online');
    document.getElementById('topbar-agent').textContent = info.agent;
    document.getElementById('topbar-model').textContent = info.model;
    document.getElementById('version-badge').textContent = `v${info.version || '—'}`;

    // Sidebar agent card
    document.getElementById('sidebar-agent-name').textContent = info.agent_full || info.agent;
    document.getElementById('sidebar-agent-desc').textContent = info.agent_desc || '';
    document.getElementById('agent-avatar').textContent = (info.agent_full || info.agent)[0].toUpperCase();

    // Info panel
    document.getElementById('info-agent').textContent = info.agent;
    document.getElementById('info-model').textContent = info.model;
    setPerfilUI(info);

    // Tools: só a contagem — a lista vive em /tools e na paleta
    atualizarTools(info.tools);

    // Auth badge
    await updateAuthBadge(info);

    const safeHint = info.force_safe
      ? ' · 🔒 safe permanente'
      : (info.authenticated ? ' · 🔓 autenticado' : ' · 🔒 modo seguro');
    addSysMsg(`ciel · ${info.agent} · ${(info.tools||[]).length} tools${safeHint}`);

    // trace ao vivo: assina o SSE antes de qualquer turno
    initEventos();

    // Sessões + fontes da sessão
    await loadSessions();
    setEstadoSessao('nova');
    setRodapeLeitura(false);
    renderTokens();
    await refreshSources();
  } catch(e) {
    setStatus('error');
    addSysMsg('erro ao conectar — servidor rodando?');
  }
}

// ── API ───────────────────────────────────────────────────────
async function api(url, opts = {}) {
  // credentials: 'include' garante que o cookie ciel_auth é enviado
  // em requests para o mesmo origin (acesso via IP na rede local incluso)
  const r = await fetch(url, { credentials: 'include', ...opts });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    throw new Error(err.error || `HTTP ${r.status}`);
  }
  return r.json();
}

// ── status dot ────────────────────────────────────────────────
function setStatus(state) {
  const dot = document.getElementById('status-dot');
  dot.className = `status-dot ${state}`;
}

// ── Tokens ───────────────────────────────────────────────────
// O painel mostra o detalhamento (entrada/saída + total); a topbar só o total.
// Sessão salva não guarda tokens — ali o valor é "—" em vez de um 0 mentiroso.
let tokensDesconhecidos = false;

function updateTokenDisplay(dIn = 0, dOut = 0) {
  tokenIn  += dIn;
  tokenOut += dOut;
  renderTokens();
}

function setTokensDesconhecidos() {
  tokensDesconhecidos = true;
  renderTokens();
}

function renderTokens() {
  const total = tokenIn + tokenOut;
  const tin   = document.getElementById('info-tin');
  const tout  = document.getElementById('info-tout');
  const tot   = document.getElementById('info-total');
  if (!tin || !tout || !tot) return;

  const desconhecido = tokensDesconhecidos;
  tin.textContent  = desconhecido ? '—' : fmt(tokenIn);
  tout.textContent = desconhecido ? '—' : fmt(tokenOut);
  tot.textContent  = desconhecido ? '—' : fmt(total);

  const bar  = document.getElementById('rp-bar');
  const card = document.getElementById('rp-uso');
  const pill = document.getElementById('token-pill');
  const pillV = document.getElementById('token-total');

  if (bar) bar.classList.toggle('oculto', desconhecido);
  if (card) {
    card.classList.toggle('is-desconhecido', desconhecido);
    card.title = desconhecido ? 'tokens não foram salvos no histórico desta sessão' : '';
  }
  if (pillV) pillV.textContent = desconhecido ? '—' : fmt(total);
  if (pill) {
    pill.title = desconhecido
      ? 'tokens não foram salvos nesta sessão'
      : `tokens desta sessão · ${fmtCheio(tokenIn)} entrada · ${fmtCheio(tokenOut)} saída`;
  }

  if (!desconhecido && bar) {
    const pct = total ? Math.round((tokenIn / total) * 100) : 0;
    document.getElementById('bar-in').style.width  = (total ? pct : 0) + '%';
    document.getElementById('bar-out').style.width = (total ? 100 - pct : 0) + '%';
  }
}

/** 12.4k em pt-BR (vírgula decimal); inteiros ficam sem sufixo. */
function fmt(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(1).replace('.', ',')}k` : String(n);
}
function fmtCheio(n) {
  return Number(n).toLocaleString('pt-BR');
}

// ── Cabeçalho do painel: estado, título e modo ────────────────
function setEstadoSessao(estado) {
  const el = document.getElementById('sess-state');
  if (!el) return;
  el.className = `rp-state is-${estado}`;
  el.innerHTML = estado === 'leitura'
    ? `${icone('eye')}<span>leitura</span>`
    : `<i></i><span>${estado}</span>`;
}

/** Título (texto) e id (#56 | #—) da sessão no cabeçalho. */
function setTituloSessao(titulo, id) {
  const el = document.getElementById('sess-title');
  if (el) {
    el.textContent = titulo || 'conversa nova';
    el.title = titulo || 'conversa nova';
  }
  if (id !== undefined) {
    const sid = document.getElementById('info-session');
    if (sid) sid.textContent = id ? `#${id}` : '#—';
  }
}

/** Alterna o rodapé entre ações da sessão ativa e o "retomar" da leitura. */
function setRodapeLeitura(leitura) {
  document.getElementById('rp-foot-normal')?.classList.toggle('hidden', leitura);
  document.getElementById('rp-foot-leitura')?.classList.toggle('hidden', !leitura);
  document.getElementById('right-panel')?.classList.toggle('is-leitura', leitura);
}

window.retomarSessao = () => {
  const inp = inputEl();
  if (inp) {
    inp.placeholder = 'escreva para retomar esta sessão (branch automática)…';
    inp.focus();
  }
  scrollBottom();
};

// ── Mensagens ─────────────────────────────────────────────────
function addSysMsg(text) {
  const div = document.createElement('div');
  div.className = 'msg sys';
  div.innerHTML = `<div class="msg-bubble">${esc(text)}</div>`;
  messagesEl().appendChild(div);
  scrollBottom();
}

function addUserMsg(text, fileInfo = null) {
  const div = document.createElement('div');
  div.className = 'msg user';
  let content = renderMarkdown(text);
  if (fileInfo) {
    content += `<div style="margin-top:6px;font-size:11px;color:var(--muted);font-family:var(--font-mono)">📎 ${esc(fileInfo)}</div>`;
  }
  div.innerHTML = `
    <div class="msg-label">você</div>
    <div class="msg-bubble">
      <button class="copy-btn" onclick="copyBubble(this,'${escAttr(text)}')">copy</button>
      <div class="msg-body">${content}</div>
    </div>`;
  messagesEl().appendChild(div);
  scrollBottom();
}

function addAgentMsg(text, role = 'agent', arquivos = null) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const label = role === 'warn' ? '⚡ auto tool' : 'ciel';

  // detecta arquivos na resposta
  const refs = extractFileRefs(text);

  // o servidor já disse o que o turno gerou: para esses, só o chip (nome abre
  // a prévia, ↓ baixa). Sem isso a mesma resposta mostrava baixar + ver + chip.
  // Menção solta ("index.html" no meio do texto) não vira link: o caminho não
  // é um arquivo real e o /download devolveria 404.
  const lista = Array.isArray(arquivos) ? arquivos : [];
  const gerados = new Set(lista.map(a => String(a.path || '').toLowerCase()));
  // projeto gerado: os arquivos dentro dele também não viram link solto
  const pastas = lista.filter(a => a.dir).map(a => String(a.path || '').toLowerCase() + '/');
  const refsChat = refs.filter(p => {
    const alvo = previewPath(p);
    if (!alvo) return false;
    const baixo = alvo.toLowerCase();
    if (gerados.has(baixo)) return false;
    return !pastas.some(pasta => baixo.startsWith(pasta));
  });

  let dlLinks = '';
  if (refsChat.length) dlLinks = buildDownloadLinks(refsChat);

  // arquivos que o servidor viu sendo gerados (tool de escrita), sem regex
  const fileStrip = (window.Preview && Array.isArray(arquivos) && arquivos.length)
    ? Preview.strip(arquivos) : '';

  // imagens inline
  let imgBlocks = '';
  refs.filter(p => IMAGE_EXTS.has(p.split('.').pop().toLowerCase())).forEach(p => {
    imgBlocks += `<img class="msg-img" src="/download?path=${encodeURIComponent(p)}" 
                       onerror="this.remove()" alt="">`;
  });

  div.innerHTML = `
    <div class="msg-label">${label}</div>
    <div class="msg-bubble">
      <button class="copy-btn" onclick="copyBubble(this,\`${escAttr(text)}\`)">copy</button>
      <div class="msg-body">${renderMarkdown(text)}</div>
      ${dlLinks}${fileStrip}${imgBlocks}
    </div>`;
  messagesEl().appendChild(div);
  scrollBottom();
}

/* ── Trace ao vivo (SSE) ────────────────────────────────────────
   O POST /api/chat é bloqueante e devolve só a resposta final. O que
   aconteceu no meio do caminho chega por aqui, etiquetado com turn_id. */
function novoTurno() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID().slice(0, 18);
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

/* O botão de enviar vira "parar" (quadrado) enquanto o turno roda — padrão de
   outras interfaces e mais visível que um botão dentro do acordeão. */
function entrarModoParar() {
  const btn = sendBtn();
  btn.classList.add('parando');
  btn.innerHTML = '■';
  btn.title = 'parar';
  btn.setAttribute('aria-label', 'Parar o turno');
}

function sairModoParar() {
  const btn = sendBtn();
  turnoAtivo = false;
  cancelando = false;
  btn.classList.remove('parando');
  btn.style.opacity = '';
  btn.innerHTML = '↑';
  btn.title = 'enviar';
  btn.setAttribute('aria-label', 'Enviar');
  btn.disabled = false;
  // qualquer pergunta que tenha ficado sem resposta morre com o turno
  limparPensando();
  travarInput(false);
}

/* Para o turno em andamento. O server cancela no começo do próximo passo:
   a chamada ao modelo em curso não é interrompível. */
async function cancelarTurno(turno) {
  if (!turnoAtivo || cancelando) return;
  cancelando = true;
  sendBtn().style.opacity = '0.6';
  try {
    await api('/api/chat/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ turn_id: turno }),
    });
  } catch (e) {
    // 404 = o turno já tinha terminado; não vale incomodar o usuário
    if (!/não está em execução/.test(e.message)) {
      addSysMsg(`não deu para cancelar: ${e.message}`);
    }
  }
}

let _sse = null;
function initEventos() {
  if (_sse || !window.EventSource || !window.CielTrace) return;
  _sse = new EventSource('/api/events');
  _sse.onmessage = (e) => {
    let m;
    try { m = JSON.parse(e.data); } catch (_) { return; }
    if (!m || !m.turn_id || m.turn_id !== currentTurn) return;
    if (m.tipo === 'pergunta') {
      mostrarPergunta(m);
    } else if (m.tipo === 'pergunta_expirada') {
      limparPergunta(m.turn_id, 'a pergunta expirou — turno encerrado');
    } else if (m.tipo === 'passo') {
      CielTrace.passo(m.turn_id, m);
    } else if (m.tipo === 'pensando') {
      CielTrace.pensando(m.turn_id, m);
    } else if (m.tipo === 'turno_fim') {
      turnosFechados.add(m.turn_id);
      limparPergunta(m.turn_id, 'turno encerrado');
      CielTrace.fim(m.turn_id, m);
    }
  };
}

/* ── Perguntas de tools INTERACTIVE (entrevista_interativa…) ────
   A tool pausa o turno no servidor e publica "pergunta" no mesmo SSE
   do trace. Enquanto há pergunta, o textarea principal fica travado;
   o botão de enviar continua sendo o "parar" do turno, então cancelar
   segue funcionando mesmo com a pergunta pendente. */
function travarInput(travado) {
  const ta = inputEl();
  if (!ta) return;
  ta.disabled = travado;
  ta.placeholder = travado
    ? 'responda a pergunta acima…'
    : 'mensagem para o agente…';
  if (!travado) ta.focus();
}

function marcarPerguntaRespondida(card, resposta) {
  const controles = card.querySelector('.pergunta-controles');
  if (controles) controles.remove();
  const ok = document.createElement('div');
  ok.className = 'pergunta-resposta';
  ok.textContent = `✓ ${resposta}`;
  card.querySelector('.msg-bubble').appendChild(ok);
  card.classList.add('respondida');
  card.classList.remove('pendente');
}

/* Depois de responder, o turno continua no modelo. Sem um indicador local o
   card parece finalizado e o usuário não sabe se a resposta foi aceita. */
function mostrarPensandoNaPergunta(card) {
  limparPensando();
  const linha = document.createElement('div');
  linha.className = 'pergunta-pensando';
  linha.setAttribute('role', 'status');
  const glyph = document.createElement('span');
  glyph.className = 'pp-glyph';
  glyph.setAttribute('aria-hidden', 'true');
  glyph.textContent = '✦';
  const texto = document.createElement('span');
  texto.textContent = 'o agente está pensando…';
  linha.appendChild(glyph);
  linha.appendChild(texto);
  card.querySelector('.msg-bubble').appendChild(linha);
  const ta = inputEl();
  if (ta) ta.placeholder = 'o agente está pensando…';
  scrollBottom();
}

function limparPensando() {
  document.querySelectorAll('.pergunta-pensando').forEach(el => el.remove());
  const ta = inputEl();
  if (ta && ta.placeholder === 'o agente está pensando…') {
    ta.placeholder = 'mensagem para o agente…';
  }
}

function limparPergunta(turnId, motivo) {
  limparPensando();
  if (!perguntaPendente) return;
  if (turnId && perguntaPendente.turnId !== turnId) return;
  const el = perguntaPendente.el;
  // resposta em voo: deixa o sucesso/erro do POST fechar o ciclo deste card
  if (el.dataset.enviando !== '1' && !el.classList.contains('respondida')) {
    const controles = el.querySelector('.pergunta-controles');
    if (controles) controles.remove();
    el.classList.add('expirada');
    el.classList.remove('pendente');
    const aviso = document.createElement('div');
    aviso.className = 'pergunta-aviso';
    aviso.textContent = motivo || 'pergunta encerrada';
    el.querySelector('.msg-bubble').appendChild(aviso);
  }
  perguntaPendente = null;
  travarInput(false);
}

async function responderPergunta(card, turnId, resposta) {
  if (!card || card.dataset.enviando === '1' || card.classList.contains('respondida')) return;
  card.dataset.enviando = '1';
  card.querySelectorAll('button, input').forEach(el => { el.disabled = true; });
  try {
    await api('/api/chat/responder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ turn_id: turnId, resposta }),
    });
    marcarPerguntaRespondida(card, resposta);
    // Só destrava se nenhuma pergunta nova chegou enquanto o POST corria.
    if (perguntaPendente && perguntaPendente.el === card) {
      perguntaPendente = null;
      travarInput(false);
      mostrarPensandoNaPergunta(card);
    }
  } catch (e) {
    card.dataset.enviando = '';
    // Só reabilita para nova tentativa se este ainda é o card pendente. Se
    // uma pergunta nova já chegou, o servidor pode ter recebido esta resposta
    // e seguido o fluxo; reenviar a antiga responderia a pergunta errada.
    if (perguntaPendente && perguntaPendente.el === card) {
      card.querySelectorAll('button, input').forEach(el => { el.disabled = false; });
    }
    let erro = card.querySelector('.pergunta-erro');
    if (!erro) {
      erro = document.createElement('div');
      erro.className = 'pergunta-erro';
      card.querySelector('.msg-bubble').appendChild(erro);
    }
    erro.textContent = `não deu para responder: ${e.message}`;
    // 404 = a pergunta já não existe (expirou ou o turno acabou)
    if (/não há pergunta pendente/.test(e.message)) {
      limparPergunta(turnId, 'esta pergunta já foi encerrada');
    }
  }
}

function mostrarPergunta(ev) {
  // Evento atrasado de um turno que já terminou não deve travar a UI.
  if (!ev || !ev.turn_id || ev.turn_id !== currentTurn || !turnoAtivo) return;
  limparPensando();
  if (perguntaPendente) {
    const anterior = perguntaPendente.el;
    if (anterior.dataset.enviando === '1') {
      // a resposta da pergunta anterior ainda está voltando; o handler dela
      // marca o card como respondido. Só solta o ponteiro para a nova.
      perguntaPendente = null;
    } else {
      limparPergunta(perguntaPendente.turnId, 'substituída por uma nova pergunta');
    }
  }

  const opcoes = Array.isArray(ev.opcoes) ? ev.opcoes.slice() : [];
  const card = document.createElement('div');
  card.className = 'msg agent pergunta pendente';
  card.dataset.turno = ev.turn_id;
  card.id = `pergunta-${ev.turn_id}-${++_perguntaSeq}`;
  card.innerHTML = `
    <div class="msg-label">ciel · pergunta</div>
    <div class="msg-bubble">
      <div class="msg-body pergunta-texto">${renderMarkdown(ev.texto || '')}</div>
    </div>`;

  const bubble = card.querySelector('.msg-bubble');
  const controles = document.createElement('div');
  controles.className = 'pergunta-controles';

  if (opcoes.length) {
    opcoes.forEach((opcao, i) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'pergunta-opcao';
      btn.dataset.opcao = String(i);
      btn.textContent = `${i + 1}) ${opcao}`;
      btn.addEventListener('click', () => responderPergunta(card, ev.turn_id, String(opcao)));
      controles.appendChild(btn);
    });
    const dica = document.createElement('div');
    dica.className = 'pergunta-dica';
    dica.textContent = 'clique numa opção para responder';
    controles.appendChild(dica);
  } else {
    const linha = document.createElement('div');
    linha.className = 'pergunta-livre';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'pergunta-input';
    input.placeholder = 'digite sua resposta…';
    input.autocomplete = 'off';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pergunta-enviar';
    btn.textContent = 'responder';
    const enviar = () => {
      const valor = input.value.trim();
      if (!valor) { input.focus(); return; }
      responderPergunta(card, ev.turn_id, valor);
    };
    btn.addEventListener('click', enviar);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); enviar(); }
    });
    linha.appendChild(input);
    linha.appendChild(btn);
    controles.appendChild(linha);
  }

  bubble.appendChild(controles);
  messagesEl().appendChild(card);
  perguntaPendente = { turnId: ev.turn_id, el: card };
  travarInput(true);
  scrollBottom();

  const foco = card.querySelector('.pergunta-input, .pergunta-opcao');
  if (foco) setTimeout(() => foco.focus(), 0);
}

function addBranchNotice(text) {
  const div = document.createElement('div');
  div.className = 'msg sys branch-notice';
  div.innerHTML = `<div class="msg-bubble branch-bubble">${esc(text)}</div>`;
  messagesEl().appendChild(div);
  scrollBottom();
}

function addViewModeBanner(sessionId, title) {
  // banner fixo no topo do chat indicando modo leitura
  const existing = document.getElementById('view-mode-banner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.id = 'view-mode-banner';
  banner.className = 'view-mode-banner';
  banner.innerHTML = `
    <span>${icone('eye')} visualizando sessão #${sessionId} — ${esc(title || 'sem título')}</span>
    <span class="view-mode-hint">envie uma mensagem para retomar com branch automática</span>
  `;
  // insere antes das mensagens
  const wrapper = document.querySelector('.chat-wrapper');
  wrapper.insertBefore(banner, wrapper.firstChild);
}

function removeViewModeBanner() {
  document.getElementById('view-mode-banner')?.remove();
}

function addParentSeparator(parent) {
  const div = document.createElement('div');
  div.className = 'parent-separator';

  const summary = parent.has_summary
    ? `<div class="parent-summary">${esc(parent.summary)}</div>`
    : '';

  div.innerHTML = `
    <div class="parent-sep-line"></div>
    <div class="parent-sep-body">
      <span class="parent-sep-label">↪ branch de</span>
      <button class="parent-sep-link" onclick="loadSession(${parent.id})">
        #${parent.id} · ${esc(parent.title || 'sem título')}
      </button>
      ${summary}
    </div>
    <div class="parent-sep-line"></div>
  `;
  messagesEl().appendChild(div);
  scrollBottom();
}

function scrollBottom() {
  const el = messagesEl();
  el.scrollTop = el.scrollHeight;
}

// ── Envio de mensagem ─────────────────────────────────────────
window.sendMessage = async () => {
  const text = inputEl().value.trim();
  if (turnoAtivo || (!text && !pendingFile)) return;

  const displayText = text || (pendingFile ? `[arquivo: ${pendingFile.file.name}]` : '');
  inputEl().value = '';
  autoResize(inputEl());
  inputEl().placeholder = 'mensagem para o agente…';
  if (window.Paleta) Paleta.fechar();
  removeViewModeBanner();
  setRodapeLeitura(false);

  const fileInfo = pendingFile ? pendingFile.file.name : null;
  addUserMsg(displayText, fileInfo);
  setStatus('loading');
  turnoAtivo = true;
  cancelando = false;
  entrarModoParar();
  setEstadoSessao('pensando');

  // trace do turno: /task também mostra (roda o agente); os demais comandos
  // são instantâneos e não precisam de acordeão
  const temTrace = !text.startsWith('/') || /^\/task\b/.test(text);
  const turno = novoTurno();
  currentTurn = turno;
  if (temTrace && window.CielTrace) CielTrace.criar(turno);

  const file = pendingFile;
  clearUpload();

  try {
    let body, headers = { 'Content-Type': 'application/json' };

    if (file?.type === 'image') {
      body = JSON.stringify({
        message:   text || 'Descreva ou analise esta imagem.',
        image_b64: file.dataUrl.split(',')[1],
        filename:  file.file.name,
        session_id: currentSessionId,
        turn_id:   turno,
        perguntas_interativas: true,
      });
    } else if (file?.type === 'text') {
      body = JSON.stringify({
        message:   text || `Analise o arquivo: ${file.file.name}`,
        file_text: file.content,
        filename:  file.file.name,
        session_id: currentSessionId,
        turn_id:   turno,
        perguntas_interativas: true,
      });
    } else {
      body = JSON.stringify({
        message: text, session_id: currentSessionId, turn_id: turno, perguntas_interativas: true,
      });
    }

    const data = await api('/api/chat', { method: 'POST', headers, body });
    setStatus('online');

    // se o SSE não entregou o turno_fim (ex.: reconexão), fecha pelo resultado
    if (temTrace && window.CielTrace && !turnosFechados.has(turno)) {
      turnosFechados.add(turno);
      CielTrace.fim(turno, { status: data.status || 'done' });
    }

    // aviso de branch criada (antes da resposta do agente)
    if (data.branch_notice) {
      addBranchNotice(data.branch_notice);
    }

    const role = data.status === 'needs_tool' ? 'warn' : 'agent';
    addAgentMsg(data.reply || data.error || '?', role, data.arquivos || []);

    // o agente gerou arquivo: abre a prévia do principal (se o "auto" estiver on)
    if (window.Preview && Array.isArray(data.arquivos) && data.arquivos.length) {
      Preview.autoOpen(data.arquivos);
    }

    // atualiza tokens
    if (data.tokens_in || data.tokens_out) {
      updateTokenDisplay(data.tokens_in || 0, data.tokens_out || 0);
    }

    // atualiza session_id (inclusive quando veio de uma branch)
    if (data.session_id) {
      currentSessionId = data.session_id;
      viewingSessionId = data.session_id;
      document.getElementById('info-session').textContent = `#${data.session_id}`;
    }

    // recarrega tools e sessões em background
    if (data.tools_changed) {
      const info = await api('/api/info');
      atualizarTools(info.tools);
    }

    await loadSessions();

  } catch(e) {
    setStatus('error');
    const ocupado = /turno em execu[çc][ãa]o/i.test(e.message);
    if (temTrace && window.CielTrace && !turnosFechados.has(turno)) {
      CielTrace.falhar(turno, ocupado ? 'o servidor já está em outro turno' : e.message);
    }
    addSysMsg(ocupado
      ? 'já existe um turno em execução — aguarde ele terminar'
      : `erro: ${e.message}`);
  }

  // se a resposta final chegou sem o turno_fim do SSE, encerra a pergunta
  // pendente (se houver) antes de devolver o input ao usuário
  limparPergunta(turno, 'turno encerrado');

  sairModoParar();
  setEstadoSessao(currentSessionId ? 'ativa' : 'nova');
  await refreshSources();   // branch copia as fontes do pai; a lista tem de refletir
  inputEl().focus();
};
// ── Limpar / nova sessão ──────────────────────────────────────
window.clearChat = async () => {
  try { await api('/api/clear', { method: 'POST' }); } catch(_) {}
  messagesEl().innerHTML = '';
  tokenIn = 0; tokenOut = 0;
  currentSessionId = null;
  viewingSessionId = null;
  resetRightPanel();   // zera tokens, título, estado e fontes
  addSysMsg('nova sessão iniciada');
  await loadSessions();
  await refreshSources();   // fontes globais continuam disponíveis
};

window.newSession = () => pedirNovaSessao();

/** Confirma só quando há uma conversa em andamento (a antiga fica no histórico). */
window.pedirNovaSessao = () => {
  if (!currentSessionId && !tokenIn && !tokenOut) { clearChat(); return; }
  openConfirm({
    title: 'nova sessão',
    icon: '↺',
    subject: 'começar uma conversa nova?',
    text: 'A conversa atual continua no histórico. A nova sessão começa sem contexto.',
    okLabel: 'nova sessão',
    perigo: false,
    onOk: () => clearChat(),
  });
};

// ── Quick command ─────────────────────────────────────────────
window.quickCommand = (cmd) => {
  if (window.Paleta) Paleta.fechar();
  inputEl().value = cmd;
  sendMessage();
};

// ── Tools: contagem no menu (a lista vive em /tools e na paleta) ──
function atualizarTools(tools) {
  const el = document.getElementById('tools-count');
  if (el) el.textContent = (tools || []).length;
}

// ── Sidebar ───────────────────────────────────────────────────
window.toggleSidebar  = () => {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebar-overlay').classList.toggle('open');
};
window.closeSidebar   = () => {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-overlay').classList.remove('open');
};

// ── Right panel ───────────────────────────────────────────────
// O visualizador usa estas funções para recolher o painel quando a prévia
// espremeria o chat. A memória fica aqui: se o usuário reabrir na mão com a
// prévia aberta, a interface não fecha mais sozinha.
let painelAutoFechado = false;   // foi o visualizador que recolheu (não o usuário)
let painelOverride    = false;   // usuário reabriu por conta própria: não insistir

function _pintarBotaoPainel() {
  document.getElementById('right-panel-btn').textContent = rightPanelOpen ? '⊟' : '⊞';
}

window.toggleRightPanel = () => {
  const panel = document.getElementById('right-panel');
  rightPanelOpen = !rightPanelOpen;
  panel.classList.toggle('collapsed', !rightPanelOpen);
  _pintarBotaoPainel();

  painelAutoFechado = false;
  // escolha manual de reabrir: desiste de recolher automaticamente
  if (rightPanelOpen) painelOverride = true;
};

/** Recolhe o painel direito para o visualizador ganhar espaço.
 *  Devolve true só se foi ele quem recolheu (para poder restaurar depois). */
window.recolherPainelParaPreview = () => {
  if (!rightPanelOpen || painelOverride) return false;
  rightPanelOpen = false;
  document.getElementById('right-panel').classList.add('collapsed');
  _pintarBotaoPainel();
  painelAutoFechado = true;
  return true;
};

/** Devolve o espaço — só se o fechamento anterior foi automático. */
window.restaurarPainelDoPreview = () => {
  if (!painelAutoFechado) return;
  painelAutoFechado = false;
  if (rightPanelOpen) return;
  rightPanelOpen = true;
  document.getElementById('right-panel').classList.remove('collapsed');
  _pintarBotaoPainel();
};

// ── Modais ─────────────────────────────────────────────────────
window.closeModal = (id) => document.getElementById(id).classList.add('hidden');

// Modal: Agentes
window.openAgentModal = async () => {
  const modal = document.getElementById('agent-modal');
  modal.classList.remove('hidden');
  const grid = document.getElementById('agents-grid');
  grid.innerHTML = '<div class="panel-empty">carregando…</div>';
  closeSidebar();
  try {
    const data = await api('/api/agents');
    grid.innerHTML = data.agents.map(a => `
      <button class="agent-option ${a.id === currentAgent ? 'active' : ''}"
              onclick="switchAgent('${esc(a.id)}')">
        <div class="agent-option-avatar">${a.name[0].toUpperCase()}</div>
        <div class="agent-option-body">
          <div class="agent-option-name">${esc(a.name)}</div>
          <div class="agent-option-desc">${esc(a.description || '')}</div>
        </div>
      </button>`).join('');
  } catch(e) {
    grid.innerHTML = `<div class="panel-empty">erro: ${esc(e.message)}</div>`;
  }
};

// ── Reset painel direito (compartilhado por switchAgent e clearChat) ──────
function resetRightPanel({ agentName = null, agentFull = null, agentDesc = null, tools = null } = {}) {
  removeViewModeBanner();

  // sessão: identidade, estado e uso
  setTituloSessao('conversa nova');
  setEstadoSessao('nova');
  setRodapeLeitura(false);
  tokenIn = 0;
  tokenOut = 0;
  tokensDesconhecidos = false;
  renderTokens();

  // agente (só atualiza se veio como argumento)
  if (agentName !== null) {
    document.getElementById('info-agent').textContent         = agentName;
    document.getElementById('topbar-agent').textContent       = agentFull || agentName;
    document.getElementById('sidebar-agent-name').textContent = agentFull || agentName;
    document.getElementById('sidebar-agent-desc').textContent = agentDesc || '';
    document.getElementById('agent-avatar').textContent       = (agentFull || agentName)[0].toUpperCase();
    currentAgent = agentName;
  }

  // tools: só a contagem (lista fica no /tools e na paleta)
  if (tools !== null) atualizarTools(tools);

  // fontes: volta ao estado vazio (as globais vêm do refreshSources)
  renderFontesPainel([]);
}

window.switchAgent = async (agentId) => {
  closeModal('agent-modal');
  addSysMsg(`trocando para agente: ${agentId}…`);
  try {
    const data = await api('/api/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent: agentId }),
    });

    tokenIn = 0; tokenOut = 0; updateTokenDisplay();
    messagesEl().innerHTML = '';
    currentSessionId = null;
    viewingSessionId = null;

    resetRightPanel({
      agentName: data.agent,
      agentFull: data.agent_full || data.agent,
      agentDesc: data.agent_desc || '',
      tools:     data.tools || [],
    });

    addSysMsg(`agente: ${data.agent_full || data.agent} · ${(data.tools||[]).length} tools`);
    await loadSessions();
    await refreshSources();   // fontes são por agente
  } catch(e) {
    addSysMsg(`erro ao trocar agente: ${e.message}`);
  }
};

// Modal: Tasks
window.openTaskModal = async () => {
  const modal = document.getElementById('task-modal');
  modal.classList.remove('hidden');
  const list = document.getElementById('tasks-list-modal');
  list.innerHTML = '<div class="panel-empty">carregando…</div>';
  closeSidebar();
  try {
    const data = await api('/api/tasks');
    if (!data.tasks.length) {
      list.innerHTML = '<div class="panel-empty">nenhuma task em tasks/</div>';
      return;
    }
    list.innerHTML = data.tasks.map(t => `
      <button class="task-option" onclick="runTask('${esc(t.id)}')">
        <span class="task-option-icon">⚡</span>
        <div>
          <div class="task-option-name">${esc(t.name)}</div>
          <div class="task-option-obj">${esc(t.objective || '')}</div>
        </div>
      </button>`).join('');
  } catch(e) {
    list.innerHTML = `<div class="panel-empty">erro: ${esc(e.message)}</div>`;
  }
};

window.runTask = (taskId) => {
  closeModal('task-modal');
  quickCommand(`/task ${taskId}`);
};

// Modal: Sources
let activeSourceTab = 'file';
let pendingSourceFile = null;   // File object selecionado no picker

window.openSourceModal = async () => {
  document.getElementById('source-modal').classList.remove('hidden');
  closeSidebar();
  switchSourceTab('file');   // sempre abre na tab de arquivo
  await refreshSources();
};

window.switchSourceTab = (tab) => {
  activeSourceTab = tab;
  document.querySelectorAll('.source-tab').forEach(el => {
    el.classList.toggle('active', el.getAttribute('onclick')?.includes(`'${tab}'`));
  });
  ['file','path','url'].forEach(t => {
    document.getElementById(`source-tab-${t}`).classList.toggle('hidden', t !== tab);
  });
};

// Seleção via file picker
window.onSourceFileSelected = (input) => {
  const file = input.files[0];
  if (!file) return;
  pendingSourceFile = file;
  const label = document.getElementById('source-upload-label');
  const area  = document.getElementById('source-drop-area');
  label.textContent = file.name;
  area.classList.add('has-file');
  area.classList.remove('drag-over');
};

// Drag & drop na área de upload de fontes
document.addEventListener('DOMContentLoaded', () => {
  const area = document.getElementById('source-drop-area');
  if (!area) return;
  area.addEventListener('dragover', e => { e.preventDefault(); area.classList.add('drag-over'); });
  area.addEventListener('dragleave', () => area.classList.remove('drag-over'));
  area.addEventListener('drop', e => {
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    pendingSourceFile = file;
    document.getElementById('source-upload-label').textContent = file.name;
    area.classList.add('has-file');
    area.classList.remove('drag-over');
  });
});

/** Atributos de clique de uma fonte: arquivo em data/, rota de fonte
 *  registrada (pode estar fora de data/) ou o motivo de não abrir. */
function atributosFonte(s) {
  const nome = ` data-preview-name="${esc(s.filename)}"`;
  if (s.preview_path) return `${nome} data-preview-path="${esc(s.preview_path)}"`;
  if (s.preview_url)  return `${nome} data-preview-source="${s.id}"`;
  return `${nome} data-preview-bloqueado="${esc(s.preview_motivo || 'sem prévia para esta fonte')}"`;
}

/** Mini-lista de fontes do painel: sessão primeiro, globais marcadas.
 *  A lista do modal continua mostrando todas, com chunks e escopo. */
function renderFontesPainel(sources = [], { leitura = false } = {}) {
  const list  = document.getElementById('sources-panel-list');
  const badge = document.getElementById('sources-count');
  if (!list) return;
  if (badge) badge.textContent = sources.length;

  if (!sources.length) {
    list.innerHTML = `
      <div class="rp-empty">
        <p>nenhum documento anexado a esta conversa</p>
        ${leitura ? '' : '<button class="rp-btn" onclick="openSourceModal()">+ adicionar fonte</button>'}
      </div>`;
    return;
  }

  const visiveis  = sources.slice(0, 4);
  const restantes = sources.length - visiveis.length;

  list.innerHTML = visiveis.map(s => {
    const global = s.scope === 'global';
    const escopo = global ? 'global' : 'sessao';
    const dica = `${s.filename} · ${s.n_chunks} chunk${s.n_chunks === 1 ? '' : 's'} · `
               + (global ? 'global' : 'sessão');
    const preview = atributosFonte(s);
    const clicavel = !!(s.preview_path || s.preview_url);
    const dicaFinal = dica + (clicavel
      ? ' · abrir no visualizador'
      : ` · ${s.preview_motivo || 'sem prévia'}`);
    const acao = leitura ? '' : `
        <button class="rp-del" title="remover fonte" aria-label="remover ${esc(s.filename)}"
                data-nome="${esc(s.filename)}"
                onclick="event.stopPropagation(); removeSource(${s.id}, '${global ? 'global' : ''}', this.dataset.nome)">✕</button>`;
    return `
      <div class="rp-src ${escopo}${clicavel ? '' : ' sem-previa'}"${preview} role="button" tabindex="0"
           title="${esc(dicaFinal)}">
        ${icone('file')}
        <span class="rp-src-name">${esc(s.filename)}</span>
        <span class="rp-tag ${escopo}">${global ? 'global' : 'sessão'}</span>
        ${acao}
      </div>`;
  }).join('') + (restantes > 0
    ? `<button class="rp-more" onclick="openSourceModal()">ver todas (${sources.length}) →</button>`
    : '');
}

async function refreshSources() {
  const list = document.getElementById('sources-list-modal');
  if (list) list.innerHTML = '<div class="panel-empty">carregando…</div>';
  try {
    const data = await api('/api/sources');
    renderFontesPainel(data.sources || []);
    if (!list) return;
    if (!data.sources.length) {
      list.innerHTML = '<div class="panel-empty">nenhuma fonte indexada</div>';
      return;
    }
    const attrFonte = (s) => {
      const clicavel = !!(s.preview_path || s.preview_url);
      const dica = clicavel
        ? `abrir ${s.filename} no visualizador`
        : (s.preview_motivo || 'sem prévia para esta fonte');
      return `class="source-item-name${clicavel ? ' clicavel' : ' sem-previa'}"`
           + atributosFonte(s) + ` title="${esc(dica)}"`;
    };
    list.innerHTML = data.sources.map(s => `
      <div class="source-item">
        <span ${attrFonte(s)}>${icone('file')} ${esc(s.filename)}</span>
        <span class="source-item-meta">${s.n_chunks} chunks · ${esc(s.scope)}</span>
        <button class="source-item-del"
                data-nome="${esc(s.filename)}"
                onclick="removeSource(${s.id}, '${s.scope === 'global' ? 'global' : ''}', this.dataset.nome)"
                title="remover">✕</button>
      </div>`).join('');
  } catch(e) {
    if (list) list.innerHTML = `<div class="panel-empty">erro: ${esc(e.message)}</div>`;
    renderFontesPainel([]);
  }
}

window.addSource = async () => {
  const isGlobal  = document.getElementById('source-global').checked;
  const btn       = document.getElementById('source-add-btn');
  btn.disabled    = true;
  btn.textContent = 'indexando…';

  try {
    if (activeSourceTab === 'file') {
      // upload de arquivo via FormData
      if (!pendingSourceFile) {
        addSysMsg('selecione um arquivo primeiro.');
        return;
      }
      const form = new FormData();
      form.append('file', pendingSourceFile);
      form.append('global', isGlobal);
      form.append('session_id', currentSessionId ?? '');

      const r = await fetch('/api/source/upload', { method: 'POST', credentials: 'include', body: form });
      if (!r.ok) { const e = await r.json(); throw new Error(e.error || `HTTP ${r.status}`); }

      const name = pendingSourceFile.name;
      // reset picker
      pendingSourceFile = null;
      document.getElementById('source-file-input').value = '';
      document.getElementById('source-upload-label').textContent = 'clique para selecionar ou arraste um arquivo';
      document.getElementById('source-drop-area').classList.remove('has-file');
      addSysMsg(`fonte indexada: ${name}`);

    } else if (activeSourceTab === 'path') {
      const path = document.getElementById('source-path-input').value.trim();
      if (!path) { addSysMsg('informe o caminho do arquivo.'); return; }
      await api('/api/source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, global: isGlobal, session_id: currentSessionId }),
      });
      document.getElementById('source-path-input').value = '';
      addSysMsg(`fonte indexada: ${path}`);

    } else {
      const url = document.getElementById('source-url-input').value.trim();
      if (!url) { addSysMsg('informe a URL.'); return; }
      await api('/api/source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: url, global: isGlobal, session_id: currentSessionId }),
      });
      document.getElementById('source-url-input').value = '';
      addSysMsg(`fonte indexada: ${url}`);
    }

    await refreshSources();

  } catch(e) {
    addSysMsg(`erro ao indexar: ${e.message}`);
  } finally {
    btn.disabled    = false;
    btn.textContent = '+ indexar';
  }
};

window.removeSource = async (id, escopo = '', nome = '') => {
  if (escopo === 'global') {
    openConfirm({
      title: 'remover fonte global',
      icon: '⚠',
      subject: nome || 'fonte compartilhada',
      text: 'Ela fica disponível para todas as sessões deste agente. Remover afeta todas elas.',
      okLabel: 'remover',
      onOk: () => apagarFonte(id),
    });
    return;
  }
  await apagarFonte(id);
};

async function apagarFonte(id) {
  try {
    await api('/api/source/' + id, { method: 'DELETE' });
    await refreshSources();
  } catch(e) {
    addSysMsg(`erro ao remover fonte: ${e.message}`);
  }
};

// Modal: History
window.openHistoryModal = async () => {
  const modal = document.getElementById('history-modal');
  modal.classList.remove('hidden');
  const list = document.getElementById('history-sessions-list');
  list.innerHTML = '<div class="panel-empty">carregando…</div>';
  try {
    const data = await api('/api/sessions');
    if (!data.sessions.length) {
      list.innerHTML = '<div class="panel-empty">nenhuma sessão salva</div>';
      return;
    }
    list.innerHTML = data.sessions.map(s => {
      const isBranch = !!s.parent_session_id;
      return `
      <div class="history-item" data-session-id="${s.id}">
        <div class="history-item-dot ${isBranch ? 'branch' : ''}"></div>
        <div class="history-item-body">
          <div class="history-item-title">
            ${isBranch ? '<span class="branch-indicator">↪</span>' : ''}${esc(s.title || 'sem título')}
          </div>
          <div class="history-item-meta">
            ${esc(s.agent_id)} · ${esc(s.updated_at || '')}
            ${isBranch ? `· <span class="parent-ref">pai: #${s.parent_session_id}</span>` : ''}
          </div>
        </div>
        <span class="history-item-badge">${esc(s.agent_id)}</span>
        <button class="history-item-del"
                data-del-id="${s.id}"
                data-del-title="${escAttr(s.title || 'sem título')}"
                title="deletar">×</button>
      </div>`;
    }).join('');
  } catch(e) {
    list.innerHTML = `<div class="panel-empty">erro: ${esc(e.message)}</div>`;
  }
};

// ── Confirmação genérica (modal único) ─────────────────────────
let _acaoConfirmada = null;

window.openConfirm = ({
  title = 'confirmar', icon = '⚠', subject = '', text = '',
  okLabel = 'confirmar', perigo = true, onOk = null,
} = {}) => {
  _acaoConfirmada = onOk;
  document.getElementById('confirm-title').textContent   = title;
  document.getElementById('confirm-icon').textContent    = icon;
  document.getElementById('confirm-icon').classList.toggle('confirm-icon-info', !perigo);
  document.getElementById('confirm-subject').textContent = subject;
  document.getElementById('confirm-text').textContent    = text;
  const ok = document.getElementById('confirm-ok');
  ok.textContent = okLabel;
  ok.classList.toggle('btn-danger', perigo);
  ok.classList.toggle('btn-outline', !perigo);
  document.getElementById('confirm-modal').classList.remove('hidden');
};

window.confirmarAcao = () => {
  const cb = _acaoConfirmada;
  _acaoConfirmada = null;
  closeModal('confirm-modal');
  if (cb) cb();
};

// ── Delete de sessão ───────────────────────────────────────────
window.openConfirmDelete = (sessionId, title) => {
  openConfirm({
    title: 'deletar sessão',
    icon: '⚠',
    subject: title,
    text: 'Esta ação é irreversível. A conversa e todas as fontes associadas serão removidas.',
    okLabel: 'deletar',
    onOk: () => deletarSessao(sessionId),
  });
};

async function deletarSessao(id) {
  try {
    await api(`/api/session/${id}`, { method: 'DELETE' });

    // se deletou a sessão atual/visualizada, reseta o chat
    if (id === currentSessionId || id === viewingSessionId) {
      messagesEl().innerHTML = '';
      currentSessionId = null;
      viewingSessionId = null;
      resetRightPanel();
      addSysMsg('sessão deletada — nova sessão iniciada');
    } else {
      addSysMsg(`sessão #${id} deletada`);
    }

    await loadSessions();
    // atualiza modal de histórico se ainda estiver aberto
    if (!document.getElementById('history-modal').classList.contains('hidden')) {
      openHistoryModal();
    }
  } catch(e) {
    addSysMsg(`erro ao deletar sessão: ${e.message}`);
  }
}

window.loadSession = async (sessionId) => {
  closeModal('history-modal');
  closeSidebar();
  try {
    const data = await api(`/api/session/${sessionId}/load`, { method: 'POST' });

    // limpa chat e reseta contadores — sessão antiga não guarda tokens
    messagesEl().innerHTML = '';
    tokenIn = 0; tokenOut = 0;
    setTokensDesconhecidos();
    currentSessionId = null;   // ainda não é a sessão ativa — é só visualização
    viewingSessionId = sessionId;

    // atualiza agente se mudou
    if (data.agent !== undefined) {
      document.getElementById('topbar-agent').textContent       = data.agent_full || data.agent;
      document.getElementById('sidebar-agent-name').textContent = data.agent_full || data.agent;
      document.getElementById('sidebar-agent-desc').textContent = data.agent_desc || '';
      document.getElementById('agent-avatar').textContent       = (data.agent_full || data.agent)[0].toUpperCase();
      document.getElementById('info-agent').textContent         = data.agent;
      atualizarTools(data.tools);
    }

    // cabeçalho: identidade + estado de leitura
    const sess = data.session;
    setTituloSessao(sess.title || 'sem título', sess.id);
    setEstadoSessao('leitura');
    setRodapeLeitura(true);
    document.getElementById('info-model').textContent = document.getElementById('topbar-model').textContent;

    // fontes da sessão no painel (sem remoção enquanto é leitura)
    renderFontesPainel(data.sources || [], { leitura: true });

    // separador de origem se for branch
    if (data.parent) {
      addParentSeparator(data.parent);
    }

    // renderiza histórico da sessão (modo leitura), com o trace salvo
    (data.turns || []).forEach(t => {
      if (t.role === 'user') { addUserMsg(t.content); return; }
      if (t.role !== 'agent') return;
      replayTrace(t);
      // chips "arquivo gerado" do turno salvo (o servidor manda a lista; em
      // sessão antiga ele reconstrói pelos caminhos citados na resposta)
      addAgentMsg(t.content, 'agent', t.arquivos || []);
    });

    // aviso de modo leitura
    const hasSummary = data.session?.has_summary;
    addSysMsg(
      `sessão #${sess.id} · ${sess.title || 'sem título'} · modo leitura` +
      (hasSummary ? ' · resumo disponível' : ' · sem resumo — branch iniciará sem contexto')
    );
    addViewModeBanner(sess.id, sess.title);

    await loadSessions();

  } catch(e) {
    addSysMsg(`erro ao carregar sessão: ${e.message}`);
  }
};

/* Reconstrói o acordeão de um turno salvo (modo leitura do histórico). */
function replayTrace(turn) {
  if (!turn.trace || !window.CielTrace) return;
  const id = 'hist-' + turn.id;
  CielTrace.criar(id);
  (turn.trace.passos || []).forEach(p => CielTrace.passo(id, p));
  CielTrace.fim(id, turn.trace.fim || { status: 'done' });
}

// ── Sessões sidebar ────────────────────────────────────────────
async function loadSessions() {
  try {
    const data = await api('/api/sessions');
    const list = document.getElementById('sessions-list');
    if (!data.sessions.length) {
      list.innerHTML = '<div class="sessions-empty">nenhuma sessão salva</div>';
      return;
    }
    list.innerHTML = data.sessions.slice(0, 20).map(s => {
      const isBranch = !!s.parent_session_id;
      return `
      <div class="session-item ${s.id === viewingSessionId ? 'active' : ''}"
           data-session-id="${s.id}">
        <span class="session-item-dot"></span>
        <div class="session-item-body">
          <div class="session-item-title">
            ${isBranch ? '<span class="branch-indicator">↪</span>' : ''}${esc(s.title || 'sem título')}
          </div>
          <div class="session-item-meta">${esc(s.agent_id)} · ${esc(s.updated_at || '')}</div>
        </div>
        <button class="session-item-del"
                data-del-id="${s.id}"
                data-del-title="${escAttr(s.title || 'sem título')}"
                title="deletar">×</button>
      </div>`;
    }).join('');

    // mantém o título do cabeçalho alinhado com a sessão ativa/visualizada
    const alvo = data.sessions.find(s => s.id === (viewingSessionId ?? currentSessionId));
    if (alvo) setTituloSessao(alvo.title || 'sem título', alvo.id);
  } catch(_) {}
}

// ── Upload de arquivo ──────────────────────────────────────────
window.triggerUpload = () => document.getElementById('file-input').click();

document.addEventListener('DOMContentLoaded', () => {

  // Delegation: sidebar sessions
  document.getElementById('sessions-list').addEventListener('click', e => {
    const delBtn = e.target.closest('[data-del-id]');
    if (delBtn) {
      openConfirmDelete(Number(delBtn.dataset.delId), delBtn.dataset.delTitle);
      return;
    }
    const item = e.target.closest('[data-session-id]');
    if (item) {
      loadSession(Number(item.dataset.sessionId));
      closeSidebar();
    }
  });

  // Delegation: history modal
  document.getElementById('history-sessions-list').addEventListener('click', e => {
    const delBtn = e.target.closest('[data-del-id]');
    if (delBtn) {
      openConfirmDelete(Number(delBtn.dataset.delId), delBtn.dataset.delTitle);
      return;
    }
    const item = e.target.closest('[data-session-id]');
    if (item) {
      loadSession(Number(item.dataset.sessionId));
    }
  });
  const fileInput = document.getElementById('file-input');
  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (!file) return;
    fileInput.value = '';
    const ext = file.name.split('.').pop().toLowerCase();
    if (IMAGE_EXTS.has(ext)) {
      const reader = new FileReader();
      reader.onload = e => {
        pendingFile = { file, dataUrl: e.target.result, type: 'image' };
        showUploadPreview('img', e.target.result, file.name);
      };
      reader.readAsDataURL(file);
    } else {
      const reader = new FileReader();
      reader.onload = e => {
        pendingFile = { file, content: e.target.result, type: 'text' };
        showUploadPreview('text', null, file.name);
      };
      reader.readAsText(file);
    }
  });

  // drag & drop
  document.addEventListener('dragover', e => e.preventDefault());
  document.addEventListener('drop', e => {
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event('change'));
  });
});

function showUploadPreview(type, src, name) {
  document.getElementById('upload-preview').classList.add('active');
  document.getElementById('prev-name').textContent = name;
  const ext = name.split('.').pop().toUpperCase();
  document.getElementById('prev-type').textContent = ext;
  if (type === 'img' && src) {
    document.getElementById('prev-thumb').innerHTML = `<img src="${src}" alt="">`;
  } else {
    document.getElementById('prev-thumb').innerHTML = icone('file');
  }
}

window.clearUpload = () => {
  pendingFile = null;
  document.getElementById('upload-preview').classList.remove('active');
  document.getElementById('prev-thumb').innerHTML = '';
  document.getElementById('prev-name').textContent = '';
  document.getElementById('prev-type').textContent = '';
};


// ── Markdown ───────────────────────────────────────────────────
function renderMarkdown(text) {
  if (window.marked) {
    marked.setOptions({ breaks: true, gfm: true });
    const html = marked.parse(text);
    // aplica highlight após renderizar
    setTimeout(() => {
      document.querySelectorAll('.msg-body pre code:not(.hljs)').forEach(el => {
        if (window.hljs) hljs.highlightElement(el);
      });
    }, 0);
    return html;
  }
  return esc(text).replace(/\n/g, '<br>');
}

// ── File refs detection ────────────────────────────────────────
function extractFileRefs(text) {
  const patterns = [
    /(?:salvo?|criado?|gerado?|escrito?|saved?)\s+em[:\s]+['"]?([^\s\n,'"]+\.[a-zA-Z0-9]{1,6})['"]?/gi,
    /arquivo[:\s]+['"]?([^\s\n,'"]+\.[a-zA-Z0-9]{1,6})['"]?/gi,
    /['"]?((?:data[\/\\]user[\/\\]|uploads[\/\\])[^\s\n,'"]+\.[a-zA-Z0-9]{1,6})['"]?/gi,
    /dispon[ií]vel\s+em[:\s]+['"]?([^\s\n,'"]+\.[a-zA-Z0-9]{1,6})['"]?/gi,
  ];
  const refs = new Set();
  for (const re of patterns) {
    let m;
    while ((m = re.exec(text)) !== null) {
      const p = m[1].replace(/['"\\]/g, '').replace(/\\/g, '/');
      if (!p.includes('://') && p.length > 3) refs.add(p);
    }
  }
  return [...refs];
}

// caminho relativo a data/ (o único que /preview serve); absoluto é reduzido
function previewPath(p) {
  const norm = String(p || '').replace(/\\/g, '/');
  if (/^data\//i.test(norm)) return norm;
  const i = norm.toLowerCase().indexOf('/data/');
  return i >= 0 ? norm.slice(i + 1) : null;
}

function buildDownloadLinks(refs) {
  if (!refs.length) return '';
  return refs.map(p => {
    const ext  = p.split('.').pop().toLowerCase();
    const name = p.split(/[\\/]/).pop();
    const ic = icone(IMAGE_EXTS.has(ext) ? 'image' : 'download');
    // "ver" abre o painel de visualização (Preview em preview.js); o link
    // continua sendo o download — e é o que sobra quando o tipo não renderiza
    const alvo = previewPath(p);
    const ver = alvo
      ? `<button class="dl-view" data-preview-path="${esc(alvo)}" data-preview-name="${esc(name)}"
                 title="visualizar no painel">ver</button>`
      : '';
    return `<span class="dl-row">
      <a class="dl-link" href="/download?path=${encodeURIComponent(p)}"
         download="${esc(name)}" target="_blank">${ic} ${esc(name)}</a>
      ${ver}
    </span>`;
  }).join('');
}

// ── View nav ───────────────────────────────────────────────────
window.showView = (view) => {
  // Por enquanto só chat existe; extensível
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  event.currentTarget.classList.add('active');
  closeSidebar();
};

// ── Keyboard ───────────────────────────────────────────────────
window.handleKey = e => {
  // paleta aberta: setas navegam, Enter/Tab executa, Esc fecha
  if (window.Paleta && Paleta.aberta()) {
    if (e.key === 'ArrowDown') { e.preventDefault(); Paleta.mover(1); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); Paleta.mover(-1); return; }
    if (e.key === 'Escape')    { e.preventDefault(); Paleta.fechar(); return; }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      Paleta.executar(Paleta.selecionado());
      return;
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!turnoAtivo) sendMessage();
  }
  if (e.key === 'Escape' && window.Paleta) Paleta.fechar();
};

window.autoResize = el => {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
};

// ── Copy ───────────────────────────────────────────────────────
window.copyBubble = async (btn, text) => {
  let ok = false;
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); ok = true; } catch(_) {}
  }
  if (!ok) {
    const ta = Object.assign(document.createElement('textarea'), {
      value: text, style: 'position:fixed;top:0;left:0;opacity:0'
    });
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); ok = true; } catch(_) {}
    document.body.removeChild(ta);
  }
  btn.textContent = ok ? '✓' : '!';
  btn.classList.add('copied');
  setTimeout(() => { btn.textContent = 'copy'; btn.classList.remove('copied'); }, 1500);
};

// ── Helpers ────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(s) {
  return String(s ?? '').replace(/\\/g,'\\\\').replace(/`/g,'\\`').replace(/\$/g,'\\$');
}

// ══════════════════════════════════════════════════════════════
//  Auth
// ══════════════════════════════════════════════════════════════

// estado local de auth (atualizado pelo badge e pelo modal)
let _authState = { authenticated: false, is_default: false, force_safe: false };

/** Busca /api/auth/status e atualiza o badge. Pode receber info já carregado. */
async function updateAuthBadge(infoOrNull = null) {
  try {
    const s = infoOrNull
      ? { authenticated: infoOrNull.authenticated, force_safe: infoOrNull.force_safe }
      : await api('/api/auth/status');
    _authState = { ..._authState, ...s };
    _renderAuthBadge();
  } catch(_) {}
}

function _renderAuthBadge() {
  const badge  = document.getElementById('safe-badge');
  const icon   = document.getElementById('safe-badge-icon');
  const label  = document.getElementById('safe-badge-label');
  if (!badge) return;

  badge.classList.remove('authed', 'force-safe');

  if (_authState.force_safe) {
    icon.innerHTML = icone('lock');
    label.textContent = 'safe';
    badge.classList.add('force-safe');
    badge.title = 'modo seguro permanente (--safe)';
  } else if (_authState.authenticated) {
    icon.innerHTML = icone('unlock');
    label.textContent = 'autenticado';
    badge.classList.add('authed');
    badge.title = 'autenticado — clique para gerenciar';
  } else {
    icon.innerHTML = icone('lock');
    label.textContent = 'safe';
    badge.title = 'modo seguro ativo — clique para autenticar';
  }
}

/** Abre o modal correto dependendo do estado */
async function openAuthModal() {
  if (_authState.force_safe) return;  // modal não faz sentido com --safe

  // busca status fresco (senha padrão, etc.)
  let status;
  try { status = await api('/api/auth/status'); }
  catch(_) { return; }

  _authState = { ..._authState, ...status };

  // limpa erros
  document.getElementById('auth-error').classList.add('hidden');
  document.getElementById('auth-changepw-error').classList.add('hidden');
  document.getElementById('auth-password-input').value = '';
  document.getElementById('auth-newpw-input').value    = '';

  if (status.authenticated) {
    showAuthedPanel();
  } else {
    showLoginPanel(status);
  }

  document.getElementById('auth-modal').classList.remove('hidden');
  setTimeout(() => {
    const inp = document.getElementById('auth-password-input');
    if (inp && !status.authenticated) inp.focus();
  }, 80);
}

function showLoginPanel(status) {
  document.getElementById('auth-panel-login').classList.remove('hidden');
  document.getElementById('auth-panel-authed').classList.add('hidden');
  document.getElementById('auth-panel-changepw').classList.add('hidden');

  const hint   = document.getElementById('auth-default-hint');
  const hintTx = document.getElementById('auth-default-pw-text');

  if (status && status.is_default && status.default_password) {
    hintTx.innerHTML =
      `Senha padrão ativa: <strong style="font-family:var(--font-mono);letter-spacing:.05em">`
      + esc(status.default_password) + `</strong>. Entre e troque-a em seguida.`;
    hint.classList.remove('hidden');
  } else {
    hint.classList.add('hidden');
  }
}

function showAuthedPanel() {
  document.getElementById('auth-panel-login').classList.add('hidden');
  document.getElementById('auth-panel-authed').classList.remove('hidden');
  document.getElementById('auth-panel-changepw').classList.add('hidden');
}

function openChangePwPanel() {
  document.getElementById('auth-panel-login').classList.add('hidden');
  document.getElementById('auth-panel-authed').classList.add('hidden');
  document.getElementById('auth-panel-changepw').classList.remove('hidden');
  setTimeout(() => document.getElementById('auth-newpw-input').focus(), 80);
}

async function doLogin() {
  const btn = document.getElementById('auth-login-btn');
  const pw  = document.getElementById('auth-password-input').value;
  const err = document.getElementById('auth-error');

  btn.disabled    = true;
  btn.textContent = '…';
  err.classList.add('hidden');

  try {
    await fetch('/api/auth/login', {
      method:      'POST',
      credentials: 'include',
      headers:     { 'Content-Type': 'application/json' },
      body:        JSON.stringify({ password: pw }),
    }).then(async r => {
      if (!r.ok) throw new Error('incorreta');
      return r.json();
    });

    _authState.authenticated = true;
    _renderAuthBadge();
    closeModal('auth-modal');
    // recarrega info para atualizar tools disponíveis
    const info = await api('/api/info');
    atualizarTools(info.tools);
    addSysMsg('🔓 autenticado — todas as tools disponíveis');
  } catch(_) {
    err.classList.remove('hidden');
    document.getElementById('auth-password-input').value = '';
    document.getElementById('auth-password-input').focus();
  } finally {
    btn.disabled    = false;
    btn.textContent = 'entrar';
  }
}

async function doLogout() {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST', credentials: 'include',
    });
  } catch(_) {}

  _authState.authenticated = false;
  _renderAuthBadge();
  closeModal('auth-modal');
  const info = await api('/api/info');
  atualizarTools(info.tools);
  addSysMsg('🔒 sessão encerrada — modo seguro ativo');
}

async function doChangePassword() {
  const newPw = document.getElementById('auth-newpw-input').value;
  const err   = document.getElementById('auth-changepw-error');
  err.classList.add('hidden');

  try {
    const r = await fetch('/api/auth/change-password', {
      method:      'POST',
      credentials: 'include',
      headers:     { 'Content-Type': 'application/json' },
      body:        JSON.stringify({ new_password: newPw }),
    });
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || 'erro');

    _authState.is_default = false;
    closeModal('auth-modal');
    addSysMsg('✓ senha alterada com sucesso');
  } catch(e) {
    err.textContent = e.message || 'erro ao trocar senha';
    err.classList.remove('hidden');
  }
}

/* ══ Ajustes ═══════════════════════════════════════════════════
   Modal com menu lateral: modelos, provedores e sobre. Toda a leitura vem de
   /api/settings, que nunca devolve chave — só "tem_chave". */
let _settings = null;

window.openSettings = async () => {
  document.getElementById('settings-modal').classList.remove('hidden');
  closeSidebar();
  settingsTab('modelos');
  ['modelos', 'provedores', 'sobre'].forEach(aba => {
    document.getElementById('settings-' + aba).innerHTML =
      '<div class="panel-empty">carregando…</div>';
  });
  try {
    _settings = await api('/api/settings');
    renderSettingsModelos();
    renderSettingsProvedores();
    renderSettingsSobre();
  } catch (e) {
    document.getElementById('settings-modelos').innerHTML =
      `<div class="panel-empty">erro ao carregar: ${esc(e.message)}</div>`;
  }
};

window.settingsTab = (nome) => {
  document.querySelectorAll('.settings-tab').forEach(el =>
    el.classList.toggle('active', el.dataset.aba === nome));
  document.querySelectorAll('.settings-pane').forEach(el =>
    el.classList.toggle('active', el.id === 'settings-' + nome));
};

function renderSettingsModelos() {
  const d = _settings;
  const modelos = d.ollama || [];
  const cloud = d.provedores_configurados || [];
  const ativo = d.secundario_ativo;
  const mesmo = (p) => !!ativo && ativo.provider === p.provider && ativo.model === p.model;

  document.getElementById('settings-modelos').innerHTML = `
    <div class="sett-row">
      <div>
        <div class="sett-label">perfil ativo</div>
        <div class="sett-value">${esc(d.perfil)} · ${esc(d.perfil_label || d.model)}</div>
      </div>
      <span class="sett-pill">${esc(d.agent_full || d.agent)}</span>
    </div>

    <div class="sett-secao">Ollama (local)</div>
    <div class="sett-hint">Usado quando o perfil é <strong>local</strong>. Se o Ollama não responder,
      digite o nome abaixo (ex.: <code>gemma4:cloud</code>).</div>
    <div class="sett-list">
      ${modelos.length ? modelos.map(m => `
        <button class="sett-item ${m === d.model && d.perfil === 'local' ? 'ativo' : ''}" data-modelo="${esc(m)}">
          <span>${esc(m)}</span>
          <span class="sett-item-meta">${m === d.model ? (d.perfil === 'local' ? 'em uso' : 'local salvo') : 'usar'}</span>
        </button>`).join('') : '<div class="panel-empty">nenhum modelo listado</div>'}
    </div>
    <div class="sett-form-row">
      <input id="sett-modelo-input" class="panel-search" placeholder="nome do modelo" value="${esc(d.model)}">
      <button class="btn-primary btn-sm" id="sett-modelo-btn">aplicar</button>
    </div>
    <div id="sett-modelo-msg" class="sett-msg"></div>

    <div class="sett-secao">Provedores configurados</div>
    <div class="sett-hint">Usado quando o perfil é <strong>nuvem</strong> — só aparecem os provedores
      com chave salva.</div>
    <div class="sett-list">
      ${cloud.length ? cloud.map(p => `
        <button class="sett-item ${mesmo(p) ? 'ativo' : ''}" data-provedor="${esc(p.chave)}">
          <span>${esc(p.chave)}</span>
          <span class="sett-item-meta">${mesmo(p) ? 'em uso' : 'usar na nuvem'}</span>
        </button>`).join('') : '<div class="panel-empty">nenhuma chave salva — veja a aba Provedores</div>'}
    </div>`;
  document.getElementById('sett-modelo-btn').onclick = () =>
    aplicarModelo(document.getElementById('sett-modelo-input').value);
}

window.aplicarProvedor = async (chave) => {
  try {
    await api('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provedor: chave }),
    });
    _settings = await api('/api/settings');
    renderSettingsModelos();
    addSysMsg(`provedor da nuvem: ${chave}`);
  } catch (e) {
    addSysMsg(`não deu para trocar o provedor: ${e.message}`);
  }
};

window.aplicarModelo = async (nome) => {
  const modelo = String(nome || '').trim();
  if (!modelo) return;
  try {
    const r = await api('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelo }),
    });
    currentModel = r.model;
    document.getElementById('topbar-model').textContent = r.model;
    document.getElementById('info-model').textContent   = r.model;
    addSysMsg(`modelo: ${r.model}`);
    _settings.model = r.model;
    renderSettingsModelos();
    const msg = document.getElementById('sett-modelo-msg');
    msg.textContent = `aplicado: ${r.model}`;
    msg.className = 'sett-msg ok';
  } catch (e) {
    const msg = document.getElementById('sett-modelo-msg');
    if (msg) { msg.textContent = e.message; msg.className = 'sett-msg err'; }
  }
};

function renderSettingsProvedores() {
  const d = _settings;
  document.getElementById('settings-provedores').innerHTML = `
    <div class="sett-hint">A chave fica em <code>${esc(d.caminhos.segredos)}</code>
      e não volta para a tela — só o indicador “chave salva”.</div>
    <div class="sett-list">
      ${d.providers.map(p => `
        <div class="sett-prov ${p.tem_chave ? 'ok' : ''}">
          <div class="sett-prov-top">
            <span>${esc(p.name)}</span>
            <span class="sett-pill ${p.tem_chave ? 'ok' : ''}">${p.tem_chave ? 'chave salva' : 'sem chave'}</span>
          </div>
          <div class="sett-prov-meta">${esc(p.base_url || '—')} · ${esc(p.model || '—')}</div>
          ${p.notes ? `<div class="sett-prov-notes">${esc(p.notes)}</div>` : ''}
          <div class="sett-prov-actions">
            <button class="btn-outline btn-sm" data-prov="${esc(p.id)}">configurar</button>
            ${p.key_url ? `<a class="sett-link" href="${esc(p.key_url)}" target="_blank" rel="noopener">obter chave</a>` : ''}
          </div>
        </div>`).join('')}
    </div>
    <div class="sett-divider"></div>
    <div class="sett-form">
      <div class="sett-label">salvar chave</div>
      <select id="sett-prov-id" class="panel-search">
        ${d.providers.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}
      </select>
      <input id="sett-prov-base"  class="panel-search" placeholder="base_url">
      <input id="sett-prov-model" class="panel-search" placeholder="modelo (opcional)">
      <input id="sett-prov-key"   class="panel-search" type="password"
             autocomplete="new-password" placeholder="api_key">
      <button class="btn-primary btn-sm" id="sett-prov-btn">salvar</button>
      <div id="sett-prov-msg" class="sett-msg"></div>
    </div>`;
  document.getElementById('sett-prov-btn').onclick = salvarProvider;
  preencherProvider(d.providers[0] ? d.providers[0].id : '');
}

window.preencherProvider = (id) => {
  const p = (_settings.providers || []).find(x => x.id === id);
  if (!p) return;
  const sel = document.getElementById('sett-prov-id');
  if (sel) sel.value = id;
  const base  = document.getElementById('sett-prov-base');
  const model = document.getElementById('sett-prov-model');
  const key   = document.getElementById('sett-prov-key');
  if (base)  base.value  = p.base_url || '';
  if (model) model.value = p.model || '';
  if (key)   key.value   = '';
};

window.salvarProvider = async () => {
  try {
    const r = await api('/api/settings/provider', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: document.getElementById('sett-prov-id').value,
        base_url: document.getElementById('sett-prov-base').value.trim(),
        model:    document.getElementById('sett-prov-model').value.trim(),
        api_key:  document.getElementById('sett-prov-key').value.trim(),
      }),
    });
    _settings = await api('/api/settings');
    renderSettingsProvedores();
    preencherProvider(r.provider);
    const msg = document.getElementById('sett-prov-msg');
    msg.textContent = `chave salva para ${r.provider}`;
    msg.className = 'sett-msg ok';
  } catch (e) {
    const msg = document.getElementById('sett-prov-msg');
    if (msg) { msg.textContent = e.message; msg.className = 'sett-msg err'; }
  }
};

function renderSettingsSobre() {
  const d = _settings;
  const linhas = [
    ['versão',    d.version],
    ['agente',    `${d.agent_full} (${d.agent})`],
    ['modelo',    d.model],
    ['agentes',   d.contagem.agents],
    ['tools',     d.contagem.tools],
    ['workspace', d.caminhos.workspace],
    ['histórico', d.caminhos.historico],
    ['segredos',  d.caminhos.segredos],
  ];
  document.getElementById('settings-sobre').innerHTML = `
    <div class="sett-info">
      ${linhas.map(([k, v]) => `
        <div class="sett-info-row"><span>${esc(k)}</span><code>${esc(v)}</code></div>`).join('')}
    </div>
    <div class="sett-divider"></div>
    <div class="sett-links">
      <a class="sett-link" href="${esc(d.repo)}" target="_blank" rel="noopener">${icone('book')} repositório</a>
      <a class="sett-link" href="${esc(d.repo)}/blob/main/README.md" target="_blank" rel="noopener">${icone('book')} documentação</a>
    </div>`;
}

// delegação: os painéis são re-renderizados a cada mudança
document.getElementById('settings-modelos').addEventListener('click', (ev) => {
  const m = ev.target.closest('[data-modelo]');
  if (m) { aplicarModelo(m.dataset.modelo); return; }
  const p = ev.target.closest('[data-provedor]');
  if (p) aplicarProvedor(p.dataset.provedor);
});
document.getElementById('settings-provedores').addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-prov]');
  if (b) preencherProvider(b.dataset.prov);
});

/* ══ Perfil do orquestrador (local / nuvem) ════════════════════
   local = Ollama; nuvem = provider secundário como orquestrador (mesma
   semântica de /perfil na CLI). A troca exige login (PUT /api/settings). */
function setPerfilUI(d) {
  const label = d.perfil_label || d.model || '';
  const botao = document.getElementById('perfil-btn');
  if (botao) {
    const nuvem = d.perfil === 'nuvem';
    botao.innerHTML = icone(nuvem ? 'cloud' : 'pc') + `<span>${esc(d.perfil || 'local')}</span>`;
    botao.classList.toggle('nuvem', nuvem);
    botao.title = `perfil ${d.perfil || 'local'} · ${label}`;
  }
  const topo = document.getElementById('topbar-model');
  if (topo) topo.textContent = label;
  const painel = document.getElementById('info-model');
  if (painel) painel.textContent = label;
  currentModel = label;
}

let _infoCache = null;

function _renderPerfilMenu(d) {
  const menu = document.getElementById('perfil-menu');
  menu.innerHTML = `
    <button class="perfil-opcao ${d.perfil === 'local' ? 'ativo' : ''}" data-perfil="local">
      <span class="perfil-opcao-nome">${icone('pc')} local</span>
      <span class="perfil-meta">${esc(d.model || '')}</span>
    </button>
    <button class="perfil-opcao ${d.perfil === 'nuvem' ? 'ativo' : ''}" data-perfil="nuvem"${d.nuvem_disponivel ? '' : ' disabled'}>
      <span class="perfil-opcao-nome">${icone('cloud')} nuvem</span>
      <span class="perfil-meta">${d.nuvem_disponivel ? 'provider configurado' : 'configure um provedor'}</span>
    </button>`;
  menu.classList.remove('hidden');
}

window.togglePerfilMenu = async (ev) => {
  ev.stopPropagation();
  const menu = document.getElementById('perfil-menu');
  if (!menu.classList.contains('hidden')) { menu.classList.add('hidden'); return; }

  // abre na hora com o que já está em memória; a atualização vem em seguida
  // (antes era um /api/settings, que consulta o Ollama e travava o clique)
  if (_infoCache) _renderPerfilMenu(_infoCache);
  try {
    const d = await api('/api/info');
    _infoCache = d;
    setPerfilUI(d);
    if (!menu.classList.contains('hidden')) _renderPerfilMenu(d);
  } catch (e) {
    if (!_infoCache) addSysMsg(`erro ao ler ajustes: ${e.message}`);
  }
};

window.aplicarPerfil = async (perfil) => {
  try {
    const r = await api('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ perfil }),
    });
    document.getElementById('perfil-menu').classList.add('hidden');
    setPerfilUI(r);
    addSysMsg(`perfil: ${r.perfil} · ${r.perfil_label}`);

    // nuvem tira secondary_model do schema; mantém o painel de tools coerente
    const info = await api('/api/info');
    _infoCache = info;
    atualizarTools(info.tools);
  } catch (e) {
    addSysMsg(`não deu para trocar o perfil: ${e.message}`);
  }
};

document.getElementById('perfil-menu').addEventListener('click', (ev) => {
  const b = ev.target.closest('[data-perfil]');
  if (b && !b.disabled) aplicarPerfil(b.dataset.perfil);
});

document.addEventListener('click', (ev) => {
  const menu = document.getElementById('perfil-menu');
  if (menu && !menu.classList.contains('hidden') &&
      !menu.contains(ev.target) && !ev.target.closest('#perfil-btn')) {
    menu.classList.add('hidden');
  }
});

// Digitar "/" (ou filtrar) abre a paleta de comandos
document.getElementById('msg-input').addEventListener('input', () => {
  if (window.Paleta) Paleta.atualizar();
});

// O mesmo botão envia e para: o estado do turno decide o que ele faz.
document.getElementById('send-btn').addEventListener('click', (ev) => {
  ev.preventDefault();
  if (turnoAtivo) cancelarTurno(currentTurn);
  else sendMessage();
});

// Fonte do painel como botão: Enter/Espaço abrem no visualizador.
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Enter' && ev.key !== ' ') return;
  const src = ev.target.closest?.('.rp-src');
  if (!src || !src.dataset.previewPath) return;
  ev.preventDefault();
  src.click();
});

// ── Boot ───────────────────────────────────────────────────────
init();