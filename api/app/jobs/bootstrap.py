import argparse

from sqlalchemy import select

from app.database import SessionLocal, load_all_models
from app.security import hash_password
from app.tenants.models import Tenant
from app.users.models import TenantUser, User


def bootstrap(tenant_name: str, tenant_slug: str, email: str, name: str, password: str) -> None:
    load_all_models()
    with SessionLocal() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            tenant = Tenant(name=tenant_name, slug=tenant_slug)
            db.add(tenant)
            db.flush()
        user = db.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            user = User(email=email.lower(), name=name, password_hash=hash_password(password))
            db.add(user)
            db.flush()
        membership = db.scalar(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant.id, TenantUser.user_id == user.id
            )
        )
        if membership is None:
            db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role="admin"))
        db.commit()
        print(f"Bootstrap concluído para tenant={tenant.slug} user={user.email}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cria o primeiro tenant e administrador")
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    bootstrap(args.tenant_name, args.tenant_slug, args.email, args.name, args.password)
