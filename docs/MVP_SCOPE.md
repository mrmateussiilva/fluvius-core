# Escopo do MVP

## Entra no MVP

- Autenticação simples e gestão de administradores/atendentes associados a tenants. Administradores criam, atualizam senha, definem papel, atribuem canais e desativam usuários da própria empresa.
- Administração global mínima da instalação: criar, listar, inspecionar,
  ativar/suspender empresas e entrar para suporte com auditoria, sem billing ou
  métricas comerciais. A criação entrega um link de login próprio da empresa e
  as credenciais iniciais uma única vez.
- Identificação automática do atendente em textos e legendas enviados pelo número compartilhado, usando o nome de exibição persistido no momento do envio.
- Um ou mais canais WhatsApp por tenant.
- Filas separadas por canal: administradores podem selecionar um canal ou a visão consolidada; atendentes enxergam somente os canais atribuídos.
- Evolution Go como provider inicial plugável.
- Provisionamento administrativo de instâncias Evolution Go, estado e reconexão/QR inteiramente por meio da API, com credenciais cifradas e sem configuração por canal no frontend ou `.env`.
- Contatos criados a partir de mensagens recebidas.
- Grupos do WhatsApp na mesma inbox: uma conversa por grupo/canal, badge e
  filtro na lista, nome do participante nas mensagens incoming e resposta
  enviada ao JID do grupo. Sem administração de membros nesta etapa.
- Painel operacional do contato com perfil básico do WhatsApp e histórico de atendimentos.
- Filas `new`, `open` e `closed`.
- Assumir e finalizar atendimento, com takeover e transferência por administradores para usuários ativos da própria empresa.
- Quadro operacional exclusivo para administradores, com fila aguardando, colunas por atendente, atualização realtime e redistribuição por drag-and-drop ou seletor.
- Sincronização operacional exclusiva para administradores: atualização limitada dos contatos conhecidos e reconciliação de edições/recibos recentes já recebidos.
- Saúde operacional exclusiva para administradores da empresa: presença dos
  workers, disponibilidade do Redis, entregas pendentes/atrasadas, falhas das
  últimas 24 horas e estado dos canais, com alerta global na interface.
- Receber e enviar texto.
- Entrega assíncrona de texto e mídia por worker exclusivo, com outbox
  persistente, ordem por conversa e retry conservador.
- Responder/citar mensagens, refletir edições, acompanhar horários de
  entrega/leitura e reenviar falhas manualmente.
- Anexos de imagem, documento, áudio, vídeo e figurinha nativa, com limite local de 25 MB, validação do conteúdo e envio idempotente. PNG e JPG escolhidos como figurinha são convertidos para WebP 512×512 antes do envio.
- Seletor de emojis Unicode por categoria e botão dedicado para escolher figurinha no composer.
- Player de áudio com progresso e velocidades `1x`, `1,5x` e `2x`.
- Respostas rápidas.
- Atualizações realtime essenciais.
- Auditoria/eventos técnicos suficientes para diagnosticar provider.
- Implantação em uma VPS com Caddy, HTTPS/WSS, serviços internos, mídias
  persistentes, healthchecks e backup local versionado.

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
- Antivírus, CDN e storage distribuído.
- Importação completa do histórico ou da agenda do WhatsApp quando o provider não oferecer um contrato confirmado para isso.

## Plano dos próximos 10 dias

1. Validar Compose, migration, bootstrap e smoke test do login.
2. Criar testes de isolamento entre dois tenants para todos os endpoints atuais.
3. Fixar e validar a versão do Evolution Go, licença e criação de instância.
4. Capturar fixtures reais de status, QR e envio de texto; ajustar o adapter.
5. Capturar webhooks reais de incoming, ACK e conexão; garantir idempotência.
6. Cobrir máquina de estados de mensagens e canal com testes de integração.
7. Validar em uma sessão real a outbox, o worker de entrega e a chave
   idempotente usada no retry já implementado.
8. Integrar upload de mídia ponta a ponta e definir MinIO/S3 para o ambiente seguinte.
9. Refinar UX operacional de filas, erros e reconexão sem criar dashboard/CRM.
10. Executar teste de atendimento completo, registrar riscos e congelar o escopo do MVP.

Ao fim desse ciclo, o critério não é quantidade de telas: é um atendimento real e rastreável, do webhook à resposta confirmada, sem cruzar tenants e sem acesso direto ao gateway pelo navegador.
