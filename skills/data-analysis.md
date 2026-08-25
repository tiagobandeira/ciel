# Data Analysis

description: Análise exploratória de dados com Python e pandas — inspeção, limpeza, estatísticas, visualizações e interpretação dos resultados.

## Objetivo

Realizar análise exploratória de dados (EDA) completa sobre o dataset recebido. O resultado deve incluir código Python executável, saídas esperadas comentadas e interpretação dos achados em linguagem clara. Não entregue apenas código — entregue código + o que ele revela.

---

## Estrutura padrão de uma análise

Siga essa ordem. Adapte conforme o que foi pedido, mas não pule etapas sem motivo.

### 1. Inspeção inicial
```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

df = pd.read_csv("dados.csv")  # ou o formato recebido

# dimensões
print(f"Shape: {df.shape}")           # (linhas, colunas)
print(f"\nColunas:\n{df.dtypes}")     # tipos de cada coluna
print(f"\nPrimeiras linhas:\n{df.head()}")
print(f"\nEstatísticas básicas:\n{df.describe(include='all')}")
```

Após rodar, comente o que cada saída revela — não deixe o usuário interpretar sozinho.

### 2. Valores ausentes
```python
nulos = df.isnull().sum()
pct_nulos = (nulos / len(df) * 100).round(2)
resumo_nulos = pd.DataFrame({'total': nulos, 'percentual': pct_nulos})
print(resumo_nulos[resumo_nulos['total'] > 0].sort_values('percentual', ascending=False))
```

Para cada coluna com nulos, decida e justifique:
- **< 5%** — pode imputar (mediana para numérico, moda para categórico) ou dropar as linhas
- **5–20%** — imputar com cuidado ou criar flag `coluna_missing`
- **> 20%** — considerar dropar a coluna ou análise específica

### 3. Duplicatas
```python
n_dup = df.duplicated().sum()
print(f"Duplicatas: {n_dup} ({n_dup/len(df)*100:.2f}%)")
# se houver, mostrar exemplos
if n_dup > 0:
    print(df[df.duplicated(keep=False)].head(10))
```

### 4. Distribuição de variáveis numéricas
```python
numericas = df.select_dtypes(include=[np.number]).columns

fig, axes = plt.subplots(len(numericas), 2, figsize=(14, 4 * len(numericas)))
for i, col in enumerate(numericas):
    # histograma
    df[col].hist(bins=30, ax=axes[i, 0])
    axes[i, 0].set_title(f'{col} — distribuição')
    # boxplot
    df.boxplot(column=col, ax=axes[i, 1])
    axes[i, 1].set_title(f'{col} — outliers')
plt.tight_layout()
plt.savefig('distribuicoes.png', dpi=150)
```

Interprete: simetria, assimetria, bimodalidade, outliers evidentes.

### 5. Variáveis categóricas
```python
categoricas = df.select_dtypes(include=['object', 'category']).columns

for col in categoricas:
    print(f"\n{col} — {df[col].nunique()} categorias únicas")
    print(df[col].value_counts(normalize=True).head(10).to_string())
```

Identifique: cardinalidade alta, categorias raras (< 1%), inconsistências de grafia.

### 6. Correlações (variáveis numéricas)
```python
corr = df[numericas].corr()

plt.figure(figsize=(10, 8))
sns.heatmap(corr, annot=True, fmt='.2f', cmap='coolwarm',
            center=0, vmin=-1, vmax=1)
plt.title('Matriz de correlação')
plt.tight_layout()
plt.savefig('correlacoes.png', dpi=150)
```

Interprete correlações > 0.7 ou < -0.7 — possível multicolinearidade ou relação causal.

### 7. Análise temporal (se houver coluna de data)
```python
# identifica coluna de data
date_cols = df.select_dtypes(include=['datetime64']).columns
# se necessário: df['data'] = pd.to_datetime(df['data'])

for col in date_cols:
    df_time = df.set_index(col).resample('M').size()
    df_time.plot(figsize=(12, 4), title=f'Volume por mês — {col}')
    plt.savefig(f'serie_temporal_{col}.png', dpi=150)
```

### 8. Resumo e achados

Ao final, sempre inclua uma seção em texto:

```
## Principais achados

1. **Qualidade dos dados**: X% de nulos em [coluna], Y duplicatas removidas.
2. **Distribuições**: [coluna A] tem distribuição assimétrica à direita com outliers acima de Z.
3. **Correlações relevantes**: [coluna A] e [coluna B] têm correlação de 0.85 — possível colinearidade.
4. **Padrões temporais**: volume crescente de jan a mar, queda em abr.
5. **Próximos passos recomendados**: [o que analisar depois com base nos achados].
```

---

## Bibliotecas padrão

```python
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats  # para testes estatísticos quando necessário
```

Configurações recomendadas no início do script:
```python
pd.set_option('display.max_columns', None)
pd.set_option('display.float_format', '{:.4f}'.format)
sns.set_theme(style='whitegrid', palette='muted')
plt.rcParams['figure.dpi'] = 150
```

---

## Testes estatísticos — quando usar

| Situação | Teste |
|---|---|
| Comparar médias de dois grupos | t-test (`scipy.stats.ttest_ind`) |
| Comparar médias de 3+ grupos | ANOVA (`scipy.stats.f_oneway`) |
| Verificar normalidade | Shapiro-Wilk (`scipy.stats.shapiro`) — para n < 5000 |
| Associação entre categóricas | Qui-quadrado (`scipy.stats.chi2_contingency`) |
| Correlação não paramétrica | Spearman (`df.corr(method='spearman')`) |

Use testes estatísticos quando o usuário pedir ou quando a inspeção visual não for conclusiva. Sempre reporte p-value e interprete o resultado.

---

## Limpeza de dados — padrões

```python
# remover duplicatas
df = df.drop_duplicates()

# imputar mediana em numéricos
for col in numericas:
    df[col] = df[col].fillna(df[col].median())

# imputar moda em categóricos
for col in categoricas:
    df[col] = df[col].fillna(df[col].mode()[0])

# padronizar strings
df[col] = df[col].str.strip().str.lower()

# converter tipos
df['data'] = pd.to_datetime(df['data'], dayfirst=True, errors='coerce')
df['valor'] = pd.to_numeric(df['valor'].str.replace(',', '.'), errors='coerce')
```

Sempre mostre o shape antes e depois de qualquer limpeza.

---

## Formato de entrega

Entregue um único script Python completo e executável, organizado em seções comentadas com `# ──`. Cada seção deve ter:
1. O código
2. Um comentário explicando o que a saída revela (não o que o código faz)

Salve todas as visualizações como `.png` em vez de usar `plt.show()` — o ambiente pode ser não interativo.

---

## O que não fazer

- Não entregue apenas código sem interpretação
- Não use `df.info()` como substituto para análise real
- Não ignore colunas com muitos nulos sem justificar
- Não afirme causalidade a partir de correlação
- Não gere visualizações sem título, labels nos eixos e unidades
- Não use `print(df)` em datasets grandes — use `.head()`, `.sample()` ou `.describe()`
