"""
ASGI/WSGI entry helpers — create_app() builds the complete server.

The stack is deliberately boring and bullet-proof:

* Flask for routing,
* SQLite (WAL) for durable storage,
* Server-Sent Events for live delivery,
* stdlib threads for concurrency.

Run it with ``python app.py`` (development) or point any WSGI server at
``create_app()`` (production).
"""

import time
from types import SimpleNamespace

from flask import Flask, jsonify

from .api import create_api_blueprint
from .assets import AssetVault
from .bus import Bus
from .config import Config
from .security import RateLimiter
from .store import Store


def create_app(config=None, data_dir=None, testing=False):
    """Build the Syncro WSGI app.  ``data_dir`` overrides the storage folder
    (used by the test-suite so tests never touch real user data)."""
    cfg = config or Config.from_env()
    if data_dir:
        cfg.DATA_DIR = data_dir

    store = Store(cfg.db_path(), journal_keep=cfg.JOURNAL_KEEP).init()
    bus = Bus(store)
    vault = AssetVault(store, cfg, journal=lambda uid, kind, detail=None: store.journal(uid, kind, detail))
    ctx = SimpleNamespace(
        cfg=cfg, store=store, bus=bus, vault=vault,
        limiter_auth=RateLimiter(cfg.RATE_LIMIT_AUTH),
        limiter_pub=RateLimiter(cfg.RATE_LIMIT_PUB),
        started_at=time.time(),
    )

    app = Flask("syncro", static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_CONTENT_LENGTH
    app.config["JSON_SORT_KEYS"] = False
    app.extensions["syncro"] = ctx

    from .web.page import render_page
    app.register_blueprint(create_api_blueprint(ctx))

    @app.get("/")
    def index():
        return render_page(cfg)

    @app.get("/favicon.ico")
    def favicon():
        return ("", 204)

    @app.after_request
    def harden(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Server", "syncro-python")
        return resp

    @app.errorhandler(404)
    def not_found(_e):
        if request_path_is_api():
            return jsonify({"ok": False, "error": "not found"}), 404
        return render_page(cfg)

    @app.errorhandler(405)
    def bad_method(_e):
        return jsonify({"ok": False, "error": "method not allowed"}), 405

    @app.errorhandler(413)
    def too_large(_e):
        return jsonify({"ok": False, "error": "payload too large"}), 413

    @app.errorhandler(400)
    def bad_request(_e):
        return jsonify({"ok": False, "error": "bad request"}), 400

    def request_path_is_api():
        from flask import request
        return request.path.startswith("/api") or request.path.startswith("/assets")

    if testing:
        app.testing = True
    return app


def main():
    """Console entry point — ``python app.py``."""
    cfg = Config.from_env()
    app = create_app(cfg)
    print(f"""
  ┌─────────────────────────────────────────────────────┐
  │  Syncro · live ID network · served entirely by Python
  │  local     http://127.0.0.1:{cfg.PORT:<5d}                  │
  │  lan       http://<this-machine>:{cfg.PORT:<5d}              │
  │  storage   {cfg.DATA_DIR:<44s}│
  └─────────────────────────────────────────────────────┘""", flush=True)
    app.run(host=cfg.HOST, port=cfg.PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
