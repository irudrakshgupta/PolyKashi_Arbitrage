"""
DNS override for Polymarket.

Your ISP's resolver returns 49.44.79.236 (wrong) for Polymarket domains.
Real Cloudflare IPs: 104.18.34.205 / 172.64.153.51

Fix: monkey-patch socket.getaddrinfo so the hostname still flows through to
TLS SNI (keeping the SSL handshake valid) while the TCP connection goes to
the correct IP — all without touching /etc/hosts or needing sudo.
"""
import socket
import urllib.request
import json

# ── Known-good IPs (from Cloudflare's own 1.1.1.1 DoH) ───────────────────────
_OVERRIDE: dict[str, str] = {
    "clob.polymarket.com":      "172.64.153.51",
    "gamma-api.polymarket.com": "172.64.153.51",
}

_original_getaddrinfo = socket.getaddrinfo


def _resolve_doh(hostname: str) -> str:
    """Resolve hostname via Cloudflare DNS-over-HTTPS (1.1.1.1)."""
    try:
        url = f"https://1.1.1.1/dns-query?name={hostname}&type=A"
        req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        for ans in data.get("Answer", []):
            if ans.get("type") == 1:
                return ans["data"]
    except Exception:
        pass
    return ""


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """
    Intercept DNS for known Polymarket domains and return the correct IP.
    Everything else passes through to the real resolver.
    """
    if isinstance(host, str) and host in _OVERRIDE:
        ip = _OVERRIDE[host]
        # Build the same structure getaddrinfo normally returns:
        # (family, socktype, proto, canonname, sockaddr)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    return _original_getaddrinfo(host, port, family, type, proto, flags)


def _refresh_override_map():
    """Re-resolve via DoH and update the override map."""
    for domain in list(_OVERRIDE.keys()):
        ip = _resolve_doh(domain)
        if ip:
            _OVERRIDE[domain] = ip
            print(f"  [DNS fix] {domain} → {ip}  (via DoH)")
        else:
            print(f"  [DNS fix] {domain} → {_OVERRIDE[domain]}  (fallback)")


def install():
    """
    Patch socket.getaddrinfo globally.  Call once at startup.
    Safe to call multiple times (idempotent).
    """
    _refresh_override_map()
    socket.getaddrinfo = _patched_getaddrinfo


def patched_session():
    """
    Return a requests.Session that benefits from the DNS override.
    install() must have been called first (or call it here).
    """
    import requests
    install()
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    return s


# ── Auto-install on import ────────────────────────────────────────────────────
install()
