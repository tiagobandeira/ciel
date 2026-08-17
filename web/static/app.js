/* ── estado ──────────────────────────────────────────────────────────────── */
let pendingFile = null;   // { file, dataUrl, type: 'image'|'text', content }

const messagesEl  = document.getElementById('messages');
const inputEl     = document.getElementById('msg-input');
const sendBtn     = document.getElementById('send-btn');
const fileInput   = document.getElementById('file-input');
const uploadPrev  = document.getElementById('upload-preview');
const prevThumb   = document.getElementById('prev-thumb');
const prevName    = document.getElementById('prev-name');

/* ── init ────────────────────────────────────────────────────────────────── */
async function init() {
  try {
    const info = await apiFetch('/info');
    document.getElementById('agent-badge').textContent = info.agent;
    document.getElementById('model-badge').textContent  = info.model;
    renderTools(info.tools);
    addMsg('sys', `agente: ${info.agent} · ${info.tools.length} tools`);
  } catch(e) {
    addMsg('sys', 'erro ao conectar — servidor rodando?');
  }
}

/* ── api ─────────────────────────────────────────────────────────────────── */
async function apiFetch(url, opts = {}) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/* ── tools drawer ────────────────────────────────────────────────────────── */
function renderTools(tools) {
  const drawer = document.getElementById('tools-drawer');
  drawer.innerHTML = tools.map(t =>
    `<div class="tool-row">
      <span class="tool-name">⚙ ${esc(t.name)}</span>
      <span class="tool-cat">[${esc(t.cat)}]</span>
      <span class="tool-desc">${esc(t.desc)}</span>
    </div>`
  ).join('');
}
window.toggleTools = () =>
  document.getElementById('tools-drawer').classList.toggle('open');

/* ── markdown render ─────────────────────────────────────────────────────── */
function renderMarkdown(text) {
  // usa marked.js se disponível, senão fallback simples
  if (window.marked) {
    marked.setOptions({ breaks: true, gfm: true });
    return marked.parse(text);
  }
  // fallback: só escapa e preserva quebras
  return esc(text).replace(/\n/g, '<br>');
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── detecta arquivos mencionados na resposta ────────────────────────────── */
function extractFileRefs(text) {
  const patterns = [
    // "salvo em: data/user/x.pdf" ou "criado em x.mp3"
    /(?:salvo?|criado?|gerado?|escrito?|saved?)\s+em[:\s]+['"]?([^\s\n,'"]+\.[a-zA-Z0-9]{1,6})['"]?/gi,
    // "arquivo: x.pdf" ou "arquivo salvo: x"
    /arquivo[:\s]+['"]?([^\s\n,'"]+\.[a-zA-Z0-9]{1,6})['"]?/gi,
    // qualquer path com data/user/ explícito
    /['"]?((?:data[\\\/]user[\\\/]|uploads[\\\/])[^\s\n,'"]+\.[a-zA-Z0-9]{1,6})['"]?/gi,
    // "disponível em: x.ext"
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

const IMAGE_EXTS = new Set(['png','jpg','jpeg','gif','webp','bmp','svg']);

function buildDownloadLinks(refs) {
  if (!refs.length) return '';
  return refs.map(p => {
    const ext  = p.split('.').pop().toLowerCase();
    const name = p.split(/[\\/]/).pop();
    const isImg = IMAGE_EXTS.has(ext);
    const icon  = isImg ? '🖼' : '⬇';
    return `<a class="dl-link" href="/download?path=${encodeURIComponent(p)}" 
               download="${esc(name)}" target="_blank">
              ${icon} ${esc(name)}
            </a>`;
  }).join(' ');
}

/* ── mensagens ───────────────────────────────────────────────────────────── */
function addMsg(role, text, rawText = null) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;

  if (role !== 'sys') {
    const label = { user: 'você', agent: 'agente', warn: '⚡ auto tool' }[role] || role;
    div.innerHTML = `<div class="msg-label">${label}</div>`;

    // botão de copy
    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.textContent = 'copy';
    copyBtn.onclick = () => copyText(copyBtn, rawText || text);
    div.appendChild(copyBtn);

    // conteúdo com markdown
    const body = document.createElement('div');
    body.className = 'msg-body';
    body.innerHTML = renderMarkdown(text);
    div.appendChild(body);

    // links de download detectados automaticamente
    const refs = extractFileRefs(rawText || text);
    if (refs.length) {
      const dlDiv = document.createElement('div');
      dlDiv.innerHTML = buildDownloadLinks(refs);
      div.appendChild(dlDiv);
    }

    // preview de imagem se a msg menciona imagem
    refs.filter(p => IMAGE_EXTS.has(p.split('.').pop().toLowerCase())).forEach(p => {
      const img = document.createElement('img');
      img.className = 'msg-img';
      img.src = `/download?path=${encodeURIComponent(p)}`;
      img.onerror = () => img.remove();
      div.appendChild(img);
    });
  } else {
    div.textContent = text;
  }

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function addTyping() {
  const div = document.createElement('div');
  div.className = 'msg agent';
  div.id = 'typing';
  div.innerHTML = '<div class="msg-label">agente</div>'
    + '<div class="typing"><span></span><span></span><span></span></div>';
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}
function removeTyping() {
  document.getElementById('typing')?.remove();
}

async function copyText(btn, text) {
  let ok = false;
  // tenta clipboard API (HTTPS ou localhost)
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); ok = true; } catch(_) {}
  }
  // fallback: textarea temporario (funciona em HTTP no celular)
  if (!ok) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    try { document.execCommand('copy'); ok = true; } catch(_) {}
    document.body.removeChild(ta);
  }
  btn.textContent = ok ? '✓' : '!';
  btn.classList.add('copied');
  setTimeout(() => { btn.textContent = 'copy'; btn.classList.remove('copied'); }, 1500);
}

