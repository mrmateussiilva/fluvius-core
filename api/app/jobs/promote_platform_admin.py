import argparse

from sqlalchemy import select

from app.database import SessionLocal, load_all_models
from app.users.models import User


def promote(email: str) -> None:
    load_all_models()
    normalized_email = email.strip().lower()
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(
                User.email == normalized_email,
                User.is_active.is_(True),
            )
        )
        if user is None:
            raise SystemExit(f"Usuário ativo não encontrado: {normalized_email}")
        if user.is_platform_admin:
            print(f"Usuário já é administrador da plataforma: {normalized_email}")
            return
        user.is_platform_admin = True
        db.commit()
        print(f"Administrador da plataforma promovido: {normalized_email}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Promove um usuário existente a administrador da plataforma"
    )
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    promote(args.email)
