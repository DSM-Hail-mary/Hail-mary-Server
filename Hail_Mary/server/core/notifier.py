"""M9 Notification Service (문서/제안서_백엔드추가.md 4.4.1/4.4.2): sends an
anomaly alert to a subscribed admin channel and logs the real outcome.

`NotificationChannel` is the abstraction named in the spec. Only
WebPushChannel is implemented (1차 Web Push per the doc; FCM is an explicit
future extension, out of scope here).

Important limitation, stated plainly rather than hidden: this environment has
no real demo Web Push infrastructure -- no browser has actually registered a
push subscription against real VAPID keys served by this backend. So every
send this module makes is a genuine HTTP attempt via pywebpush against
whatever subscription it's given; without a real subscriber there is nothing
to receive it, and that failure is what gets reported/logged. Nothing here
ever reports "sent" unless the push service genuinely accepted the request.
"""
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional


def generate_vapid_keypair():
    """Generate a real VAPID (P-256 EC) keypair for Web Push, using py_vapid.
    Returns (private_key_pem: bytes, public_key_urlsafe_b64: str)."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    vapid = Vapid02()
    vapid.generate_keys()
    private_pem = vapid.private_pem()
    public_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962, format=serialization.PublicFormat.UncompressedPoint,
    )
    import base64
    public_b64 = base64.urlsafe_b64encode(public_bytes).decode().rstrip("=")
    return private_pem, public_b64


class NotificationChannel(ABC):
    name: str

    @abstractmethod
    def send(self, subscription_info: dict, title: str, body: str, timeout: float = 5) -> Dict[str, Optional[str]]:
        """Attempt delivery. Returns {"status": "sent"|"failed", "error": str|None}.
        Must never return "sent" unless delivery actually succeeded."""
        raise NotImplementedError


class WebPushChannel(NotificationChannel):
    name = "web_push"

    def __init__(self, vapid_private_key_pem, vapid_claims: dict):
        from py_vapid import Vapid02

        # pywebpush accepts a py_vapid Vapid instance directly (it treats a
        # plain str as either a file path or a raw key string, neither of
        # which matches a full PEM blob) -- reconstruct it once here.
        self._vapid = Vapid02.from_pem(vapid_private_key_pem)
        self._vapid_claims = vapid_claims

    def send(self, subscription_info: dict, title: str, body: str, timeout: float = 5) -> Dict[str, Optional[str]]:
        from pywebpush import WebPushException, webpush

        try:
            response = webpush(
                subscription_info=subscription_info,
                data=f"{title}\n{body}",
                vapid_private_key=self._vapid,
                vapid_claims=dict(self._vapid_claims),
                timeout=timeout,
            )
            if hasattr(response, "status_code") and not (200 <= response.status_code < 300):
                return {"status": "failed", "error": f"push service returned HTTP {response.status_code}"}
            return {"status": "sent", "error": None}
        except WebPushException as exc:
            return {"status": "failed", "error": str(exc)}
        except Exception as exc:  # real network/crypto errors (ConnectionError, ValueError, ...)
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def send_anomaly_notifications(
    conn: sqlite3.Connection,
    channel: NotificationChannel,
    event: dict,
    subscriptions: List[dict],
    timeout: float = 5,
) -> List[Dict[str, Optional[str]]]:
    """Send (attempt) an alert for `event` to every subscription and persist
    the real outcome of each attempt to notification_log."""
    title = f"Hail-Mary anomaly: {event.get('severity', 'unknown')}"
    body = f"zone={event.get('zone_id')} event_id={event.get('event_id')}"

    results = []
    for subscription in subscriptions:
        result = channel.send(subscription, title=title, body=body, timeout=timeout)
        sent_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO notification_log (event_id, channel, sent_at, status) VALUES (?, ?, ?, ?)",
            (event["event_id"], channel.name, sent_at, result["status"]),
        )
        results.append(result)
    conn.commit()
    return results