/* ── upload de arquivo ───────────────────────────────────────────────────── */
window.triggerUpload = () => fileInput.click();

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
    // texto, csv, md, py, etc.
    const reader = new FileReader();
    reader.onload = e => {
      pendingFile = { file, content: e.target.result, type: 'text' };
      showUploadPreview('text', null, file.name);
    };
    reader.readAsText(file);
  }
});

function showUploadPreview(type, src, name) {
  uploadPrev.classList.add('active');
  prevName.textContent = name;
  if (type === 'img' && src) {
    prevThumb.innerHTML = `<img src="${src}" alt="preview">`;
  } else {
    prevThumb.innerHTML = '📄';
  }
}

window.clearUpload = () => {
  pendingFile = null;
  uploadPrev.classList.remove('active');
  prevThumb.innerHTML = '';
  prevName.textContent = '';
};

/* ── envio ───────────────────────────────────────────────────────────────── */
window.sendMessage = async () => {
  const text = inputEl.value.trim();
  if ((!text && !pendingFile) || sendBtn.disabled) return;

  const displayText = text || (pendingFile ? `[arquivo: ${pendingFile.file.name}]` : '');
  inputEl.value = '';
  autoResize(inputEl);
  addMsg('user', displayText);
  sendBtn.disabled = true;
  addTyping();

  const file = pendingFile;
  clearUpload();

  try {
    let body;
    let headers = {};

    if (file?.type === 'image') {
      // envia imagem como base64 no JSON
      body = JSON.stringify({
        message: text || 'Descreva ou analise esta imagem.',
        image_b64: file.dataUrl.split(',')[1],
        filename:  file.file.name,
      });
      headers['Content-Type'] = 'application/json';
    } else if (file?.type === 'text') {
      body = JSON.stringify({
        message:  text || `Analise o arquivo: ${file.file.name}`,
        file_text: file.content,
        filename:  file.file.name,
      });
      headers['Content-Type'] = 'application/json';
    } else {
      body = JSON.stringify({ message: text });
      headers['Content-Type'] = 'application/json';
    }

    const data = await apiFetch('/chat', { method: 'POST', headers, body });
    removeTyping();

    const role = data.status === 'needs_tool' ? 'warn' : 'agent';
    addMsg(role, data.reply || data.error || '?', data.reply);

    if (data.status === 'done') {
      const info = await apiFetch('/info');
      renderTools(info.tools);
    }
  } catch(e) {
    removeTyping();
    addMsg('sys', `erro: ${e.message}`);
  }

  sendBtn.disabled = false;
  inputEl.focus();
};

window.clearChat = async () => {
  await apiFetch('/clear', { method: 'POST' });
  messagesEl.innerHTML = '';
  addMsg('sys', 'histórico limpo');
};

/* ── utils ───────────────────────────────────────────────────────────────── */
window.handleKey = e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
};

window.autoResize = el => {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
};

/* ── drag & drop na janela ───────────────────────────────────────────────── */
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', e => {
  e.preventDefault();
  const file = e.dataTransfer?.files?.[0];
  if (!file) return;
  const fakeEvt = { target: { files: [file] } };
  // simula seleção
  const dt = new DataTransfer();
  dt.items.add(file);
  fileInput.files = dt.files;
  fileInput.dispatchEvent(new Event('change'));
});

init();