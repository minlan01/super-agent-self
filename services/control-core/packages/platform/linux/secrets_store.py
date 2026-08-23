"""Linux SecretStore — Secret Service (libsecret) via DBus (P5).

Spec §4.4: Linux uses the Secret Service (gnome-keyring / kwallet behind
the freedesktop spec). Fail closed: without a running Secret Service we
raise SecretAccessError — we NEVER fall back to plaintext files.
"""

from __future__ import annotations

from typing import Any

import structlog

from packages.platform.shared.contracts import SecretRef, SecretStore
from packages.platform.shared.errors import SecretAccessError

logger = structlog.get_logger()


def _collection_path(ref: SecretRef) -> str:
    return f"zcode/{ref.namespace}"


class SecretServiceStore(SecretStore):
    """Secret Service backed store (requires `secretstorage` package).

    The DB only ever holds SecretRef metadata; plaintext lives in the
    user's keyring, which is locked with the login password.
    """

    def __init__(self) -> None:
        try:
            import secretstorage  # noqa: F401
        except ImportError as exc:
            raise SecretAccessError(
                "python package 'secretstorage' is required on Linux "
                "(sudo apt install python3-secretstorage)"
            ) from exc
        self._bus: Any = None

    def _connect(self) -> Any:
        import secretstorage
        if self._bus is None:
            self._bus = secretstorage.dbus_init()
        return self._bus

    def _collection(self):
        import secretstorage
        bus = self._connect()
        collection = secretstorage.get_default_collection(bus)
        if collection.is_locked():
            unlocked = collection.unlock()
            if not unlocked:
                raise SecretAccessError(
                    "Secret Service collection is locked and unlock was "
                    "denied — refusing to fall back to plaintext (fail closed)"
                )
        return collection

    async def store(self, ref: SecretRef, plaintext: bytes) -> None:
        try:
            collection = self._collection()
            label = f"zcode:{ref.namespace}:{ref.key_id}"
            attrs = {
                "namespace": ref.namespace,
                "key_id": ref.key_id,
                "service": "zcode-control-core",
            }
            # Replace semantics: delete any previous item with same attrs.
            for item in collection.search_items(attrs):
                item.delete()
            collection.create_item(label, attrs, plaintext, replace=True)
            logger.info("secret stored: ns=%s key=%s", ref.namespace, ref.key_id)
        except SecretAccessError:
            raise
        except Exception as exc:
            raise SecretAccessError(f"failed to store secret: {exc}") from exc

    async def load(self, ref: SecretRef) -> bytes:
        try:
            collection = self._collection()
            attrs = {
                "namespace": ref.namespace,
                "key_id": ref.key_id,
                "service": "zcode-control-core",
            }
            items = list(collection.search_items(attrs))
            if not items:
                raise SecretAccessError(
                    f"secret not found: ns={ref.namespace} key={ref.key_id}"
                )
            item = items[0]
            if item.is_locked():
                item.unlock()
            return item.get_secret()
        except SecretAccessError:
            raise
        except Exception as exc:
            raise SecretAccessError(f"failed to load secret: {exc}") from exc

    async def list_refs(self, namespace: str) -> list[SecretRef]:
        try:
            collection = self._collection()
            refs = []
            for item in collection.search_items({
                "namespace": namespace, "service": "zcode-control-core",
            }):
                attrs = item.get_attributes()
                refs.append(SecretRef(
                    namespace=namespace,
                    key_id=str(attrs.get("key_id", "")),
                ))
            return refs
        except SecretAccessError:
            raise
        except Exception as exc:
            raise SecretAccessError(f"failed to list secrets: {exc}") from exc

    async def rotate(self, ref: SecretRef, new_plaintext: bytes) -> None:
        """Replace the stored secret atomically (store is replace-on-write)."""
        await self.store(ref, new_plaintext)

    async def delete(self, ref: SecretRef) -> None:
        try:
            collection = self._collection()
            attrs = {
                "namespace": ref.namespace,
                "key_id": ref.key_id,
                "service": "zcode-control-core",
            }
            found = False
            for item in collection.search_items(attrs):
                item.delete()
                found = True
            if not found:
                raise SecretAccessError(
                    f"secret not found: ns={ref.namespace} key={ref.key_id}"
                )
        except SecretAccessError:
            raise
        except Exception as exc:
            raise SecretAccessError(f"failed to delete secret: {exc}") from exc
