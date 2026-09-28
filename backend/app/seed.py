"""Explicit local-only demo setup; reruns never reset existing passwords/data."""
import argparse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import password_hasher
from app.db import engine
from app.models import Membership, Project, Tenant, User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="Create documented local demo credentials")
    args = parser.parse_args()
    if not args.local:
        parser.error("This seeds public demo credentials. Explicitly pass --local for local development only.")
    with Session(engine) as db:
        for suffix, name in [("a", "Flight Operations"), ("b", "Ground Services")]:
            email = f"demo-{suffix}@dataflow.local"
            if db.scalar(select(User).where(User.email == email)):
                print(f"Already exists: {email} (unchanged)")
                continue
            user = User(email=email, name=f"Demo {suffix.upper()}", password_hash=password_hasher.hash("Demo-local-2026!"))
            tenant = Tenant(name=name)
            db.add_all([user, tenant])
            db.flush()
            db.add(Membership(user_id=user.id, tenant_id=tenant.id))
            db.add(Project(tenant_id=tenant.id, name=f"{name} sample", description="로컬 데모 프로젝트"))
            print(f"Created: {email}")
        db.commit()
    print("Local demo password: Demo-local-2026!")


if __name__ == "__main__":
    main()
