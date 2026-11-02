"""
The HTTP API — one blueprint that is the entire server-side system.

    /                    the single-page app (built from embedded Python modules)
    /api/health          liveness + counters
    /api/bus/<topic>     retained get / publish   (the MQTT replacement)
    /api/stream          Server-Sent Events live delivery
    /api/ids[...]        the profile directory & ID availability
    /api/session         server-side sign-in -> bearer token
    /api/activity/<id>   the user's activity journal
    /api/export/<id>     the user's full archive (assets + working + journal)
    /api/assets[...]     direct asset upload / serving
    /api/owner/*         owner passcode operations (remove / restore an ID)
"""

import json
import re
import time

from flask import Blueprint, Response, jsonify, request

from .assets import AssetVault
from .bus import sse_frame
from .security import (new_token, verify_owner, verify_profile_password)

ID_RE = re.compile(r"^[A-Z0-9]{3,14}$")
TOPIC_RE = re.compile(r"^[A-Za-z0-9_\-/.#]{1,240}$")

KINDS_QUIET = {"dir", "presence", "need"}     # heartbeats: not journaled per-publish


def norm_id(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def topic_parts(topic):
    """'splidchat/v1/<kind>/<ID>/…' -> (kind, ID)."""
    parts = [p for p in str(topic).split("/") if p]
    if len(parts) >= 4:
        return parts[2], parts[3]
    if len(parts) == 3:
        return parts[2], None
    return None, None


def create_api_blueprint(ctx):
    """ctx: simple namespace with cfg, store, bus, vault, limiters, started_at."""
    cfg, store, bus, vault = ctx.cfg, ctx.store, ctx.bus, ctx.vault
    bp = Blueprint("api", __name__)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def client_ip():
        return request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()

    def jlog(uid, kind, detail=None):
        store.journal(uid, kind, detail, ip=client_ip())

    def get_dir_payload(pid):
        hit = store.get_retained("splidchat/v1/dir/" + pid)
        if not hit:
            return None
        try:
            return json.loads(hit["payload"])
        except ValueError:
            return None

    def get_state_payload(pid):
        hit = store.get_retained("splidchat/v1/state/" + pid)
        if not hit:
            return None
        try:
            return json.loads(hit["payload"])
        except ValueError:
            return None

    def is_online(dirp):
        if not dirp or dirp.get("on") != 1:
            return False
        return (time.time() * 1000) - float(dirp.get("at") or 0) <= cfg.HEARTBEAT_STALE_SECS * 1000

    def public_view(row):
        """Merge a profile row with its directory beacon + presence."""
        pid = row["id"]
        dirp = get_dir_payload(pid)
        return {
            "id": pid,
            "name": row.get("name") or (dirp or {}).get("name") or pid,
            "color": row.get("color") or (dirp or {}).get("color") or "#4283F2",
            "pic": row.get("pic") or (dirp or {}).get("pic") or "",
            "joined": row.get("joined") or (dirp or {}).get("joined"),
            "friends": (dirp or {}).get("fr") if dirp else row.get("friends"),
            "on": is_online(dirp),
            "last_seen": (dirp or {}).get("at"),
            "removed": bool(row.get("removed")),
        }

    def find_profile_proof(pid):
        """The {salt, hash} proof for an ID: profile row first, cloud fallback."""
        row = store.get_profile(pid)
        if row and not row.get("removed") and row.get("salt") and row.get("hash"):
            return row, {"salt": row["salt"], "hash": row["hash"]}
        prof = get_profile_payload(pid)
        if prof and prof.get("salt") and prof.get("hash"):
            if row is None:
                store.upsert_profile(pid, name=prof.get("name"), color=prof.get("color"),
                                     pic=prof.get("pic"), dev=prof.get("dev"),
                                     salt=prof.get("salt"), hash=prof.get("hash"))
                row = store.get_profile(pid)
            return row, {"salt": prof["salt"], "hash": prof["hash"]}
        return row, None

    def get_profile_payload(pid):
        hit = store.get_retained("splidchat/v1/profile/" + pid)
        if not hit:
            return None
        try:
            data = json.loads(hit["payload"])
        except ValueError:
            return None
        prof = data.get("profile") if isinstance(data, dict) else None
        return prof if isinstance(prof, dict) else None

    def require_access(pid):
        """Session token of the ID, or a valid owner passcode."""
        token = request.headers.get("X-Token", "")
        sess = store.session_get(token, cfg.SESSION_TTL_HOURS) if token else None
        if sess and sess["uid"] == pid:
            return "self"
        if verify_owner(cfg, request.headers.get("X-Owner", "")):
            return "owner"
        return None

    # ------------------------------------------------------------------ #
    # the publish pipeline (used by /api/bus and by owner operations)
    # ------------------------------------------------------------------ #
    def publish(topic, p, retain, sender=None):
        if not TOPIC_RE.match(topic):
            return {"ok": False, "error": "bad topic"}, 400
        if p is not None:
            blob = json.dumps(p, ensure_ascii=False)
            if len(blob) > cfg.MAX_PAYLOAD:
                return {"ok": False, "error": "payload too large"}, 413

        kind, owner = topic_parts(topic)
        if kind == "profile" and not owner and isinstance(p, dict):
            owner = norm_id((p.get("profile") or {}).get("id") or "") or None

        # -- hoist user assets out of the payload into the vault ----------
        saved_n = 0
        if retain and p is not None:
            p, saved_n = vault.extract_and_replace(p, owner)

        text = "" if p is None else json.dumps(p, ensure_ascii=False, separators=(",", ":"))

        # -- durable layer --------------------------------------------------
        if retain:
            if text == "":
                store.clear_retained(topic)
            else:
                store.set_retained(topic, text, sender)

        # -- live layer ------------------------------------------------------
        bus.fanout(topic, text)

        # -- identity side-effects: the server keeps its own authoritative rows
        now_ms = int(time.time() * 1000)
        if kind == "profile" and isinstance(p, dict) and isinstance(p.get("profile"), dict) and owner:
            prof = p["profile"]
            store.upsert_profile(owner,
                                 name=prof.get("name"), color=prof.get("color"),
                                 pic=prof.get("pic"), dev=prof.get("dev"),
                                 salt=prof.get("salt"), hash=prof.get("hash"))
            jlog(owner, "profile.publish",
                 {"name": prof.get("name"), "pic": bool(prof.get("pic"))})
        elif kind == "dir" and isinstance(p, dict) and owner:
            store.upsert_profile(owner, name=p.get("name"), color=p.get("color"),
                                 pic=p.get("pic"), joined=p.get("joined"),
                                 friends=p.get("fr"))
        elif kind == "state" and isinstance(p, dict) and owner:
            me = (p.get("state") or {}).get("me") or {}
            store.upsert_profile(owner, name=me.get("name"), color=me.get("color"),
                                 pic=me.get("pic"), joined=me.get("joinedAt"),
                                 salt=me.get("salt"), hash=me.get("hash"))
            jlog(owner, "state.save",
                 {"bytes": len(text), "friends": len((p.get("state") or {}).get("friends") or {}),
                  "threads": len((p.get("state") or {}).get("threads") or {})})
        elif kind == "removed" and owner:
            if text == "":
                store.mark_removed(owner, 0)
                jlog(owner, "profile.restored", None)
            elif isinstance(p, dict) and p.get("type") == "removed":
                store.mark_removed(owner, 1)
                store.sessions_drop_for(owner)
                jlog(owner, "profile.removed", {"by": p.get("by") or "owner"})

        if kind not in KINDS_QUIET:
            jlog(owner, "bus.publish" if p is not None else "bus.clear",
                 {"topic": topic, "retain": bool(retain), "bytes": len(text),
                  "assets": saved_n} if kind != "profile" else {"bytes": len(text), "assets": saved_n})

        return {"ok": True, "topic": topic, "retained": bool(retain),
                "bytes": len(text), "assets_saved": saved_n}, 200

    # ------------------------------------------------------------------ #
    # system
    # ------------------------------------------------------------------ #
    @bp.get("/api/health")
    def health():
        return jsonify({
            "ok": True,
            "service": "syncro",
            "version": "1.0.0",
            "time": int(time.time() * 1000),
            "uptime_s": int(time.time() - ctx.started_at),
            "bus": bus.stats(),
            "counts": store.counts(),
            "config": cfg.as_dict(),
        })

    # ------------------------------------------------------------------ #
    # the bus (retained + live) — drop-in replacement for the public broker
    # ------------------------------------------------------------------ #
    @bp.get("/api/bus/<path:topic>")
    def bus_get(topic):
        hit = store.get_retained(topic)
        if not hit:
            return jsonify({"topic": topic, "payload": None})
        return jsonify(hit)

    @bp.post("/api/bus/<path:topic>")
    def bus_post(topic):
        if not ctx.limiter_pub.allow(client_ip()):
            return jsonify({"ok": False, "error": "slow down"}), 429
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        p = body.get("p", None)
        retain = bool(body.get("retain", True))
        result, code = publish(topic, p, retain, sender=client_ip())
        return jsonify(result), code

    @bp.get("/api/stream")
    def stream():
        topics = [t for t in request.args.getlist("topic") if TOPIC_RE.match(t)][:8]
        if not topics:
            return jsonify({"ok": False, "error": "no topics"}), 400
        sub = bus.subscribe(topics)

        def gen():
            try:
                yield "retry: 2000\n\n"
                for item in bus.initial_events(topics):
                    yield sse_frame(item)
                while True:
                    try:
                        item = sub.q.get(timeout=cfg.SSE_PING_SECS)
                        yield sse_frame(item)
                    except Exception:
                        yield ": ping\n\n"
            finally:
                bus.unsubscribe(sub)

        return Response(gen(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        })

    # ------------------------------------------------------------------ #
    # the profile directory
    # ------------------------------------------------------------------ #
    @bp.get("/api/ids")
    def ids():
        rows = {r["id"]: r for r in store.list_profiles() if not r.get("removed")}
        for row in store.list_retained_all():
            kind, pid = topic_parts(row["topic"])
            if kind == "dir" and pid and pid not in rows:
                rows[pid] = {"id": pid, "name": None, "color": None, "pic": None,
                             "joined": None, "removed": 0}
        out = [public_view(r) for r in rows.values()]
        out.sort(key=lambda v: (not v["on"], -(v["joined"] or 0)))
        return jsonify({"ids": out, "count": len(out)})

    @bp.get("/api/ids/<pid>")
    def ids_one(pid):
        pid = norm_id(pid)
        if not ID_RE.match(pid):
            return jsonify({"ok": False, "error": "bad id"}), 400
        row = store.get_profile(pid)
        if row is None:
            prof = get_profile_payload(pid)
            if not prof:
                return jsonify({"ok": False, "error": "not found"}), 404
            row = {"id": pid, "removed": 0, "name": prof.get("name"), "color": prof.get("color"),
                   "pic": prof.get("pic"), "joined": prof.get("joined")}
        return jsonify(public_view(row))

    @bp.get("/api/ids/<pid>/available")
    def ids_available(pid):
        pid = norm_id(pid)
        if not ID_RE.match(pid):
            return jsonify({"ok": False, "error": "bad id"}), 400
        row = store.get_profile(pid)
        taken = bool(row) or bool(get_profile_payload(pid))
        removed = bool(row and row.get("removed")) or bool(
            store.get_retained("splidchat/v1/removed/" + pid))
        return jsonify({"id": pid, "taken": taken and not removed,
                        "removed": removed, "available": not taken and not removed})

    # ------------------------------------------------------------------ #
    # sessions — the server-side half of sign-in
    # ------------------------------------------------------------------ #
    @bp.post("/api/session")
    def session_create():
        if not ctx.limiter_auth.allow(client_ip()):
            return jsonify({"ok": False, "error": "slow down"}), 429
        body = request.get_json(silent=True) or {}
        pid = norm_id(body.get("id"))
        password = str(body.get("password") or "")
        if not ID_RE.match(pid) or not password:
            return jsonify({"ok": False, "error": "id and password required"}), 400
        row, proof = find_profile_proof(pid)
        if not proof:
            return jsonify({"ok": False, "error": "unknown id or no password proof"}), 404
        if row and row.get("removed"):
            return jsonify({"ok": False, "error": "id removed by owner"}), 403
        if not verify_profile_password(proof, password):
            jlog(pid, "session.fail", None)
            return jsonify({"ok": False, "error": "wrong password"}), 401
        token = new_token()
        store.session_create(token, pid, cfg.SESSION_TTL_HOURS)
        jlog(pid, "session.create", None)
        return jsonify({"ok": True, "token": token, "profile": public_view(row or {"id": pid})})

    @bp.get("/api/session")
    def session_whoami():
        token = request.headers.get("X-Token", "")
        sess = store.session_get(token, cfg.SESSION_TTL_HOURS) if token else None
        if not sess:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        row = store.get_profile(sess["uid"])
        return jsonify({"ok": True, "id": sess["uid"], "profile": public_view(row) if row else None})

    @bp.delete("/api/session")
    def session_drop():
        token = request.headers.get("X-Token", "")
        sess = store.session_get(token, cfg.SESSION_TTL_HOURS) if token else None
        if not sess:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        store.session_drop(token)
        jlog(sess["uid"], "session.drop", None)
        return jsonify({"ok": True})

    # ------------------------------------------------------------------ #
    # the activity journal — every step the user took, saved
    # ------------------------------------------------------------------ #
    @bp.get("/api/activity/<pid>")
    def activity(pid):
        pid = norm_id(pid)
        if not ID_RE.match(pid):
            return jsonify({"ok": False, "error": "bad id"}), 400
        if not require_access(pid):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        try:
            limit = min(int(request.args.get("limit", "200")), 1000)
        except ValueError:
            limit = 200
        return jsonify({"id": pid, "activity": store.journal_for(pid, limit)})

    # ------------------------------------------------------------------ #
    # the export — all assets + all working of the user, one file
    # ------------------------------------------------------------------ #
    @bp.get("/api/export/<pid>")
    def export_user(pid):
        pid = norm_id(pid)
        if not ID_RE.match(pid):
            return jsonify({"ok": False, "error": "bad id"}), 400
        if not require_access(pid):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        import base64 as _b64
        row = store.get_profile(pid)
        state = get_state_payload(pid)
        assets = []
        for a in store.assets_for(pid, with_data=True):
            assets.append({k: a[k] for k in ("id", "ext", "mime", "nbytes", "created_at")} | {
                "data_base64": _b64.b64encode(a["data"]).decode("ascii")})
        topics = [t["topic"] for t in store.list_retained_all()
                  if topic_parts(t["topic"])[1] == pid]
        jlog(pid, "export.requested", {"assets": len(assets), "topics": len(topics)})
        return jsonify({
            "service": "syncro",
            "exported_at": int(time.time() * 1000),
            "id": pid,
            "profile": row,
            "directory": get_dir_payload(pid),
            "presence": {"on": is_online(get_dir_payload(pid))},
            "state": state,
            "assets": assets,
            "retained_topics": topics,
            "activity": store.journal_for(pid, 1000),
        })

    # ------------------------------------------------------------------ #
    # assets — direct upload & serving
    # ------------------------------------------------------------------ #
    @bp.post("/api/assets")
    def asset_upload():
        if not ctx.limiter_pub.allow(client_ip()):
            return jsonify({"ok": False, "error": "slow down"}), 429
        body = request.get_json(silent=True) or {}
        url = vault.save_dataurl(body.get("dataurl"), norm_id(body.get("owner") or "") or None)
        if not url:
            return jsonify({"ok": False, "error": "not a supported image data URL"}), 400
        return jsonify({"ok": True, "url": url})

    @bp.get("/assets/<name>")
    def asset_serve(name):
        got = vault.serve(name)
        if not got:
            return jsonify({"ok": False, "error": "not found"}), 404
        mime, blob = got
        return Response(blob, mimetype=mime, headers={
            "Cache-Control": "public, max-age=31536000, immutable",
        })

    # ------------------------------------------------------------------ #
    # owner operations — remove / restore an ID with the build-time passcode
    # ------------------------------------------------------------------ #
    @bp.post("/api/owner/remove")
    def owner_remove():
        body = request.get_json(silent=True) or {}
        pid, passcode = norm_id(body.get("id")), str(body.get("passcode") or "")
        if not ID_RE.match(pid):
            return jsonify({"ok": False, "error": "bad id"}), 400
        if not verify_owner(cfg, passcode):
            jlog(pid, "owner.remove.denied", None)
            return jsonify({"ok": False, "error": "wrong owner passcode"}), 401
        result, _ = publish("splidchat/v1/removed/" + pid,
                            {"app": "splidchat", "type": "removed", "id": pid,
                             "at": int(time.time() * 1000), "by": "owner"}, True, "owner")
        for suffix in ("profile", "state", "presence", "dir"):
            publish(f"splidchat/v1/{suffix}/{pid}", None, True, "owner")
        jlog(pid, "owner.remove", None)
        return jsonify({"ok": True, "id": pid, "removed": True, "bus": result})

    @bp.post("/api/owner/restore")
    def owner_restore():
        body = request.get_json(silent=True) or {}
        pid, passcode = norm_id(body.get("id")), str(body.get("passcode") or "")
        if not ID_RE.match(pid):
            return jsonify({"ok": False, "error": "bad id"}), 400
        if not verify_owner(cfg, passcode):
            jlog(pid, "owner.restore.denied", None)
            return jsonify({"ok": False, "error": "wrong owner passcode"}), 401
        publish("splidchat/v1/removed/" + pid, None, True, "owner")
        jlog(pid, "owner.restore", None)
        return jsonify({"ok": True, "id": pid, "restored": True})

    return bp
