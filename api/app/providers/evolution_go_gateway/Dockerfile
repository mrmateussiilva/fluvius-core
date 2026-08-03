FROM golang:1.25.0-alpine AS build

ARG EVOLUTION_GO_SOURCE_URL=https://github.com/evolution-foundation/evolution-go.git
ARG EVOLUTION_GO_SOURCE_REF=9337afc47e10b86cc896a6f432240e40fee95dd1
ARG VERSION=0.7.2-fluvius-edit-media-fix.2

RUN apk update && apk add --no-cache git build-base libjpeg-turbo-dev libwebp-dev

WORKDIR /build

RUN git clone "${EVOLUTION_GO_SOURCE_URL}" . \
    && git checkout --detach "${EVOLUTION_GO_SOURCE_REF}" \
    && test "$(git rev-parse HEAD)" = "${EVOLUTION_GO_SOURCE_REF}"

COPY api/app/providers/evolution_go_gateway/message_edits.patch /tmp/message_edits.patch
RUN git apply --check /tmp/message_edits.patch \
    && git apply /tmp/message_edits.patch

COPY api/app/providers/evolution_go_gateway/document_media.patch /tmp/document_media.patch
RUN git apply --check /tmp/document_media.patch \
    && git apply /tmp/document_media.patch

RUN go mod download
RUN CGO_ENABLED=1 go build -ldflags "-X main.version=${VERSION}" -o server ./cmd/evolution-go

FROM alpine:3.19.1 AS final

RUN apk update && apk add --no-cache tzdata ffmpeg libjpeg-turbo libwebp poppler-utils

WORKDIR /app

COPY --from=build /build/server .
COPY --from=build /build/manager/dist ./manager/dist
COPY --from=build /build/VERSION ./VERSION
COPY --from=build /build/LICENSE /licenses/evolution-go-LICENSE
COPY --from=build /build/NOTICE /licenses/evolution-go-NOTICE

ENV TZ=America/Sao_Paulo

ENTRYPOINT ["/app/server"]
