"""One adapter class per website. login() must return a session dict
(cookies/token) and must never keep or log the password."""

class LoginFailed(Exception):
    pass

class SubsGigsAdapter:
    slug = "subsgigs"
    name = "SubsGigs"

    async def login(self, username: str, password: str) -> dict:
        # NOT IMPLEMENTED ON PURPOSE: the real login request has not been
        # inspected or tested yet. Fill this in once the login request
        # (URL, fields, cookies/token returned) is confirmed.
        raise NotImplementedError("SubsGigs login not implemented yet")

ADAPTERS = {"subsgigs": SubsGigsAdapter()}
