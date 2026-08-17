# PyAgentCLI — Casos de Uso e Benchmark

Documento para validação do sistema em cenários reais.
Cada caso de uso testa uma dimensão diferente do agente:
capacidade de raciocínio, uso do RAG, criação de tools, gestão de estado entre sessões.

Serve também como benchmark comparativo entre modelos —
os mesmos casos rodados com modelos diferentes permitem medir
desempenho, qualidade de resposta e custo de tokens.

---

## Modelos testados

| Modelo | Tipo | Observações |
|---|---|---|
| gemma4:cloud | cloud | rápido, gratuito, baixo consumo de tokens — ótimo pra orquestração |
| gemma4:local | local | bom desempenho, mais lento — útil quando tempo não é crítico |
| _(adicionar)_ | | |

---

## Como usar este documento

1. Escolhe um caso de uso
2. Configura o agente conforme descrito
3. Indexa as fontes indicadas
4. Executa as tarefas na ordem, em sessões separadas quando indicado
5. Preenche os resultados — sucesso, falha parcial ou falha total
6. Anota observações livres: o que surpreendeu, o que faltou, tools criadas

**Critérios de avaliação:**
- ✅ sucesso — resolveu sem intervenção manual
- ⚠️ parcial — resolveu com ajuda ou dica adicional
- ❌ falha — não conseguiu resolver

---

## Caso 1 — Gestão de Loja

**Objetivo:** avaliar capacidade de manter contexto entre sessões,
criar tools sob demanda e lidar com problemas práticos de negócio.

**Agente:** `loja_manager`  
**Fontes sugeridas:** catálogo de produtos, tabela de preços, regras de desconto, histórico de pedidos

**Sessão 1 — Configuração inicial**

Tarefas:
- [ ] indexar catálogo de produtos como fonte global
- [ ] indexar tabela de preços como fonte global
- [ ] pedir pro agente listar os produtos disponíveis
- [ ] pedir pro agente identificar o produto mais caro e o mais barato
- [ ] pedir um resumo do estoque atual

Resultado por tarefa: _(preencher)_  
Tools criadas nessa sessão: _(listar)_  
Observações: _(livre)_

---

**Sessão 2 — Operação do dia**

Tarefas:
- [ ] registrar 3 pedidos fictícios (produto, quantidade, cliente)
- [ ] pedir um relatório de vendas da sessão
- [ ] simular falta de estoque de um produto e pedir sugestão
- [ ] aplicar regra de desconto e recalcular total de um pedido

Resultado por tarefa: _(preencher)_  
Tools criadas nessa sessão: _(listar)_  
Observações: _(livre)_

---

**Sessão 3 — Análise e crescimento**

Tarefas:
- [ ] pedir análise comparativa entre os pedidos das sessões anteriores
- [ ] pedir sugestão de reposição de estoque
- [ ] pedir pro agente criar uma tool de cálculo de margem de lucro
- [ ] usar a tool criada em pelo menos 2 cálculos reais

Resultado por tarefa: _(preencher)_  
Tools criadas nessa sessão: _(listar)_  
Observações: _(livre)_

---

**Resultado geral — Caso 1**

| Modelo | Sessão 1 | Sessão 2 | Sessão 3 | Impressão geral |
|---|---|---|---|---|
| gemma4:cloud | | | | |
| gemma4:local | | | | |

---

## Caso 2 — Assistente de Estudos (ENEM)

**Objetivo:** avaliar qualidade do RAG com conteúdo denso,
capacidade de síntese e geração de material de estudo.

**Agente:** `enem_tutor`  
**Fontes sugeridas:** resumos de matérias (História, Biologia, Matemática),
redações modelo, coletânea de questões anteriores

**Sessão 1 — Base de conhecimento**

Tarefas:
- [x] indexar resumo de pelo menos 2 matérias como fontes globais — `resumo_matematica.md` + `resumo_portugues_redacao.md`
- [x] pedir um resumo do que o agente sabe sobre cada matéria
- [x] fazer uma pergunta conceitual que cruza duas matérias
- [x] pedir uma lista dos tópicos mais importantes de uma matéria
- [x] *(extra, do benchmark)* explicar diferença entre Combinação e Arranjo com exemplo prático

Resultado por tarefa (`gemma4:cloud` · janela padrão Ollama · 2026-08-13):

