import subprocess

import pytest

from squint import auth
from squint.auth import KeychainError, SessionSigner, password_matches, read_keychain_password
from squint.ratelimit import SlidingWindowLimiter


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_sliding_window():
    clock = Clock()
    lim = SlidingWindowLimiter(3, 3600, clock=clock)
    for _ in range(3):
        assert lim.retry_after("a") == 0
        lim.hit("a")
    assert lim.retry_after("a") == 3600
    assert lim.retry_after("b") == 0
    clock.t += 1800.4
    assert lim.retry_after("a") == 1800  # ceil of the remaining 1799.6 s
    clock.t += 1800
    assert lim.retry_after("a") == 0
    lim.hit("a")
    lim.reset("a")
    assert lim.retry_after("a") == 0


def test_session_signer():
    clock = Clock(1_700_000_000)
    s = SessionSigner(ttl_s=60, clock=clock)
    tok = s.issue()
    assert s.verify(tok)
    assert not s.verify(None) and not s.verify("") and not s.verify("abc") and not s.verify(tok + "x")
    assert not SessionSigner(ttl_s=60, clock=clock).verify(tok)  # another process key
    body, sig = tok.split(".")
    assert not s.verify(body[:-1] + ("A" if body[-1] != "A" else "B") + "." + sig)
    clock.t += 61
    assert not s.verify(tok)


def test_password_matches():
    assert password_matches("pässword", "pässword")
    assert not password_matches("password", "pässword")
    assert not password_matches("", "x")


def test_keychain_missing_item_means_no_password():
    # read-only lookup of an item that does not exist
    assert read_keychain_password("squint-test-item-that-does-not-exist-7f3a") is None


def test_keychain_reads_and_fails_closed(monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        service = argv[3]
        if service == "ok":
            return subprocess.CompletedProcess(argv, 0, "s3cret\n", "")
        if service == "missing":
            return subprocess.CompletedProcess(argv, 44, "", "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain.")
        return subprocess.CompletedProcess(argv, 51, "", "User interaction is not allowed.")

    monkeypatch.setattr(auth.subprocess, "run", fake_run)
    assert read_keychain_password("ok") == "s3cret"
    assert read_keychain_password("missing") is None
    with pytest.raises(KeychainError):
        read_keychain_password("locked")
    assert all(c[:2] == ["/usr/bin/security", "find-generic-password"] and c[-1] == "-w" for c in calls)
