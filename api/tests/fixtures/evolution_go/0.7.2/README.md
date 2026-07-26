# Fixtures do Evolution Go 0.7.2

Capturadas em 24 de julho de 2026 durante um smoke test local com a imagem:

```text
evoapicloud/evolution-go@sha256:6fa601464bd76d3d19ece4c48d8bb5373d025d95d45b939ae4bf0c77b03f5aaa
```

Os arquivos preservam o envelope e os tipos retornados pelo gateway. Nome de
instância, telefone, identificadores, QR, pairing code, tokens e outros dados
operacionais são substituídos ou omitidos antes de entrar no repositório.

`qr-session-already-logged-in.json` é a resposta HTTP 400 observada ao pedir um
QR para uma sessão já autenticada. Nesse caso específico, o canal permanece
`connected`; outros erros HTTP continuam conservadoramente como `failed`.

`message-edited-encrypted.json` e `reaction-removed.json` foram capturadas em
25 de julho de 2026. A primeira preserva a estrutura de uma edição cujo novo
texto não foi disponibilizado pela Evolution Go; a segunda representa uma
remoção de reação. Material criptográfico e identificadores operacionais foram
removidos.
