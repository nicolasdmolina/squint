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


def test_session_signer_rejects_non_ascii_junk():
    s = SessionSigner(ttl_s=60)
    tok = s.issue()
    body, sig = tok.split(".")
    for junk in (body + ".\xe9", body + "." + sig[:-1] + "\xe9", "\xe9.\xe9", "e30.éé", ".", body + ".", 5, b"x.y"):
        assert s.verify(junk) is False


def test_password_matches_lone_surrogates():
    assert not password_matches("\ud83d", "pw")
    assert password_matches("\ud83d", "\ud83d")  # never raises, even with odd stored values


@pytest.mark.parametrize("addr,key", [
    ("203.0.113.5", "203.0.113.5"),
    ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),
    ("2001:DB8:1:2::abcd", "2001:db8:1:2::/64"),
    ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
    ("::ffff:203.0.113.5", "203.0.113.5"),
    ("testclient", "testclient"),
    ("", "unknown"),
    ("x" * 100, "x" * 64),
])
def test_rate_key(addr, key):
    from squint.app import rate_key
    assert rate_key(addr) == key


def test_require_password_setting(tmp_path, monkeypatch):
    from conftest import SERVER_DIR
    from squint.config import load_settings

    monkeypatch.delenv("SQUINT_REQUIRE_PASSWORD", raising=False)
    monkeypatch.setenv("SQUINT_PROFILE", "qwen2.5-0.5b-standin")
    toml = (SERVER_DIR / "squint.toml").read_text()
    assert "require_password = false" in toml
    assert load_settings(SERVER_DIR / "squint.toml").require_password is False
    strict = tmp_path / "squint.toml"
    strict.write_text(toml.replace("require_password = false", "require_password = true"))
    assert load_settings(strict).require_password is True
    for value, want in (("1", True), ("true", True), ("0", False), ("", False)):
        monkeypatch.setenv("SQUINT_REQUIRE_PASSWORD", value)
        assert load_settings(SERVER_DIR / "squint.toml").require_password is want
    assert load_settings(strict).require_password is False  # the environment wins ("" -> off)
    assert load_settings(SERVER_DIR / "squint.toml").limits.extracts_per_hour == 30
