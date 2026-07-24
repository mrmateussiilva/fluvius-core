# Escopo do MVP

## Entra no MVP

- Autenticação simples e usuários associados a tenants.
- Um ou mais canais WhatsApp por tenant.
- Evolution Go como provider inicial plugável.
- Estado e reconexão/QR do canal por meio da API.
- Contatos criados a partir de mensagens recebidas.
- Painel operacional do contato com perfil básico do WhatsApp e histórico de atendimentos.
- Filas `new`, `open` e `closed`.
- Assumir e finalizar atendimento.
- Receber e enviar texto.
- Responder/citar mensagens, acompanhar horários de entrega/leitura e reenviar falhas manualmente.
- Anexos de imagem, documento, áudio, vídeo e figurinha, com limite local de 25 MB.
- Respostas rápidas.
- Atualizações realtime essenciais.
- Auditoria/eventos técnicos suficientes para diagnosticar provider.

## Não entra no MVP

- Dashboard, métricas e gráficos.
- CRM, funil, negócios ou cadastro rico de empresas.
- IA, bots, classificação automática ou resumo.
- Billing, assinatura e limites comerciais.
- Campanhas, broadcast ou marketing.
- Meta Cloud API completa ou BSP completo.
- Omnichannel além do WhatsApp.
- Importação de código, dados ou arquitetura do Chatwoot.
- Alta disponibilidade e realtime multi-réplica nesta primeira etapa.
- Storage de produção, antivírus e CDN.

## Plano dos próximos 10 dias

1. Validar Compose, migration, bootstrap e smoke test do login.
2. Criar testes de isolamento entre dois tenants para todos os endpoints atuais.
3. Fixar e validar a versão do Evolution Go, licença e criação de instância.
4. Capturar fixtures reais de status, QR e envio de texto; ajustar o adapter.
5. Capturar webhooks reais de incoming, ACK e conexão; garantir idempotência.
6. Cobrir máquina de estados de mensagens e canal com testes de integração.
7. Enfileirar envio/retry no RQ com idempotency key e política de backoff.
8. Integrar upload de mídia ponta a ponta e definir MinIO/S3 para o ambiente seguinte.
9. Refinar UX operacional de filas, erros e reconexão sem criar dashboard/CRM.
10. Executar teste de atendimento completo, registrar riscos e congelar o escopo do MVP.

Ao fim desse ciclo, o critério não é quantidade de telas: é um atendimento real e rastreável, do webhook à resposta confirmada, sem cruzar tenants e sem acesso direto ao gateway pelo navegador.
