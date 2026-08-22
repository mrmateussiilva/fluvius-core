from uuid import UUID

from sqlalchemy import select

from app.common.audit_models import AuditLog
from app.database import SessionLocal
from app.tenants.models import Tenant
from app.users.models import TenantUser, User

from .base import TEST_PASSWORD, PostgresIntegrationTestCase


class PlatformAdminTest(PostgresIntegrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        with SessionLocal() as db:
            platform_user = db.scalar(select(User).where(User.id == self.tenant_a.user_id))
            platform_user.is_platform_admin = True
            db.commit()

    def test_platform_routes_require_global_authorization(self) -> None:
        denied = self.client.get(
            "/api/v1/platform/tenants",
            headers=self.headers_b,
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        allowed = self.client.get(
            "/api/v1/platform/tenants",
            headers=self.headers_a,
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(
            {tenant["id"] for tenant in allowed.json()},
            {
                str(self.tenant_a.tenant_id),
                str(self.tenant_b.tenant_id),
            },
        )
        tenant_a = next(
            tenant for tenant in allowed.json() if tenant["id"] == str(self.tenant_a.tenant_id)
        )
        self.assertEqual(tenant_a["user_count"], 1)
        self.assertEqual(tenant_a["channel_count"], 1)
        self.assertEqual(tenant_a["connected_channel_count"], 1)

    def test_creates_company_with_initial_admin_and_audit(self) -> None:
        created = self.client.post(
            "/api/v1/platform/tenants",
            headers=self.headers_a,
            json={
                "name": "Empresa Nova",
                "slug": "empresa-nova",
                "admin_name": "Admin Empresa Nova",
                "admin_email": "admin@empresa-nova.example",
                "admin_password": "senha-inicial-segura",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        tenant_id = UUID(created.json()["id"])
        self.assertEqual(created.json()["slug"], "empresa-nova")
        self.assertEqual(created.json()["user_count"], 1)
        self.assertEqual(created.json()["channel_count"], 0)

        detail = self.client.get(
            f"/api/v1/platform/tenants/{tenant_id}",
            headers=self.headers_a,
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(
            detail.json()["users"][0]["email"],
            "admin@empresa-nova.example",
        )
        self.assertEqual(detail.json()["users"][0]["role"], "admin")
        self.assertEqual(detail.json()["channels"], [])

        login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@empresa-nova.example",
                "password": "senha-inicial-segura",
                "tenant_id": str(tenant_id),
            },
        )
        self.assertEqual(login.status_code, 200, login.text)

        duplicate = self.client.post(
            "/api/v1/platform/tenants",
            headers=self.headers_a,
            json={
                "name": "Duplicada",
                "slug": "empresa-nova",
                "admin_name": "Outro Admin",
                "admin_email": "outro@example.com",
                "admin_password": "outra-senha-segura",
            },
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        active_email = self.client.post(
            "/api/v1/platform/tenants",
            headers=self.headers_a,
            json={
                "name": "E-mail Duplicado",
                "slug": "email-duplicado",
                "admin_name": "Admin Existente",
                "admin_email": self.tenant_b.email,
                "admin_password": "outra-senha-segura",
            },
        )
        self.assertEqual(active_email.status_code, 409, active_email.text)

        with SessionLocal() as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.action == "platform.tenant_created",
                    AuditLog.user_id == self.tenant_a.user_id,
                )
            )
            self.assertIsNotNone(audit)

    def test_company_login_link_forces_the_selected_tenant(self) -> None:
        identity = self.client.get("/api/v1/auth/tenant-login/tenant-a")
        self.assertEqual(identity.status_code, 200, identity.text)
        self.assertEqual(
            identity.json(),
            {"name": "Tenant A", "slug": "tenant-a"},
        )

        login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.tenant_a.email,
                "password": TEST_PASSWORD,
                "tenant_slug": "tenant-a",
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        me = self.client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {login.json()['access_token']}",
            },
        )
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["tenant_id"], str(self.tenant_a.tenant_id))

        wrong_company = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.tenant_a.email,
                "password": TEST_PASSWORD,
                "tenant_slug": "tenant-b",
            },
        )
        self.assertEqual(wrong_company.status_code, 403, wrong_company.text)

        ambiguous = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.tenant_a.email,
                "password": TEST_PASSWORD,
                "tenant_id": str(self.tenant_a.tenant_id),
                "tenant_slug": "tenant-a",
            },
        )
        self.assertEqual(ambiguous.status_code, 422, ambiguous.text)

    def test_reuses_user_only_after_all_memberships_are_inactive(self) -> None:
        with SessionLocal() as db:
            membership = db.scalar(
                select(TenantUser).where(
                    TenantUser.tenant_id == self.tenant_b.tenant_id,
                    TenantUser.user_id == self.tenant_b.user_id,
                )
            )
            membership.is_active = False
            db.commit()

        created = self.client.post(
            "/api/v1/platform/tenants",
            headers=self.headers_a,
            json={
                "name": "Cliente Teste",
                "slug": "cliente-teste",
                "admin_name": "Cliente Reaproveitado",
                "admin_email": self.tenant_b.email,
                "admin_password": "nova-senha-inicial-segura",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)

        login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.tenant_b.email,
                "password": "nova-senha-inicial-segura",
                "tenant_slug": "cliente-teste",
            },
        )
        self.assertEqual(login.status_code, 200, login.text)

        old_company = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.tenant_b.email,
                "password": "nova-senha-inicial-segura",
                "tenant_slug": "tenant-b",
            },
        )
        self.assertEqual(old_company.status_code, 403, old_company.text)

        with SessionLocal() as db:
            users = list(db.scalars(select(User).where(User.email == self.tenant_b.email)))
            new_tenant = db.scalar(select(Tenant).where(Tenant.slug == "cliente-teste"))
            new_membership = db.scalar(
                select(TenantUser).where(
                    TenantUser.tenant_id == new_tenant.id,
                    TenantUser.user_id == self.tenant_b.user_id,
                )
            )
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0].name, "Cliente Reaproveitado")
            self.assertIsNotNone(new_membership)
            self.assertTrue(new_membership.is_active)

    def test_support_access_is_audited_and_protected_from_tenant_admin(self) -> None:
        access = self.client.post(
            f"/api/v1/platform/tenants/{self.tenant_b.tenant_id}/access",
            headers=self.headers_a,
        )
        self.assertEqual(access.status_code, 200, access.text)
        support_headers = {"Authorization": f"Bearer {access.json()['access_token']}"}
        me = self.client.get("/api/v1/auth/me", headers=support_headers)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["tenant_id"], str(self.tenant_b.tenant_id))
        self.assertEqual(me.json()["tenant_name"], "Tenant B")
        self.assertTrue(me.json()["is_platform_admin"])

        memberships = self.client.get(
            "/api/v1/auth/tenants",
            headers=support_headers,
        )
        self.assertEqual(memberships.status_code, 200, memberships.text)
        self.assertEqual(
            {tenant["id"] for tenant in memberships.json()},
            {
                str(self.tenant_a.tenant_id),
                str(self.tenant_b.tenant_id),
            },
        )
        switched_back = self.client.post(
            "/api/v1/auth/switch-tenant",
            headers=support_headers,
            json={"tenant_id": str(self.tenant_a.tenant_id)},
        )
        self.assertEqual(switched_back.status_code, 200, switched_back.text)

        tenant_users = self.client.get(
            "/api/v1/users",
            headers=self.headers_b,
        )
        self.assertEqual(tenant_users.status_code, 200, tenant_users.text)
        support_user = next(
            user for user in tenant_users.json() if user["id"] == str(self.tenant_a.user_id)
        )
        self.assertTrue(support_user["is_platform_admin"])

        tenant_admin_attack = self.client.patch(
            f"/api/v1/users/{self.tenant_a.user_id}",
            headers=self.headers_b,
            json={"password": "senha-controlada-pelo-cliente"},
        )
        self.assertEqual(tenant_admin_attack.status_code, 403)

        with SessionLocal() as db:
            membership = db.scalar(
                select(TenantUser).where(
                    TenantUser.tenant_id == self.tenant_b.tenant_id,
                    TenantUser.user_id == self.tenant_a.user_id,
                )
            )
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.tenant_id == self.tenant_b.tenant_id,
                    AuditLog.action == "platform.support_access",
                    AuditLog.user_id == self.tenant_a.user_id,
                )
            )
            self.assertEqual(membership.role, "admin")
            self.assertTrue(membership.is_active)
            self.assertIsNotNone(audit)

    def test_suspension_invalidates_tenant_sessions(self) -> None:
        current_tenant = self.client.patch(
            f"/api/v1/platform/tenants/{self.tenant_a.tenant_id}",
            headers=self.headers_a,
            json={"is_active": False},
        )
        self.assertEqual(current_tenant.status_code, 409, current_tenant.text)

        suspended = self.client.patch(
            f"/api/v1/platform/tenants/{self.tenant_b.tenant_id}",
            headers=self.headers_a,
            json={"is_active": False},
        )
        self.assertEqual(suspended.status_code, 200, suspended.text)
        self.assertFalse(suspended.json()["is_active"])
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me",
                headers=self.headers_b,
            ).status_code,
            401,
        )
        inactive_login = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": self.tenant_b.email,
                "password": TEST_PASSWORD,
                "tenant_id": str(self.tenant_b.tenant_id),
            },
        )
        self.assertEqual(inactive_login.status_code, 403, inactive_login.text)
        tenant_link = self.client.get("/api/v1/auth/tenant-login/tenant-b")
        self.assertEqual(tenant_link.status_code, 404, tenant_link.text)

        reactivated = self.client.patch(
            f"/api/v1/platform/tenants/{self.tenant_b.tenant_id}",
            headers=self.headers_a,
            json={"is_active": True},
        )
        self.assertEqual(reactivated.status_code, 200, reactivated.text)
        self.assertTrue(reactivated.json()["is_active"])

        with SessionLocal() as db:
            tenant = db.scalar(
                select(Tenant).where(
                    Tenant.id == self.tenant_b.tenant_id,
                )
            )
            self.assertTrue(tenant.is_active)
