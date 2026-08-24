"""Zoho Desk over REST, with two separate clients.

`Reader` sends GET only. `Writer` may reach exactly five endpoints, each with
fixed body keys, and the check sits inside the one request method, so no
convenience method can get around it:

* POST /tickets/{id}/associateTag    tags with the desk's prefix only
* POST /tickets/{id}/comments        private notes only (isPublic false), carrying the desk marker
* PATCH /tickets/{id}                one configured custom field (the desk case number) only
* POST /tickets/{id}/draftReply      an unsent EMAIL draft carrying the desk marker
* POST /uploads                      a file for that draft

There is no send, close, assign, status, priority or delete call anywhere.
The stop switch and the helpdesk mode are read inside the request method at
the moment of writing, never from settings saved with a run.

OAuth uses Zoho self clients (refresh token grant), one for reading and a
separate one for writing. Tokens are cached in the hub's private data folder
with mode 0600.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

TIMEOUT = 30.0
RETRIES = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
EARLY_EXPIRY = 120
SLEEP: Callable[[float], None] = time.sleep
MARKER_RE = re.compile(r"hubzoid-customer-desk:[0-9a-f]{16}")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")
DRAFT_KEYS = {"channel", "content", "contentType", "fromEmailAddress", "to", "inReplyToThreadId", "attachmentIds"}
_LOCK = threading.Lock()
_TOKENS: dict[str, dict] = {}
_ORGS: dict[str, str] = {}


class ZohoError(Exception):
    def __init__(self, status: int, code: str, message: str, *, path: str = ""):
        super().__init__(f"Zoho Desk {status} {code} on {path}: {message}")
        self.status, self.code, self.message, self.path = status, code, message, path


class WriteRefused(Exception):
    """The guard refused a write. Nothing was sent."""


class WritesBlocked(Exception):
    """The stop switch or the mode blocks writes right now. Nothing was sent."""


def marker(ticket_id: str, key: str) -> str:
    return "hubzoid-customer-desk:" + hashlib.sha256(f"{ticket_id}:{key}".encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str
    refresh_token: str
    api_base: str
    accounts_base: str
    org_id: str = ""

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.client_id}:{self.refresh_token}".encode()).hexdigest()[:16]


def _redact(text: str) -> str:
    text = re.sub(r"1000\.[0-9a-f]+\.[0-9a-f]+", "[token]", text or "")
    return re.sub(r"(refresh_token|client_secret|access_token)=[^&\s]+", r"\1=[redacted]", text)


def stop_switch(hub_dir: Path) -> str | None:
    """Why writes are blocked right now, or None. Read at the moment of each write."""
    if os.environ.get("DESK_STOP_WRITES", "").strip().lower() in ("1", "true", "yes", "on"):
        return "DESK_STOP_WRITES is set"
    from ..store import db_path

    if (db_path(hub_dir).parent / "STOP_WRITES").exists():
        return "the STOP_WRITES file is present"
    return None


class _Base:
    def __init__(self, creds: Credentials, *, state_dir: Path, transport: httpx.BaseTransport | None = None):
        self.creds = creds
        self.state_dir = Path(state_dir)
        self.http = httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=transport)

    # -- OAuth ----------------------------------------------------------------------
    def _token_file(self) -> Path:
        return self.state_dir / f"zoho-token-{self.creds.key}.json"

    def _token(self, force: bool = False) -> str:
        with _LOCK:
            now = time.time()
            cached = _TOKENS.get(self.creds.key)
            if not force and cached and cached["expires_at"] - EARLY_EXPIRY > now:
                return cached["access_token"]
            f = self._token_file()
            if not force and f.is_file():
                try:
                    data = json.loads(f.read_text())
                    if data["expires_at"] - EARLY_EXPIRY > now:
                        _TOKENS[self.creds.key] = data
                        return data["access_token"]
                except (ValueError, KeyError):
                    pass
            resp = self.http.post(f"{self.creds.accounts_base.rstrip('/')}/oauth/v2/token",
                                  data={"grant_type": "refresh_token", "client_id": self.creds.client_id,
                                        "client_secret": self.creds.client_secret,
                                        "refresh_token": self.creds.refresh_token})
            try:
                body = resp.json()
            except ValueError:
                body = {}
            if resp.status_code != 200 or "access_token" not in body:
                raise ZohoError(resp.status_code, "auth_failed", _redact(str(body.get("error", "no token")))[:160],
                                path="/oauth/v2/token")
            data = {"access_token": body["access_token"], "expires_at": now + int(body.get("expires_in", 3600))}
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.chmod(tmp, 0o600)
            os.replace(tmp, f)
            _TOKENS[self.creds.key] = data
            return data["access_token"]

    def _org(self) -> str:
        if self.creds.org_id:
            return self.creds.org_id
        if self.creds.key in _ORGS:
            return _ORGS[self.creds.key]
        body = self._request("GET", "/organizations", with_org=False) or {}
        orgs = body.get("data") or []
        if not orgs:
            raise ZohoError(404, "no_organization", "The account has no Zoho Desk organization.", path="/organizations")
        _ORGS[self.creds.key] = str(orgs[0]["id"])
        return _ORGS[self.creds.key]

    # -- the one request method -------------------------------------------------------
    def _guard(self, method: str, path: str, body) -> None:
        if method != "GET":
            raise WriteRefused(f"The read client never sends {method}.")

    def _request(self, method: str, path: str, *, params: dict | None = None, body=None, files=None,
                 with_org: bool = True, retry: bool = True):
        self._guard(method, path, body)
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        url = self.creds.api_base.rstrip("/") + path
        refreshed = False
        attempts = RETRIES if retry else 1
        last: Exception | None = None
        for attempt in range(attempts):
            headers = {"Authorization": f"Zoho-oauthtoken {self._token(force=refreshed)}"}
            if with_org:
                headers["orgId"] = self._org()
            try:
                resp = self.http.request(method, url, params=params, headers=headers,
                                         json=body if files is None else None, files=files)
            except httpx.HTTPError as exc:
                last = exc
                if not retry:
                    raise ZohoError(0, "transport_error", type(exc).__name__, path=path) from None
                SLEEP(min(2 ** attempt, 10))
                continue
            if resp.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if resp.status_code in RETRY_STATUS and retry and attempt + 1 < attempts:
                wait = resp.headers.get("Retry-After", "")
                SLEEP(min(max(float(wait) if wait.isdigit() else 0, 2 ** attempt - 1), 30))
                continue
            if resp.status_code == 204:
                return None
            if resp.status_code >= 400:
                try:
                    detail = resp.json()
                except ValueError:
                    detail = {}
                raise ZohoError(resp.status_code, str(detail.get("errorCode") or "error"),
                                _redact(str(detail.get("message") or ""))[:160], path=path)
            try:
                return resp.json()
            except ValueError:
                raise ZohoError(resp.status_code, "protocol_error", "The answer was not JSON.", path=path) from None
        raise ZohoError(0, "unavailable", _redact(str(last))[:160] if last else "retries exhausted", path=path)


class Reader(_Base):
    """GET only."""

    def ticket(self, ticket_id: str) -> dict:
        return self._request("GET", f"/tickets/{int(ticket_id)}", params={"include": "contacts"})

    def threads(self, ticket_id: str) -> list[dict]:
        body = self._request("GET", f"/tickets/{int(ticket_id)}/threads",
                             params={"limit": 200, "sortBy": "-sendDateTime"}) or {}
        return body.get("data") or []

    def thread(self, ticket_id: str, thread_id: str) -> dict:
        return self._request("GET", f"/tickets/{int(ticket_id)}/threads/{int(thread_id)}",
                             params={"include": "plainText"})

    def tags(self, ticket_id: str) -> list[str]:
        body = self._request("GET", f"/tickets/{int(ticket_id)}/tags") or {}
        return [t.get("name") for t in body.get("tags") or [] if t.get("name")]

    def comments(self, ticket_id: str) -> list[dict]:
        body = self._request("GET", f"/tickets/{int(ticket_id)}/comments", params={"limit": 100}) or {}
        return body.get("data") or []

    def modified(self, start: str, end: str, *, offset: int = 0, limit: int = 100,
                 department_id: str | None = None) -> list[dict]:
        if offset > 4900:
            raise ZohoError(400, "offset_limit", "Zoho search cannot page past 5000. Narrow the window.",
                            path="/tickets/search")
        body = self._request("GET", "/tickets/search", params={"modifiedTimeRange": f"{start},{end}",
                                                               "sortBy": "modifiedTime", "limit": limit,
                                                               "from": offset, "departmentId": department_id})
        return (body or {}).get("data") or []


@dataclass(frozen=True)
class WritePolicy:
    mode: str                 # shadow or live
    tag_prefix: str
    shadow_prefix: str = "shadow-"
    allow_drafts: bool = False
    case_field: str | None = None

    @property
    def effective_prefix(self) -> str:
        return (self.shadow_prefix + self.tag_prefix) if self.mode == "shadow" else self.tag_prefix

    def check(self, method: str, path: str, body) -> None:
        if self.mode not in ("shadow", "live"):
            raise WriteRefused(f"Helpdesk mode {self.mode} writes nothing.")
        if method == "POST" and re.fullmatch(r"/tickets/\d+/associateTag", path):
            tags = (body or {}).get("tags")
            if set(body or {}) != {"tags"} or not tags or not isinstance(tags, list):
                raise WriteRefused("associateTag takes exactly {tags: [...]}.")
            for t in tags:
                if not isinstance(t, str) or not TAG_RE.match(t) or not t.startswith(self.effective_prefix):
                    raise WriteRefused(f"Tag {t!r} is not one of the desk's own {self.effective_prefix}* tags.")
            return
        if method == "POST" and re.fullmatch(r"/tickets/\d+/comments", path):
            if self.mode != "live":
                raise WriteRefused("Private notes are written only in live mode.")
            b = body or {}
            if set(b) != {"isPublic", "contentType", "content"} or b.get("isPublic") is not False:
                raise WriteRefused("A comment must be a private note: {isPublic: false, contentType, content}.")
            if b.get("contentType") not in ("plainText", "html") or not MARKER_RE.search(b.get("content") or ""):
                raise WriteRefused("A private note must carry the desk marker.")
            return
        if method == "PATCH" and re.fullmatch(r"/tickets/\d+", path):
            if self.mode != "live" or not self.case_field:
                raise WriteRefused("Ticket fields are written only in live mode with ZOHO_DESK_CASE_FIELD set.")
            b = body or {}
            if set(b) != {"cf"} or set(b["cf"]) != {self.case_field} or not re.fullmatch(r"[A-Z]{2,6}-\d{6}",
                                                                                          str(b["cf"][self.case_field])):
                raise WriteRefused(f"Only the custom field {self.case_field} may be set, to a desk case number.")
            return
        if method == "POST" and re.fullmatch(r"/tickets/\d+/draftReply", path):
            if self.mode != "live" or not self.allow_drafts:
                raise WriteRefused("Draft replies need live mode and DESK_HELPDESK_DRAFTS.")
            b = body or {}
            if not set(b) <= DRAFT_KEYS or b.get("channel") != "EMAIL":
                raise WriteRefused(f"A draft reply takes only {sorted(DRAFT_KEYS)} on the EMAIL channel.")
            if not b.get("fromEmailAddress") or not b.get("content") or not MARKER_RE.search(b["content"]):
                raise WriteRefused("A draft reply needs a from address and content carrying the desk marker.")
            return
        if method == "POST" and path == "/uploads":
            if self.mode != "live" or not self.allow_drafts:
                raise WriteRefused("Uploads are only for live draft replies.")
            return
        raise WriteRefused(f"The desk never calls {method} {path}.")


class Writer(Reader):
    """The write client. Its guard is the only way out."""

    def __init__(self, creds: Credentials, policy: WritePolicy, *, hub_dir: Path, state_dir: Path,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(creds, state_dir=state_dir, transport=transport)
        self.policy, self.hub_dir = policy, Path(hub_dir)

    def _guard(self, method: str, path: str, body) -> None:
        if method == "GET":
            return
        blocked = stop_switch(self.hub_dir)
        if blocked:
            raise WritesBlocked(f"Helpdesk writes are stopped: {blocked}.")
        self.policy.check(method, path, body)

    def associate_tags(self, ticket_id: str, tags: list[str]):
        return self._request("POST", f"/tickets/{int(ticket_id)}/associateTag", body={"tags": sorted(set(tags))},
                             retry=False)

    def private_note(self, ticket_id: str, content: str):
        return self._request("POST", f"/tickets/{int(ticket_id)}/comments",
                             body={"isPublic": False, "contentType": "plainText", "content": content}, retry=False)

    def set_case_field(self, ticket_id: str, case_number: str):
        return self._request("PATCH", f"/tickets/{int(ticket_id)}", body={"cf": {self.policy.case_field: case_number}},
                             retry=False)

    def upload(self, name: str, data: bytes, media_type: str):
        return self._request("POST", "/uploads", files={"file": (name, data, media_type)}, retry=False)

    def draft_reply(self, ticket_id: str, *, from_address: str, to: str, html: str, in_reply_to: str | None,
                    attachment_ids: list[str] | None = None):
        body = {"channel": "EMAIL", "fromEmailAddress": from_address, "to": to, "content": html,
                "contentType": "html"}
        if in_reply_to:
            body["inReplyToThreadId"] = in_reply_to
        if attachment_ids:
            body["attachmentIds"] = attachment_ids
        return self._request("POST", f"/tickets/{int(ticket_id)}/draftReply", body=body, retry=False)


def credentials(hub_dir: Path, values: dict, *, write: bool) -> Credentials:
    """From the hub's secret settings. Raises KeyError naming the missing one."""
    from hubzoid.hubs import settings as hub_settings
    from hubzoid import secretstore

    prefix = "ZOHO_DESK_WRITE_" if write else "ZOHO_DESK_"
    got = {}
    for name in ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"):
        key = prefix + name
        ref = hub_settings.secret_ref(Path(hub_dir), key) or f"env:{key}"
        try:
            got[name] = secretstore.resolve(ref, hub_dir)
        except Exception:  # noqa: BLE001 - name the setting, never a value
            raise KeyError(key) from None
    return Credentials(client_id=got["CLIENT_ID"], client_secret=got["CLIENT_SECRET"],
                       refresh_token=got["REFRESH_TOKEN"], api_base=values["ZOHO_DESK_API_BASE"],
                       accounts_base=values["ZOHO_DESK_ACCOUNTS_BASE"], org_id=values.get("ZOHO_DESK_ORG_ID") or "")


def reset_caches() -> None:
    _TOKENS.clear()
    _ORGS.clear()
