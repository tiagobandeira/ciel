/* ═══════════════════════════════════════════════════════════════
   Ciel — trace.js
   "Fio de pensamento": o acordeão que mostra o que o agente fez no
   turno. Consome os eventos passo/pensando/turno_fim do /api/events
   (SSE) e escreve no #messages. Isolado do app.js de propósito, para
   o /ui poder reusar o mesmo componente depois.

   Classes CSS em style.css (bloco "fio de pensamento").
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // mesmo vocabulário de glifos da TUI (ciel_tui.msg_system / msg_tool)
  const GLIFO = {
    model: '✦', tool: '⚙', done: '✓', error: '✗',
    parse_error: '↻', lote: '≡', registry: '◈',
    bloqueado: '⊘', recusado: '⊘', cancelado: '⊘', nativo: '↻',
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function fmtMs(ms) {
    const n = Number(ms) || 0;
    if (n < 1000) return Math.round(n) + 'ms';
    if (n < 60000) return (n / 1000).toFixed(1).replace('.', ',') + 's';
    return Math.floor(n / 60000) + 'm' + Math.round((n % 60000) / 1000) + 's';
  }

  /* título do cabeçalho a partir do passo — é o que "muda sozinho" */
  function titulo(ev) {
    const label = String(ev.label || '');
    if (ev.status === 'parse_error') return 'reajustando o formato';
    if (ev.status === 'error') return 'erro no passo';
    if (label === 'modelo' || ev.status === 'model') return 'analisando o pedido';
    if (label === 'resultado') return 'lendo o resultado';
    if (label.indexOf('tool › ') === 0) return 'executando ' + label.slice(7);
    if (label === 'lote') return 'leituras em paralelo';
    if (label === 'registry') return 'recarregando tools';
    if (label === 'done') return 'concluindo';
    return label || 'pensando';
  }

  function rolar() {
    const msgs = document.getElementById('messages');
    if (msgs) msgs.scrollTop = msgs.scrollHeight;
  }

  function abrir(raiz) {
    raiz.classList.add('aberto');
    const head = raiz.querySelector('.thought-head');
    if (head) head.setAttribute('aria-expanded', 'true');
  }

  function fechar(raiz) {
    raiz.classList.remove('aberto');
    const head = raiz.querySelector('.thought-head');
    if (head) head.setAttribute('aria-expanded', 'false');
  }

  function resumo(raiz) {
    const d = raiz.dataset;
    const partes = [];
    const passos = Number(d.passos || 0);
    const tools = Number(d.tools || 0);
    if (passos) partes.push(passos + (passos === 1 ? ' passo' : ' passos'));
    if (tools) partes.push(tools + (tools === 1 ? ' tool' : ' tools'));
    if (d.ms) partes.push(fmtMs(d.ms));
    return partes.join(' · ');
  }

  function mostrarMeta(raiz) {
    const el = raiz.querySelector('.thought-meta');
    if (el) el.textContent = resumo(raiz);
  }

  /* ── API ─────────────────────────────────────────────────────── */

  function criar(turnId) {
    const existente = document.getElementById('thought-' + turnId);
    if (existente) return existente;

    const raiz = document.createElement('div');
    raiz.className = 'thought';
    raiz.id = 'thought-' + turnId;
    raiz.dataset.turno = turnId;
    raiz.dataset.passos = '0';
    raiz.dataset.tools = '0';
    raiz.dataset.ms = '0';

    // Nasce sempre recolhido, e o fim do turno NÃO mexe mais nesse estado:
    // abrir/fechar é decisão do usuário. Antes, quem tinha expandido via o
    // log fechar sozinho no fim (e o turno seguinte já nascia aberto), o que
    // dava a impressão de que o pensamento sumia.
    raiz.innerHTML =
      '<button class="thought-head" type="button" aria-expanded="false">' +
        '<span class="thought-glyph" aria-hidden="true">✦</span>' +
        '<span class="thought-title">pensando…</span>' +
        '<span class="thought-meta"></span>' +
        '<span class="thought-chevron" aria-hidden="true">›</span>' +
      '</button>' +
      '<div class="thought-body">' +
        '<div class="thought-log" role="log" aria-live="polite"></div>' +
      '</div>';

    raiz.querySelector('.thought-head').addEventListener('click', () => {
      if (raiz.classList.contains('aberto')) fechar(raiz); else abrir(raiz);
    });

    const msgs = document.getElementById('messages');
    if (msgs) msgs.appendChild(raiz);
    rolar();
    return raiz;
  }

  function passo(turnId, ev) {
    const raiz = document.getElementById('thought-' + turnId);
    if (!raiz) return;

    const log = raiz.querySelector('.thought-log');
    const linha = document.createElement('div');
    linha.className = 'thought-line st-' + (ev.status || 'model');
    linha.innerHTML =
      '<span class="tl-step">' + esc(ev.step || '') + '</span>' +
      '<span class="tl-glyph" aria-hidden="true">' + esc(GLIFO[ev.status] || '·') + '</span>' +
      '<span class="tl-label">' + esc(titulo(ev)) + '</span>' +
      '<span class="tl-texto">' + esc(ev.texto || '') + '</span>' +
      '<span class="tl-ms">' + fmtMs(ev.ms) + '</span>';
    log.appendChild(linha);

    raiz.dataset.passos = String(Math.max(Number(raiz.dataset.passos || 0), Number(ev.step) || 0));
    if (ev.status === 'tool') raiz.dataset.tools = String(Number(raiz.dataset.tools || 0) + 1);
    raiz.dataset.ms = String(ev.ms || raiz.dataset.ms || 0);

    const g = raiz.querySelector('.thought-glyph');
    if (g) g.textContent = GLIFO[ev.status] || '✦';
    const t = raiz.querySelector('.thought-title');
    if (t) t.textContent = titulo(ev);
    mostrarMeta(raiz);

    if (ev.status === 'error' || ev.status === 'parse_error') {
      raiz.classList.add('tem-erro');
      abrir(raiz);   // falha se explica: não esconde o que deu errado
    }
    if (log.scrollHeight > log.clientHeight) log.scrollTop = log.scrollHeight;
    rolar();
  }

  function pensando(turnId, ev) {
    const raiz = document.getElementById('thought-' + turnId);
    if (!raiz) return;
    raiz.classList.toggle('ativo', !!ev.ativo);
    if (ev.ativo) {
      const t = raiz.querySelector('.thought-title');
      if (t && !raiz.classList.contains('fim')) t.textContent = 'analisando o pedido';
    }
    if (ev.ms) {
      raiz.dataset.ms = String(ev.ms);
      mostrarMeta(raiz);
    }
  }

  function fim(turnId, ev) {
    const raiz = document.getElementById('thought-' + turnId);
    if (!raiz) return;
    if (raiz.classList.contains('fim')) return;   // idempotente: SSE + resposta

    raiz.classList.add('fim');
    raiz.classList.remove('ativo');
    if (ev.ms) raiz.dataset.ms = String(ev.ms);
    if (ev.steps) raiz.dataset.passos = String(ev.steps);

    const ok = (ev.status || 'done') === 'done';
    const t = raiz.querySelector('.thought-title');
    const g = raiz.querySelector('.thought-glyph');
    if (t) t.textContent = ok ? 'pensamento concluído' : 'pensamento interrompido';
    if (g) g.textContent = ok ? '✓' : '⚠';
    raiz.classList.toggle('erro', !ok);
    mostrarMeta(raiz);

    // só força abrir quando deu errado — o resto é escolha do usuário
    if (!ok) abrir(raiz);
    rolar();
  }

  function falhar(turnId, mensagem) {
    const raiz = document.getElementById('thought-' + turnId);
    if (!raiz) return;
    raiz.classList.add('fim', 'erro', 'tem-erro');
    const t = raiz.querySelector('.thought-title');
    const g = raiz.querySelector('.thought-glyph');
    if (t) t.textContent = mensagem || 'falhou antes de começar';
    if (g) g.textContent = '✗';
    abrir(raiz);
    rolar();
  }

  window.CielTrace = { criar, passo, pensando, fim, falhar, titulo, fmtMs };
})();
