"""
Assembles the single-page app — one HTML document built entirely from the
embedded Python modules in this package:

    vendor_tailwind / vendor_react / vendor_reactdom / vendor_htm
        the vendored libraries (zero CDN, zero internet needed)
    head_js.TAILWIND_CONFIG_JS
        the design tokens
    theme.CSS
        the stylesheet
    shim_js.MQTT_SHIM_JS
        the live-bus shim (Python backend transport)
    app_js.APP_JS
        the application itself

If a vendored module is ever missing, the page falls back to the original
CDN script tags, so the file degrades gracefully.
"""

from . import app_js, head_js, shim_js, theme

FAVICON_SVG = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Crect width='64' height='64' rx='14' fill='%23F6F1E8'/%3E"
    "%3Cpath d='M32 12c11.6 0 21 7.8 21 17.4S43.6 46.8 32 46.8c-2.5 0-4.9-.4-7.1-1.1L15 51"
    "l3.4-9.6C14.4 38 12 34 12 29.4 12 19.8 20.4 12 32 12z' fill='%23E14B4F'/%3E"
    "%3Ccircle cx='24' cy='29.4' r='2.2' fill='%23FCF9F3'/%3E"
    "%3Ccircle cx='32' cy='29.4' r='2.2' fill='%23FCF9F3'/%3E"
    "%3Ccircle cx='40' cy='29.4' r='2.2' fill='%23FCF9F3'/%3E%3C/svg%3E"
)

CDN_FALLBACK = {
    "tailwind": '<script src="https://cdn.tailwindcss.com"></script>',
    "react": '<script crossorigin src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>',
    "reactdom": '<script crossorigin src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>',
    "htm": '<script src="https://unpkg.com/htm@3.1.1/dist/htm.umd.js"></script>',
}


def _script(js_or_none, cdn_key):
    if js_or_none:
        return "<script>\n" + js_or_none + "\n</script>"
    return CDN_FALLBACK[cdn_key]


def render_page(cfg):
    """Return the complete HTML document as a str."""
    try:
        from . import vendor_tailwind
        tailwind_tag = _script(getattr(vendor_tailwind, "TAILWIND_PLAY_JS", ""), "tailwind")
    except ImportError:
        tailwind_tag = CDN_FALLBACK["tailwind"]
    try:
        from . import vendor_react
        react_tag = _script(getattr(vendor_react, "REACT_UMD_JS", ""), "react")
    except ImportError:
        react_tag = CDN_FALLBACK["react"]
    try:
        from . import vendor_reactdom
        reactdom_tag = _script(getattr(vendor_reactdom, "REACT_DOM_UMD_JS", ""), "reactdom")
    except ImportError:
        reactdom_tag = CDN_FALLBACK["reactdom"]
    try:
        from . import vendor_htm
        htm_tag = _script(getattr(vendor_htm, "HTM_UMD_JS", ""), "htm")
    except ImportError:
        htm_tag = CDN_FALLBACK["htm"]

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="UTF-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>\n'
        '<meta name="theme-color" content="#F6F1E8"/>\n'
        '<meta name="description" content="Syncro — a live ID network. Make an ID, keep your '
        'pictures and your whole history safe on one Python server."/>\n'
        '<title>Syncro · your live ID</title>\n'
        f'<link rel="icon" href="{FAVICON_SVG}"/>\n'
        + tailwind_tag + "\n"
        + "<script>\n" + head_js.TAILWIND_CONFIG_JS + "\n</script>\n"
        '<link rel="preconnect" href="https://fonts.googleapis.com"/>\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300..700'
        '&family=Instrument+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>\n'
        "<style>\n" + theme.CSS + "\n</style>\n"
        '</head>\n<body class="bg-paper text-ink font-sans antialiased">\n'
        '<div id="root"></div>\n'
        '<noscript>This app needs JavaScript to run.</noscript>\n'
        + react_tag + "\n" + reactdom_tag + "\n" + htm_tag + "\n"
        + "<script>\n" + shim_js.MQTT_SHIM_JS + "\n</script>\n"
        + "<script>\n" + app_js.APP_JS + "\n</script>\n"
        "</body>\n</html>\n"
    )