| Tarefa | Resultado | Observação |
|---|---|---|
| Indexar 2 fontes globais | ✅ | Executado sem intervenção |
| Resumo por matéria | ✅ | Listagem completa e bem organizada; rodou duas vezes (usuário repetiu o prompt) — segunda resposta idêntica à primeira, sem degradação |
| Pergunta cruzando matérias | ✅ | Boa síntese em 3 pontos; usou termos das duas fontes corretamente (multimodal, Bhaskara, coesão lógica); sem alucinação detectada |
| Top 5 tópicos de Matemática | ✅ | Priorizou corretamente com base na seção "Recorrentes ENEM"; justificativas ancoradas no resumo; dica de estudo como bônus |
| Combinação vs Arranjo | ⚠️ | Conceito correto, mas a resposta foi curta — não gerou o exemplo prático detalhado pedido; ficou em nível de definição |

Tools criadas nessa sessão: nenhuma  
Observações:
- O modelo se saiu bem em recuperação e síntese dentro da janela padrão
- A tarefa de Combinação vs Arranjo sofreu truncamento notável — a resposta foi muito mais curta que as anteriores, sugerindo que a janela de tokens estava próxima do limite no final da sessão (#52)
- O prompt da Tarefa 1 foi enviado duas vezes; o agente não acusou repetição nem pediu confirmação — comportamento neutro
- Nenhuma tool foi criada nem sugerida espontaneamente nesta sessão (esperado, dado o perfil das tarefas)

---

**Sessão 2 — Simulado**

Tarefas:
- [x] pedir 5 questões no estilo ENEM sobre tópicos variados
- [x] responder as questões e pedir correção com explicação
- [x] pedir pra identificar os pontos fracos com base nas respostas
- [x] pedir um plano de revisão focado nos pontos fracos

Resultado por tarefa (`gemma4:cloud` · janela padrão Ollama · 2026-08-15):

| Tarefa | Resultado | Observação |
|---|---|---|
| Gerar 5 questões estilo ENEM | ✅ | 5 questões completas, enunciados contextualizados, 5 alternativas cada, gabarito não revelado; tópicos cobriram Matemática e Linguagens conforme solicitado |
| Corrigir respostas com explicação | ✅ | Correção completa das 5 questões com raciocínio detalhado; cálculos corretos (Bhaskara, juros compostos, combinação); sem inconsistência com o gabarito gerado |
| Identificar pontos fracos | ✅ | Diagnóstico preciso com base nas respostas; explicou por que cada tópico é armadilha no ENEM; mencionou o padrão de confusão Arranjo vs Combinação (consistente com S1) |
| Plano de revisão 7 dias | ✅ | Plano completo com tópico, atividade, tempo estimado e priorização; incluiu dicas práticas de técnica de estudo como bônus |

Tools criadas nessa sessão: nenhuma  
Observações:
- Sessão mais densa que a S1 (4 turnos, respostas longas) e sem sinal de truncamento — a janela padrão suportou bem nessa sessão (#53)
- O agente corrigiu Combinação vs Arranjo com qualidade superior à S1: desta vez gerou o exemplo prático comparativo que faltou antes, possivelmente porque o contexto do simulado forçou o raciocínio completo
- Diagnóstico de pontos fracos foi personalizado e não genérico — bom sinal de que o agente usou o histórico da conversa e não só as fontes
- O plano de 7 dias priorizou corretamente os tópicos de maior peso no ENEM (Combinatória e Funções nos primeiros dias)
- Nenhuma tool criada nem sugerida (esperado para esse perfil de tarefa)

---

**Sessão 3 — Redação**

Tarefas:
- [x] indexar uma coletânea de textos motivadores como fonte da sessão
- [x] pedir pro agente propor um tema de redação baseado nos textos
- [x] escrever uma redação e pedir avaliação com nota e comentários
- [x] pedir uma versão melhorada de um parágrafo específico

Resultado por tarefa (`gemma4:cloud` · janela padrão Ollama · 2026-08-15):

| Tarefa | Resultado | Observação |
|---|---|---|
| Indexar coletânea como fonte de sessão | ✅ | Executado sem intervenção |
| Propor tema no formato ENEM | ✅ | Tema derivado corretamente dos textos; formato completo (título, contextualização, o que abordar, restrição); coerente com o eixo da coletânea |
| Avaliar redação nas 5 competências | ✅ | Avaliação completa com nota por competência (C1:200, C2:160, C3:160, C4:200, C5:120 = 840 pts); prompt enviado sem o texto por erro do usuário — agente inferiu pelo contexto e avaliou corretamente |
| Reescrever segundo parágrafo | ✅ | Parágrafo reescrito com dados da coletânea, conectivos mais sofisticados e argumentação crítica mais profunda; nível compatível com C3 > 160 |

Tools criadas nessa sessão: nenhuma  
Observações:
- Sessão densa (4 turnos com respostas longas) sem sinal de truncamento — janela padrão suportou bem até o fim
- Robustez ao erro do usuário: prompt da Tarefa 2 enviado sem o texto da redação; o agente inferiu pelo contexto da conversa e avaliou corretamente — comportamento positivo, mas dependente do histórico estar dentro da janela
- O agente emitiu "pedido de desculpas por erro" nos steps intermediários do loop de raciocínio; como os steps aparecem no terminal para o usuário isso não é crítico, mas é um ruído a considerar filtrar no futuro
- Nenhuma tool criada (esperado para esse perfil de tarefa)

---

**Resultado geral — Caso 2**

| Modelo | Sessão 1 | Sessão 2 | Sessão 3 | Impressão geral |
|---|---|---|---|---|
| gemma4:cloud | ✅ 4/5 · ⚠️ 1/5 | ✅ 4/4 | ✅ 4/4 | RAG sólido nas 3 sessões; robusto a erros de prompt; ruído de "desculpas" nos steps do loop; sem truncamento na S2 e S3 |
| gemma4:local | | | | |

---

## Caso 3 — Assistente de Professor

**Objetivo:** avaliar capacidade de organização, geração de documentos
e suporte a fluxos de trabalho repetitivos do dia a dia escolar.

**Agente:** `prof_assistant`  
**Fontes sugeridas:** plano de curso, lista de alunos, critérios de avaliação, conteúdo das aulas

**Sessão 1 — Planejamento**

Tarefas:
- [ ] indexar plano de curso como fonte global
- [ ] pedir um cronograma semanal baseado no plano
- [ ] pedir sugestão de atividade para um tema específico do plano
- [ ] gerar um plano de aula completo para uma unidade

Resultado por tarefa: _(preencher)_  
Observações: _(livre)_

---

**Sessão 2 — Avaliação**

Tarefas:
- [ ] indexar lista de alunos e critérios de avaliação
- [ ] registrar notas fictícias de 5 alunos em 3 atividades
- [ ] pedir cálculo de média e situação de cada aluno
- [ ] pedir identificação de alunos em risco de reprovação
- [ ] gerar um relatório de turma formatado

Resultado por tarefa: _(preencher)_  
Tools criadas nessa sessão: _(listar)_  
Observações: _(livre)_

---

**Sessão 3 — Comunicação**

Tarefas:
- [ ] pedir um comunicado pros pais sobre data de prova
- [ ] pedir um feedback individualizado para 2 alunos com perfis diferentes
- [ ] pedir sugestão de atividade de recuperação para alunos com baixa nota
- [ ] gerar um resumo da semana pra enviar pra coordenação

Resultado por tarefa: _(preencher)_  
Observações: _(livre)_

---

**Resultado geral — Caso 3**

| Modelo | Sessão 1 | Sessão 2 | Sessão 3 | Impressão geral |
|---|---|---|---|---|
| gemma4:cloud | | | | |
| gemma4:local | | | | |

---

## Caso 4 — Desenvolvimento de Software *(planejado)*

**Dependência:** modelo secundário para tarefas complexas (orquestração multi-modelo)

**Objetivo:** avaliar capacidade de criar projetos funcionais,
debugging e geração de código com suporte a modelo mais avançado quando necessário.

**Status:** aguardando implementação do roteamento multi-modelo.

---

## Síntese geral

_(preencher após rodar os casos)_

| Caso de uso | Melhor modelo | Pior gargalo | Prioridade de melhoria |
|---|---|---|---|
| Gestão de Loja | | | |
| Assistente ENEM | | | |
| Assistente Professor | | | |
| Desenvolvimento | | | |

**Principais limitações identificadas:**
- _(preencher)_

**Tools mais criadas pelos agentes:**
- _(preencher)_

**Próximas implementações sugeridas pelos testes:**
- _(preencher)_
