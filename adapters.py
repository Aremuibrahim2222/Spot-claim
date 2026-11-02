"""One adapter per platform. Nothing is marked ready until its real
login/claim flow has been inspected and tested."""
from urllib.parse import urlparse


class BaseAdapter:
    slug = ""
    name = ""
    domain = ""
    ready = False  # flip to True only after login() is implemented and tested

    async def login(self, username: str, password: str) -> dict:
        """Log in once. Return a session dict (cookies/token). Never keep the password."""
        raise NotImplementedError

    async def revoke(self, session: dict) -> None:
        """Log out / revoke on the platform if it supports it."""
        return None


class SubsGigsAdapter(BaseAdapter):
    slug = "subsgigs"
    name = "SubsGigs"
    domain = "subsgigs-alpha.vercel.app"
    ready = False  # login endpoint and claim flow not yet inspected/tested

    async def login(self, username, password):
        raise NotImplementedError("SubsGigs login flow not implemented yet")


REGISTRY = {a.domain: a for a in (SubsGigsAdapter(),)}
BY_SLUG = {a.slug: a for a in REGISTRY.values()}


def normalize(url: str):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    if not p.netloc or "." not in p.netloc or " " in url:
        return None
    return p.netloc.lower().removeprefix("www.")


def lookup(domain: str):
    return REGISTRY.get(domain)
