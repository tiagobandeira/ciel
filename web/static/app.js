/* ═══════════════════════════════════════════════════════════════
   Ciel — app.js
   Frontend da interface web. Comunica com server.py via /api/*.
   ═══════════════════════════════════════════════════════════════ */

// ── estado global ─────────────────────────────────────────────
let pendingFile      = null;   // { file, dataUrl?, content?, type: 'image'|'text' }
let currentAgent     = null;   // string: id do agente ativo
let currentModel     = null;   // string
let currentSessionId = null;   // int | null
let tokenIn          = 0;
let tokenOut         = 0;
let allTools         = {};     // cache de tools
let rightPanelOpen   = true;

const IMAGE_EXTS = new Set(['png','jpg','jpeg','gif','webp','bmp','svg']);

// ── refs DOM ──────────────────────────────────────────────────
const messagesEl  = () => document.getElementById('messages');
const inputEl     = () => document.getElementById('msg-input');
const sendBtn     = () => document.getElementById('send-btn');

// ── init ──────────────────────────────────────────────────────
async function init() {
  try {
    const info = await api('/api/info');
    currentAgent = info.agent;
    currentModel = info.model;
    allTools     = {};
    (info.tools || []).forEach(t => { allTools[t.name] = t; });

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

    // Tools count badge
    document.getElementById('tools-count').textContent = (info.tools || []).length;

    renderToolsList(info.tools || []);
    addSysMsg(`ciel · ${info.agent} · ${(info.tools||[]).length} tools`);

    // Sessões
    await loadSessions();
  } catch(e) {
    setStatus('error');
    addSysMsg('erro ao conectar — servidor rodando?');
  }
}

// ── API ───────────────────────────────────────────────────────
async function api(url, opts = {}) {
  const r = await fetch(url, opts);
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
function updateTokenDisplay(dIn = 0, dOut = 0) {
  tokenIn  += dIn;
  tokenOut += dOut;
  document.getElementById('token-in').textContent  = fmt(tokenIn);
  document.getElementById('token-out').textContent = fmt(tokenOut);
  document.getElementById('info-tin').textContent  = fmt(tokenIn);
  document.getElementById('info-tout').textContent = fmt(tokenOut);
}
function fmt(n) {
  return n >= 1000 ? `${(n/1000).toFixed(1)}k` : String(n);
}

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

function addAgentMsg(text, role = 'agent') {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const label = role === 'warn' ? '⚡ auto tool' : 'ciel';

  // detecta arquivos na resposta
  const refs = extractFileRefs(text);
  let dlLinks = '';
  if (refs.length) dlLinks = buildDownloadLinks(refs);

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
      ${dlLinks}${imgBlocks}
    </div>`;
  messagesEl().appendChild(div);
  scrollBottom();
}

function addTypingIndicator() {
  const div = document.createElement('div');
  div.className = 'msg agent';
  div.id = 'typing-indicator';
  div.innerHTML = `
    <div class="msg-label">ciel</div>
    <div class="msg-bubble">
      <div class="typing-row">
        <div class="typing-dots"><span></span><span></span><span></span></div>
        <span class="typing-label">pensando…</span>
      </div>
    </div>`;
  messagesEl().appendChild(div);
  scrollBottom();
}

function removeTypingIndicator() {
  document.getElementById('typing-indicator')?.remove();
}

function scrollBottom() {
  const el = messagesEl();
  el.scrollTop = el.scrollHeight;
}

// ── Envio de mensagem ─────────────────────────────────────────
window.sendMessage = async () => {
  const text = inputEl().value.trim();
  if ((!text && !pendingFile) || sendBtn().disabled) return;

  const displayText = text || (pendingFile ? `[arquivo: ${pendingFile.file.name}]` : '');
  inputEl().value = '';
  autoResize(inputEl());
  closeCommandMenu();

  const fileInfo = pendingFile ? pendingFile.file.name : null;
  addUserMsg(displayText, fileInfo);
  sendBtn().disabled = true;
  setStatus('loading');
  addTypingIndicator();

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
      });
    } else if (file?.type === 'text') {
      body = JSON.stringify({
        message:   text || `Analise o arquivo: ${file.file.name}`,
        file_text: file.content,
        filename:  file.file.name,
        session_id: currentSessionId,
      });
    } else {
      body = JSON.stringify({ message: text, session_id: currentSessionId });
    }

    const data = await api('/api/chat', { method: 'POST', headers, body });
    removeTypingIndicator();
    setStatus('online');

    const role = data.status === 'needs_tool' ? 'warn' : 'agent';
    addAgentMsg(data.reply || data.error || '?', role);

    // atualiza tokens
    if (data.tokens_in || data.tokens_out) {
      updateTokenDisplay(data.tokens_in || 0, data.tokens_out || 0);
    }

    // atualiza session_id se veio na resposta
    if (data.session_id && !currentSessionId) {
      currentSessionId = data.session_id;
      document.getElementById('info-session').textContent = `#${data.session_id}`;
    }

    // recarrega tools e sessões em background
    if (data.tools_changed) {
      const info = await api('/api/info');
      allTools = {};
      (info.tools || []).forEach(t => { allTools[t.name] = t; });
      renderToolsList(info.tools || []);
      document.getElementById('tools-count').textContent = (info.tools || []).length;
    }

    await loadSessions();

  } catch(e) {
    removeTypingIndicator();
    setStatus('error');
    addSysMsg(`erro: ${e.message}`);
  }

  sendBtn().disabled = false;
  inputEl().focus();
};

