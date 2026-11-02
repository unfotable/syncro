"""
Integration tests for the whole server — no network, no browser, just the
Flask test client driving the real stack (Store → Bus → Vault → API).

    python -m unittest discover -s tests -v
"""

import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from syncro.config import Config
from syncro.security import client_pw_hash
from syncro.server import create_app

# a real 1x1 transparent PNG
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PNG_DATAURL = "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()

SALT, PW = "unittest-salt", "correct horse"
PROOF = {"salt": SALT, "hash": client_pw_hash(SALT, PW)}


def png_variant(n):
    """A unique image per test — the vault is content-addressed, so identical
    bytes dedup to one blob and only the FIRST owner gets it journaled."""
    blob = bytearray(TINY_PNG)
    blob[-1] ^= (n % 251) + 1
    return "data:image/png;base64," + base64.b64encode(bytes(blob)).decode()


class ApiTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="syncro_test_")
        cfg = Config()
        cfg.OWNER_PROOFS["TESTOWNER"] = {
            "salt": "tsalt", "hash": client_pw_hash("tsalt", "owner-secret")}
        cls.app = create_app(cfg, data_dir=cls.tmp, testing=True)
        cls.c = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def publish(self, topic, p, retain=True):
        return self.c.post(f"/api/bus/{topic}", json={"p": p, "retain": retain})

    def publish_profile(self, pid="TESTID01", name="Unit Tester", pic=None):
        prof = {"id": pid, "name": name, "color": "#E14B4F", "dev": "unittest-dev",
                "salt": PROOF["salt"], "hash": PROOF["hash"]}
        prof["pic"] = PNG_DATAURL if pic is None else pic
        return self.publish(f"splidchat/v1/profile/{pid}",
                            {"app": "splidchat", "type": "profile", "profile": prof})

    def sign_in(self, pid="TESTID01", password=PW):
        return self.c.post("/api/session", json={"id": pid, "password": password})

    # ------------------------------------------------------------------ #
    # system
    # ------------------------------------------------------------------ #
    def test_01_health(self):
        r = self.c.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("counts", body)
        self.assertIn("bus", body)

    def test_02_index_page(self):
        r = self.c.get("/")
        html = r.get_data(as_text=True)
        self.assertIn('<div id="root"></div>', html)
        self.assertIn("tailwind.config", html)
        self.assertIn("window.mqtt", html)          # the bus shim
        self.assertIn("hisaab.v4", html)            # the app itself

    # ------------------------------------------------------------------ #
    # retained bus
    # ------------------------------------------------------------------ #
    def test_10_retained_roundtrip_and_clear(self):
        r = self.publish("test/roundtrip", {"v": 42})
        self.assertEqual(r.get_json()["retained"], True)
        got = self.c.get("/api/bus/test/roundtrip").get_json()
        self.assertEqual(json.loads(got["payload"]), {"v": 42})
        r = self.publish("test/roundtrip", None)
        got = self.c.get("/api/bus/test/roundtrip").get_json()
        self.assertIsNone(got["payload"])

    def test_11_publish_rejects_bad_topic(self):
        r = self.c.post("/api/bus/bad topic with spaces", json={"p": {}, "retain": True})
        self.assertEqual(r.status_code, 400)

    def test_12_oversized_payload_rejected(self):
        big = {"blob": "x" * 950_000}
        r = self.publish("test/big", big)
        self.assertEqual(r.status_code, 413)

    # ------------------------------------------------------------------ #
    # profile lifecycle
    # ------------------------------------------------------------------ #
    def test_20_profile_publish_syncs_identity(self):
        r = self.publish_profile()
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.get_json()["assets_saved"], 1)   # avatar hoisted

        ids = self.c.get("/api/ids").get_json()["ids"]
        self.assertTrue(any(i["id"] == "TESTID01" for i in ids))

        one = self.c.get("/api/ids/TESTID01").get_json()
        self.assertEqual(one["name"], "Unit Tester")
        self.assertTrue(one["pic"].startswith("/assets/"))         # vaulted, not data:

    def test_21_availability(self):
        self.publish_profile("TAKEN001")
        a = self.c.get("/api/ids/TAKEN001/available").get_json()
        self.assertFalse(a["available"])
        self.assertTrue(a["taken"])
        b = self.c.get("/api/ids/FREEID99/available").get_json()
        self.assertTrue(b["available"])

    def test_22_removed_tombstone_blocks_availability(self):
        self.publish_profile("GONE001")
        self.publish("splidchat/v1/removed/GONE001",
                     {"app": "splidchat", "type": "removed", "id": "GONE001"})
        a = self.c.get("/api/ids/GONE001/available").get_json()
        self.assertTrue(a["removed"])
        self.assertFalse(a["available"])
        self.publish("splidchat/v1/removed/GONE001", None)          # restore
        a = self.c.get("/api/ids/GONE001/available").get_json()
        self.assertFalse(a["removed"])

    # ------------------------------------------------------------------ #
    # sessions — server-side sign-in with the client-compatible proof
    # ------------------------------------------------------------------ #
    def test_30_session_flow(self):
        self.publish_profile("AUTHID01")
        self.assertEqual(self.sign_in("AUTHID01", "wrong").status_code, 401)
        r = self.sign_in("AUTHID01")
        self.assertEqual(r.status_code, 200)
        token = r.get_json()["token"]

        who = self.c.get("/api/session", headers={"X-Token": token}).get_json()
        self.assertEqual(who["id"], "AUTHID01")

        dropped = self.c.delete("/api/session", headers={"X-Token": token})
        self.assertEqual(dropped.status_code, 200)
        self.assertEqual(
            self.c.get("/api/session", headers={"X-Token": token}).status_code, 401)

    def test_31_session_unknown_id(self):
        self.assertEqual(self.sign_in("NOBODY00").status_code, 404)

    # ------------------------------------------------------------------ #
    # assets
    # ------------------------------------------------------------------ #
    def test_40_asset_upload_and_serve(self):
        r = self.c.post("/api/assets", json={"dataurl": PNG_DATAURL, "owner": "TESTID01"})
        url = r.get_json()["url"]
        got = self.c.get(url)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content_type, "image/png")
        self.assertEqual(got.data, TINY_PNG)

    def test_41_asset_dedup_by_content(self):
        url = png_variant(1)
        for _ in range(3):
            self.c.post("/api/assets", json={"dataurl": url, "owner": "A"})
        # same content -> same URL, one blob
        self.assertEqual(len(self.app.extensions["syncro"].store.assets_for("A")), 1)

    # ------------------------------------------------------------------ #
    # journal & export — "all working of the user, saved"
    # ------------------------------------------------------------------ #
    def test_50_journal_records_the_work(self):
        self.publish_profile("JRNL001", pic=png_variant(2))
        self.publish("splidchat/v1/state/JRNL001",
                     {"app": "splidchat", "type": "state",
                      "state": {"me": {"id": "JRNL001", "joinedAt": 123}, "friends": {}}})
        token = self.sign_in("JRNL001").get_json()["token"]
        acts = self.c.get("/api/activity/JRNL001",
                          headers={"X-Token": token}).get_json()["activity"]
        kinds = {a["kind"] for a in acts}
        self.assertIn("profile.publish", kinds)
        self.assertIn("state.save", kinds)
        self.assertIn("asset.saved", kinds)
        self.assertIn("session.create", kinds)

    def test_51_journal_requires_auth(self):
        self.assertEqual(self.c.get("/api/activity/JRNL001").status_code, 401)

    def test_52_export_contains_everything(self):
        self.publish_profile("JRNL001", pic=png_variant(3))
        token = self.sign_in("JRNL001").get_json()["token"]
        ex = self.c.get("/api/export/JRNL001",
                        headers={"X-Token": token}).get_json()
        self.assertEqual(ex["id"], "JRNL001")
        self.assertIsNotNone(ex["profile"])
        self.assertIn("state", ex)
        self.assertTrue(len(ex["activity"]) >= 4)
        self.assertTrue(any(a["data_base64"] for a in ex["assets"]))

    # ------------------------------------------------------------------ #
    # owner operations
    # ------------------------------------------------------------------ #
    def test_60_owner_remove_and_restore(self):
        self.publish_profile("OWNED01")
        bad = self.c.post("/api/owner/remove",
                          json={"id": "OWNED01", "passcode": "nope"})
        self.assertEqual(bad.status_code, 401)

        ok = self.c.post("/api/owner/remove",
                         json={"id": "OWNED01", "passcode": "owner-secret"})
        self.assertEqual(ok.status_code, 200)
        tomb = self.c.get("/api/bus/splidchat/v1/removed/OWNED01").get_json()
        self.assertIn("removed", tomb["payload"])
        self.assertTrue(self.c.get("/api/ids/OWNED01/available").get_json()["removed"])

        self.c.post("/api/owner/restore",
                    json={"id": "OWNED01", "passcode": "owner-secret"})
        tomb = self.c.get("/api/bus/splidchat/v1/removed/OWNED01").get_json()
        self.assertIsNone(tomb["payload"])

    # ------------------------------------------------------------------ #
    # bus unit semantics (direct, no HTTP)
    # ------------------------------------------------------------------ #
    def test_70_bus_matching(self):
        from syncro.bus import topic_matches
        self.assertTrue(topic_matches(["a/b"], "a/b"))
        self.assertTrue(topic_matches(["inbox/X#"], "inbox/X/whatever"))
        self.assertTrue(topic_matches(["inbox/X#"], "inbox/X"))
        self.assertFalse(topic_matches(["inbox/X#"], "inbox/Y/1"))
        self.assertFalse(topic_matches(["a/b"], "a/b/c"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
