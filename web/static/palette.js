/* ═══════════════════════════════════════════════════════════════
   Ciel — palette.js
   Paleta de comandos/ações: abre ao digitar "/" no campo (ou pelo botão),
   filtra enquanto digita e navega por teclado. Substitui o menu estático
   antigo. Comandos ("/x") viram mensagem; ações abrem a tela direto.
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const IC = window.icone || function () { return ''; };
  const esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };

  const COMANDOS = [
    { rot: '/novo',             desc: 'começar uma sessão nova',       ic: 'plus',      grupo: 'sessão',  cmd: true },
    { rot: '/history salvar',   desc: 'salvar a sessão atual',         ic: 'save',      grupo: 'sessão',  cmd: true },
    { rot: '/history exportar', desc: 'exportar a conversa em .md',    ic: 'file',      grupo: 'sessão',  cmd: true },
    { rot: '/tokens',           desc: 'tokens gastos nesta sessão',    ic: 'chart',     grupo: 'sessão',  cmd: true },
    { rot: '/tools',            desc: 'listar as tools ativas',        ic: 'gear',      grupo: 'sessão',  cmd: true },
    { rot: '/task',             desc: 'listar ou executar uma task',   ic: 'zap',       grupo: 'tarefas', cmd: true },
    { rot: 'executar task…',    desc: 'escolher na lista de tasks',    ic: 'list',      grupo: 'tarefas', acao: function () { window.openTaskModal(); } },
    { rot: '/source --listar',  desc: 'listar fontes indexadas',       ic: 'clipboard', grupo: 'fontes',  cmd: true },
    { rot: 'fontes',            desc: 'gerenciar fontes da sessão',    ic: 'book',      grupo: 'fontes',  acao: function () { window.openSourceModal(); } },
    { rot: 'trocar agente',     desc: 'mudar a persona ativa',         ic: 'chat',      grupo: 'sistema', acao: function () { window.openAgentModal(); } },
    { rot: 'ajustes',           desc: 'modelos, provedores e sobre',   ic: 'gear',      grupo: 'sistema', acao: function () { window.openSettings(); } },
    { rot: 'modo interativo',   desc: 'abrir a interface visual (/ui)', ic: 'spark',    grupo: 'sistema', acao: function () { window.open('/ui', '_blank', 'noopener'); } },
    { rot: '/limpar-temp',      desc: 'remover tools temporárias',     ic: 'trash',     grupo: 'sistema', cmd: true },
  ];

  let itens = [];
  let sel = 0;
  let aberta = false;

  const caixa = () => document.getElementById('paleta');
  const campo = () => document.getElementById('msg-input');

  function normaliza(s) {
    return String(s || '').toLowerCase().normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');
  }

  function filtrar(filtro) {
    const f = normaliza(filtro).trim();
    if (!f) return COMANDOS.slice();
    return COMANDOS.filter(c => normaliza(c.rot + ' ' + c.desc + ' ' + c.grupo).includes(f));
  }

  function render() {
    const el = caixa();
    if (!el) return;

    if (!itens.length) {
      el.innerHTML = '<div class="paleta-vazia">nenhum comando ou ação</div>';
    } else {
      let grupo = '';
      el.innerHTML = itens.map((c, i) => {
        let cabecalho = '';
        if (c.grupo !== grupo) {
          grupo = c.grupo;
          cabecalho = `<div class="paleta-grupo">${esc(grupo)}</div>`;
        }
        return cabecalho +
          `<button type="button" class="paleta-item${i === sel ? ' ativo' : ''}" data-i="${i}" role="option">` +
            `<span class="paleta-ic">${IC(c.ic)}</span>` +
            `<span class="paleta-rot">${esc(c.rot)}</span>` +
            `<span class="paleta-desc">${esc(c.desc)}</span>` +
          '</button>';
      }).join('');
    }

    el.classList.remove('hidden');
    aberta = true;
    const ativo = el.querySelector('.paleta-item.ativo');
    if (ativo && ativo.scrollIntoView) ativo.scrollIntoView({ block: 'nearest' });
  }

  function fechar() {
    const el = caixa();
    if (el) el.classList.add('hidden');
    aberta = false;
    itens = [];
    sel = 0;
  }

  function atualizar() {
    const c = campo();
    const v = c ? c.value : '';
    if (!v.startsWith('/') || v.includes('\n')) { fechar(); return; }
    itens = filtrar(v.slice(1));
    sel = 0;
    render();
  }

  function mover(delta) {
    if (!itens.length) return;
    sel = (sel + delta + itens.length) % itens.length;
    render();
  }

  function executar(i) {
    const c = itens[i];
    if (!c) return;
    fechar();
    if (c.acao) { c.acao(); return; }
    if (window.quickCommand) window.quickCommand(c.rot);
  }

  function botao() {
    const c = campo();
    if (!c) return;
    if (!c.value.startsWith('/')) c.value = '/';
    c.focus();
    atualizar();
  }

  document.addEventListener('click', function (ev) {
    const el = caixa();
    if (!el || el.classList.contains('hidden')) return;
    const item = ev.target.closest('[data-i]');
    if (item) { executar(Number(item.dataset.i)); return; }
    if (!el.contains(ev.target) && !ev.target.closest('.input-bar')) fechar();
  });

  document.addEventListener('mouseover', function (ev) {
    const item = ev.target.closest('[data-i]');
    if (!item) return;
    const i = Number(item.dataset.i);
    if (i !== sel) { sel = i; render(); }
  });

  window.Paleta = {
    atualizar:   atualizar,
    fechar:      fechar,
    mover:       mover,
    executar:    executar,
    botao:       botao,
    aberta:      function () { return aberta; },
    selecionado: function () { return sel; },
  };
})();
