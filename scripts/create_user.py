import getpass
import sys

from sqlmodel import Session, select

from app.auth import hash_password
from app.db import engine
from app.models import User
from app.seed import seed_user_if_empty


class UsernameTakenError(Exception):
    pass


def create_user(session: Session, username: str, password: str) -> User:
    existing = session.exec(select(User).where(User.username == username)).first()
    if existing is not None:
        raise UsernameTakenError(f"username '{username}' already exists")

    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)

    seed_user_if_empty(session, user.id)
    return user


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.create_user <username>", file=sys.stderr)
        sys.exit(1)

    username = sys.argv[1]
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(1)

    with Session(engine) as session:
        try:
            user = create_user(session, username, password)
        except UsernameTakenError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        print(f"Created user '{user.username}' ({user.id}).")


if __name__ == "__main__":
    main()
