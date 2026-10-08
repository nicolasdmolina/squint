"""Shared password (macOS Keychain) and signed session cookies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import subprocess
import time

log = logging.getLogger("squint.auth")

COOKIE_NAME = "squint_session"


class KeychainError(RuntimeError):
    pass


class PasswordMissing(KeychainError):
    """`require_password` is on but no password was found."""


def read_keychain_password(service: str) -> str | None:
    """Read the generic-password item `service`; None when it does not exist.

    Fails closed: any other error (locked keychain, denied access) raises instead of quietly
    running without a password. Never creates an item.
    """
    try:
        proc = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        log.warning("macOS `security` tool not found; running without a password")
        return None
    except subprocess.TimeoutExpired as exc:
        raise KeychainError(f"timed out reading Keychain item {service!r}") from exc
    if proc.returncode == 0:
        pw = proc.stdout.rstrip("\n")
        return pw or None
    if proc.returncode == 44 or "could not be found" in proc.stderr:
        return None
    raise KeychainError(f"could not read Keychain item {service!r} (security exit {proc.returncode})")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SessionSigner:
    """HMAC-SHA256 signed, expiring session tokens. The key is random per process, so a
    restart signs everyone out; nothing about sessions is stored."""

    def __init__(self, ttl_s: int, key: bytes | None = None, clock=time.time):
        self._key = key or secrets.token_bytes(32)
        self.ttl_s = ttl_s
        self._clock = clock

    def _sig(self, payload: bytes) -> str:
        return _b64(hmac.new(self._key, payload, hashlib.sha256).digest())

    def issue(self) -> str:
        now = int(self._clock())
        payload = json.dumps({"iat": now, "exp": now + self.ttl_s, "n": secrets.token_hex(8)},
                             separators=(",", ":")).encode()
        return f"{_b64(payload)}.{self._sig(payload)}"

    def verify(self, token: str | None) -> bool:
        """False for anything that is not a valid, unexpired token (including non-ASCII junk)."""
        try:
            if not isinstance(token, str) or token.count(".") != 1:
                return False
            body, sig = token.split(".")
            payload = _unb64(body)
            if not hmac.compare_digest(sig.encode("utf-8"), self._sig(payload).encode("ascii")):
                return False
            data = json.loads(payload)
            return int(data["exp"]) > self._clock()
        except Exception:
            return False


def password_matches(given: str, expected: str) -> bool:
    # surrogatepass: a lone surrogate from JSON ("\ud83d") never matches and never raises
    return hmac.compare_digest(given.encode("utf-8", "surrogatepass"), expected.encode("utf-8", "surrogatepass"))
