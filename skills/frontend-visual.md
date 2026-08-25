---
mode: code
---
# Frontend Visual Rico

description: Sites e landing pages com design robusto, animações fluidas e estética imersiva — dark themes, partículas, parallax, glassmorphism.

## Filosofia

Você está criando uma experiência visual, não apenas uma página. Cada projeto deve ter:

- **Profundidade** — múltiplas camadas visuais (fundo, meio, frente), nunca flat
- **Movimento com propósito** — animações que reforçam a narrativa do site, não decoração aleatória
- **Atmosfera coerente** — paleta, tipografia e efeitos alinhados ao tema pedido
- **Qualidade de produção** — nada de placeholders, lorem ipsum ou caixas cinzas

Se o tema for espacial → negro profundo, azuis frios, brilhos de estrelas, fontes sem serifa finas.
Se o tema for tecnologia/hacking → verde neon ou ciano em fundo quase preto, fontes monospace, glitch.
Se o tema for luxo/elegância → dourado, off-white, tipografia serifada, transições lentas.
Se o tema for natureza → verdes orgânicos, texturas sutis, movimentos suaves.

Leia o tema pedido e derive a paleta, fontes e estilo de animação antes de escrever código.

---

## Estrutura de arquivos obrigatória

Sempre entregue **3 arquivos separados**:

```
index.html   — estrutura semântica, importa style.css e script.js
style.css    — todo o visual, variáveis CSS, animações keyframe
script.js    — toda a lógica interativa e animações via JS
```

Nunca coloque `<style>` inline no HTML nem `<script>` inline. Separe sempre.

---

## HTML — regras

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title><!-- título temático, nunca genérico --></title>
  <link rel="stylesheet" href="style.css">
  <!-- fontes do Google Fonts via CDN se necessário -->
</head>
<body>
  <!-- estrutura semântica: header, main, section, footer -->
  <script src="script.js"></script>
</body>
</html>
```

- Nunca use `id` para estilização — apenas `class`
- Elementos interativos sempre com `aria-label` ou texto visível
- Canvas para partículas/estrelas sempre com `id` próprio e posição `fixed` ou `absolute`

---

## CSS — regras e padrões

### Variáveis obrigatórias no `:root`

```css
:root {
  /* paleta derivada do tema */
  --color-bg:        #05050f;
  --color-primary:   #4fc3f7;
  --color-accent:    #7c4dff;
  --color-text:      #e0e0e0;
  --color-text-muted:#7986cb;
  --color-glow:      rgba(79, 195, 247, 0.4);

  /* tipografia */
  --font-display:    'Orbitron', sans-serif;  /* títulos */
  --font-body:       'Inter', sans-serif;      /* corpo */
  --font-mono:       'JetBrains Mono', monospace;

  /* espaçamento e raios */
  --radius-sm: 8px;
  --radius-md: 16px;
  --radius-lg: 24px;
}
```

### Reset mínimo

```css
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html { scroll-behavior: smooth; }

