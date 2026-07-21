"""Notification service and WebSocket broadcasting package."""

__all__ = [
    "Notification",
    "NotificationBroadcaster",
    "NotificationService",
    "NotificationWSManager",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependency at module load time."""
    _lazy = {
        "Notification": ("packages.notification.notification_service", "Notification"),
        "NotificationService": ("packages.notification.notification_service", "NotificationService"),
        "NotificationWSManager": ("packages.notification.notification_ws_manager", "NotificationWSManager"),
        "NotificationBroadcaster": ("packages.notification.ws_broadcaster", "NotificationBroadcaster"),
    }
    if name in _lazy:
        import importlib
        mod_path, attr = _lazy[name]
        return getattr(importlib.import_module(mod_path), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
