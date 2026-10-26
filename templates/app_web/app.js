// Skeleton do app de notas. Complete os TODOs.
const STORAGE_KEY = "notas";

const state = {
  notas: JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"),
  ativa: null,
};

const lista = document.querySelector("#lista-notas");
const titulo = document.querySelector("#titulo");
const editor = document.querySelector("#editor");
const preview = document.querySelector("#preview");

function salvar() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.notas));
}

function renderPreview() {
  // TODO: preview simples de Markdown (títulos, negrito, listas, código).
  preview.textContent = editor.value;
}

function renderLista() {
  lista.innerHTML = "";
  for (const nota of state.notas) {
    const li = document.createElement("li");
    li.textContent = nota.titulo || "(sem título)";
    li.addEventListener("click", () => abrir(nota.id));
    lista.appendChild(li);
  }
}

function abrir(id) {
  const nota = state.notas.find((n) => n.id === id);
  if (!nota) return;
  state.ativa = id;
  titulo.value = nota.titulo;
  editor.value = nota.conteudo;
  renderPreview();
}

function novaNota() {
  const nota = { id: crypto.randomUUID(), titulo: "", conteudo: "" };
  state.notas.unshift(nota);
  salvar();
  renderLista();
  abrir(nota.id);
}

function atualizarAtiva() {
  const nota = state.notas.find((n) => n.id === state.ativa);
  if (!nota) return;
  nota.titulo = titulo.value;
  nota.conteudo = editor.value;
  salvar();
  renderLista();
  renderPreview();
}

document.querySelector("#nova-nota").addEventListener("click", novaNota);
titulo.addEventListener("input", atualizarAtiva);
editor.addEventListener("input", atualizarAtiva);
renderLista();
if (state.notas[0]) abrir(state.notas[0].id);
