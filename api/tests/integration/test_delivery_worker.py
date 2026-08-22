from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import select

from app.common.enums import MessageStatus
from app.config import settings
from app.database import SessionLocal
from app.delivery.dispatcher import dispatch_delivery, dispatch_due_deliveries
from app.delivery.models import MessageDelivery
from app.delivery.tasks import run_delivery
from app.messages.models import Message
from app.providers.base import SendResult

from .base import PostgresIntegrationTestCase


class SequenceProvider:
    def __init__(self, results: list[SendResult]) -> None:
        self.results = results
        self.calls: list[str] = []

    async def send_text(
        self,
        channel,
        to: str,
        text: str,
        **kwargs,
    ) -> SendResult:
        self.calls.append(kwargs["idempotency_key"])
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]

    async def send_media(self, *args, **kwargs) -> SendResult:
        raise AssertionError("Este teste não envia mídia")


class DeliveryWorkerTest(PostgresIntegrationTestCase):
    def _assign(self) -> None:
        response = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/assign",
            headers=self.headers_a,
            json={},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _create_message(self, text: str) -> tuple[UUID, UUID]:
        message_id = uuid4()
        response = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/messages",
            headers=self.headers_a,
            json={
                "text": text,
                "client_message_id": str(message_id),
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(response.json()["attempt_count"], 0)
        with SessionLocal() as db:
            delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                    MessageDelivery.message_id == message_id,
                )
            )
            self.assertIsNotNone(delivery)
            return message_id, delivery.id

    def _make_due(self, delivery_id: UUID) -> None:
        with SessionLocal() as db:
            delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            delivery.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()

    def test_delivery_is_tenant_scoped_and_duplicate_worker_jobs_are_safe(self) -> None:
        self._assign()
        message_id, delivery_id = self._create_message("Entrega idempotente")
        provider = SequenceProvider(
            [
                SendResult(
                    success=True,
                    provider_message_id="worker-confirmed-1",
                    status=MessageStatus.SENT,
                )
            ]
        )
        with (
            patch.object(settings, "environment", "development"),
            patch("app.delivery.dispatcher.delivery_queue.enqueue") as enqueue,
        ):
            self.assertFalse(dispatch_delivery(delivery_id, self.tenant_b.tenant_id))
            self.assertTrue(dispatch_delivery(delivery_id, self.tenant_a.tenant_id))
            enqueue.assert_called_once()
            self.assertEqual(
                enqueue.call_args.args[0],
                "app.delivery.tasks.run_delivery",
            )
        with (
            patch("app.delivery.service.get_provider", return_value=provider),
            patch("app.delivery.tasks.claim_evolution_credential"),
        ):
            run_delivery(str(delivery_id), str(self.tenant_b.tenant_id))
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(provider.calls, [str(message_id)])
        with SessionLocal() as db:
            message = db.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.tenant_id == self.tenant_a.tenant_id,
                )
            )
            delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(message.status, MessageStatus.SENT)
            self.assertEqual(message.provider_message_id, "worker-confirmed-1")
            self.assertEqual(message.attempt_count, 1)
            self.assertEqual(delivery.status, "completed")

    def test_stale_enqueued_delivery_is_recovered_and_requeued(self) -> None:
        self._assign()
        _, delivery_id = self._create_message("Recuperar após queda do worker")
        with SessionLocal() as db:
            delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            delivery.status = "enqueued"
            delivery.rq_job_id = "failed-rq-job"
            delivery.updated_at = datetime.now(UTC) - timedelta(minutes=11)
            db.commit()

        with (
            patch.object(settings, "environment", "development"),
            patch("app.delivery.dispatcher.delivery_queue.enqueue") as enqueue,
        ):
            dispatched = dispatch_due_deliveries(self.tenant_a.tenant_id)

        self.assertEqual(dispatched, 1)
        enqueue.assert_called_once()
        with SessionLocal() as db:
            delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(delivery.status, "enqueued")
            self.assertNotEqual(delivery.rq_job_id, "failed-rq-job")

    def test_failed_rq_job_is_recovered_without_waiting_ten_minutes(self) -> None:
        self._assign()
        _, delivery_id = self._create_message("Recuperação rápida do RQ")
        with SessionLocal() as db:
            delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            delivery.status = "enqueued"
            delivery.rq_job_id = "failed-rq-job"
            delivery.updated_at = datetime.now(UTC) - timedelta(seconds=20)
            db.commit()

        with (
            patch.object(settings, "environment", "development"),
            patch(
                "app.delivery.dispatcher._rq_job_is_active",
                return_value=False,
            ),
            patch("app.delivery.dispatcher.delivery_queue.enqueue") as enqueue,
        ):
            dispatched = dispatch_due_deliveries(self.tenant_a.tenant_id)

        self.assertEqual(dispatched, 1)
        enqueue.assert_called_once()

    def test_dispatcher_does_not_enqueue_a_newer_pending_message_first(
        self,
    ) -> None:
        self._assign()
        _, first_delivery_id = self._create_message("Primeira pendente")
        _, second_delivery_id = self._create_message("Segunda pendente")

        with (
            patch.object(settings, "environment", "development"),
            patch("app.delivery.dispatcher.delivery_queue.enqueue") as enqueue,
        ):
            self.assertFalse(
                dispatch_delivery(
                    second_delivery_id,
                    self.tenant_a.tenant_id,
                )
            )
            self.assertTrue(
                dispatch_delivery(
                    first_delivery_id,
                    self.tenant_a.tenant_id,
                )
            )

        enqueue.assert_called_once()
        self.assertEqual(
            enqueue.call_args.args[1],
            str(first_delivery_id),
        )

    def test_completed_delivery_enqueues_the_next_message_immediately(self) -> None:
        self._assign()
        first_id, first_delivery_id = self._create_message("Primeira imediata")
        _, second_delivery_id = self._create_message("Segunda imediata")
        provider = SequenceProvider(
            [
                SendResult(
                    success=True,
                    provider_message_id="immediate-chain-1",
                    status=MessageStatus.SENT,
                )
            ]
        )

        with (
            patch.object(settings, "environment", "development"),
            patch("app.delivery.dispatcher.delivery_queue.enqueue") as enqueue,
            patch("app.delivery.service.get_provider", return_value=provider),
            patch("app.delivery.tasks.claim_evolution_credential"),
        ):
            run_delivery(str(first_delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(provider.calls, [str(first_id)])
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.args[1], str(second_delivery_id))
        with SessionLocal() as db:
            second_delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == second_delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(second_delivery.status, "enqueued")

    def test_retry_wait_does_not_release_the_next_message(self) -> None:
        self._assign()
        first_id, first_delivery_id = self._create_message("Primeira em retry")
        _, second_delivery_id = self._create_message("Segunda bloqueada")
        provider = SequenceProvider(
            [
                SendResult(
                    success=False,
                    error="Gateway temporariamente indisponível",
                    retryable=True,
                )
            ]
        )

        with (
            patch.object(settings, "environment", "development"),
            patch("app.delivery.dispatcher.delivery_queue.enqueue") as enqueue,
            patch("app.delivery.service.get_provider", return_value=provider),
            patch("app.delivery.tasks.claim_evolution_credential"),
        ):
            run_delivery(str(first_delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(provider.calls, [str(first_id)])
        enqueue.assert_not_called()
        with SessionLocal() as db:
            first_delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == first_delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            second_delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == second_delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(first_delivery.status, "retry_wait")
            self.assertEqual(second_delivery.status, "queued")

    def test_clearly_transient_failure_retries_with_the_same_message_id(self) -> None:
        self._assign()
        message_id, delivery_id = self._create_message("Retry controlado")
        provider = SequenceProvider(
            [
                SendResult(
                    success=False,
                    error="Gateway temporariamente indisponível",
                    retryable=True,
                ),
                SendResult(
                    success=True,
                    provider_message_id="worker-retry-confirmed",
                    status=MessageStatus.SENT,
                ),
            ]
        )
        with (
            patch("app.delivery.service.get_provider", return_value=provider),
            patch("app.delivery.tasks.claim_evolution_credential"),
        ):
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))
            with SessionLocal() as db:
                message = db.scalar(
                    select(Message).where(
                        Message.id == message_id,
                        Message.tenant_id == self.tenant_a.tenant_id,
                    )
                )
                delivery = db.scalar(
                    select(MessageDelivery).where(
                        MessageDelivery.id == delivery_id,
                        MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                    )
                )
                self.assertEqual(message.status, MessageStatus.PENDING)
                self.assertIsNone(message.error)
                self.assertEqual(message.attempt_count, 1)
                self.assertEqual(delivery.status, "retry_wait")
            self._make_due(delivery_id)
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(provider.calls, [str(message_id), str(message_id)])
        with SessionLocal() as db:
            message = db.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(message.status, MessageStatus.SENT)
            self.assertEqual(message.attempt_count, 2)

    def test_ambiguous_failure_does_not_retry_automatically(self) -> None:
        self._assign()
        message_id, delivery_id = self._create_message("Falha ambígua")
        provider = SequenceProvider(
            [
                SendResult(
                    success=False,
                    error="Resposta do provider ficou incerta",
                    retryable=False,
                )
            ]
        )
        with (
            patch("app.delivery.service.get_provider", return_value=provider),
            patch("app.delivery.tasks.claim_evolution_credential"),
        ):
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(provider.calls, [str(message_id)])
        with SessionLocal() as db:
            message = db.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.tenant_id == self.tenant_a.tenant_id,
                )
            )
            delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(message.status, MessageStatus.FAILED)
            self.assertEqual(delivery.status, "failed")

        retry = self.client.post(
            f"/api/v1/conversations/{self.tenant_a.conversation_id}/messages/{message_id}/retry",
            headers=self.headers_a,
        )
        self.assertEqual(retry.status_code, 202, retry.text)
        self.assertEqual(retry.json()["status"], "pending")
        with SessionLocal() as db:
            delivery = db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.id == delivery_id,
                    MessageDelivery.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(delivery.status, "queued")
            self.assertEqual(delivery.attempt_count, 0)
            self.assertIsNone(delivery.last_error)

        confirmed_provider = SequenceProvider(
            [
                SendResult(
                    success=True,
                    provider_message_id="manual-retry-confirmed",
                    status=MessageStatus.SENT,
                )
            ]
        )
        with (
            patch(
                "app.delivery.service.get_provider",
                return_value=confirmed_provider,
            ),
            patch("app.delivery.tasks.claim_evolution_credential"),
        ):
            run_delivery(str(delivery_id), str(self.tenant_a.tenant_id))
        with SessionLocal() as db:
            message = db.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.tenant_id == self.tenant_a.tenant_id,
                )
            )
            self.assertEqual(message.status, MessageStatus.SENT)
            self.assertEqual(message.attempt_count, 2)
            self.assertEqual(
                message.provider_message_id,
                "manual-retry-confirmed",
            )

    def test_newer_message_waits_for_the_earlier_message(self) -> None:
        self._assign()
        first_id, first_delivery_id = self._create_message("Primeira")
        second_id, second_delivery_id = self._create_message("Segunda")
        provider = SequenceProvider(
            [
                SendResult(
                    success=True,
                    provider_message_id="ordered-1",
                    status=MessageStatus.SENT,
                ),
                SendResult(
                    success=True,
                    provider_message_id="ordered-2",
                    status=MessageStatus.SENT,
                ),
            ]
        )
        with (
            patch("app.delivery.service.get_provider", return_value=provider),
            patch("app.delivery.tasks.claim_evolution_credential"),
        ):
            run_delivery(str(second_delivery_id), str(self.tenant_a.tenant_id))
            self.assertEqual(provider.calls, [])
            run_delivery(str(first_delivery_id), str(self.tenant_a.tenant_id))
            self._make_due(second_delivery_id)
            run_delivery(str(second_delivery_id), str(self.tenant_a.tenant_id))

        self.assertEqual(provider.calls, [str(first_id), str(second_id)])
