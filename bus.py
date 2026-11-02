"""
The live bus — the Python replacement for the public MQTT broker.

Semantics preserved from the original design:

* **publish(topic, payload, retain)** — a payload published with ``retain``
  stays on the server and is handed to every future subscriber of that topic;
  publishing an empty payload clears the retained copy.
* **subscribe(pattern)** — an exact topic, or a trailing ``#`` meaning
  "everything under this prefix" (the inbox wildcard).
* **live delivery** — every publish is fanned out, instantly, to every
  connected subscriber whose pattern matches (including the publisher's own
  session, exactly like a broker would).

Transport: subscribers hold one Server-Sent Events stream per client
(``GET /api/stream?topic=…``), publishers POST to ``/api/bus/<topic>``.
"""

import json
import queue
import threading


def topic_matches(patterns, topic):
    """True if any pattern matches: exact, or trailing '#' = prefix match."""
    for pat in patterns:
        if pat == topic:
            return True
        if pat.endswith("#") and topic.startswith(pat[:-1]):
            return True
    return False


class Subscription:
    """One connected client's interest set plus its delivery queue."""

    __slots__ = ("topics", "q")

    def __init__(self, topics):
        self.topics = list(topics)
        self.q = queue.Queue(maxsize=500)


class Bus:
    """Fan-out hub.  Retained storage lives in the Store; the Bus does live."""

    def __init__(self, store):
        self.store = store
        self._subs = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def subscribe(self, topics):
        sub = Subscription(topics)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub):
        with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass

    def subscriber_count(self):
        with self._lock:
            return len(self._subs)

    # ------------------------------------------------------------------ #
    def fanout(self, topic, payload_text):
        """Deliver (topic, payload_text) to every matching subscriber."""
        with self._lock:
            targets = [s for s in self._subs if topic_matches(s.topics, topic)]
        for sub in targets:
            try:
                sub.q.put_nowait({"topic": topic, "payload": payload_text})
            except queue.Full:
                pass  # a stalled client misses this event; SSE retry recovers it

    def initial_events(self, topics):
        """Retained backfill for a fresh subscription (MQTT semantics)."""
        out = []
        for pat in topics:
            if pat.endswith("#"):
                prefix = pat[:-1]
                for row in self.store.list_retained_all():
                    if row["topic"].startswith(prefix):
                        out.append({"topic": row["topic"], "payload": row["payload"]})
            else:
                hit = self.store.get_retained(pat)
                if hit:
                    out.append({"topic": pat, "payload": hit["payload"]})
        return out

    # ------------------------------------------------------------------ #
    def stats(self):
        return {"subscribers": self.subscriber_count()}


def sse_frame(item):
    """Encode one bus event as a Server-Sent Events frame."""
    return "data: " + json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n\n"
