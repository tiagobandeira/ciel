// Skeleton do jogo. Complete a lógica (movimento, colisão, comida e placar).
const canvas = document.querySelector("#game");
const ctx = canvas.getContext("2d");
const placarEl = document.querySelector("#placar");

const state = {
  rodando: true,
  gameOver: false,
  pontos: 0,
  cobra: [{ x: 10, y: 10 }],
  direcao: { x: 1, y: 0 },
  comida: { x: 15, y: 10 },
  tick: 0,
};

function reset() {
  state.rodando = true;
  state.gameOver = false;
  state.pontos = 0;
  state.cobra = [{ x: 10, y: 10 }];
  state.direcao = { x: 1, y: 0 };
  state.comida = { x: 15, y: 10 };
  placarEl.textContent = "0";
}

function update() {
  // TODO: mover a cobra, comer, colidir e atualizar o placar.
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  // TODO: desenhar grade, cobra, comida e game over.
}

function loop() {
  if (state.rodando) {
    update();
    draw();
  }
  requestAnimationFrame(loop);
}

document.addEventListener("keydown", (event) => {
  // TODO: setas/WASD; espaço reinicia.
});

loop();