// ── Limpar / nova sessão ──────────────────────────────────────
window.clearChat = async () => {
  try { await api('/api/clear', { method: 'POST' }); } catch(_) {}
  messagesEl().innerHTML = '';
  tokenIn = 0; tokenOut = 0;
  updateTokenDisplay();
  currentSessionId = null;
  document.getElementById('info-session').textContent = 'nova';
  addSysMsg('nova sessão iniciada');
};

window.newSession = () => clearChat();

// ── Quick command ─────────────────────────────────────────────
window.quickCommand = (cmd) => {
  closeCommandMenu();
  inputEl().value = cmd;
  sendMessage();
};

// ── Tools panel ───────────────────────────────────────────────
function renderToolsList(tools) {
  const list = document.getElementById('tools-list');
  if (!tools.length) {
    list.innerHTML = '<div class="panel-empty">nenhuma tool carregada</div>';
    return;
  }
  list.innerHTML = tools.map(t => {
    const isTemp = t.cat === 'temp';
    return `<div class="tool-item">
      <div class="tool-item-name">
        ⚙ ${esc(t.name)}
        <span class="tool-cat-badge${isTemp?' temp':''}">
          ${isTemp?'temp':'perm'}
        </span>
      </div>
      <div class="tool-item-desc">${esc(t.desc || '')}</div>
    </div>`;
  }).join('');
}

window.filterTools = (q) => {
  const items = document.querySelectorAll('.tool-item');
  items.forEach(el => {
    const name = el.querySelector('.tool-item-name')?.textContent.toLowerCase() || '';
    el.style.display = name.includes(q.toLowerCase()) ? '' : 'none';
  });
};

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
window.toggleRightPanel = () => {
  const panel = document.getElementById('right-panel');
  rightPanelOpen = !rightPanelOpen;
  panel.classList.toggle('collapsed', !rightPanelOpen);
  document.getElementById('right-panel-btn').textContent = rightPanelOpen ? '⊟' : '⊞';
};

window.toggleToolsPanel = () => {
  // from sidebar nav: abre painel direito e muda tab
  if (!rightPanelOpen) toggleRightPanel();
  switchPanelTab('tools');
  closeSidebar();
};

// ── Panel tabs ─────────────────────────────────────────────────
window.switchPanelTab = (tab) => {
  // marca o botão cujo onclick contém o nome da tab
  document.querySelectorAll('.panel-tab').forEach(el => {
    el.classList.toggle('active', el.getAttribute('onclick')?.includes(`'${tab}'`));
  });
  document.getElementById('panel-tools').classList.toggle('active', tab === 'tools');
  document.getElementById('panel-session').classList.toggle('active', tab === 'session');
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

window.switchAgent = async (agentId) => {
  closeModal('agent-modal');
  addSysMsg(`trocando para agente: ${agentId}…`);
  try {
    const data = await api('/api/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent: agentId }),
    });
    currentAgent = agentId;
    tokenIn = 0; tokenOut = 0; updateTokenDisplay();
    messagesEl().innerHTML = '';
    currentSessionId = null;

    document.getElementById('topbar-agent').textContent = data.agent;
    document.getElementById('sidebar-agent-name').textContent = data.agent_full || data.agent;
    document.getElementById('sidebar-agent-desc').textContent = data.agent_desc || '';
    document.getElementById('agent-avatar').textContent = (data.agent_full || data.agent)[0].toUpperCase();
    document.getElementById('info-agent').textContent = data.agent;
    document.getElementById('info-session').textContent = 'nova';

    allTools = {};
    (data.tools || []).forEach(t => { allTools[t.name] = t; });
    renderToolsList(data.tools || []);
    document.getElementById('tools-count').textContent = (data.tools || []).length;

    addSysMsg(`agente: ${data.agent_full || data.agent} · ${(data.tools||[]).length} tools`);
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
window.openSourceModal = async () => {
  const modal = document.getElementById('source-modal');
  modal.classList.remove('hidden');
  closeSidebar();
  await refreshSources();
};

async function refreshSources() {
  const list   = document.getElementById('sources-list-modal');
  const miniList = document.getElementById('sources-panel-list');
  list.innerHTML = '<div class="panel-empty">carregando…</div>';
  try {
    const data = await api('/api/sources');
    if (!data.sources.length) {
      list.innerHTML = '<div class="panel-empty">nenhuma fonte indexada</div>';
      miniList.innerHTML = '<div class="panel-empty">nenhuma fonte</div>';
      return;
    }
    list.innerHTML = data.sources.map(s => `
      <div class="source-item">
        <span class="source-item-name">📄 ${esc(s.filename)}</span>
        <span class="source-item-meta">${s.n_chunks} chunks · ${s.scope}</span>
        <button class="source-item-del" onclick="removeSource(${s.id})" title="remover">✕</button>
      </div>`).join('');
    miniList.innerHTML = data.sources.slice(0,5).map(s => `
      <div class="source-mini-item">
        <span class="source-mini-name">📄 ${esc(s.filename)}</span>
        <button class="source-mini-del" onclick="removeSource(${s.id})">✕</button>
      </div>`).join('');
  } catch(e) {
    list.innerHTML = `<div class="panel-empty">erro: ${esc(e.message)}</div>`;
  }
}

window.addSource = async () => {
  const input  = document.getElementById('source-input');
  const global = document.getElementById('source-global').checked;
  const path   = input.value.trim();
  if (!path) return;

  try {
    await api('/api/source', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, global, session_id: currentSessionId }),
    });
    input.value = '';
    await refreshSources();
    addSysMsg(`fonte indexada: ${path}`);
  } catch(e) {
    addSysMsg(`erro ao indexar: ${e.message}`);
  }
};

