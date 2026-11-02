"""
Central configuration for the Syncro server.

Every knob lives here and every value can be overridden with an environment
variable (prefix ``SYNCRO_``), so the same codebase serves a laptop demo, a
LAN party or a small public deployment without code changes.
"""

import os

# Build-time owner passcodes — the same provisioned proofs the original app
# ships in the browser.  Each entry is {ID: {salt, hash}} where
# hash == sha256_hex(salt + ':' + passcode).  The passcodes themselves are
# known only to the project owner; the server uses them to authenticate
# owner operations (removing / restoring an ID, cross-account export).
OWNER_PROOFS = {
    "DEVANSHU": {
        "salt": "splid-owner-DEVANSHU-3f9c2b81d4e6a759",
        "hash": "4263e4212b8a1a50392c2459d3654da7b8c4d6766c28da015f07e5dc589e536d",
    },
    "DEV": {
        "salt": "splid-owner-DEV-a6c5caf631aa2507b5f95712",
        "hash": "0492e0883228f50136775b0083984f757e6a062217ef067e67b33c9fad152d62",
    },
    "UNFOTABLE": {
        "salt": "splid-owner-UNFOTABLE-c8d9290545848806c73b676a",
        "hash": "97a436a341f287d5a6477f32ca5b95a9d55d83c28ecd9e6426082fde14f2036c",
    },
}


class Config:
    """All runtime settings.  Instantiate via :meth:`from_env`."""

    def __init__(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # -- network -------------------------------------------------------
        self.HOST = os.environ.get("SYNCRO_HOST", "0.0.0.0")
        self.PORT = int(os.environ.get("SYNCRO_PORT", "8787"))

        # -- storage -------------------------------------------------------
        self.DATA_DIR = os.environ.get("SYNCRO_DATA", os.path.join(here, "syncro_data"))
        self.DB_FILENAME = "syncro.sqlite3"

        # -- payloads & assets ----------------------------------------------
        self.MAX_PAYLOAD = 900_000          # largest retained payload (chars)
        self.MAX_ASSET_BYTES = 200_000      # largest decoded profile picture
        self.MAX_ASSETS_PER_PAYLOAD = 24    # extraction budget per publish
        self.MAX_CONTENT_LENGTH = 2_000_000  # Flask request body cap

        # -- sessions & presence ---------------------------------------------
        self.SESSION_TTL_HOURS = 24 * 30    # a token lives a month of idleness
        self.HEARTBEAT_STALE_SECS = 170     # dir heartbeat is every 120 s
        self.SSE_PING_SECS = 15

        # -- journal ---------------------------------------------------------
        self.JOURNAL_KEEP = 5_000           # newest N activity rows are kept

        # -- abuse guards ------------------------------------------------------
        self.RATE_LIMIT_AUTH = 15           # sensitive POSTs per minute / IP
        self.RATE_LIMIT_PUB = 240           # bus publishes per minute / IP

        # -- owner proofs (build-time passcodes, see module docstring) --------
        self.OWNER_PROOFS = dict(OWNER_PROOFS)

    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls):
        """Build a Config from the process environment (defaults included)."""
        cfg = cls()
        extra = os.environ.get("SYNCRO_OWNER_EXTRA_JSON")
        if extra:
            import json
            try:
                parsed = json.loads(extra)
                if isinstance(parsed, dict):
                    cfg.OWNER_PROOFS.update(parsed)
            except ValueError:
                pass
        return cfg

    def db_path(self):
        return os.path.join(self.DATA_DIR, self.DB_FILENAME)

    def as_dict(self):
        """A redacted view of the config (safe to show in /api/health)."""
        return {
            "host": self.HOST,
            "port": self.PORT,
            "max_payload": self.MAX_PAYLOAD,
            "max_asset_bytes": self.MAX_ASSET_BYTES,
            "heartbeat_stale_secs": self.HEARTBEAT_STALE_SECS,
            "journal_keep": self.JOURNAL_KEEP,
            "owner_ids": sorted(self.OWNER_PROOFS.keys()),
        }
