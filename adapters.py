"""Platform registry. Each supported site gets its own adapter.
Nothing is registered until a real integration is built and tested."""
from urllib.parse import urlparse

# domain -> adapter info. Empty on purpose: no fabricated integrations.
SUPPORTED = {
    # "example.com": {"name": "Example", "auth": "oauth"},
}

def normalize(url: str):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    if not p.netloc or "." not in p.netloc or " " in url:
        return None
    return p.netloc.lower().removeprefix("www.")

def lookup(domain: str):
    return SUPPORTED.get(domain)
