"""
The asset vault — where "saving all assets of the user" actually happens.

Profile pictures arrive inside JSON payloads as ``data:image/...;base64,…``
data URLs.  On the way into the bus, the vault intercepts every data URL,
decodes it, stores the raw bytes as a content-addressed blob in SQLite, and
rewrites the payload to reference ``/assets/<id>.<ext>``.  The picture the
user uploaded therefore becomes a first-class server asset: servable,
cacheable, exportable — never trapped inside a JSON string again.
"""

import base64
import hashlib
import re

DATA_URL_RE = re.compile(
    r"data:image/(png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=\s]+)")

MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


class AssetVault:

    def __init__(self, store, cfg, journal=None):
        self.store = store
        self.cfg = cfg
        self._journal = journal or (lambda *a, **k: None)

    # ------------------------------------------------------------------ #
    def _save_blob(self, raw, owner):
        """Store decoded bytes; returns (asset_id, ext) or None."""
        if not raw or len(raw) > self.cfg.MAX_ASSET_BYTES:
            return None
        ext = "png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else (
            "gif" if raw[:3] == b"GIF" else (
                "webp" if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" else "jpg"))
        aid = "a" + hashlib.sha256(raw).hexdigest()[:20]
        created = self.store.save_asset(aid, owner, ext, MIME[ext], raw)
        if created:
            self._journal(owner, "asset.saved",
                          {"asset": aid, "bytes": len(raw), "ext": ext})
        return aid, ext

    def save_dataurl(self, dataurl, owner=None):
        """Explicit upload endpoint helper: data URL -> /assets/<id>.<ext>."""
        m = DATA_URL_RE.search(str(dataurl or ""))
        if not m:
            return None
        try:
            raw = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=False)
        except Exception:
            return None
        saved = self._save_blob(raw, owner)
        return self.url_for(saved) if saved else None

    @staticmethod
    def url_for(saved):
        aid, ext = saved
        return f"/assets/{aid}.{ext}"

    # ------------------------------------------------------------------ #
    def extract_and_replace(self, obj, owner):
        """Walk a JSON-ready structure; hoist every data URL into the vault.

        Returns (new_object, saved_count).  Budget-capped per payload so one
        huge publish can't flood storage.
        """
        budget = [self.cfg.MAX_ASSETS_PER_PAYLOAD]

        def walk(node):
            if budget[0] <= 0:
                return node
            if isinstance(node, str):
                if "data:image/" not in node:
                    return node

                def repl(m):
                    if budget[0] <= 0:
                        return m.group(0)
                    try:
                        raw = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=False)
                    except Exception:
                        return m.group(0)
                    saved = self._save_blob(raw, owner)
                    if not saved:
                        return m.group(0)
                    budget[0] -= 1
                    return self.url_for(saved)

                return DATA_URL_RE.sub(repl, node)
            if isinstance(node, dict):
                return {k: walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v) for v in node]
            return node

        return walk(obj), self.cfg.MAX_ASSETS_PER_PAYLOAD - budget[0]

    # ------------------------------------------------------------------ #
    def serve(self, name):
        """Lookup for GET /assets/<id>[.<ext>] -> (mime, bytes) or None."""
        aid = str(name).split(".", 1)[0]
        row = self.store.get_asset(aid)
        if not row:
            return None
        return row["mime"] or "application/octet-stream", row["data"]
