"""Design system of the UI — the original stylesheet, embedded verbatim.
Paper background, rust & sage accents, Fraunces display + Instrument Sans."""

# --- embedded stylesheet (extracted from the original index.html) ---
CSS = r'''  *{-webkit-tap-highlight-color:transparent}
  button{touch-action:manipulation}
  html{color-scheme:light}
  :root{--c-paper:246 241 232;--c-card:252 249 243;--c-ink:38 34 27;--c-muted:125 116 99;--c-line:230 220 198;--c-rust:225 75 79;--c-rust-deep:185 53 57;--c-rust-tint:253 233 233;--c-sage:43 182 94;--c-sage-deep:29 138 72;--c-sage-tint:223 246 230}
  ::selection{background:rgb(var(--c-ink));color:rgb(var(--c-paper))}
  .dotbg{
    background-color:rgb(var(--c-paper));
    background-image:radial-gradient(rgba(38,34,27,.12) 1.2px,transparent 1.2px);
    background-size:22px 22px;
  }
  @keyframes livePulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.8)}}
  .live-dot{animation:livePulse 1.6s ease-in-out infinite}
  .numtab{font-variant-numeric:tabular-nums lining-nums}
  .font-display{font-optical-sizing:auto}
  .lbl{display:block;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:rgb(var(--c-muted));margin-bottom:8px}
  .inp{width:100%;background:rgb(var(--c-paper));border:1px solid rgb(var(--c-line));border-radius:12px;padding:10px 14px;font-size:15px;font-weight:500;outline:none;transition:border-color .2s}
  .inp:focus{border-color:rgb(var(--c-ink))}
  .inp::placeholder{color:rgb(var(--c-muted));opacity:.75}

  @keyframes sheetUp{from{transform:translateY(48px) scale(.98);opacity:0}to{transform:none;opacity:1}}
  .sheet-in{animation:sheetUp .36s cubic-bezier(.32,.72,.24,1) both}
  @keyframes rise{from{transform:translateY(10px);opacity:0}to{transform:none;opacity:1}}
  .rise{animation:rise .45s cubic-bezier(.22,.9,.3,1) both}
  @keyframes toastIn{from{transform:translateY(16px);opacity:0}to{transform:none;opacity:1}}
  .toast-in{animation:toastIn .32s cubic-bezier(.2,1.1,.4,1) both}'''
