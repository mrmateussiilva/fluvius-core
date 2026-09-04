# Plano de qualidade para a versão 1.0.0

Meta: publicar a `v1.0.0` até **6 de setembro de 2026**, desde que o fluxo
principal esteja confortável para uso diário e todos os gates abaixo sejam
atendidos. A versão não será tratada como uma coleção de funcionalidades: o
resultado esperado é receber, assumir, responder e finalizar atendimentos com
clareza e confiança.

## Prioridades

### 1. Legibilidade e orientação

- Tema claro com contraste verificável para texto, controles e estados.
- Conversa selecionada, canal, responsável, mensagens não lidas e bloqueios
  devem ser reconhecidos sem releitura.
- Texto operacional não deve depender de tamanhos menores que 12 px; tamanhos
  inferiores ficam restritos a metadados recuperáveis.
- Validar 390×844 e 1440×1000 nos temas claro e escuro.

### 2. Fluxo diário de atendimento

- Testar ponta a ponta: incoming, fila, assumir, responder, confirmar envio,
  receber resposta, transferir quando aplicável e finalizar.
- Remover fricções que obriguem o atendente a navegar por páginas
  administrativas durante uma conversa.
- Tornar loading, vazio, erro, canal desconectado e retry inequívocos.
- Preservar rascunho, posição de leitura e feedback de nova mensagem.

### 3. Confiança operacional

- Nenhum erro, timeout ou resposta ambígua pode aparecer como sucesso.
- Validar outbox, inbox, webhooks idempotentes, reconciliação e recuperação dos
  workers com um canal real.
- Confirmar isolamento de tenant e permissão de canal em todos os fluxos
  exercitados.

## Sequência curta

| Data | Resultado esperado |
| --- | --- |
| 03/09 | Contraste do tema claro e hierarquia da central de conversas corrigidos. |
| 04/09 | Auditoria do fluxo diário, correção das principais fricções e validação mobile. |
| 05/09 | Teste completo com canal real, regressão técnica e `v1.0.0-rc.1`. |
| 06/09 | Soak em produção, correções bloqueantes e `v1.0.0`. |

## Gates da 1.0.0

A tag final só pode ser criada quando:

1. Pelo menos dois operadores completarem um ciclo real de atendimento sem
   ajuda de quem desenvolveu o sistema e sem bloqueio de severidade alta.
2. Não houver defeito conhecido que impeça receber, assumir, responder ou
   finalizar.
3. Contraste automatizado, build TypeScript, testes da API, Alembic e
   `docker compose config` estiverem aprovados.
4. Um teste real confirmar incoming, envio com ID do provider, recibo e
   reconexão após interrupção controlada.
5. O deploy por tag concluir, o HTML público mostrar `1.0.0` e
   `/health/ready` responder `ready`.

Itens como CRM, campanhas, billing, dashboard comercial e novos providers
continuam fora deste marco.
