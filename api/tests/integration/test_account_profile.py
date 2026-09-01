from sqlalchemy import select

from app.common.audit_models import AuditLog
from app.database import SessionLocal
from app.security import verify_password
from app.users.models import User

from .base import TEST_PASSWORD, PostgresIntegrationTestCase


class AccountProfileTest(PostgresIntegrationTestCase):
    def test_authenticated_user_updates_own_name_and_password(self) -> None:
        wrong_password = self.client.patch(
            "/api/v1/auth/me",
            headers=self.headers_a,
            json={
                "name": "Nome não persistido",
                "current_password": "senha-incorreta",
                "new_password": "nova-senha-segura",
            },
        )
        self.assertEqual(wrong_password.status_code, 400, wrong_password.text)

        response = self.client.patch(
            "/api/v1/auth/me",
            headers=self.headers_a,
            json={
                "name": "  Agente Atualizado  ",
                "current_password": TEST_PASSWORD,
                "new_password": "nova-senha-segura",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "Agente Atualizado")
        self.assertEqual(response.json()["tenant_id"], str(self.tenant_a.tenant_id))

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.id == self.tenant_a.user_id))
            self.assertIsNotNone(user)
            assert user is not None
            self.assertEqual(user.name, "Agente Atualizado")
            self.assertTrue(verify_password("nova-senha-segura", user.password_hash))
            self.assertFalse(verify_password(TEST_PASSWORD, user.password_hash))

            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.tenant_id == self.tenant_a.tenant_id,
                    AuditLog.user_id == self.tenant_a.user_id,
                    AuditLog.action == "profile.updated",
                )
            )
            self.assertIsNotNone(audit)
            assert audit is not None
            self.assertEqual(audit.metadata_["fields"], ["name", "password"])

    def test_profile_update_rejects_empty_payload(self) -> None:
        response = self.client.patch(
            "/api/v1/auth/me",
            headers=self.headers_a,
            json={},
        )

        self.assertEqual(response.status_code, 422, response.text)
