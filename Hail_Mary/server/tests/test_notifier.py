"""Red-Green-Refactor: M9 Notification Service.

This environment has no real Web Push demo infrastructure (no browser has
registered a real push subscription with real VAPID keys served to it, per
문서/제안서_백엔드추가.md 4.4.1's "Web Push (데모)" note and the task's explicit
instruction not to fake a "sent" result). What IS real and tested here:
  - VAPID keypair generation (real EC crypto, py_vapid).
  - WebPushChannel.send() makes a REAL HTTP attempt via pywebpush against a
    subscription endpoint; since no real push service is registered to
    receive it, the attempt genuinely fails and that failure -- not a faked
    success -- is what gets logged.
"""
import base64
import os

from Hail_Mary.server.core.notifier import (
    WebPushChannel,
    generate_vapid_keypair,
    send_anomaly_notifications,
)
from Hail_Mary.server.db.connection import open_database


def _fake_but_well_formed_subscription():
    # A syntactically valid push subscription (real EC point for p256dh, real
    # random bytes for auth) pointing at an endpoint no real push service is
    # listening on -- so the send is a genuine network attempt, not a stub.
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    client_keys = Vapid02()
    client_keys.generate_keys()
    pub_bytes = client_keys.public_key.public_bytes(
        encoding=serialization.Encoding.X962, format=serialization.PublicFormat.UncompressedPoint,
    )
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/hail-mary-no-such-subscription",
        "keys": {
            "p256dh": base64.urlsafe_b64encode(pub_bytes).decode().rstrip("="),
            "auth": base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("="),
        },
    }


def test_generate_vapid_keypair_returns_distinct_real_keys():
    private_pem_1, public_b64_1 = generate_vapid_keypair()
    private_pem_2, public_b64_2 = generate_vapid_keypair()

    assert b"PRIVATE KEY" in private_pem_1
    assert private_pem_1 != private_pem_2
    assert public_b64_1 != public_b64_2
    assert len(public_b64_1) > 60  # base64url of a 65-byte uncompressed EC point


def test_web_push_channel_send_honestly_reports_failure_without_real_infra():
    private_pem, _ = generate_vapid_keypair()
    channel = WebPushChannel(vapid_private_key_pem=private_pem, vapid_claims={"sub": "mailto:demo@hail-mary.example"})

    result = channel.send(_fake_but_well_formed_subscription(), title="Anomaly", body="test", timeout=5)

    assert result["status"] == "failed"
    assert result["error"]  # a real exception message, not empty/fabricated


def test_send_anomaly_notifications_logs_the_real_outcome(tmp_path):
    conn = open_database(tmp_path / "hail_mary.db")
    private_pem, _ = generate_vapid_keypair()
    channel = WebPushChannel(vapid_private_key_pem=private_pem, vapid_claims={"sub": "mailto:demo@hail-mary.example"})
    event = {"event_id": "e1", "zone_id": "hall_main", "severity": "high"}

    results = send_anomaly_notifications(
        conn, channel, event, subscriptions=[_fake_but_well_formed_subscription()], timeout=5,
    )

    assert len(results) == 1
    assert results[0]["status"] == "failed"  # honest: no real subscriber exists

    logged = conn.execute("SELECT * FROM notification_log WHERE event_id='e1'").fetchone()
    assert logged is not None
    assert logged["channel"] == "web_push"
    assert logged["status"] == "failed"
    conn.close()
