"""
The live-bus shim.

The original front end was written against the mqtt.js browser client
(``mqtt.connect`` → ``client.on / subscribe / publish / end``).  This shim
exposes exactly that surface — the entire app runs **unchanged** — while the
wire protocol underneath becomes the Python backend:

* retained lookups  → the server re-plays retained messages on subscribe,
* live delivery     → one Server-Sent Events stream per client,
* publishing        → ``POST /api/bus/<topic>`` (retained or transient),
* presence          → connection health probes map to ``connect``/``close``.

It also publishes ``window.BUS_URL``, which the app's ``MQTT_URL`` constant
picks up for display and connection purposes.
"""

MQTT_SHIM_JS = r'''/* Syncro live-bus shim — a drop-in mqtt.js client that runs on the Python backend.
   Same surface (connect → on/subscribe/publish/end), new wires: retained lookups
   ride HTTP, live delivery rides Server-Sent Events, publishing is a POST. */
(function () {
  'use strict';
  var BASE = (location.origin && location.origin !== 'null') ? location.origin : 'http://127.0.0.1:8787';
  window.BUS_URL = BASE + '/api/bus';

  function Client(opts) {           /* opts kept for mqtt.js compatibility (clientId, will, keepalive…) */
    this._h = {};
    this._topics = [];
    this._es = null;
    this._openT = null;
    this._up = false;
    this._dead = false;
    this._timer = null;
    this._probe();
  }

  Client.prototype.on = function (evt, cb) {
    (this._h[evt] = this._h[evt] || []).push(cb);
    return this;
  };

  Client.prototype._fire = function (evt, a, b) {
    (this._h[evt] || []).slice().forEach(function (cb) {
      try { cb(a, b); } catch (e) {}
    });
  };

  Client.prototype._setUp = function (up) {
    if (this._dead || this._up === up) return;
    this._up = up;
    this._fire(up ? 'connect' : 'close');
  };

  /* health probe — instant connect/close events, with a gentle retry loop */
  Client.prototype._probe = function () {
    var self = this;
    if (this._dead) return;
    fetch(BASE + '/api/health', { cache: 'no-store' })
      .then(function (r) { self._setUp(!!r.ok); }, function () { self._setUp(false); })
      .catch(function () { self._setUp(false); });
    this._timer = setTimeout(function () { self._probe(); }, this._up ? 5000 : 2000);
  };

  /* one EventSource carries every subscription; (re)opened whenever the set grows */
  Client.prototype._open = function () {
    var self = this;
    if (this._dead || !this._topics.length) return;
    if (this._openT) return;
    this._openT = setTimeout(function () {
      self._openT = null;
      if (self._dead || !self._topics.length) return;
      if (self._es) { try { self._es.close(); } catch (e) {} }
      var url = BASE + '/api/stream?' +
        self._topics.map(function (t) { return 'topic=' + encodeURIComponent(t); }).join('&');
      var es = new EventSource(url);
      self._es = es;
      es.onopen = function () { self._setUp(true); };
      es.onerror = function () { self._setUp(false); };
      es.onmessage = function (e) {
        try {
          var m = JSON.parse(e.data);
          self._fire('message', m.topic, m.payload == null ? '' : String(m.payload));
        } catch (err) {}
      };
    }, 40);
  };

  Client.prototype.subscribe = function (topic) {
    if (this._dead) return;
    topic = String(topic);
    if (this._topics.indexOf(topic) !== -1) return;
    this._topics.push(topic);
    this._open();
  };

  Client.prototype.publish = function (topic, payload, opts) {
    if (this._dead) return false;
    opts = opts || {};
    var p = null;
    if (payload !== '' && payload !== null && payload !== undefined) {
      if (typeof payload === 'string') { try { p = JSON.parse(payload); } catch (e) { p = payload; } }
      else { p = payload; }
    }
    try {
      fetch(window.BUS_URL + '/' + String(topic).split('/').map(encodeURIComponent).join('/'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ p: p, retain: !!opts.retain }),
        keepalive: true
      });
      return true;
    } catch (e) { return false; }
  };

  Client.prototype.end = function (force, cb) {
    var wasUp = this._up;
    this._dead = true;
    this._up = false;
    clearTimeout(this._timer);
    if (this._openT) { clearTimeout(this._openT); this._openT = null; }
    if (this._es) { try { this._es.close(); } catch (e) {} this._es = null; }
    if (wasUp) this._fire('close');
    if (cb) setTimeout(cb, 0);
  };

  window.mqtt = { connect: function (url, opts) { return new Client(opts || {}); } };
})();
'''
