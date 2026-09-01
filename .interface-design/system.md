# Sistema visual do Fluvius Core

## Direção

O Fluvius é uma estação de atendimento WhatsApp para pessoas que alternam entre fila, conversa e encerramento durante um turno. A interface deve parecer calma, operacional e confiável: compacta o suficiente para uso contínuo, mas sem a densidade de um painel técnico.

- Domínio: fila, conversa, canal, plantão, identidade do atendente, presença, alerta e confirmação de entrega.
- Mundo de cores: verde de canal conectado, branco de mensagem recebida, verde-claro de mensagem enviada, cinza da fila, grafite da navegação e âmbar de atenção.
- Assinatura: o estado operacional aparece junto da pessoa ou do canal, como parte da tarefa, não como métrica decorativa. A faixa verde de 4 px no resumo de conta e os pontos de estado são expressões desse padrão.
- Evitar: grades genéricas de métricas, gradientes decorativos, múltiplas cores de destaque, cards idênticos sem hierarquia e controles que não persistem de verdade.
- Escopo: priorizar receber, assumir, responder e finalizar. Não introduzir dashboard, CRM, billing, campanhas ou outras áreas fora do MVP.

## Paleta e tokens

Usar exclusivamente os tokens semânticos de `web/src/styles/main.css` e seus mapeamentos no Tailwind. Não adicionar hex avulso em componentes.

- Estrutura: `canvas`, `panel`, `panel-muted`, `panel-raised`, `line`, `line-strong`.
- Texto em quatro níveis: `ink`, `ink-secondary`, `ink-muted`, `ink-faint`.
- Marca e ação principal: escala `fluvius`, com `fluvius-700` como botão principal e `fluvius-600` para foco/seleção.
- Navegação: `nav`.
- Estados: `success`, `warning`, `danger` e `info`, sempre com as variantes `soft` e `strong` correspondentes.
- Controles inset: fundo `canvas`, borda `line-strong`; desabilitados usam `panel-muted`, `line` e `ink-muted`.
- Dark mode: manter os mesmos papéis semânticos. Usar bordas para definição e evitar aumentar sombras.

A distribuição visual deve permanecer próxima de 60% neutros de base, 30% superfícies e estrutura, 10% marca/estado. Verde comunica conexão, seleção ou ação principal; não é decoração.

## Profundidade, superfícies e raios

A estratégia é de sombras sutis com bordas discretas:

- Canvas: `bg-canvas`, sem sombra.
- Card/painel: `bg-panel border border-line shadow-sm`.
- Popover: `bg-panel-raised border border-line` com sombra mais evidente somente para comunicar sobreposição.
- Inputs: visualmente inset, com `bg-canvas border-line-strong`.
- Cards: raio de 12 px (`rounded-xl`).
- Inputs e botões: raio de 8 px (`rounded-lg`).
- Pills e indicadores: raio completo (`rounded-full`).
- Elementos aninhados devem manter raio concêntrico: card 12 px, controle interno 8 px.

## Espaçamento e densidade

Base de 4 px. Usar somente múltiplos da base, salvo ajuste óptico documentado.

- Micro: 4–8 px entre ícone, label e metadado.
- Controle: 12–16 px de padding horizontal; altura mínima de 40 px.
- Card operacional: 20 px no mobile e 24 px a partir de `sm`.
- Entre grupos relacionados: 16–20 px.
- Entre áreas principais: 24–32 px.
- Área clicável: mínimo de 40 px; preferir 44 px em controles isolados.

## Hierarquia tipográfica

Usar a família já definida na raiz e uma escala compacta próxima de 1,2. Peso e cor fazem mais trabalho que aumentos pequenos de tamanho.

- Metadado: 11–12 px, peso 400–500, `ink-faint` ou `ink-muted`.
- Label de campo: 12 px/600, `ink-secondary`.
- Corpo e controles: 14 px/400–600.
- Título de seção/card: 16–18 px/600, `ink`.
- Título de página: 24 px/600, tracking levemente apertado.
- Eyebrow de página: 12 px/600, uppercase e tracking amplo, `fluvius-700`.
- Números dinâmicos devem usar algarismos tabulares.

Cada tela tem um foco principal. Em páginas de configuração, o título e o resumo operacional lideram; formulários e preferências ficam em segundo nível. Em conversa, o histórico e o compositor continuam sendo o foco.

## Layout e navegação

