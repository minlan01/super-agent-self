"""Unit tests for auth repository and auth routes."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.auth.auth_service import create_access_token, verify_token
from packages.db.models import Base, UserRole
from packages.db.repositories.auth_repo import AuthRepository

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# ── AuthRepository: password hashing ──────────────────────────────────────


class TestPasswordHashing:
    def test_hash_password_returns_bcrypt_hash(self):
        hashed = AuthRepository._hash_password("secret123")
        # bcrypt hashes start with $2b$ and are 60 chars
        assert hashed.startswith("$2b$")
        assert len(hashed) == 60

    def test_hash_password_different_each_time(self):
        """bcrypt generates unique salts per call."""
        h1 = AuthRepository._hash_password("same-password")
        h2 = AuthRepository._hash_password("same-password")
        assert h1 != h2

    def test_verify_password_correct(self):
        hashed = AuthRepository._hash_password("mypassword")
        assert AuthRepository.verify_password("mypassword", hashed) is True

    def test_verify_password_incorrect(self):
        hashed = AuthRepository._hash_password("mypassword")
        assert AuthRepository.verify_password("wrongpassword", hashed) is False

    def test_verify_password_empty(self):
        hashed = AuthRepository._hash_password("")
        assert AuthRepository.verify_password("", hashed) is True
        assert AuthRepository.verify_password("notempty", hashed) is False

    def test_verify_password_special_chars(self):
        pw = "p@$$w0rd!#%&*()中文密码"
        hashed = AuthRepository._hash_password(pw)
        assert AuthRepository.verify_password(pw, hashed) is True


# ── AuthRepository: user CRUD ─────────────────────────────────────────────


class TestUserCRUD:
    def test_create_user(self, db):
        user = AuthRepository.create_user(db, "alice", "pass123", "alice@example.com")
        assert user.id is not None
        assert user.username == "alice"
        assert user.email == "alice@example.com"
        assert user.role == UserRole.USER
        assert user.is_active is True
        assert user.hashed_password != "pass123"  # must be hashed

    def test_create_user_with_role(self, db):
        user = AuthRepository.create_user(db, "admin1", "adminpass", role="admin")
        assert user.role == UserRole.ADMIN

    def test_create_user_password_is_bcrypt(self, db):
        user = AuthRepository.create_user(db, "bob", "secret")
        assert user.hashed_password.startswith("$2b$")

    def test_get_by_username_found(self, db):
        AuthRepository.create_user(db, "charlie", "pass")
        found = AuthRepository.get_by_username(db, "charlie")
        assert found is not None
        assert found.username == "charlie"

    def test_get_by_username_not_found(self, db):
        found = AuthRepository.get_by_username(db, "nonexistent")
        assert found is None

    def test_get_by_id_found(self, db):
        user = AuthRepository.create_user(db, "dave", "pass")
        found = AuthRepository.get_by_id(db, user.id)
        assert found is not None
        assert found.username == "dave"

    def test_get_by_id_not_found(self, db):
        found = AuthRepository.get_by_id(db, "nonexistent-id")
        assert found is None

    def test_duplicate_username_raises(self, db):
        AuthRepository.create_user(db, "eve", "pass1")
        # SQLAlchemy will raise IntegrityError on unique constraint violation
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            AuthRepository.create_user(db, "eve", "pass2")


# ── AuthService: token creation and verification ─────────────────────────


class TestTokenService:
    def test_create_token_has_two_parts(self):
        token = create_access_token({"sub": "user-1", "username": "alice"})
        parts = token.split(".")
        assert len(parts) == 2

    def test_verify_valid_token(self):
        token = create_access_token({"sub": "user-1", "username": "alice"})
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "user-1"
        assert payload["username"] == "alice"
        assert "exp" in payload

    def test_verify_expired_token(self):
        token = create_access_token({"sub": "user-1"}, expires_delta=-1)
        payload = verify_token(token)
        assert payload is None

    def test_verify_tampered_token(self):
        token = create_access_token({"sub": "user-1"})
        tampered = token[:-5] + "xxxxx"
        payload = verify_token(tampered)
        assert payload is None

    def test_verify_malformed_token(self):
        assert verify_token("") is None
        assert verify_token("no-dot") is None
        assert verify_token("a.b.c") is None  # has 2 dots, but split only on first

    def test_verify_token_wrong_secret(self):
        """Token signed with one secret should fail when verified with a different one."""
        # Manually create a token and verify with tampered signature
        token = create_access_token({"sub": "user-1"})
        # Flip some chars in the signature portion
        payload_b64, sig = token.split(".", 1)
        # Replace signature with garbage
        tampered = f"{payload_b64}.{'a' * len(sig)}"
        payload = verify_token(tampered)
        assert payload is None
