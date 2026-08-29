# Ciel TUI

Interface de terminal (TUI) para o **Ciel**, construída com [Textual](https://github.com/Textualize/textual).

## Visão geral

A CLI padrão do Ciel é funcional, mas limitada a texto puro e saídas estáticas. A TUI surge como uma camada visual que mantém a agilidade do terminal e adiciona navegação por teclado, painéis interativos e feedback em tempo real — sem abrir mão do fluxo de trabalho já consolidado.

## Interface

A tela é organizada em três regiões principais:

- **Sidebar** — ASCII art do Ciel, card do agente ativo e botões de ação rápida (`/tool`, `/task`, `/skill`, `/agente`). Na parte inferior, histórico de sessões navegável.
- **Painel central** — log de chat com suporte a Markdown, indicador de "pensando" e input destacado.
- **Painel direito** — informações da sessão atual: modelo, número de sessão e contagem de tokens de entrada/saída.

## Comandos

| Comando | Descrição |
|---|---|
| `/agente [nome]` | Troca de persona (interativo ou direto) |
| `/task [nome]` | Executa uma task (interativo ou direto) |
| `/skill` | Ativa uma skill disponível |
| `/tool` | Lista e inspeciona ferramentas |
| `/model <nome>` | Troca o modelo principal |
| `/source <arquivo>` | Indexa arquivo na base de conhecimento |
| `/history` | Lista, salva ou exporta sessões |
| `/novo` | Inicia nova sessão |
| `/tokens` | Exibe uso de tokens da sessão |
| `/sair` | Encerra a aplicação |

## Atalhos de teclado

| Tecla | Ação |
|---|---|
| `F1` – `F4` | Tool / Task / Skill / Agente |
| `Tab` | Circula pelos painéis visíveis |
| `/` | Foca o input com `/` pré-digitado |
| `Ctrl+L` | Limpa o chat |
| `Ctrl+S` | Salva sessão |
| `Ctrl+N` | Nova sessão |
| `Ctrl+B` | Alterna sidebar |
| `Ctrl+Y` | Modo seleção — abre o chat em tela cheia para copiar trechos |
| `Ctrl+Q` | Sair |

## Pill de texto e link

O input suporta dois tipos de conteúdo além do texto puro:

**Pill de texto** — paste com 4 ou mais linhas é recolhido automaticamente em um pill `[Colado ~N linhas]` para não poluir o input. No chat, exibe as 3 primeiras linhas + contador de linhas restantes ao lado do prompt enviado. O fluxo esperado é: colar o contexto primeiro, digitar o prompt no input e enviar.

**Chip de link** — URLs digitadas ou coladas são convertidas em chip com o domínio visível. `Ctrl+Click` abre o link para verificação.

**Editor do pill** — abre com `Ctrl+K` sem precisar clicar no pill.

| Tecla | Ação |
|---|---|
| `Ctrl+K` | Abre o editor do pill |
| `Ctrl+G` | Confirma as alterações |
| `Ctrl+D` | Deleta o pill |
| `Ctrl+Up/Down` | Navega entre linhas |
| `Esc` | Cancela sem alterar |

## Tecnologias

- Python 3.7+
- [Textual](https://github.com/Textualize/textual) — framework TUI
- [Rich](https://github.com/Textualize/rich) — renderização de Markdown e estilos no terminal
- `psutil` / `pynvml` *(opcionais)* — monitoramento de sistema e GPU

## Como executar

**Dependência extra** (além das do projeto principal):

```bash
pip install textual
```

**Iniciar:**

```bash
python ciel.py                         # abre TUI automaticamente se Textual instalado
python ciel.py --tui                   # força TUI
python ciel.py --tui --agent dev_helper
python ciel.py --tui --safe
```

> A TUI compartilha o mesmo banco de sessões, agentes, tools e base de conhecimento do `cli.py` — não é necessária nenhuma configuração adicional.