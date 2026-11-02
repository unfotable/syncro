"""The application itself — the original React (via htm) front end, embedded
verbatim with only the transport constants re-pointed at the Python bus.
Everything else — profile making, the device vault, presence, state sync —
is unchanged and now speaks to the Python backend through shim_js.MQTT_SHIM_JS."""

# --- embedded application script (React + htm, transport re-pointed to the Python bus) ---
APP_JS = r'''const { useState, useEffect, useMemo, useRef } = React;
const html = htm.bind(React.createElement);

/* ---------------- constants & helpers ---------------- */

const KEY = 'hisaab.v4';
const uid = () => Math.random().toString(36).slice(2, 10);
const P = d => ({ t:'p', d });

const AV = ['#4283F2','#E95EC0','#3FCE6E','#EE5458','#9A5CF5','#22B8D4','#F27A3C','#DE9A2E'];
const firstName = n => (n || '?').trim().split(/\s+/)[0];

const ICONS = {
  chat:[P('M7.9 20A9 9 0 1 0 4 16.1L2 22Z')],
  check:[P('M20 6 9 17l-5-5')],
  x:[P('M18 6 6 18'),P('M6 6l12 12')],
  copy:[P('M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'),P('M11 9h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Z')],
  lock:[{t:'p',d:'M5.5 10.5h13A1.5 1.5 0 0 1 20 12v8a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 20v-8a1.5 1.5 0 0 1 1.5-1.5Z'},P('M7.5 10.5V7a4.5 4.5 0 0 1 9 0v3.5')],
  eye:[P('M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z'),{t:'c',cx:12,cy:12,r:3}],
  eyeOff:[P('M10.7 5.7A9.7 9.7 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17.9 17.9 0 0 1-2.4 3.2'),P('M6.6 6.6C3.8 8.4 2.5 12 2.5 12s3.5 6.5 9.5 6.5a9.3 9.3 0 0 0 4.4-1.1'),P('M9.9 9.9a3 3 0 1 0 4.2 4.2'),P('M3 3l18 18')],
  dice:[{t:'p',d:'M4.5 3h15A1.5 1.5 0 0 1 21 4.5v15a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5v-15A1.5 1.5 0 0 1 4.5 3Z'},P('M8 8h.01'),P('M16 8h.01'),P('M12 12h.01'),P('M8 16h.01'),P('M16 16h.01')],
  camera:[P('M14.5 4h-5L7.7 6.3a1 1 0 0 1-.8.4H4a2 2 0 0 0-2 2V18a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8.7a2 2 0 0 0-2-2h-2.9a1 1 0 0 1-.8-.4L14.5 4Z'),{t:'c',cx:12,cy:13,r:3.2}],
  logout:[P('M9 21H5.5A1.5 1.5 0 0 1 4 19.5v-15A1.5 1.5 0 0 1 5.5 3H9'),P('M16 17l5-5-5-5'),P('M21 12H9')],
  sparkle:[P('M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9Z'),P('M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9Z')],
};

function Icon({ name, size=18, sw=2, className='' }) {
  if (!ICONS[name]) return null;
  return html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth=${sw} strokeLinecap="round" strokeLinejoin="round" className=${className} aria-hidden="true">
    ${ICONS[name].map((s, i) => s.t === 'p'
      ? html`<path key=${i} d=${s.d}/>`
      : html`<circle key=${i} cx=${s.cx} cy=${s.cy} r=${s.r}/>`)}
  </svg>`;
}

/* ---------------- live server backend · mqtt over wss ----------------
   One public broker is primary; identity lookups try both, in this order. */

const MQTT_URL = (typeof BUS_URL === 'string' && BUS_URL) ? BUS_URL : 'http://127.0.0.1:8787/api/bus';
const BROKERS = [MQTT_URL, MQTT_URL];   /* every route lands on the Python bus */
const CHAT_ROOT = 'splidchat/v1/';
const cTopic = (...p) => CHAT_ROOT + p.join('/');
const DIR_TOPIC = id => cTopic('dir', normId(id));
const REMOVED_TOPIC = id => cTopic('removed', normId(id));   /* owner removal tombstones */
const CODE_ABC = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
const chunkCode = c => String(c || '').replace(/(.{4})(?=.)/g, '$1-');
const hashStr = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return h; };

const normId = s => String(s || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
const newChatId = () => Array.from({ length: 8 }, () => CODE_ABC[Math.floor(Math.random() * CODE_ABC.length)]).join('');

/* any ID from 3 to 14 letters/numbers works — shorter or longer than 8, it registers as-is.
   What you type is exactly what you get: no padding, no forced length. */
/* dice: a random ID grown from the chosen name — "Meera" → MEE482, ITSME7739, MECHAT42 … */
const idFromName = nm => {
  const base = normId(nm);
  if (base.length < 2) return newChatId();
  const digs = n => Array.from({ length: n }, () => String(Math.floor(Math.random() * 10))).join('');
  const pats = [
    () => base.slice(0, 3 + Math.floor(Math.random() * 3)) + digs(2 + Math.floor(Math.random() * 3)),
    () => 'ITS' + base.slice(0, 2 + Math.floor(Math.random() * 2)) + digs(2 + Math.floor(Math.random() * 3)),
    () => base.slice(0, 2) + 'CHAT' + digs(1 + Math.floor(Math.random() * 3)),
  ];
  return pats[Math.floor(Math.random() * pats.length)]();
};

const freshChat = () => ({ me: null, friends: {}, reqsIn: {}, reqsOut: {}, threads: {}, unread: {}, seenUpto: {}, tripReqs: {}, tripReqDec: {} });

/* ---------------- splid vault — the device keyring that makes sign-in instant & offline-proof ----------------
   Every ID this device has ever created or signed into keeps its password proof (salt + hash) and a
   local archive here — so signing in again NEVER depends on the network. */
const VAULT_KEY = 'hisaab.chat.vault';
const vaultAll = () => { try { const v = JSON.parse(localStorage.getItem(VAULT_KEY)); return v && typeof v === 'object' && !Array.isArray(v) ? v : {}; } catch (e) { return {}; } };
const vaultGet = id => vaultAll()[normId(id)] || null;
const vaultPut = (id, entry) => {
  try {
    const k = normId(id); if (!k) return;
    const all = vaultAll();
    all[k] = { ...(all[k] || {}), ...entry, id: k, savedAt: Date.now() };
    localStorage.setItem(VAULT_KEY, JSON.stringify(all));
  } catch (e) {}
};
const vaultDrop = id => { try { const all = vaultAll(); delete all[normId(id)]; localStorage.setItem(VAULT_KEY, JSON.stringify(all)); } catch (e) {} };
/* snapshot a chat state for the vault */
const vaultPickState = c => {
  const base = { me: c.me, friends: c.friends || {}, reqsIn: c.reqsIn || {}, reqsOut: c.reqsOut || {}, threads: c.threads || {}, unread: c.unread || {}, seenUpto: c.seenUpto || {}, updatedAt: Date.now() };
  return base;
};
const vaultArchive = (id, chatState) => { if (id && chatState && chatState.me) vaultPut(id, { archive: { at: Date.now(), state: vaultPickState(chatState) } }); };

/* one retained-message pull with a short "absent" window — the primitive behind every lookup.
   Resolves { data, connected } so callers can tell "network down" from "truly not there". */
function pullRetained(topic, match, opts) {
  opts = opts || {};
  return new Promise(resolve => {
    if (typeof mqtt === 'undefined') { resolve({ data: null, connected: false }); return; }
    let c;
    try { c = mqtt.connect(opts.url || MQTT_URL, { clientId: 'splidp-' + uid(), keepalive: 20, reconnectPeriod: 0, connectTimeout: 6000 }); }
    catch (e) { resolve({ data: null, connected: false }); return; }
    let done = false, sawConn = false, to = null, fast = null;
    const finish = v => { if (done) return; done = true; clearTimeout(to); clearTimeout(fast); try { c.end(true); } catch (e) {} resolve(v); };
    to = setTimeout(() => finish({ data: null, connected: sawConn }), opts.timeout || 5000);
    c.on('connect', () => {
      sawConn = true;
      try { c.subscribe(topic, { qos: 0 }); } catch (e) {}
      fast = setTimeout(() => finish({ data: null, connected: true }), opts.fastMs || 2600); // retained (or absence) resolves fast after connect
    });
    c.on('message', (t, payload) => {
      const s = payload.toString();
      if (!s) { finish({ data: null, connected: true }); return; }
      try { const d = JSON.parse(s); if (d && match(d)) finish({ data: d, connected: true }); } catch (e) {}
    });
    c.on('error', () => finish({ data: null, connected: sawConn }));
    c.on('close', () => { if (!done && sawConn) finish({ data: null, connected: true }); });
  });
}

async function fetchChatProfile(id, timeout) {
  const r = await pullRetained(cTopic('profile', id), d => d.app === 'splidchat' && d.profile && d.profile.id === id, { timeout: timeout || 4500, fastMs: 2400 });
  return r.data && r.data.profile ? r.data.profile : null;
}

/* one-shot lookup of the retained per-account cloud snapshot */
async function fetchChatState(id, timeout) {
  const r = await pullRetained(cTopic('state', id), d => d.app === 'splidchat' && d.type === 'state' && d.state && d.state.me && d.state.me.id === id, { timeout: timeout || 8000, fastMs: 2400 });
  return r.data && r.data.state ? r.data.state : null;
}

/* live handshake — when retained lookups come back empty (public brokers sometimes stop serving retained
   messages), ping splidchat/v1/need/<ID>: any ONLINE device that owns the ID answers with its profile or
   state over live delivery. Only helps while the owner is online somewhere — but that's the common case
   (signing in on a laptop while your phone still has the account open). */
function lookupLive(id, want, timeout) {
  return new Promise(resolve => {
    if (typeof mqtt === 'undefined') { resolve({ data: null, connected: false }); return; }
    let c;
    try { c = mqtt.connect(MQTT_URL, { clientId: 'splidn-' + uid(), keepalive: 20, reconnectPeriod: 0, connectTimeout: 6000 }); }
    catch (e) { resolve({ data: null, connected: false }); return; }
    let done = false, sawConn = false, to = null, rep1 = null, rep2 = null;
    const finish = v => { if (done) return; done = true; clearTimeout(to); clearTimeout(rep1); clearTimeout(rep2); try { c.end(true); } catch (e) {} resolve(v); };
    const matchProfile = d => d && d.app === 'splidchat' && d.profile && d.profile.id === id;
    const matchState = d => d && d.app === 'splidchat' && d.type === 'state' && d.state && d.state.me && d.state.me.id === id;
    to = setTimeout(() => finish({ data: null, connected: sawConn }), timeout || 4200);
    c.on('connect', () => {
      sawConn = true;
      try { c.subscribe(want === 'state' ? cTopic('state', id) : cTopic('profile', id), { qos: 0 }); } catch (e) {}
      const ping = () => { try { c.publish(cTopic('need', id), JSON.stringify({ app: 'splidchat', type: 'need', want, id, t: Date.now() }), { qos: 0 }); } catch (e) {} };
      ping(); rep1 = setTimeout(ping, 900); rep2 = setTimeout(ping, 2000);
    });
    c.on('message', (t, payload) => {
      const s = payload.toString(); if (!s) return;
      try { const d = JSON.parse(s); if ((want === 'state' && matchState(d)) || (want !== 'state' && matchProfile(d))) finish({ data: d, connected: true }); } catch (e) {}
    });
    c.on('error', () => finish({ data: null, connected: sawConn }));
  });
}
/* sign-in identity chase — device vault is checked before this; here we chase the ID across two brokers and
   both retained topics, then a live handshake, before ever saying "not found". Offline stays distinguishable. */
async function lookupIdentity(id, onStep) {
  const tries = [
    { kind: 'profile', url: BROKERS[0] },
    { kind: 'profile', url: BROKERS[1] },
    { kind: 'state', url: BROKERS[0] },
    { kind: 'state', url: BROKERS[1] },
    { kind: 'live', want: 'profile' },
    { kind: 'live', want: 'state' },
  ];
  let connected = false, src = null, srcKind = null;
  for (let i = 0; i < tries.length && !src; i++) {
    const t = tries[i];
    if (onStep) { try { onStep(t.kind === 'live' ? 'live' : (t.kind === 'profile' ? 'lookup' : 'cloud')); } catch (e) {} }
    let r;
    if (t.kind === 'live') r = await lookupLive(id, t.want, 4200);
    else r = await pullRetained(
      cTopic(t.kind, id),
      t.kind === 'profile'
        ? d => d.app === 'splidchat' && d.profile && d.profile.id === id
        : d => d.app === 'splidchat' && d.type === 'state' && d.state && d.state.me && d.state.me.id === id,
      { url: t.url, timeout: i === 0 ? 6000 : 4600, fastMs: i === 0 ? 2600 : 2200 }
    );
    if (r.connected) connected = true;
    if (r.data) { src = t.kind === 'state' || (t.kind === 'live' && t.want === 'state') ? r.data.state : r.data.profile; srcKind = t.kind === 'live' && t.want === 'state' ? 'state' : t.kind; }
  }
  return { src, srcKind, connected };
}

/* ---------------- password hashing & profile pictures ---------------- */

/* SHA-256 hex, pure-JS fallback for contexts where crypto.subtle is unavailable (e.g. file://) */
function sha256Hex(str) {
  const maxWord = Math.pow(2, 32);
  let ascii;
  try { ascii = encodeURIComponent(String(str)).replace(/%([0-9A-F]{2})/g, (m, p) => String.fromCharCode(parseInt(p, 16))); }
  catch (e) { ascii = String(str); }
  const words = [];
  const asciiBitLength = ascii.length * 8;
  const hash = [], k = [];
  let primeCounter = 0;
  const isComposite = {};
  for (let candidate = 2; primeCounter < 64; candidate++) {
    if (!isComposite[candidate]) {
      for (let i = 0; i < 313; i += candidate) isComposite[i] = candidate;
      hash[primeCounter] = (Math.pow(candidate, .5) * maxWord) | 0;
      k[primeCounter++] = (Math.pow(candidate, 1 / 3) * maxWord) | 0;
    }
  }
  ascii += '\x80';
  while (ascii.length % 64 - 56) ascii += '\x00';
  for (let i = 0; i < ascii.length; i++) {
    const j = ascii.charCodeAt(i);
    if (j >> 8) return '';
    words[i >> 2] |= j << ((3 - i) % 4) * 8;
  }
  words[words.length] = (asciiBitLength / maxWord) | 0;
  words[words.length] = asciiBitLength;
  const rr = (v, a) => (v >>> a) | (v << (32 - a));
  for (let j0 = 0; j0 < words.length;) {
    const w = words.slice(j0, j0 += 16);
    const oldHash = hash.slice(0);
    const hh = hash.slice(0, 8);
    for (let i = 0; i < 64; i++) {
      const w15 = w[i - 15], w2 = w[i - 2];
      const a = hh[0], e = hh[4];
      const temp1 = hh[7]
        + (rr(e, 6) ^ rr(e, 11) ^ rr(e, 25))
        + ((e & hh[5]) ^ ((~e) & hh[6]))
        + k[i]
        + (w[i] = (i < 16) ? w[i] : (
          w[i - 16]
          + (rr(w15, 7) ^ rr(w15, 18) ^ (w15 >>> 3))
          + w[i - 7]
          + (rr(w2, 17) ^ rr(w2, 19) ^ (w2 >>> 10))
        ) | 0);
      const temp2 = (rr(a, 2) ^ rr(a, 13) ^ rr(a, 22)) + ((a & hh[1]) ^ (a & hh[2]) ^ (hh[1] & hh[2]));
      hh.unshift((temp1 + temp2) | 0);
      hh[4] = (hh[4] + temp1) | 0;
    }
    for (let i = 0; i < 8; i++) hash[i] = (hh[i] + oldHash[i]) | 0;
  }
  let result = '';
  for (let i = 0; i < 8; i++) for (let j = 3; j + 1; j--) {
    const b = (hash[i] >> (j * 8)) & 255;
    result += ((b < 16) ? 0 : '') + b.toString(16);
  }
  return result;
}

/* salted password hash — prefers the platform WebCrypto, falls back to sha256Hex */
const sha256 = async s => {
  try {
    if (typeof crypto !== 'undefined' && crypto.subtle && crypto.subtle.digest) {
      const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(s)));
      return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
    }
  } catch (e) {}
  return sha256Hex(s);
};
const pwHash = (salt, pw) => sha256(String(salt) + ':' + String(pw));

/* read an image file → compact square-ish JPEG data URL (fits comfortably in MQTT payloads) */
const fileToPic = file => new Promise(resolve => {
  if (!file || !/^image\//.test(file.type || '')) { resolve(null); return; }
  const fr = new FileReader();
  fr.onerror = () => resolve(null);
  fr.onload = () => {
    const img = new Image();
    img.onerror = () => resolve(null);
    img.onload = () => {
      try {
        const MAX = 256;
        let w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
        if (!w || !h) { resolve(null); return; }
        const sc = Math.min(1, MAX / Math.max(w, h));
        w = Math.max(1, Math.round(w * sc)); h = Math.max(1, Math.round(h * sc));
        const cv = document.createElement('canvas');
        cv.width = w; cv.height = h;
        cv.getContext('2d').drawImage(img, 0, 0, w, h);
        let q = 0.72, url = cv.toDataURL('image/jpeg', q);
        while (url.length > 60000 && q > 0.4) { q -= 0.12; url = cv.toDataURL('image/jpeg', q); }
        resolve(url.length > 90000 ? null : url);
      } catch (e) { resolve(null); }
    };
    img.src = String(fr.result || '');
  };
  fr.readAsDataURL(file);
});

/* build-time owner passcode — the owner's password is provisioned here, so it always works:
   any device, even offline; on match it becomes THE proof (this vault + the cloud on next connect) */
const OWNER_PROOFS = { DEVANSHU: { salt: 'splid-owner-DEVANSHU-3f9c2b81d4e6a759', hash: '4263e4212b8a1a50392c2459d3654da7b8c4d6766c28da015f07e5dc589e536d' }, DEV: { salt: 'splid-owner-DEV-a6c5caf631aa2507b5f95712', hash: '0492e0883228f50136775b0083984f757e6a062217ef067e67b33c9fad152d62' }, UNFOTABLE: { salt: 'splid-owner-UNFOTABLE-c8d9290545848806c73b676a', hash: '97a436a341f287d5a6477f32ca5b95a9d55d83c28ecd9e6426082fde14f2036c' } };

/* ---------------- primitives ---------------- */

function Avatar({ m, size = 36, className = '' }) {
  if (m && m.pic) {
    return html`<img src=${m.pic} alt=${(m.name || '?') + '’s avatar'} draggable=${false}
      className=${'rounded-full object-cover select-none shrink-0 bg-paper ' + className}
      style=${{ width:size, height:size, boxShadow:'0 0 0 2px rgb(var(--c-card))' }}/>`;
  }
  return html`<span className=${'inline-flex items-center justify-center rounded-full font-semibold text-[#FCF9F3] select-none shrink-0 ' + className}
    style=${{ width:size, height:size, background:m.color, fontSize:Math.round(size * .42), boxShadow:'0 0 0 2px rgb(var(--c-card))' }}>
    ${(m.name || '?').trim()[0].toUpperCase()}
  </span>`;
}

function ChatIdCopy({ id, big }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const done = () => { setCopied(true); setTimeout(() => setCopied(false), 1600); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(id).then(done, done);
    else {
      const ta = document.createElement('textarea');
      ta.value = id; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch (e) {}
      ta.remove(); done();
    }
  };
  return html`<button onClick=${copy} aria-label="Copy ID" title="Copy your ID"
    className="shrink-0 inline-flex items-center gap-2 bg-paper border border-line rounded-full pl-3.5 pr-1.5 py-1.5 hover:border-muted transition active:scale-95">
    <code className=${'font-mono font-bold tracking-[.12em] numtab ' + (big ? 'text-[15px]' : 'text-[12.5px]')}>${chunkCode(id)}</code>
    <span className=${'w-6 h-6 rounded-full flex items-center justify-center shrink-0 transition ' + (copied ? 'bg-sage text-paper' : 'bg-ink text-paper')}>
      <${Icon} name=${copied ? 'check' : 'copy'} size=${12} sw=${2.4}/>
    </span>
  </button>`;
}

const SIGNIN_ERRS = {
  notfound: 'We couldn’t find that ID on the live server right now. Check the spelling — if the ID was created on another device, the network may be slow to sync, so try again in a moment.',
  nopass: 'This ID was made before passwords existed, so it can’t be verified on a new device.',
  wrongpass: 'Wrong password for that ID — try again.',
  removed: 'The owner removed this ID — it can no longer be used.',
  bad: 'Enter your ID (3–14 letters or numbers) and your password.',
  offline: 'Couldn’t reach the live server — check your internet and try again.',
  try: 'Sign-in failed — check your connection and try again.',
};
const SIGNIN_STEPS = { lookup: 'Searching the network for your ID…', cloud: 'Checking the cloud snapshot…', live: 'Asking online devices for your ID…', verify: 'Checking your password…', restore: 'Restoring your profile…' };

/* circular profile-picture picker: tap → file input → compressed JPEG preview */
function PicPicker({ pic, color, initial, onPic, size = 72 }) {
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const pick = async e => {
    const f = e.target && e.target.files && e.target.files[0];
    e.target.value = '';
    if (!f) return;
    setBusy(true);
    const url = await fileToPic(f);
    setBusy(false);
    if (url) onPic(url);
  };
  return html`<button type="button" onClick=${() => fileRef.current && fileRef.current.click()} aria-label="Choose profile picture"
    title="Upload a profile picture"
    className="relative rounded-full shrink-0 transition active:scale-95 group" style=${{ width:size, height:size }}>
    ${pic
      ? html`<img src=${pic} alt="Profile picture" draggable=${false} className="w-full h-full rounded-full object-cover bg-paper"
          style=${{ boxShadow:'0 0 0 2px rgb(var(--c-card)), 0 10px 28px -12px rgba(38,34,27,.4)' }}/>`
      : html`<span className="w-full h-full rounded-full flex items-center justify-center font-semibold text-[#FCF9F3] select-none"
          style=${{ background:color, fontSize:Math.round(size * .4), boxShadow:'0 0 0 2px rgb(var(--c-card)), 0 10px 28px -12px rgba(38,34,27,.4)' }}>${(initial || '?').toUpperCase()}</span>`}
    <span className=${'absolute -bottom-0.5 -right-0.5 w-7 h-7 rounded-full bg-ink text-paper border-2 border-card flex items-center justify-center transition ' + (busy ? 'opacity-60' : 'group-hover:bg-ink/90')}>
      <${Icon} name="camera" size=${13} sw=${2.2}/>
    </span>
    <input ref=${fileRef} type="file" accept="image/*" className="hidden" onChange=${pick}/>
  </button>`;
}

function ToastView({ toast }) {
  if (!toast) return null;
  return html`<div key=${toast.key} className="fixed left-1/2 bottom-6 sm:bottom-10 z-[90]" style=${{ transform:'translateX(-50%)' }}>
    <div className="toast-in flex items-center gap-2.5 bg-ink text-paper rounded-full pl-2 pr-4 py-2 shadow-pop">
      <span className="w-6 h-6 rounded-full bg-sage flex items-center justify-center shrink-0"><${Icon} name=${toast.icon || 'check'} size=${13} sw=${3} className="text-paper"/></span>
      <span className="text-[13.5px] font-semibold pr-1">${toast.msg}</span>
    </div>
  </div>`;
}

function LivePill({ on }) {
  return html`<span className=${'inline-flex items-center gap-1.5 text-[9.5px] font-bold tracking-[.14em] uppercase rounded-full px-1.5 py-0.5 shrink-0 ' + (on ? 'bg-sage-tint text-sage-deep' : 'bg-card border border-line text-muted')}>
    <span className=${'w-1.5 h-1.5 rounded-full ' + (on ? 'bg-sage live-dot' : 'bg-muted')}></span>
    ${on ? 'Live' : 'Sync…'}
  </span>`;
}

/* ---------------- id making · create an ID or sign back in ---------------- */

function ChatOnboard({ onCreate, onSignIn }) {
  /* IDs this device already knows — one tap prefills the sign-in form */
  const [known] = useState(() => Object.values(vaultAll()).filter(e => e && e.id && e.salt && e.hash).sort((a, b) => (b.savedAt || 0) - (a.savedAt || 0)).slice(0, 4));
  /* one ID, many devices — a device that has ever held an ID starts on SIGN IN, never on make-a-new-one */
  const [tab, setTab] = useState(() => (known.length ? 'signin' : 'create'));
  const [name, setName] = useState('');
  const [idv, setIdv] = useState(newChatId());
  const [color, setColor] = useState(AV[Math.floor(Math.random() * AV.length)]);
  const [pic, setPic] = useState('');
  const [pass, setPass] = useState('');
  const [pass2, setPass2] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [inId, setInId] = useState(() => (known.length ? known[0].id : ''));
  const [inPass, setInPass] = useState('');
  const [chk, setChk] = useState('idle');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [busyStep, setBusyStep] = useState(null);

  const targetId = normId(idv);        /* exactly what you type — any length from 3 to 14, no padding */
  const idOk = targetId.length >= 3 && targetId.length <= 14;
  const passOk = pass.length >= 4;
  const passMatch = pass === pass2;

  useEffect(() => {
    if (tab !== 'create' || !idOk) { setChk('idle'); return; }
    let live = true;
    setChk('checking');
    const t = setTimeout(async () => {
      const v0 = vaultGet(targetId);       /* the device remembers — no network needed to know it's taken */
      if (v0 && v0.salt && v0.hash) { if (live) setChk('yours'); return; }
      const p = await fetchChatProfile(targetId);
      if (!live) return;
      if (p) { setChk('taken'); return; }
      const tomb = await pullRetained(REMOVED_TOPIC(targetId), d => d && d.app === 'splidchat' && d.type === 'removed' && d.id === targetId, { timeout: 3200, fastMs: 1600 });
      if (live) setChk(tomb && tomb.data ? 'removed' : 'free');   /* profile gone but tombstone retained → the owner removed it */
    }, 600);
    return () => { live = false; clearTimeout(t); };
  }, [targetId, tab]);

  const canCreate = name.trim().length >= 1 && idOk && chk !== 'checking' && chk !== 'taken' && chk !== 'yours' && chk !== 'removed' && passOk && passMatch && !busy;

  const create = async () => {
    if (!canCreate) return;
    setBusy(true); setErr(null);
    const res = await onCreate({ name, id: targetId, color, pic, password: pass });
    if (res && res.taken) setChk('taken');
    if (res && res.removedId) setErr('The owner removed ' + chunkCode(targetId) + ' — this ID stays unusable until the owner restores it.');
    if (res && res.takenLocal) {   /* this device already holds that ID — send them to sign in instead */
      setTab('signin'); setInId(targetId); setPass(''); setPass2('');
      setErr('You already made ' + chunkCode(targetId) + ' on this device — type its password to sign in.');
    }
    setBusy(false);
  };

  const cleanIn = normId(inId);
  const knownMatch = cleanIn ? vaultGet(cleanIn) : null;
  const canSign = cleanIn.length >= 3 && inPass.length >= 1 && !busy;
  const signIn = async () => {
    if (!canSign) return;
    setBusy(true); setErr(null); setBusyStep(null);
    try { await onSignIn({ id: cleanIn, password: inPass, onStep: setBusyStep }); }
    catch (e) { setErr(SIGNIN_ERRS[e] || SIGNIN_ERRS.try); }
    setBusyStep(null); setBusy(false);
  };

  const pickKnown = k => {
    setInId(k.id); setErr(null);
    const el = document.getElementById('signin-pass');
    if (el) el.focus();
  };

  const passField = (val, set, ph, ac, onEnter, inpId) => html`<div className="relative">
    <input type=${showPass ? 'text' : 'password'} className="inp pr-11" placeholder=${ph} autoComplete=${ac} id=${inpId}
      maxLength=${40} value=${val} onChange=${e => { set(e.target.value); setErr(null); }}
      onKeyDown=${e => { if (e.key === 'Enter' && onEnter) onEnter(); }}/>
    <button type="button" onClick=${() => setShowPass(s => !s)} aria-label=${showPass ? 'Hide password' : 'Show password'}
      className="absolute right-1.5 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center text-muted hover:text-ink transition">
      <${Icon} name=${showPass ? 'eyeOff' : 'eye'} size=${15}/>
    </button>
  </div>`;

  return html`<div className="flex-1 overflow-y-auto flex items-start sm:items-center justify-center p-4">
    <div className="sheet-in w-full max-w-md bg-card border border-line rounded-3xl shadow-pop p-5 sm:p-6 my-4">
      <div className="flex flex-col items-center text-center">
        ${tab === 'create'
          ? html`<${PicPicker} pic=${pic} color=${color} initial=${name.trim()[0]} onPic=${setPic} size=${72}/>`
          : html`<span className="w-12 h-12 rounded-2xl bg-ink text-paper flex items-center justify-center shadow-soft"><${Icon} name="chat" size=${22}/></span>`}
        <h2 className="font-display text-[22px] font-semibold mt-3 leading-tight">${tab === 'create' ? 'Make your ID' : 'Welcome back'}</h2>
        <p className="text-[13px] text-muted mt-1.5 leading-relaxed max-w-[330px]">${tab === 'create'
          ? 'Pick any free ID, lock it with a password, and it goes live on the server — no phone number needed.'
          : 'One ID works on every device. Verify it with your password and your profile comes right back on this one.'}</p>
      </div>

      ${tab === 'create' ? html`
      <div className="mt-5">
        <label className="lbl">Your name</label>
        <input className="inp" placeholder="What should people call you?" maxLength=${24} value=${name}
          onChange=${e => setName(e.target.value)}/>
      </div>

      <div className="mt-4">
        <label className="lbl">Your ID</label>
        <div className="flex gap-2">
          <input className="inp font-mono font-bold tracking-[.14em] uppercase text-[16px] select-all" placeholder="PICK-ANY-ID" spellCheck=${false}
            maxLength=${14} value=${idv} onChange=${e => setIdv(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}/>
          <button onClick=${() => setIdv(idFromName(name))} title="Randomize an ID from your name" aria-label="Randomize an ID from your name"
            className="shrink-0 w-11 rounded-xl bg-paper border border-line text-muted hover:text-ink hover:border-muted flex items-center justify-center transition active:scale-95">
            <${Icon} name="dice" size=${17}/>
          </button>
        </div>
        <div className="mt-2 text-[12px] font-semibold flex items-center gap-1.5 min-h-[18px]">
          ${chk === 'checking' && html`<span className="w-1.5 h-1.5 rounded-full bg-sage live-dot"></span><span className="text-muted">Checking ${chunkCode(targetId)}…</span>`}
          ${chk === 'free' && idOk && html`<span className="w-1.5 h-1.5 rounded-full bg-sage"></span><span className="text-sage-deep">${chunkCode(targetId)} is free — grab it!</span>`}
          ${chk === 'taken' && html`<span className="w-1.5 h-1.5 rounded-full bg-rust"></span><span className="text-rust-deep">${chunkCode(targetId)} already exists — try another, or sign in if it’s yours</span>
            <button onClick=${() => { setTab('signin'); setInId(targetId); setErr(null); }} className="underline underline-offset-2 text-ink hover:text-ink/80 transition">Sign in with it</button>`}
          ${chk === 'removed' && html`<span className="w-1.5 h-1.5 rounded-full bg-rust"></span><span className="text-rust-deep">${chunkCode(targetId)} was removed by the owner — it stays unusable until they restore it.</span>`}
          ${chk === 'yours' && html`<span className="w-1.5 h-1.5 rounded-full bg-sage"></span><span className="text-sage-deep">That one’s yours — it’s saved on this device.</span>
            <button onClick=${() => { setTab('signin'); setInId(targetId); setErr(null); }} className="underline underline-offset-2 text-ink hover:text-ink/80 transition">Sign in instead</button>`}
          ${chk === 'idle' && html`<span className="text-muted">3–14 letters or numbers — short or long, your call · the dice builds one from your name</span>`}
        </div>
      </div>

      <div className="mt-4">
        <label className="lbl">Your color</label>
        <div className="flex flex-wrap gap-2">
          ${AV.map(c => html`<button key=${c} onClick=${() => setColor(c)} aria-label=${'Color ' + c}
            className=${'w-8 h-8 rounded-full transition active:scale-90 ' + (color === c ? 'ring-2 ring-offset-2 ring-ink ring-offset-card' : 'hover:scale-110')}
            style=${{ background: c }}></button>`)}
        </div>
      </div>

      <div className="mt-4">
        <label className="lbl"><span className="inline-flex items-center gap-1.5"><${Icon} name="lock" size=${12} sw=${2.4}/>Password</span></label>
        ${passField(pass, setPass, 'At least 4 characters — needed on every new device', 'new-password', null)}
        <div className="mt-2">${passField(pass2, setPass2, 'Repeat the password', 'new-password', create)}</div>
        ${pass2 && !passMatch && html`<div className="mt-2 text-[12px] font-semibold text-rust-deep">Passwords don’t match yet</div>`}
      </div>

      ${err && html`<div className="mt-3 rounded-2xl px-3.5 py-2.5 text-[12.5px] font-semibold leading-relaxed bg-rust-tint text-rust-deep border border-rust/25">${err}</div>`}
      <button onClick=${create} disabled=${!canCreate}
        className=${'mt-6 w-full rounded-full py-3 text-[14px] font-semibold transition active:scale-[.98] ' +
          (canCreate ? 'bg-ink text-paper hover:bg-ink/90' : 'bg-ink/20 text-paper cursor-not-allowed')}>
        ${busy ? 'Creating your ID…' : 'Create my ID'}
      </button>
      <p className="text-[11px] text-muted mt-3 text-center leading-relaxed">Your ID is 3–14 letters or numbers — short or long, exactly as you type it — and public on the live server, so anyone can find it. Your password is the key: it unlocks this ID on any device.</p>
      <button onClick=${() => { setTab('signin'); setErr(null); }} className="mt-2 w-full text-center text-[12.5px] font-semibold text-muted hover:text-ink transition py-1">
        Already have an ID? <span className="text-ink underline underline-offset-2">Sign in</span>
      </button>`
      : html`
      <div className="mt-5">
        <label className="lbl">Your ID</label>
        <input className="inp font-mono font-bold tracking-[.14em] uppercase text-[16px]" placeholder="YOUR-ID" spellCheck=${false}
          maxLength=${14} value=${inId} onChange=${e => { setInId(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '')); setErr(null); }}/>
        ${cleanIn && html`<p className="text-[11.5px] text-muted mt-1.5 numtab">Signing in as ${chunkCode(cleanIn)}</p>`}
        ${knownMatch && knownMatch.salt && html`<p className="mt-2 text-[11.5px] font-semibold text-sage-deep flex items-center gap-1.5">
          <${Icon} name="check" size=${12} sw=${2.6}/>Saved on this device — sign-in is instant, even offline</p>`}
      </div>
      <div className="mt-4">
        <label className="lbl"><span className="inline-flex items-center gap-1.5"><${Icon} name="lock" size=${12} sw=${2.4}/>Password</span></label>
        ${passField(inPass, setInPass, 'Your password', 'current-password', signIn, 'signin-pass')}
      </div>
      ${!inId && known.length > 0 && html`<div className="mt-4">
        <div className="text-[10.5px] font-bold tracking-[.16em] uppercase text-muted mb-2">On this device</div>
        <div className="flex flex-wrap gap-2">
          ${known.map(k => html`<button key=${k.id} type="button" onClick=${() => pickKnown(k)}
            title=${'Sign in as ' + (k.name || k.id)}
            className="flex items-center gap-2 rounded-full bg-paper border border-line pl-1 pr-3 py-1 hover:border-muted transition active:scale-95">
            <span className="w-7 h-7 rounded-full text-[#FCF9F3] text-[12px] font-semibold flex items-center justify-center shrink-0" style=${{ background: k.color || '#26221B' }}>${(k.name || k.id)[0].toUpperCase()}</span>
            <span className="text-left leading-tight">
              <span className="block text-[12px] font-semibold text-ink max-w-[110px] truncate">${k.name || k.id}</span>
              <span className="block text-[10px] font-mono font-bold tracking-[.1em] text-muted numtab">${chunkCode(k.id)}</span>
            </span>
          </button>`)}
        </div>
      </div>`}
      ${err && html`<div className="mt-4 rounded-2xl px-3.5 py-2.5 text-[12.5px] font-semibold leading-relaxed bg-rust-tint text-rust-deep border border-rust/25">${err}</div>`}
      <button onClick=${signIn} disabled=${!canSign}
        className=${'mt-6 w-full rounded-full py-3 text-[14px] font-semibold transition active:scale-[.98] ' +
          (canSign ? 'bg-ink text-paper hover:bg-ink/90' : 'bg-ink/20 text-paper cursor-not-allowed')}>
        ${busy ? (SIGNIN_STEPS[busyStep] || 'Verifying…') : (knownMatch && knownMatch.salt ? 'Verify & sign in — it’s instant' : 'Verify & sign in')}
      </button>
      <p className="text-[11px] text-muted mt-3 text-center leading-relaxed">Saved IDs are verified right on this device — instantly, even offline. A new device verifies over the live server, then picks up right where you left off.</p>
      <button onClick=${() => { setTab('create'); setErr(null); }} className="mt-2 w-full text-center text-[12.5px] font-semibold text-muted hover:text-ink transition py-1">
        New here? <span className="text-ink underline underline-offset-2">Create an ID</span>
      </button>`}
    </div>
  </div>`;
}

/* ---------------- signed-in home · your ID + the live server status ---------------- */

function Home({ chat, chatOn, onLogout }) {
  const me = chat.me;
  const since = me.joinedAt ? new Date(me.joinedAt).toLocaleDateString('en-IN', { day:'numeric', month:'short', year:'numeric' }) : null;
  return html`<div className="flex-1 flex flex-col">
    <header className="sticky top-0 z-40 bg-paper/85 backdrop-blur-md border-b border-line">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 h-[60px] flex items-center justify-between">
        <span className="text-[12px] font-bold tracking-[.14em] uppercase text-muted">Account</span>
        <${LivePill} on=${chatOn}/>
      </div>
    </header>

    <main className="flex-1 w-full max-w-3xl mx-auto px-4 sm:px-6 py-8 space-y-5 rise">
      <section className="bg-card border border-line rounded-3xl shadow-soft p-5 sm:p-6">
        <div className="flex items-center gap-4">
          <${Avatar} m=${me} size=${64}/>
          <div className="min-w-0">
            <div className="font-display text-[22px] font-semibold truncate leading-tight">${me.name}</div>
            <div className="text-[12px] text-muted mt-1">${since ? 'On the network since ' + since : 'Signed in on this device'}</div>
          </div>
        </div>
        <div className="mt-5">
          <label className="lbl">Your ID</label>
          <div className="flex items-center gap-3 flex-wrap">
            <${ChatIdCopy} id=${me.id} big=${true}/>
            <span className="text-[11.5px] text-muted">Share this — it’s how the network finds you</span>
          </div>
        </div>
      </section>

      <section className="bg-card border border-line rounded-3xl shadow-soft p-5 sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-display text-[17px] font-semibold">Live server</h2>
          <${LivePill} on=${chatOn}/>
        </div>
        <p className="text-[12.5px] text-muted mt-1.5 leading-relaxed">
          ${chatOn ? 'Connected — this ID is live on the network right now.' : 'Connecting to the live server…'}
        </p>
        <ul className="mt-4 space-y-2.5 text-[13px] leading-relaxed">
          <li className="flex gap-2.5"><span className="w-1.5 h-1.5 rounded-full bg-sage shrink-0 mt-[7px]"></span><span><span className="font-semibold">Presence beacon</span> — an “online” flag retained on the server, cleared the moment this tab closes.</span></li>
          <li className="flex gap-2.5"><span className="w-1.5 h-1.5 rounded-full bg-sage shrink-0 mt-[7px]"></span><span><span className="font-semibold">Profile registry</span> — your ID, name and color stay published (retained), so any device can look the ID up.</span></li>
          <li className="flex gap-2.5"><span className="w-1.5 h-1.5 rounded-full bg-sage shrink-0 mt-[7px]"></span><span><span className="font-semibold">Cloud snapshot</span> — the account state is retained on the server so a brand-new device can verify and restore it.</span></li>
          <li className="flex gap-2.5"><span className="w-1.5 h-1.5 rounded-full bg-sage shrink-0 mt-[7px]"></span><span><span className="font-semibold">Handshake responder</span> — answers “need this ID” pings from other devices when the broker loses a retained copy.</span></li>
          <li className="flex gap-2.5"><span className="w-1.5 h-1.5 rounded-full bg-sage shrink-0 mt-[7px]"></span><span><span className="font-semibold">Directory heartbeat</span> — refreshes this ID’s directory entry every 2 minutes while online.</span></li>
        </ul>
        <div className="mt-4 rounded-2xl bg-paper border border-line px-3.5 py-2.5 text-[11px] font-mono text-muted numtab break-all">${MQTT_URL}</div>
      </section>

      <button onClick=${onLogout}
        className="w-full rounded-full border border-line bg-card py-3 text-[13.5px] font-semibold text-ink hover:bg-paper active:scale-[.98] transition flex items-center justify-center gap-2">
        <${Icon} name="logout" size=${15}/> Sign out
      </button>
      <p className="text-[11px] text-muted text-center pb-6 leading-relaxed">Signing out keeps this ID saved on this device — the next sign-in is instant, even offline.</p>
    </main>
  </div>`;
}

/* ---------------- app ---------------- */

function App() {
  const [db, setDb] = useState(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const d = JSON.parse(raw);
        if (d && typeof d === 'object') {
          if (!d.deviceId) d.deviceId = uid();
          if (!d.chat) d.chat = freshChat();
          return d;
        }
      }
    } catch (e) {}
    return { v: 3, deviceId: uid(), groups: [], chat: freshChat() };
  });
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(db)); } catch (e) {} }, [db]);

  const chat = db.chat || freshChat();
  const patchChat = fn => setDb(d => ({ ...d, chat: fn(d.chat || freshChat()) }));

  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);
  const showToast = (msg, icon) => {
    const key = Date.now();
    setToast({ key, msg, icon });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2400);
  };

  /* live server backend state */
  const chatClientRef = useRef(null);
  const chatSubsRef = useRef(new Set());
  const removedIdsRef = useRef(new Set());      /* IDs known to be removed by the owner — this device never re-announces them */
  const chatRef = useRef(chat); chatRef.current = chat;
  const restoreRef = useRef(false);   // true while a cloud sign-in restore is landing — pause state pushes
  const stateTimerRef = useRef(null);
  const [chatOn, setChatOn] = useState(false);

  const chatPublish = (topic, obj, retain) => {
    const c = chatClientRef.current; if (!c) return false;
    try { c.publish(topic, obj === null ? '' : JSON.stringify(obj), { qos: 0, retain: !!retain }); return true; } catch (e) { return false; }
  };

  /* owner-directory entry — one small retained beacon per ID. on=1 while this device is live,
     refreshed by a heartbeat every 2 min; logout / tab close flip it to on=0.
     Carries NO passwords or private data — only what a public profile already shares. */
  const dirPublish = on => {
    const me = chatRef.current.me; if (!me) return;
    if (removedIdsRef.current.has(normId(me.id))) return;   /* removed by the owner — never re-beacon */
    let joined = me.joinedAt;
    if (!joined) {
      const v = vaultGet(me.id);
      joined = (v && v.joinedAt) || Date.now();
      if (!v || !v.joinedAt) vaultPut(me.id, { joinedAt: joined });
      patchChat(c => (c.me && !c.me.joinedAt) ? { ...c, me: { ...c.me, joinedAt: joined } } : c);
    }
    const fr = Object.keys(chatRef.current.friends || {}).length;
    chatPublish(DIR_TOPIC(me.id), { app: 'splidchat', type: 'dir', id: me.id, name: me.name, color: me.color, pic: me.pic || '', joined, at: Date.now(), on: on ? 1 : 0, fr }, true);
  };

  const handleSelfRemoved = () => {
    const me = chatRef.current.me;
    const c = chatClientRef.current;
    if (me) {
      if (c) {
        try { c.publish(cTopic('profile', me.id), '', { qos: 0, retain: true }); } catch (e) {}
        try { c.publish(cTopic('state', me.id), '', { qos: 0, retain: true }); } catch (e) {}
        try { c.publish(cTopic('presence', me.id), '', { qos: 0, retain: true }); } catch (e) {}
        try { c.publish(DIR_TOPIC(me.id), '', { qos: 0, retain: true }); } catch (e) {}
      }
      vaultDrop(me.id);   /* the keyring forgets this ID — it can never sign in from here again */
    }
    if (c) { setTimeout(() => { try { c.end(true); } catch (e) {} }, 500); } /* let the cleanup publishes flush */
    chatClientRef.current = null;
    chatSubsRef.current = new Set();
    setChatOn(false);
    restoreRef.current = false;
    patchChat(() => freshChat());
    showToast('This ID was removed by the owner — it can no longer be used', 'x');
  };

  const onChatMsg = (topic, payload) => {
    const me = chatRef.current.me; if (!me) return;
    /* live handshake — another device is looking for MY id and the broker lost the retained copies: answer now */
    if (topic === cTopic('need', me.id)) {
      if (removedIdsRef.current.has(me.id)) return;   /* a removed ID never answers identity pings */
      let d; try { d = JSON.parse(payload.toString()); } catch (e) { return; }
      if (!d || d.app !== 'splidchat' || d.type !== 'need' || normId(d.id) !== me.id) return;
      if (d.want === 'state') chatPublish(cTopic('state', me.id), { app:'splidchat', type:'state', v:1, state: vaultPickState(chatRef.current) }, false);
      else chatPublish(cTopic('profile', me.id), { app:'splidchat', type:'profile', profile: { id: me.id, name: me.name, color: me.color, pic: me.pic || '', dev: me.dev, salt: me.salt, hash: me.hash }, updatedAt: Date.now() }, false);
      return;
    }
    /* our own tombstone — lands instantly if the owner removed this ID */
    if (topic === cTopic('removed', me.id)) {
      const s = payload.toString();
      if (!s) { removedIdsRef.current.delete(me.id); return; }   /* tombstone cleared — the owner restored the ID */
      let d; try { d = JSON.parse(s); } catch (e) { return; }
      if (!d || d.app !== 'splidchat' || d.type !== 'removed' || normId(d.id) !== me.id) return;
      if (!removedIdsRef.current.has(me.id)) { removedIdsRef.current.add(me.id); handleSelfRemoved(); }
      return;
    }
    /* profile echoes of my own ID — nothing to do in this build */
    if (topic === cTopic('profile', me.id)) return;
    /* the inbox has no feature in this build — clear any retained copy so nothing stale piles up on the broker */
    const inboxRoot = cTopic('inbox', me.id, '');
    if (topic.indexOf(inboxRoot) === 0) { chatPublish(topic, null, true); return; }
  };

  const connectChat = () => {
    if (chatClientRef.current || typeof mqtt === 'undefined') return;
    const me = chatRef.current.me; if (!me) return;
    let c;
    try {
      c = mqtt.connect(MQTT_URL, {
        clientId: 'splidchat-' + uid(), keepalive: 30, reconnectPeriod: 4000, connectTimeout: 8000, clean: true,
        will: { topic: cTopic('presence', me.id), payload: '', qos: 0, retain: true },
      });
    } catch (e) { return; }
    chatClientRef.current = c;
    c.on('connect', () => {
      setChatOn(true);
      const me2 = chatRef.current.me; if (!me2) return;
      chatSubsRef.current.add(cTopic('inbox', me2.id, '#'));
      chatSubsRef.current.add(cTopic('need', me2.id)); /* live handshake listener — answers identity pings */
      chatSubsRef.current.add(cTopic('profile', me2.id));
      chatSubsRef.current.add(cTopic('removed', me2.id)); /* our own tombstone — lands instantly if the owner removed this ID */
      chatSubsRef.current.forEach(t => { try { c.subscribe(t, { qos: 0 }); } catch (e) {} });
      chatPublish(cTopic('presence', me2.id), { app:'splidchat', on: 1, t: Date.now() }, true);
      if (!removedIdsRef.current.has(normId(me2.id))) {   /* a removed ID never re-announces its identity */
        chatPublish(cTopic('profile', me2.id), { app:'splidchat', type:'profile', profile: { id: me2.id, name: me2.name, color: me2.color, pic: me2.pic || '', dev: me2.dev, salt: me2.salt, hash: me2.hash }, updatedAt: Date.now() }, true);
        dirPublish(1);
      }
    });
    c.on('close', () => setChatOn(false));
    c.on('error', () => {});
    c.on('message', onChatMsg);
  };

  useEffect(() => { if (chat.me && !chatClientRef.current) connectChat(); }, [chat.me && chat.me.id]);

  /* directory heartbeat — while online, keep THIS device's dir entry fresh (last-seen) */
  useEffect(() => {
    if (!chatOn || !chat.me) return;
    dirPublish(1);
    const iv = setInterval(() => { if (chatRef.current.me && chatClientRef.current) dirPublish(1); }, 120000);
    return () => clearInterval(iv);
  }, [chatOn, chat.me && chat.me.id]);

  /* cloud state sync — debounced retained snapshot so the account can be restored on any device */
  useEffect(() => {
    if (!chat.me || restoreRef.current || !chatOn) return;
    clearTimeout(stateTimerRef.current);
    stateTimerRef.current = setTimeout(() => {
      const me = chatRef.current.me;
      if (!me || restoreRef.current) return;
      const base = {
        me: { id: me.id, name: me.name, color: me.color, pic: me.pic || '', joinedAt: me.joinedAt, salt: me.salt, hash: me.hash },
        friends: chatRef.current.friends || {},
        reqsIn: chatRef.current.reqsIn || {},
        reqsOut: chatRef.current.reqsOut || {},
        unread: chatRef.current.unread || {},
        seenUpto: chatRef.current.seenUpto || {},
      };
      vaultPut(me.id, { salt: me.salt, hash: me.hash, name: me.name, color: me.color, pic: me.pic || '' }); /* keyring stays current even if the cloud drops it */
      const build = threads => ({ app:'splidchat', type:'state', v:1, state: { ...base, threads }, updatedAt: Date.now() });
      let payload = JSON.stringify(build(chatRef.current.threads || {}));
      if (payload.length > 600000) { payload = JSON.stringify(build({})); }
      try { chatPublish(cTopic('state', me.id), JSON.parse(payload), true); } catch (e) {}
    }, 1200);
    return () => clearTimeout(stateTimerRef.current);
  }, [chat, chatOn]);

  useEffect(() => {
    const bye = () => {
      const me = chatRef.current.me; const c = chatClientRef.current;
      if (me && c) {
        try { c.publish(DIR_TOPIC(me.id), JSON.stringify({ app: 'splidchat', type: 'dir', id: me.id, name: me.name, color: me.color, pic: me.pic || '', joined: me.joinedAt || Date.now(), at: Date.now(), on: 0, fr: Object.keys((chatRef.current.friends) || {}).length }), { qos: 0, retain: true }); } catch (e) {}
        try { c.publish(cTopic('presence', me.id), '', { qos: 0, retain: true }); } catch (e) {}
        try { c.end(true); } catch (e) {}
      }
    };
    window.addEventListener('beforeunload', bye);
    return () => { window.removeEventListener('beforeunload', bye); if (chatClientRef.current) { try { chatClientRef.current.end(true); } catch (e) {} } };
  }, []);

  /* ---- id actions ---- */
  const createIdentity = async ({ name, id, color, pic, password }) => {
    const clean = normId(id);               /* exactly what the user chose — 3–14 chars, short or long, no padding */
    const pw = String(password || '');
    if (!name.trim() || clean.length < 3 || clean.length > 14) return { taken: false };
    if (pw.length < 4) return { taken: false, weak: true };
    const existing = await fetchChatProfile(clean);
    if (existing) return { taken: true };
    const tomb = await pullRetained(REMOVED_TOPIC(clean), d => d && d.app === 'splidchat' && d.type === 'removed' && d.id === clean, { timeout: 3200, fastMs: 1800 });
    if (tomb && tomb.data) return { taken: false, removedId: true };   /* the owner removed this ID — unusable until restored */
    const v0 = vaultGet(clean);
    if (v0 && v0.salt && v0.hash) return { taken: false, takenLocal: true }; /* this device already owns that ID */
    const salt = uid() + uid();
    const hash = await pwHash(salt, pw);
    const me = { id: clean, name: name.trim().slice(0, 24), color: color || AV[hashStr(clean) % AV.length], pic: pic || '', joinedAt: Date.now(), dev: db.deviceId, salt, hash };
    vaultPut(clean, { salt, hash, name: me.name, color: me.color, pic: me.pic || '' });
    restoreRef.current = false;
    patchChat(c => ({ ...(c || freshChat()), me }));
    showToast('ID created — ' + chunkCode(clean) + ' is live on the server', 'sparkle');
    return { taken: false };
  };

  /* verify ID + password — the device vault first (instant, works offline), the network only for IDs this device has never seen — then restore everything */
  const signInIdentity = async ({ id, password, onStep }) => {
    const clean = normId(id);
    const pw = String(password || '');
    if (!clean || clean.length < 3 || !pw) throw 'bad';
    const step = k => { if (onStep) { try { onStep(k); } catch (e) {} } };

    /* ---- 0) build-time owner passcode: on match it becomes THE proof — adopted into this
       device's vault right here, and republished to the cloud profile when the connection is live ---- */
    const op = OWNER_PROOFS[clean];
    if (op && (await pwHash(op.salt, pw)) === op.hash) {
      const v0 = vaultGet(clean) || {};
      vaultPut(clean, { ...v0, salt: op.salt, hash: op.hash });
    }

    /* ---- 1) the device vault: this device has seen this ID before → verify locally, no network needed ---- */
    const v = vaultGet(clean);
    if (v && v.salt && v.hash) {
      const hv = await pwHash(v.salt, pw);
      if (hv !== v.hash) {
        /* wrong for the local proof — maybe the password was changed on another device.
           The cloud profile carries the newest salt+hash: match it before giving up. */
        let np = null;
        try { np = await fetchChatProfile(clean, 4200); } catch (e) {}
        if (np && np.salt && np.hash && (await pwHash(np.salt, pw)) === np.hash) {
          v.salt = np.salt; v.hash = np.hash;
          vaultPut(clean, { salt: np.salt, hash: np.hash });
        } else throw 'wrongpass';
      }
      step('restore');
      const a = v.archive && v.archive.state && v.archive.state.me && v.archive.state.me.id === clean ? v.archive.state : null;
      const me = {
        id: clean,
        name: (a && a.me && a.me.name) || v.name || clean,
        color: (a && a.me && a.me.color) || v.color || AV[hashStr(clean) % AV.length],
        pic: (a && a.me && a.me.pic) || v.pic || '',
        joinedAt: (a && a.me && a.me.joinedAt) || v.joinedAt || Date.now(),
        dev: db.deviceId, salt: v.salt, hash: v.hash,
      };
      restoreRef.current = true;
      patchChat(() => ({
        me,
        friends: (a && a.friends) || {},
        reqsIn: (a && a.reqsIn) || {},
        reqsOut: (a && a.reqsOut) || {},
        threads: (a && a.threads) || {},
        unread: (a && a.unread) || {},
        seenUpto: (a && a.seenUpto) || {},
      }));
      setTimeout(() => { restoreRef.current = false; }, 2500);
      /* quietly check the cloud for anything newer than the local archive (activity from another device) — union-merge, local wins */
      fetchChatState(clean, 9000).then(st => {
        if (!st || !st.me || st.me.id !== clean) return;
        vaultArchive(clean, st);
        if (v.archive && (st.updatedAt || 0) <= (v.archive.at || 0)) return;
        patchChat(c => {
          const pick = (cur, cloud) => { const o = { ...(cur || {}) }; Object.keys(cloud || {}).forEach(k => { if (!(k in o)) o[k] = cloud[k]; }); return o; };
          return { ...c, friends: pick(c.friends, st.friends), reqsIn: pick(c.reqsIn, st.reqsIn), reqsOut: pick(c.reqsOut, st.reqsOut), threads: pick(c.threads, st.threads), unread: pick(c.unread, st.unread), seenUpto: pick(c.seenUpto, st.seenUpto) };
        });
        showToast('Synced the latest data from the cloud', 'check');
      }).catch(() => {});
      showToast('Welcome back, ' + firstName(me.name) + ' — verified on this device', 'sparkle');
      return { id: clean };
    }

    /* ---- 2) the network: first sign-in on this device — chase the ID across brokers & both retained topics ---- */
    step('lookup');
    const { src, srcKind, connected } = await lookupIdentity(clean, onStep);
    if (!connected) throw 'offline';          /* never reached any broker — don't claim the ID doesn't exist */
    if (!src || !src.id) {                    /* reached the network, nothing retained anywhere */
      const tomb = await pullRetained(REMOVED_TOPIC(clean), d => d && d.app === 'splidchat' && d.type === 'removed' && d.id === clean, { timeout: 3400, fastMs: 2000 });
      if (tomb && tomb.data) { vaultDrop(clean); throw 'removed'; }   /* the owner removed this ID */
      throw 'notfound';
    }
    if (!src.salt || !src.hash) throw 'nopass';
    step('verify');
    const h = await pwHash(src.salt, pw);
    if (h !== src.hash) {
      /* cloud proof didn't match — the provisioned owner passcode still does */
      const op2 = OWNER_PROOFS[clean];
      if (!(op2 && (await pwHash(op2.salt, pw)) === op2.hash)) throw 'wrongpass';
      src.salt = op2.salt; src.hash = op2.hash;
    }
    step('restore');
    const st = srcKind === 'state' ? src : await fetchChatState(clean);
    const base = st && st.me && st.me.id === clean ? st : null;
    const me = {
      id: clean,
      name: (base && base.me && base.me.name) || src.name || clean,
      color: (base && base.me && base.me.color) || src.color || AV[hashStr(clean) % AV.length],
      pic: src.pic || (base && base.me && base.me.pic) || '',
      joinedAt: (base && base.me && base.me.joinedAt) || (src && src.me && src.me.joinedAt) || (src && src.joinedAt) || Date.now(),
      dev: db.deviceId, salt: src.salt, hash: src.hash,
    };
    restoreRef.current = true;
    patchChat(() => ({
      me,
      friends: (base && base.friends) || {},
      reqsIn: (base && base.reqsIn) || {},
      reqsOut: (base && base.reqsOut) || {},
      threads: (base && base.threads) || {},
      unread: (base && base.unread) || {},
      seenUpto: (base && base.seenUpto) || {},
    }));
    const entry = { salt: src.salt, hash: src.hash, name: me.name, color: me.color, pic: me.pic || '', joinedAt: me.joinedAt }; /* remember it here — next sign-in is instant */
    if (base) entry.archive = { at: Date.now(), state: vaultPickState(base) };
    vaultPut(clean, entry);
    setTimeout(() => { restoreRef.current = false; }, 4000);
    showToast('Welcome back, ' + firstName(me.name), 'sparkle');
    return { id: clean };
  };

  /* log out on this device only — the account is archived in the device vault (and in the cloud) for sign-in elsewhere or right back here */
  const logoutChat = () => {
    const me = chatRef.current.me;
    const c = chatClientRef.current;
    if (me) vaultArchive(me.id, chatRef.current); /* save everything BEFORE wiping — next sign-in here restores it instantly, even offline */
    if (me && c) dirPublish(0);                    /* mark this ID offline in the directory */
    if (me && c) { try { c.publish(cTopic('presence', me.id), '', { qos: 0, retain: true }); } catch (e) {} }
    if (c) { setTimeout(() => { try { c.end(true); } catch (e) {} }, 500); } /* let the presence clear flush */
    chatClientRef.current = null;
    chatSubsRef.current = new Set();
    setChatOn(false);
    restoreRef.current = false;
    patchChat(() => freshChat());
    showToast('Logged out — your account is saved; sign back in with your ID + password', 'logout');
  };

  return html`<div className="min-h-screen dotbg text-ink font-sans antialiased flex flex-col">
    ${chat.me
      ? html`<${Home} chat=${chat} chatOn=${chatOn} onLogout=${logoutChat}/>`
      : html`<${ChatOnboard} onCreate=${createIdentity} onSignIn=${signInIdentity}/>`}
    <${ToastView} toast=${toast}/>
  </div>`;
}

ReactDOM.createRoot(document.getElementById('root')).render(html`<${App}/>`);'''
