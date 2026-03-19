"""
[web/create_admin.py] 관리자 계정 생성 스크립트
──────────────────────────────────────────────────────
역할: 최초 1회 실행 — admin 계정 생성
실행:
  cd web && python3.11 create_admin.py
  또는 커스텀 계정:
  python3.11 create_admin.py --username myid --email me@example.com --password mypassword
수정 이력:
  2026-03-19  최초 작성
──────────────────────────────────────────────────────
"""

import argparse
from api.database import SessionLocal, engine, Base
from api.models import user as user_module, stock  # noqa — 테이블 생성 보장
from api.models.user import User, UserRole
from api.auth import hash_password

Base.metadata.create_all(bind=engine)

def create_admin(username: str, email: str, password: str) -> None:
    db = SessionLocal()
    try:
        exists = db.query(User).filter(User.username == username).first()
        if exists:
            print(f"[!] '{username}' 계정이 이미 존재합니다.")
            return

        admin = User(
            username=username,
            email=email,
            hashed_pw=hash_password(password),
            role=UserRole.admin,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"[✓] 관리자 계정 생성 완료: {username} ({email})")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="관리자 계정 생성")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--email",    default="admin@stockplatform.local")
    parser.add_argument("--password", default="admin1234!")
    args = parser.parse_args()

    create_admin(args.username, args.email, args.password)