body {
  background-color: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-body);
  overflow-x: hidden;
  min-height: 100vh;
}
```

### Efeitos visuais permitidos e como usá-los

**Glassmorphism** — painéis translúcidos com blur:
```css
.glass-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
}
```

**Glow / neon text:**
```css
.glow-text {
  color: var(--color-primary);
  text-shadow:
    0 0 8px var(--color-glow),
    0 0 24px var(--color-glow),
    0 0 48px var(--color-glow);
}
```

**Glow em bordas:**
```css
.glow-border {
  box-shadow:
    0 0 0 1px var(--color-primary),
    0 0 16px var(--color-glow),
    inset 0 0 16px rgba(79, 195, 247, 0.05);
}
```

**Gradiente de texto:**
```css
.gradient-text {
  background: linear-gradient(135deg, var(--color-primary), var(--color-accent));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
```

**Parallax via CSS (camadas de fundo):**
```css
.parallax-layer {
  position: fixed;
  inset: 0;
  will-change: transform;
  pointer-events: none;
}
```

### Animações keyframe — padrões

```css
/* fade + rise (entrada de elementos) */
@keyframes fadeRise {
  from { opacity: 0; transform: translateY(30px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* pulso de brilho */
@keyframes glowPulse {
  0%, 100% { box-shadow: 0 0 16px var(--color-glow); }
  50%       { box-shadow: 0 0 40px var(--color-glow), 0 0 80px var(--color-glow); }
}

/* rotação lenta (planetas, logos) */
@keyframes rotateSlow {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

/* flutuação (elementos suspensos) */
@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50%       { transform: translateY(-12px); }
}

/* scan line / varredura */
@keyframes scanLine {
  from { transform: translateY(-100%); }
  to   { transform: translateY(100vh); }
}

/* glitch */
@keyframes glitch {
  0%  { clip-path: inset(0 0 95% 0); transform: translate(-4px, 0); }
  20% { clip-path: inset(30% 0 50% 0); transform: translate(4px, 0); }
  40% { clip-path: inset(60% 0 20% 0); transform: translate(-2px, 0); }
  60% { clip-path: inset(80% 0 5% 0);  transform: translate(2px, 0); }
  80% { clip-path: inset(10% 0 80% 0); transform: translate(-4px, 0); }
  100%{ clip-path: inset(0 0 95% 0);   transform: translate(0, 0); }
}
```

### Regras de performance

- Use **sempre** `transform` e `opacity` para animar — nunca `top`, `left`, `width`, `height`
- Aplique `will-change: transform` apenas em elementos que animam continuamente
- Prefira `transition` para estados discretos (hover, focus) e `@keyframes` para loops
- Nunca use `transition: all` — especifique a propriedade

---

## JS — regras e padrões

### Estrutura base

```javascript
// Espera o DOM carregar antes de qualquer coisa
document.addEventListener('DOMContentLoaded', () => {
  initCanvas();      // partículas / estrelas / fundo
  initAnimations();  // intersection observer para entrada de elementos
  initInteractions();// eventos de mouse, scroll, hover
});
```

### Canvas para partículas / estrelas / campo de pontos

```javascript
function initCanvas() {
  const canvas = document.getElementById('canvas-bg');
  const ctx    = canvas.getContext('2d');

  // sempre responsivo
  function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  // estrutura de partícula
  const particles = Array.from({ length: 150 }, () => ({
    x:    Math.random() * canvas.width,
    y:    Math.random() * canvas.height,
    r:    Math.random() * 1.5 + 0.5,
    vx:   (Math.random() - 0.5) * 0.3,
    vy:   (Math.random() - 0.5) * 0.3,
    alpha: Math.random() * 0.7 + 0.3,
  }));

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    particles.forEach(p => {
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0 || p.x > canvas.width)  p.vx *= -1;
      if (p.y < 0 || p.y > canvas.height) p.vy *= -1;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(79, 195, 247, ${p.alpha})`;
      ctx.fill();
    });

    requestAnimationFrame(draw);
  }
  draw(); // usa requestAnimationFrame, nunca setInterval
}
```

### Entrada de elementos com Intersection Observer

```javascript
function initAnimations() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target); // anima só uma vez
      }
    });
  }, { threshold: 0.15 });

  document.querySelectorAll('.animate-on-scroll').forEach(el => observer.observe(el));
}
```

CSS correspondente:
```css
.animate-on-scroll {
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}
.animate-on-scroll.visible {
  opacity: 1;
  transform: translateY(0);
}
```

### Parallax com mouse

```javascript
function initInteractions() {
  document.addEventListener('mousemove', (e) => {
    const cx = window.innerWidth  / 2;
    const cy = window.innerHeight / 2;
    const dx = (e.clientX - cx) / cx; // -1 a 1
    const dy = (e.clientY - cy) / cy; // -1 a 1

    document.querySelectorAll('[data-parallax]').forEach(el => {
      const depth = parseFloat(el.dataset.parallax) || 1;
      el.style.transform = `translate(${dx * depth * 12}px, ${dy * depth * 8}px)`;
    });
  });
}
```

HTML correspondente:
```html
<div class="parallax-layer" data-parallax="0.5"><!-- camada lenta --></div>
<div class="parallax-layer" data-parallax="1.5"><!-- camada rápida --></div>
```

### Proibido no JS

- **Nunca use `setInterval` para animações** — use `requestAnimationFrame`
- **Nunca manipule estilos inline para animações** — use classes CSS com transition
- Não use jQuery ou qualquer lib externa não declarada — vanilla JS apenas, salvo CDN explicitamente pedido
- Não use `document.write()`

---

## Fontes recomendadas por tema (Google Fonts CDN)

| Tema | Display | Body |
|---|---|---|
| Espacial / Sci-Fi | Orbitron, Exo 2 | Inter, Rajdhani |
| Tecnologia / Hacking | Share Tech Mono, VT323 | JetBrains Mono, Fira Code |
| Luxo / Elegância | Playfair Display, Cormorant | Lato, Raleway |
| Natureza / Orgânico | Merriweather, Lora | Nunito, DM Sans |
| Genérico moderno | Space Grotesk, Syne | Inter, Plus Jakarta Sans |

Importe sempre via `<link>` no `<head>` do HTML, não via `@import` no CSS.

---

## Checklist antes de entregar

- [ ] 3 arquivos separados: `index.html`, `style.css`, `script.js`
- [ ] Variáveis CSS no `:root` com paleta derivada do tema
- [ ] Canvas com `requestAnimationFrame` (se houver partículas/estrelas)
- [ ] Nenhum `setInterval` para animação
- [ ] `will-change` aplicado apenas onde necessário
- [ ] Fontes importadas via CDN no HTML
- [ ] Elementos com `.animate-on-scroll` usando IntersectionObserver
- [ ] Responsivo: `meta viewport` presente, layout funciona em mobile
- [ ] Sem `<style>` ou `<script>` inline no HTML
