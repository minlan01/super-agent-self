"""Repository for User CRUD and password hashing."""

import bcrypt
from sqlalchemy.orm import Session

from packages.db.models import User, UserRole


class AuthRepository:
    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash a password using bcrypt."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a plain password against its bcrypt hash."""
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

    @staticmethod
    def create_user(
        db: Session,
        username: str,
        password: str,
        email: str | None = None,
        role: str = "user",
    ) -> User:
        """Create a new user with a hashed password."""
        hashed = AuthRepository._hash_password(password)
        user = User(
            username=username,
            email=email,
            hashed_password=hashed,
            role=UserRole(role),
        )
        db.add(user)
        db.flush()
        db.refresh(user)
        return user

    @staticmethod
    def get_by_username(db: Session, username: str) -> User | None:
        """Return a user by username, or None if not found."""
        from sqlalchemy import select

        stmt = select(User).where(User.username == username)
        return db.scalar(stmt)

    @staticmethod
    def get_by_id(db: Session, user_id: str) -> User | None:
        """Return a user by id, or None if not found."""
        return db.get(User, user_id)