window.removeSource = async (id) => {
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
    list.innerHTML = data.sessions.map(s => `
      <button class="history-item" onclick="loadSession(${s.id})">
        <div class="history-item-dot"></div>
        <div class="history-item-body">
          <div class="history-item-title">${esc(s.title || 'sem título')}</div>
          <div class="history-item-meta">${esc(s.agent_id)} · ${esc(s.updated_at || '')}</div>
        </div>
        <span class="history-item-badge">${esc(s.agent_id)}</span>
      </button>`).join('');
  } catch(e) {
    list.innerHTML = `<div class="panel-empty">erro: ${esc(e.message)}</div>`;
  }
};

window.loadSession = async (sessionId) => {
  closeModal('history-modal');
  try {
    const data = await api(`/api/session/${sessionId}`);
    messagesEl().innerHTML = '';
    currentSessionId = sessionId;
    tokenIn = 0; tokenOut = 0; updateTokenDisplay();
    document.getElementById('info-session').textContent = `#${sessionId}`;
    (data.turns || []).forEach(t => {
      if (t.role === 'user')  addUserMsg(t.content);
      else if (t.role === 'agent') addAgentMsg(t.content);
    });
    addSysMsg(`sessão #${sessionId} carregada`);
  } catch(e) {
    addSysMsg(`erro ao carregar sessão: ${e.message}`);
  }
};

// ── Sessões sidebar ────────────────────────────────────────────
async function loadSessions() {
  try {
    const data = await api('/api/sessions');
    const list = document.getElementById('sessions-list');
    if (!data.sessions.length) {
      list.innerHTML = '<div class="sessions-empty">nenhuma sessão salva</div>';
      return;
    }
    list.innerHTML = data.sessions.slice(0, 20).map(s => `
      <button class="session-item ${s.id === currentSessionId ? 'active' : ''}"
              onclick="loadSession(${s.id}); closeSidebar()">
        <span class="session-item-dot"></span>
        <div class="session-item-body">
          <div class="session-item-title">${esc(s.title || 'sem título')}</div>
          <div class="session-item-meta">${esc(s.agent_id)} · ${esc(s.updated_at || '')}</div>
        </div>
      </button>`).join('');
  } catch(_) {}
}

// ── Upload de arquivo ──────────────────────────────────────────
window.triggerUpload = () => document.getElementById('file-input').click();

document.addEventListener('DOMContentLoaded', () => {
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
    document.getElementById('prev-thumb').textContent = '📄';
  }
}

window.clearUpload = () => {
  pendingFile = null;
  document.getElementById('upload-preview').classList.remove('active');
  document.getElementById('prev-thumb').innerHTML = '';
  document.getElementById('prev-name').textContent = '';
  document.getElementById('prev-type').textContent = '';
};

// ── Command menu ───────────────────────────────────────────────
window.toggleCommandMenu = () => {
  document.getElementById('command-menu').classList.toggle('hidden');
};

function closeCommandMenu() {
  document.getElementById('command-menu').classList.add('hidden');
}

// Fecha menu ao clicar fora
document.addEventListener('click', e => {
  const menu = document.getElementById('command-menu');
  if (!menu.classList.contains('hidden') && !menu.contains(e.target)) {
    const btn = e.target.closest('.input-action-btn');
    if (!btn) closeCommandMenu();
  }
});

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

function buildDownloadLinks(refs) {
  if (!refs.length) return '';
  return refs.map(p => {
    const ext  = p.split('.').pop().toLowerCase();
    const name = p.split(/[\\/]/).pop();
    const icon = IMAGE_EXTS.has(ext) ? '🖼' : '⬇';
    return `<a class="dl-link" href="/download?path=${encodeURIComponent(p)}" 
               download="${esc(name)}" target="_blank">${icon} ${esc(name)}</a>`;
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
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  if (e.key === 'Escape') closeCommandMenu();
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

// ── Boot ───────────────────────────────────────────────────────
init();