- Navegação desktop: trilho de 68 px; ícones de 20 px e alvos de aproximadamente 44 px.
- Navegação mobile: barra inferior de 64 px, escondida durante uma conversa ativa.
- Páginas de configuração: largura máxima entre `max-w-5xl` e `max-w-6xl`, padding horizontal de 16 px no mobile e 32 px em telas maiores.
- Colunas assimétricas são preferidas quando uma área é primária. O padrão de conta usa aproximadamente 1,15:0,85; no mobile vira uma coluna.
- Avisos globais no mobile devem participar do fluxo e nunca cobrir títulos ou controles. No desktop podem flutuar no topo quando pequenos e transitórios.

## Padrões reutilizáveis

### Cabeçalho de página operacional

- Eyebrow com ícone de 20 px, gap de 8 px e texto 12 px/600 uppercase.
- `h1` com 24 px/600 e margem superior de 4 px.
- Descrição com 14 px, line-height de 24 px, `ink-muted`, largura limitada.
- Primeiro conteúdo começa 24 px abaixo.

### Card de seção

- `rounded-xl border border-line bg-panel shadow-sm`.
- Padding de 20 px mobile / 24 px desktop.
- Cabeçalho interno com tile de ícone 40×40 px, raio 8 px, `panel-muted`, seguido de título 16 px/600 e descrição 12 px com line-height 20 px.

### Input padrão

- Altura aproximada de 40 px; padding 10 px vertical e 12 px horizontal.
- `rounded-lg border-line-strong bg-canvas`.
- Texto 14 px; placeholder `ink-faint`.
- Foco: `border-fluvius-600` e ring de 2 px com `fluvius-600/20`.
- Estado desabilitado: `panel-muted`, `line`, `ink-muted`, cursor bloqueado.

### Botões

- Primário: mínimo 40 px de altura, padding horizontal de 16 px, raio 8 px, texto 14 px/600, `fluvius-700`; hover `fluvius-800`; active `scale(0.97)`; disabled com opacidade 50%.
- Neutro seguro: mesmas medidas, `neutral-action`, para ações como troca de senha que não são o foco da página.
- Secundário: borda `line`, fundo transparente/panel, texto `ink-secondary`; hover `panel-muted`.
- Em loading, preservar largura e trocar/antepor ícone por spinner de 16 px.

### Opção selecionável

- Altura mínima de 56 px, raio 8 px, padding 12 px, ícone 20 px.
- Inativa: `bg-canvas border-line`.
- Ativa: `bg-fluvius-50 border-fluvius-600`, ícone/indicador `fluvius`.
- Usar controle nativo escondido visualmente para manter semântica de radio/checkbox.

### Estado e confirmação

- Pill: padding 6 px vertical / 12 px horizontal, texto 12 px/600, ponto de 8 px quando houver presença ou conexão.
- Sucesso/erro inline: fundo semântico `soft`, texto `strong`, padding 8×12 px, raio 8 px.
- Erros devem permanecer próximos da ação que falhou; nunca tratar timeout ou resposta ambígua como sucesso.

## Movimento e estados

- Transições de hover/foco entre 120–200 ms; não usar `transition: all` em novos componentes.
- Press feedback em botões: `scale(0.97)`.
- Animar apenas `transform` e `opacity` em overlays.
- Respeitar `prefers-reduced-motion` ao introduzir movimento novo.
- Todo controle deve ter default, hover, focus, active e disabled quando aplicável.
- Conteúdo assíncrono deve prever loading, vazio, erro e sucesso.

## Acessibilidade e responsividade

- Preferir elementos HTML nativos; não criar botões com `div`.
- Usar `role="switch"`, `aria-checked`, radiogroups e labels quando o controle visual exigir composição.
- Manter contraste por tokens semânticos em tema claro e escuro.
- Truncar somente metadados que possam ser recuperados por título/detalhe; textos de ação e erro devem quebrar linha.
- Validar mudanças visuais, no mínimo, em 390×844 e 1440×1000, verificando rolagem horizontal, barra mobile, tema escuro e estados interativos.

## Referência aprovada

A tela `web/src/pages/AccountSettingsPage.vue`, validada em desktop e mobile na release v0.0.62, é a referência inicial para páginas de configuração: resumo operacional com faixa de estado, cartões assimétricos, controles inset e feedback inline. Não houve geração de imagem ou moodboard externo; a direção foi extraída do domínio e dos tokens existentes do produto.
