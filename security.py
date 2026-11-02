"""
Security primitives: the client-compatible password proof, session tokens,
owner-passcode verification and a tiny sliding-window rate limiter.

The browser app proves a password as ``sha256(salt + ':' + password)`` (see
``pwHash`` in the embedded front end).  The server stores exactly that proof
when a profile is published, so it can verify sign-ins *and* stay compatible
with the device vault — no second hashing scheme to keep in sync.
"""

import hashlib
import secrets
import threading
import time
from collections import deque


def sha256_hex(text):
    """Lowercase hex SHA-256 of a str (UTF-8)."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def client_pw_hash(salt, password):
    """The proof format shared with the browser vault: sha256(salt + ':' + pw)."""
    return sha256_hex(str(salt) + ":" + str(password))


def new_token():
    """256 bits of URL-safe randomness for a session token."""
    return secrets.token_urlsafe(32)


def verify_owner(cfg, passcode):
    """True if *passcode* matches any build-time owner proof."""
    if not passcode:
        return False
    for proof in cfg.OWNER_PROOFS.values():
        if client_pw_hash(proof.get("salt", ""), passcode) == proof.get("hash"):
            return True
    return False


def verify_profile_password(proof, password):
    """Check a {salt, hash} profile proof against a candidate password."""
    if not proof or not proof.get("salt") or not proof.get("hash"):
        return False
    return client_pw_hash(proof["salt"], password) == proof["hash"]


class RateLimiter:
    """Sliding-window limiter — *limit* events per 60 s per key (usually IP)."""

    def __init__(self, limit):
        self.limit = limit
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key):
        now = time.time()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True
