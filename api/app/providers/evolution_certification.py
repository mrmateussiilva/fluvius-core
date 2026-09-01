from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from uuid import uuid4

from app.channels.models import WhatsAppChannel
from app.common.enums import ChannelProvider, ChannelStatus
from app.providers.evolution_contract import (
    EVOLUTION_GO_IMAGE_VERSION,
    EVOLUTION_GO_SOURCE_REF,
    EVOLUTION_GO_VERSION,
)
from app.providers.evolution_diagnostics import probe_evolution_channel
from app.providers.evolution_go import EvolutionGoProvider


@dataclass(frozen=True, slots=True)
class CertificationCheck:
    name: str
    success: bool
    detail: str
    provider_id_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class EvolutionCertificationReport:
    contract_version: str = EVOLUTION_GO_VERSION
    image_version: str = EVOLUTION_GO_IMAGE_VERSION
    source_ref: str = EVOLUTION_GO_SOURCE_REF
    checks: list[CertificationCheck] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.checks) and all(check.success for check in self.checks)

    def safe_dict(self) -> dict:
        payload = asdict(self)
        payload["success"] = self.success
        return payload


def _provider_id_fingerprint(provider_message_id: str | None) -> str | None:
    if not provider_message_id:
        return None
    return sha256(provider_message_id.encode()).hexdigest()[:12]


async def certify_evolution_go(
    provider: EvolutionGoProvider,
    channel: WhatsAppChannel,
    *,
    recipient: str | None = None,
    media_url: str | None = None,
    verify_idempotency: bool = False,
) -> EvolutionCertificationReport:
    checks: list[CertificationCheck] = []
    status_probe = await probe_evolution_channel(provider, channel)
    checks.append(
        CertificationCheck(
            name="instance_status",
            success=(status_probe.error is None and status_probe.status == ChannelStatus.CONNECTED),
            detail=(
                f"status={status_probe.status.value};latency_ms={status_probe.latency_ms}"
                if status_probe.error is None
                else status_probe.error
            ),
        )
    )

    if recipient is None:
        return EvolutionCertificationReport(checks=checks)

    idempotency_key = f"fluvius-certification-{uuid4()}"
    text_result = await provider.send_text(
        channel,
        recipient,
        "Teste técnico de integração Fluvius / Evolution Go",
        idempotency_key=idempotency_key,
    )
    checks.append(
        CertificationCheck(
            name="send_text",
            success=text_result.success and bool(text_result.provider_message_id),
            detail="provider confirmou o envio"
            if text_result.success
            else (text_result.error or "falha"),
            provider_id_fingerprint=_provider_id_fingerprint(text_result.provider_message_id),
        )
    )

    if verify_idempotency and text_result.success:
        duplicate_result = await provider.send_text(
            channel,
            recipient,
            "Teste técnico de integração Fluvius / Evolution Go",
            idempotency_key=idempotency_key,
        )
        same_confirmation = (
            duplicate_result.success
            and duplicate_result.provider_message_id == text_result.provider_message_id
        )
        checks.append(
            CertificationCheck(
                name="send_text_idempotency",
                success=same_confirmation,
                detail=(
                    "a mesma chave retornou a mesma confirmação"
                    if same_confirmation
                    else "a chave não foi deduplicada de forma comprovável"
                ),
                provider_id_fingerprint=_provider_id_fingerprint(
                    duplicate_result.provider_message_id
                ),
            )
        )

    if media_url:
        media_result = await provider.send_media(
            channel,
            recipient,
            media_url,
            caption="Teste técnico de mídia Fluvius / Evolution Go",
            idempotency_key=f"fluvius-certification-{uuid4()}",
        )
        checks.append(
            CertificationCheck(
                name="send_media",
                success=media_result.success and bool(media_result.provider_message_id),
                detail=(
                    "provider confirmou o envio"
                    if media_result.success
                    else (media_result.error or "falha")
                ),
                provider_id_fingerprint=_provider_id_fingerprint(media_result.provider_message_id),
            )
        )
    return EvolutionCertificationReport(checks=checks)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Certifica o contrato Evolution Go fixado pelo Fluvius sem exibir segredos."
    )
    parser.add_argument("--allow-send", action="store_true")
    parser.add_argument("--to", help="Número de teste; exige --allow-send")
    parser.add_argument("--media-url", help="URL pública de uma mídia de teste")
    parser.add_argument("--verify-idempotency", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (args.to or args.media_url or args.verify_idempotency) and not args.allow_send:
        raise SystemExit("Use --allow-send para autorizar mensagens reais de certificação.")
    if (args.media_url or args.verify_idempotency) and not args.to:
        raise SystemExit("Informe --to para certificar mídia ou idempotência.")

    provider = EvolutionGoProvider()
    if not provider.api_key:
        raise SystemExit("EVOLUTION_GO_API_KEY não está configurada para a certificação.")
    channel = WhatsAppChannel(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Evolution certification",
        provider=ChannelProvider.EVOLUTION_GO,
        status=ChannelStatus.DISCONNECTED,
        provider_config={"instance_name": "certification"},
    )
    report = asyncio.run(
        certify_evolution_go(
            provider,
            channel,
            recipient=args.to if args.allow_send else None,
            media_url=args.media_url,
            verify_idempotency=args.verify_idempotency,
        )
    )
    print(json.dumps(report.safe_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if report.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
