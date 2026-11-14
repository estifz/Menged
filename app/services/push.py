"""Firebase Cloud Messaging for the mobile app (later).

A no-op until `FIREBASE_CREDENTIALS_FILE` points at a service-account JSON and
the optional `firebase-admin` package is installed. The app always also pulls
messages from `GET /v1/trips/{id}/messages`, so push only wakes it faster.
"""

import asyncio
import logging

from app.config import get_settings

log = logging.getLogger(__name__)
_app = None


def _init():
    global _app
    if _app is not None:
        return _app
    path = get_settings().firebase_credentials_file
    if not path:
        return None
    try:
        import firebase_admin  # type: ignore
        from firebase_admin import credentials  # type: ignore

        _app = firebase_admin.initialize_app(credentials.Certificate(path))
    except Exception as e:
        log.warning("FCM disabled: %s", e)
        _app = False
    return _app


async def send(device_token: str | None, title: str, body: str, data: dict[str, str]) -> bool:
    if not device_token or not _init():
        return False
    try:
        from firebase_admin import messaging  # type: ignore

        msg = messaging.Message(
            token=device_token,
            notification=messaging.Notification(title=title, body=body),
            data=data,
        )
        await asyncio.to_thread(messaging.send, msg)
        return True
    except Exception as e:
        log.warning("FCM send failed: %s", e)
        return False
