"""Interactive local administrator command; passwords never enter argv or logs."""
import argparse
from getpass import getpass, GetPassWarning
import re
import sys
import warnings

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import password_hasher
from app.db import engine
from app.models import LoginSession, User


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("올바른 이메일 주소를 입력해 주세요.")
    return value


def update_user(db: Session, current_email: str, *, email=None, name=None, password=None) -> bool:
    current_email = normalize_email(current_email)
    email = normalize_email(email) if email is not None else None
    if name is not None:
        name = name.strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("이름은 1~100자로 입력해 주세요.")
    if password is not None and (not 12 <= len(password) <= 256 or not password.strip()):
        raise ValueError("비밀번호는 공백만 사용하지 않고 12~256자로 입력해 주세요.")
    try:
        user = db.scalar(select(User).where(User.email == current_email).with_for_update())
        if user is None:
            raise ValueError("해당 이메일의 계정이 없습니다.")
        changed = False
        if email is not None and email != user.email:
            user.email = email
            changed = True
        if name is not None and name != user.name:
            user.name = name
            changed = True
        if password is not None:
            user.password_hash = password_hasher.hash(password)
            changed = True
        if changed:
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            db.commit()
        else:
            db.rollback()
        return changed
    except IntegrityError:
        db.rollback()
        raise ValueError("이미 사용 중인 이메일입니다. 변경 사항은 저장되지 않았습니다.") from None
    except Exception:
        db.rollback()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="기존 계정의 이메일·이름·비밀번호 변경 (로컬 관리자용)")
    parser.add_argument("--email", help="변경할 계정의 현재 이메일")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("대화형 터미널에서 실행해 주세요. docker compose exec에 -T를 붙이지 마세요.", file=sys.stderr)
        return 1
    try:
        current = normalize_email(args.email or input("현재 로그인 이메일: "))
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.email == current))
            if user is None:
                raise ValueError("해당 이메일의 계정이 없습니다.")
            print(f"대상 계정: {user.email} / {user.name}")
            print("이메일과 이름은 Enter를 누르면 유지됩니다. 취소하려면 Ctrl+C.")
            email = input("새 이메일: ").strip() or None
            name = input("새 이름: ").strip() or None
            password = None
            if input("비밀번호도 변경할까요? [y/N]: ").strip().lower() == "y":
                with warnings.catch_warnings():
                    warnings.simplefilter("error", GetPassWarning)
                    password = getpass("새 비밀번호 (12~256자, 화면에 표시되지 않음): ")
                    confirmation = getpass("새 비밀번호 재입력: ")
                if password != confirmation:
                    raise ValueError("비밀번호가 일치하지 않습니다. 변경 사항은 저장되지 않았습니다.")
            if update_user(db, current, email=email, name=name, password=password):
                print("변경 완료. 기존 로그인 세션을 만료했습니다. 새 계정 정보로 다시 로그인하세요.")
            else:
                print("변경 사항이 없습니다.")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\n취소했습니다. 변경 사항은 저장되지 않았습니다.")
        return 1
    except GetPassWarning:
        print("숨김 입력을 지원하는 터미널에서 다시 실행해 주세요.", file=sys.stderr)
        return 1
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("DB 작업에 실패했습니다. 연결 상태를 확인해 주세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
