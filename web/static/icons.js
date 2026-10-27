/* ═══════════════════════════════════════════════════════════════
   Ciel — icons.js
   Helper para os ícones de linha do sprite (definido no index.html).
   Mantém o vocabulário: traço 2px, sem preenchimento, herda a cor do
   texto (currentColor) — então funciona em qualquer tema.
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /** Devolve o markup de um ícone do sprite: icone('file') */
  function icone(nome, extra) {
    const classe = 'ic' + (extra ? ' ' + extra : '');
    return '<svg class="' + classe + '" aria-hidden="true">' +
           '<use href="#i-' + nome + '"></use></svg>';
  }

  window.icone = icone;
})();
