/* ═══════════════════════════════════════════════════════════════
   Ciel — preview.js
   Painel de visualização de arquivos (gerados pelo agente e fontes
   enviadas), no estilo "chat + artefato" do Claude.

   O que ele NÃO faz: rodar backend. Só arquivo estático (html/css/js,
   markdown, texto/código, imagem, pdf). Flask/Django/binário continua
   sendo download.

   Página gerada (projeto ou html avulso) é servida por um servidor
   estático próprio, em porta separada (/api/preview_site): css/js irmãos,
   `type="module"`, `fetch()` local e `localStorage` funcionam, e por ser
   outra origem a página não alcança o cookie nem a API do Ciel.

   Depende de: /preview/<path>, /api/files e /api/preview_site (server.py),
   marked e hljs (já carregados no index.html).
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const KEY_LARGURA = 'ciel.preview.w';
  const KEY_AUTO    = 'ciel.preview.auto';
  const MAX_ABAS    = 8;
  const MAX_CHIPS   = 5;
  const MAX_TEXTO   = 800 * 1024;   // acima disso não renderiza, só baixa
  const LARGURA_MIN = 300;
  const LARGURA_PADRAO = 0.46;

  const EXT_IMG  = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'avif', 'svg']);
  const EXT_HTML = new Set(['html', 'htm', 'xhtml']);
  const EXT_MD   = new Set(['md', 'markdown']);
  const EXT_PDF  = new Set(['pdf']);
  const EXT_TXT  = new Set([
    'txt', 'log', 'py', 'js', 'mjs', 'cjs', 'jsx', 'ts', 'tsx', 'css', 'scss',
    'json', 'jsonc', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'sh', 'bash',
    'ps1', 'bat', 'cmd', 'sql', 'c', 'h', 'cpp', 'hpp', 'java', 'cs', 'go',
    'rs', 'rb', 'php', 'lua', 'r', 'kt', 'swift', 'csv', 'tsv', 'diff', 'patch',
    'xml', 'ipynb', 'env', 'gitignore', 'makefile', 'dockerfile',
  ]);

  const estado = {
    abas: [],
    ativa: -1,
    aberto: false,
    auto: true,
    seq: 0,
  };

  const el = (id) => document.getElementById(id);

  // ── utilidades ───────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function normalizar(caminho) {
    let p = String(caminho || '').trim().replace(/\\/g, '/').replace(/^\/+/, '');
    if (p.startsWith('preview/')) p = p.slice('preview/'.length);
    return p;
  }

  function baseNome(caminho) {
    const partes = normalizar(caminho).split('/');
    return partes[partes.length - 1] || caminho;
  }

  function extDe(nome) {
    const n = String(nome || '');
    const i = n.lastIndexOf('.');
    return i > 0 ? n.slice(i + 1).toLowerCase() : '';
  }

  function urlPublica(caminho, cacheBust) {
    const url = '/preview/' + normalizar(caminho).split('/').map(encodeURIComponent).join('/');
    return cacheBust ? `${url}?v=${Date.now()}` : url;
  }

  function urlDownload(caminho) {
    return '/download?path=' + encodeURIComponent(normalizar(caminho));
  }

  function tamanho(bytes) {
    const n = Number(bytes) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1).replace('.', ',') + ' KB';
    return (n / (1024 * 1024)).toFixed(1).replace('.', ',') + ' MB';
  }

  // ── painel: abrir / fechar / abas ────────────────────────────
  function mostrarPainel(abrir) {
    const painel = el('preview-pane');
    const resizer = el('preview-resizer');
    const btn = el('preview-btn');
    if (!painel) return;

    estado.aberto = abrir;
    painel.hidden = !abrir;
    if (resizer) resizer.hidden = !abrir;
    if (btn) btn.classList.toggle('active', abrir);
    document.body.classList.toggle('pv-aberto', abrir);

    if (abrir) {
      if (estado.ativa < 0 && estado.abas.length) estado.ativa = 0;
      desenhar();
    } else {
      const corpo = el('preview-body');
      if (corpo) corpo.innerHTML = '';   // para o iframe/JS do arquivo
    }
  }

  function abrir(caminho, opcoes) {
    const path = normalizar(caminho);
    if (!path) return;
    opcoes = opcoes || {};

    let indice = estado.abas.findIndex((a) => a.path === path);
    if (indice < 0) {
      estado.abas.push({
        path: path,
        name: opcoes.name || baseNome(path),
        // projeto: a pasta inteira é servida por um servidor estático próprio
        dir: !!opcoes.dir,
        entry: opcoes.entry || '',
        site: null,
      });
      indice = estado.abas.length - 1;
      // teto de abas: descarta a mais antiga
      while (estado.abas.length > MAX_ABAS) {
        estado.abas.shift();
        indice -= 1;
      }
    }
    estado.ativa = Math.max(0, indice);
    mostrarPainel(true);
  }

  function fecharAba(indice) {
    if (indice < 0 || indice >= estado.abas.length) return;
    estado.abas.splice(indice, 1);
    if (!estado.abas.length) {
      estado.ativa = -1;
      desenhar();
      return;
    }
    estado.ativa = Math.min(indice, estado.abas.length - 1);
    desenhar();
  }

  function ativar(indice) {
    if (indice < 0 || indice >= estado.abas.length) return;
    estado.ativa = indice;
    desenhar();
  }

  function toggle() {
    mostrarPainel(!estado.aberto);
  }

  /** Fecha as abas e mostra o navegador de arquivos de data/user. */
  function abrirNavegador() {
    estado.abas = [];
    estado.ativa = -1;
    mostrarPainel(true);
    desenhar();
  }

  // ── render ───────────────────────────────────────────────────
  function desenhar() {
    const painel = el('preview-pane');
    if (!painel || !estado.aberto) return;

    desenharAbas();
    desenharRodape();
    desenharCorpo();
  }

  function desenharAbas() {
    const tabs = el('preview-tabs');
    if (!tabs) return;
    tabs.innerHTML = estado.abas.map((aba, i) => {
      const ext = extDe(aba.name);
      return `<button class="pv-tab${i === estado.ativa ? ' ativa' : ''}" data-pv-tab="${i}"
                title="${esc(aba.path)}">
                <span class="pv-tab-name">${esc(aba.name)}</span>
                <span class="pv-tab-x" data-pv-close="${i}" title="fechar aba">✕</span>
              </button>`;
    }).join('');
    // rola até a aba ativa
    const ativa = tabs.querySelector('.pv-tab.ativa');
    if (ativa) ativa.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function desenharRodape() {
    const aba = estado.abas[estado.ativa];
    const caminho = el('preview-path');
    const servidor = el('preview-server');
    const dl = el('preview-download');
    if (!caminho || !dl) return;

    if (!aba) {
      caminho.textContent = 'nenhum arquivo aberto';
      if (servidor) servidor.classList.add('hidden');
      dl.setAttribute('href', '#');
      return;
    }

    const html = (aba.dir || EXT_HTML.has(extDe(aba.name))) && aba.site;
    caminho.textContent = html ? `${aba.site.path}/${aba.site.entry}` : aba.path;
    caminho.title = caminho.textContent;
    dl.setAttribute('href', aba.dir ? '#' : urlDownload(aba.path));

    if (servidor) {
      servidor.classList.toggle('hidden', !html);
      if (html) {
        servidor.textContent = `site :${aba.site.port}`;
        servidor.title = 'Servido por um servidor estático próprio, em outra origem: ' +
          'a página não alcança a API nem o cookie do Ciel.';
      }
    }
  }

  function desenharCorpo() {
    const corpo = el('preview-body');
    if (!corpo) return;
    const aba = estado.abas[estado.ativa];
    const seq = ++estado.seq;
    corpo.innerHTML = '';

    if (!aba) {
      corpo.appendChild(navegador());
      return;
    }

    const ext = extDe(aba.name);
    if (aba.dir || EXT_HTML.has(ext)) {
      carregarSite(aba, seq);
    } else if (EXT_IMG.has(ext)) {
      corpo.appendChild(imagemDe(aba));
    } else if (EXT_PDF.has(ext)) {
      corpo.appendChild(pdfDe(aba));
    } else if (EXT_MD.has(ext)) {
      carregarTexto(aba, seq, (txt) => markdownDe(aba, txt));
    } else if (EXT_TXT.has(ext) || !ext) {
      carregarTexto(aba, seq, (txt) => codigoDe(aba, txt));
    } else {
      corpo.appendChild(cartaoDe(aba, `Sem visualização no navegador para .${ext}.`));
    }
  }

  /**
   * Abre o projeto (pasta ou html) por um servidor estático próprio.
   *
   * Isso resolve o que o iframe isolado não resolvia: css/js irmãos carregam,
   * `type="module"` funciona, `fetch()` local funciona e `localStorage` existe
   * — porque a página tem origem de verdade (porta própria), separada do Ciel.
   */
  function carregarSite(aba, seq) {
    const corpo = el('preview-body');
    corpo.innerHTML = '<div class="pv-loading">abrindo página…</div>';

    fetch('/api/preview_site?path=' + encodeURIComponent(aba.path), { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('faça login (cadeado no topo) para abrir a página');
        return r.json().then((dados) => {
          if (!r.ok) throw new Error(dados.error || ('HTTP ' + r.status));
          return dados;
        });
      })
      .then((dados) => {
        if (seq !== estado.seq) return;
        aba.site = dados;
        const url = dados.url + (dados.url.includes('?') ? '&' : '?') + 'v=' + Date.now();
        corpo.innerHTML = '';
        corpo.appendChild(iframeDe(url, dados.name || aba.name));
        desenharRodape();
      })
      .catch((e) => {
        if (seq !== estado.seq) return;
        corpo.innerHTML = '';
        corpo.appendChild(cartaoDe(aba, e.message || 'não deu para abrir a página'));
      });
  }

  function iframeDe(src, titulo) {
    const f = document.createElement('iframe');
    f.className = 'pv-frame';
    f.title = titulo || 'preview';
    f.setAttribute('referrerpolicy', 'no-referrer');
    f.src = src;
    return f;
  }

  function imagemDe(aba) {
    const div = document.createElement('div');
    div.className = 'pv-image';
    const img = document.createElement('img');
    img.src = urlPublica(aba.path, true);
    img.alt = aba.name;
    div.appendChild(img);
    return div;
  }

  function pdfDe(aba) {
    // viewer nativo do browser, com toolbar
    const f = document.createElement('iframe');
    f.className = 'pv-frame';
    f.title = aba.name;
    f.src = urlPublica(aba.path) + '#toolbar=1&view=FitH';
    return f;
  }

  function carregarTexto(aba, seq, montar) {
    const corpo = el('preview-body');
    corpo.innerHTML = '<div class="pv-loading">carregando…</div>';
    fetch(urlPublica(aba.path), { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('faça login (cadeado no topo) para visualizar arquivos');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.text();
      })
      .then((txt) => {
        if (seq !== estado.seq) return;   // o usuário trocou de aba no meio
        corpo.innerHTML = '';
        if (txt.length > MAX_TEXTO) {
          corpo.appendChild(cartaoDe(aba, 'Arquivo grande demais para renderizar aqui (' + tamanho(txt.length) + ').'));
          return;
        }
        corpo.appendChild(montar(txt));
      })
      .catch((e) => {
        if (seq !== estado.seq) return;
        corpo.innerHTML = '';
        corpo.appendChild(cartaoDe(aba, e.message || 'não deu para abrir o arquivo'));
      });
  }

  function markdownDe(aba, txt) {
    const div = document.createElement('div');
    div.className = 'preview-md';
    if (window.marked) {
      try {
        marked.setOptions({ breaks: true, gfm: true });
        div.innerHTML = marked.parse(txt);
      } catch (_) {
        div.textContent = txt;
      }
    } else {
      div.textContent = txt;
    }
    destacar(div);
    return div;
  }

  function codigoDe(aba, txt) {
    const ext = extDe(aba.name);
    if (ext === 'json' || ext === 'jsonc' || ext === 'ipynb') {
      try { txt = JSON.stringify(JSON.parse(txt), null, 2); } catch (_) { /* mantém cru */ }
    }
    const pre = document.createElement('pre');
    pre.className = 'pv-code';
    const code = document.createElement('code');
    code.textContent = txt;
    pre.appendChild(code);
    if (window.hljs) {
      try { hljs.highlightElement(code); } catch (_) { /* sem destaque, sem drama */ }
    }
    return pre;
  }

  function destacar(raiz) {
    if (!window.hljs) return;
    raiz.querySelectorAll('pre code').forEach((code) => {
      try { hljs.highlightElement(code); } catch (_) { /* ignore */ }
    });
  }

  function cartaoDe(aba, mensagem) {
    const div = document.createElement('div');
    div.className = 'pv-card';
    div.innerHTML = `
      <div class="pv-card-ext">${esc(extDe(aba.name) || 'arquivo')}</div>
      <div class="pv-card-name">${esc(aba.name)}</div>
      <div class="pv-card-msg">${esc(mensagem)}</div>
      <a class="pv-card-btn" href="${esc(urlDownload(aba.path))}" download>baixar arquivo</a>`;
    return div;
  }

  // ── navegador de arquivos (estado vazio) ─────────────────────
  function navegador(caminho) {
    const div = document.createElement('div');
    div.className = 'pv-browser';
    const alvo = caminho || 'data/user';
    div.innerHTML = '<div class="pv-loading">carregando arquivos…</div>';

    fetch('/api/files?path=' + encodeURIComponent(alvo), { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('faça login (cadeado no topo) para listar arquivos');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then((dados) => {
        const partes = String(dados.path || alvo).split('/');
        const crumbs = partes.map((nome, i) => {
          const alvoCrumb = partes.slice(0, i + 1).join('/');
          return `<button class="pv-crumb" data-pv-dir="${esc(alvoCrumb)}">${esc(nome)}</button>`;
        }).join('<span class="pv-crumb-sep">/</span>');

        const linhas = (dados.items || []).map((item) => {
          if (item.dir) {
            const abrirSite = item.site
              ? `<button class="pv-site-btn" data-preview-path="${esc(item.path)}"
                         data-preview-dir="1" data-preview-name="${esc(item.name)}"
                         title="abrir como site (index.html)">▶</button>`
              : '';
            return `<div class="pv-row pv-dir">
                      <button class="pv-row-main" data-pv-dir="${esc(item.path)}">
                        <span class="pv-row-ico">▸</span>
                        <span class="pv-row-name">${esc(item.name)}</span>
                      </button>
                      ${abrirSite}
                    </div>`;
          }
          const podeVer = item.preview;
          const meta = `${tamanho(item.size)} · ${extDe(item.name) || '?'}`;
          if (podeVer) {
            return `<button class="pv-row" data-preview-path="${esc(item.path)}"
                        data-preview-name="${esc(item.name)}">
                      <span class="pv-row-ico">${esc(extDe(item.name) || '·')}</span>
                      <span class="pv-row-name">${esc(item.name)}</span>
                      <span class="pv-row-meta">${esc(meta)}</span>
                    </button>`;
          }
          return `<a class="pv-row" href="${esc(urlDownload(item.path))}" download title="sem visualização — baixar">
                    <span class="pv-row-ico">↓</span>
                    <span class="pv-row-name">${esc(item.name)}</span>
                    <span class="pv-row-meta">${esc(meta)}</span>
                  </a>`;
        }).join('');

        const rodapeSite = dados.site
          ? `<button class="pv-row pv-site" data-preview-path="${esc(dados.path)}"
                     data-preview-dir="1" title="abrir a pasta como site">
               <span class="pv-row-ico">▶</span>
               <span class="pv-row-name">abrir esta pasta como site</span>
               <span class="pv-row-meta">index.html</span>
             </button>`
          : '';

        div.innerHTML = `
          <div class="pv-crumbs">${crumbs}</div>
          <div class="pv-list">${rodapeSite}${linhas || '<div class="pv-empty">pasta vazia</div>'}</div>
          ${dados.truncado ? '<div class="pv-aviso">lista truncada — abra uma subpasta</div>' : ''}`;
      })
      .catch((e) => {
        div.innerHTML = `<div class="pv-empty">${esc(e.message || 'não deu para listar')}</div>`;
      });

    return div;
  }

  // ── arquivos que o turno gerou ──────────────────────────────
  function escolherPrincipal(arquivos) {
    const achar = (fn) => arquivos.find(fn);
    return achar((a) => a.dir)
        || achar((a) => baseNome(a.path).toLowerCase() === 'index.html')
        || achar((a) => EXT_HTML.has(extDe(a.name || a.path)))
        || achar((a) => EXT_MD.has(extDe(a.name || a.path)))
        || achar((a) => EXT_IMG.has(extDe(a.name || a.path)))
        || arquivos[0];
  }

  /** Ordem de exibição: projeto/página principal primeiro, depois o resto. */
  function ordenar(arquivos) {
    const peso = (a) => {
      if (a.dir) return -1;
      const nome = baseNome(a.path).toLowerCase();
      const ext = extDe(nome);
      if (nome === 'index.html') return 0;
      if (EXT_HTML.has(ext)) return 1;
      if (EXT_MD.has(ext)) return 2;
      if (EXT_IMG.has(ext)) return 3;
      return 4;
    };
    return arquivos.slice().sort((a, b) => peso(a) - peso(b));
  }

  /** HTML dos chips "arquivo gerado" que entram embaixo da resposta. */
  function strip(arquivos) {
    if (!Array.isArray(arquivos) || !arquivos.length) return '';
    const visiveis = ordenar(arquivos).slice(0, MAX_CHIPS);
    const restantes = arquivos.length - visiveis.length;
    const chips = visiveis.map((a) => {
      const nome = a.name || baseNome(a.path);
      const ext = a.dir ? 'site' : (extDe(nome) || 'arquivo');
      const dirAttr = a.dir ? ' data-preview-dir="1"' : '';
      const dica = a.dir
        ? `abrir o projeto${a.n_files ? ` (${a.n_files} arquivos)` : ''}`
        : `visualizar ${esc(a.path)}`;
      // um bloco só por arquivo: o nome abre a prévia, o ↓ baixa
      return `<span class="file-chip${a.dir ? ' site' : ''}">
        <button class="fc-open" data-preview-path="${esc(a.path)}"${dirAttr}
                data-preview-name="${esc(nome)}" title="${esc(dica)}">
          <span class="fc-ext">${esc(ext)}</span>
          <span class="fc-name">${esc(nome)}</span>
        </button>
        ${a.dir ? '' : `<a class="fc-dl" href="${esc(urlDownload(a.path))}" download
           title="baixar ${esc(nome)}">↓</a>`}
      </span>`;
    }).join('');
    const rotulo = arquivos.length === 1
      ? 'arquivo gerado'
      : `${arquivos.length} arquivos gerados`;
    const mais = restantes > 0 ? `<span class="fs-mais">+${restantes}</span>` : '';
    return `<div class="file-strip"><span class="fs-label">${rotulo}</span>${chips}${mais}</div>`;
  }

  /** Chamado depois do turno: abre a prévia do principal, se for o caso. */
  function autoOpen(arquivos) {
    if (!Array.isArray(arquivos) || !arquivos.length) return;
    if (!estado.auto) return;
    const abrivel = arquivos.filter((a) => {
      if (a.dir) return true;
      const ext = extDe(a.name || a.path);
      return a.preview !== false &&
        (EXT_HTML.has(ext) || EXT_MD.has(ext) || EXT_IMG.has(ext) || EXT_PDF.has(ext) || EXT_TXT.has(ext));
    });
    if (!abrivel.length) return;
    const principal = escolherPrincipal(abrivel);
    abrir(principal.path, {
      name: principal.name || baseNome(principal.path),
      dir: !!principal.dir,
      entry: principal.entry,
    });
  }

  // ── divisória arrastável ────────────────────────────────────
  function areaLargura() {
    const area = document.querySelector('.content-area');
    return area ? area.getBoundingClientRect().width : window.innerWidth;
  }

  function aplicarLargura(px) {
    const painel = el('preview-pane');
    if (!painel) return;
    const area = areaLargura();
    // sobra pelo menos ~360px para o chat, mesmo no arrasto mais extremo
    const max = Math.max(LARGURA_MIN, Math.min(area * 0.8, area - 360));
    let largura = px == null ? area * LARGURA_PADRAO : px;
    largura = Math.max(LARGURA_MIN, Math.min(max, largura));
    painel.style.setProperty('--pv-w', Math.round(largura) + 'px');
    return Math.round(largura);
  }

  function salvarLargura() {
    const painel = el('preview-pane');
    if (!painel) return;
    try {
      localStorage.setItem(KEY_LARGURA, painel.style.getPropertyValue('--pv-w'));
    } catch (_) { /* modo privado: só não persiste */ }
  }

  function restaurarLargura() {
    let salva = null;
    try { salva = localStorage.getItem(KEY_LARGURA); } catch (_) { /* ignore */ }
    const px = parseInt(String(salva || '').replace('px', ''), 10);
    aplicarLargura(Number.isFinite(px) && px > 0 ? px : null);
  }

  function ligarDivisoria() {
    const res = el('preview-resizer');
    if (!res) return;
    let arrastando = false;
    let xInicial = 0;
    let larguraInicial = 0;

    res.addEventListener('pointerdown', (e) => {
      arrastando = true;
      xInicial = e.clientX;
      larguraInicial = el('preview-pane').getBoundingClientRect().width;
      res.setPointerCapture(e.pointerId);
      document.body.classList.add('pv-arrastando');
      e.preventDefault();
    });

    res.addEventListener('pointermove', (e) => {
      if (!arrastando) return;
      aplicarLargura(larguraInicial + (xInicial - e.clientX));
    });

    const soltar = (e) => {
      if (!arrastando) return;
      arrastando = false;
      document.body.classList.remove('pv-arrastando');
      try { res.releasePointerCapture(e.pointerId); } catch (_) { /* ignore */ }
      salvarLargura();
    };
    res.addEventListener('pointerup', soltar);
    res.addEventListener('pointercancel', soltar);

    res.addEventListener('dblclick', () => {
      aplicarLargura(null);
      salvarLargura();
    });

    res.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const atual = el('preview-pane').getBoundingClientRect().width;
      aplicarLargura(atual + (e.key === 'ArrowLeft' ? 24 : -24));
      salvarLargura();
    });

    window.addEventListener('resize', () => {
      if (estado.aberto) aplicarLargura(el('preview-pane').getBoundingClientRect().width);
    });
  }

  // ── botões do cabeçalho e rodapé ────────────────────────────
  function ligarBotoes() {
    const on = (id, fn) => {
      const b = el(id);
      if (b) b.addEventListener('click', (e) => { e.preventDefault(); fn(); });
    };

    on('preview-close', () => mostrarPainel(false));
    on('preview-browse', abrirNavegador);
    on('preview-reload', () => { if (estado.aberto) desenhar(); });
    on('preview-newtab', () => {
      const aba = estado.abas[estado.ativa];
      if (aba) window.open(urlPublica(aba.path, true), '_blank', 'noopener');
    });
    on('preview-auto', () => {
      estado.auto = !estado.auto;
      try { localStorage.setItem(KEY_AUTO, estado.auto ? '1' : '0'); } catch (_) { /* ignore */ }
      atualizarBotaoAuto();
    });
  }

  function atualizarBotaoAuto() {
    const b = el('preview-auto');
    if (!b) return;
    b.classList.toggle('ligado', estado.auto);
    b.title = estado.auto
      ? 'abrir a prévia automaticamente quando o agente gerar arquivo (clique para desligar)'
      : 'prévia automática desligada — clique para ligar';
  }

  // ── cliques delegados (vale para o chat, fontes e o navegador) ─
  function ligarCliques() {
    document.addEventListener('click', (e) => {
      const alvo = e.target instanceof Element ? e.target : null;
      if (!alvo) return;

      const fecharX = alvo.closest('[data-pv-close]');
      if (fecharX) {
        e.preventDefault();
        e.stopPropagation();
        fecharAba(Number(fecharX.dataset.pvClose));
        return;
      }

      const aba = alvo.closest('[data-pv-tab]');
      if (aba) {
        e.preventDefault();
        ativar(Number(aba.dataset.pvTab));
        return;
      }

      const pasta = alvo.closest('[data-pv-dir]');
      if (pasta) {
        e.preventDefault();
        const corpo = el('preview-body');
        if (corpo) {
          corpo.innerHTML = '';
          corpo.appendChild(navegador(pasta.dataset.pvDir));
        }
        return;
      }

      const arq = alvo.closest('[data-preview-path]');
      if (arq) {
        e.preventDefault();
        abrir(arq.dataset.previewPath, {
          name: arq.dataset.previewName,
          dir: arq.dataset.previewDir === '1',
        });
      }
    });
  }

  // ── init ────────────────────────────────────────────────────
  function init() {
    try {
      const salvo = localStorage.getItem(KEY_AUTO);
      estado.auto = salvo === null ? true : salvo === '1';
    } catch (_) { /* ignore */ }

    ligarDivisoria();
    ligarBotoes();
    ligarCliques();
    atualizarBotaoAuto();
    restaurarLargura();
    mostrarPainel(false);
  }

  window.Preview = {
    open: abrir,
    toggle: toggle,
    close: () => mostrarPainel(false),
    browse: abrirNavegador,
    reload: () => { if (estado.aberto) desenhar(); },
    strip: strip,
    autoOpen: autoOpen,
    // usado pelo botão "ver" dos links antigos
    abrir: abrir,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
