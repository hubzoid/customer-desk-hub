"""A fake Zoho Desk for tests and the local demo. A test double written for
this hub, loopback only, clearly labelled, never a production helpdesk.

It speaks the parts of the Zoho Desk REST API the desk uses: the OAuth
refresh grant, organizations, tickets, threads, tags, comments, ticket field
updates, draft replies, uploads and the modified-ticket search. Writes check
the client's scope. Every request is logged, and any call outside that list
is answered 405 and recorded in `forbidden`, so a test can assert the desk
never tried to send, close or assign.

It also has a small read-only page at `/` that shows each ticket the way an
agent would see it in Zoho Desk: threads, unsent drafts, private notes, tags
and fields. Test and demo controls live under `/_fake/`.
"""
from __future__ import annotations

import html
import itertools
import json
import re
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

READ_SCOPE = "Desk.tickets.READ,Desk.basic.READ"
WRITE_SCOPE = "Desk.tickets.READ,Desk.tickets.CREATE,Desk.tickets.UPDATE,Desk.basic.READ"
ORG_ID = "70000001"


_LAST = [0.0]
_CLOCK = threading.Lock()


def _now() -> str:
    """Zoho-style UTC time in milliseconds, strictly increasing, like real thread times."""
    with _CLOCK:
        t = max(time.time(), _LAST[0] + 0.001)
        _LAST[0] = t
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d}Z"


class FakeZoho:
    def __init__(self):
        self.lock = threading.RLock()
        self.clients = {
            "read-client": {"secret": "read-secret", "refresh": "read-refresh", "scope": READ_SCOPE},   # gitleaks:allow
            "write-client": {"secret": "write-secret", "refresh": "write-refresh", "scope": WRITE_SCOPE},  # gitleaks:allow
        }
        self.tokens: dict[str, str] = {}
        self.tickets: dict[str, dict] = {}
        self.threads: dict[str, list[dict]] = {}
        self.tags: dict[str, set] = {}
        self.comments: dict[str, list[dict]] = {}
        self.uploads: dict[str, dict] = {}
        self.requests: list[tuple[str, str]] = []
        self.writes: list[tuple[str, str, dict]] = []
        self.forbidden: list[tuple[str, str]] = []
        self.failures: list[dict] = []
        self.webhook: dict | None = None
        self._ids = itertools.count(1000)
        self.server: ThreadingHTTPServer | None = None

    # -- state helpers ----------------------------------------------------------------
    def _id(self) -> str:
        return str(next(self._ids))

    def add_ticket(self, *, subject: str, text: str, email: str, first: str = "", last: str = "",
                   department_id: str = "1", when: str | None = None, notify: bool = True) -> dict:
        with self.lock:
            tid = str(10_000 + len(self.tickets) + 1)
            number = str(100 + len(self.tickets) + 1)
            when = when or _now()
            self.tickets[tid] = {"id": tid, "ticketNumber": number, "subject": subject, "status": "Open",
                                 "statusType": "Open", "email": email, "departmentId": department_id,
                                 "contact": {"firstName": first, "lastName": last, "email": email},
                                 "createdTime": when, "modifiedTime": when, "assigneeId": None, "cf": {},
                                 "threadCount": 0, "priority": None}
            self.threads[tid] = []
            self.tags[tid] = set()
            self.comments[tid] = []
            self._thread(tid, direction="in", text=text, sender=email, when=when)
        if notify:
            self._notify(tid, "ticket_created")
        return self.tickets[tid]

    def customer_reply(self, ticket_id: str, text: str, *, notify: bool = True) -> dict:
        with self.lock:
            t = self.tickets[ticket_id]
            th = self._thread(ticket_id, direction="in", text=text, sender=t["email"])
        if notify:
            self._notify(ticket_id, "customer_reply")
        return th

    def _thread(self, tid: str, *, direction: str, text: str, sender: str, status: str = "SUCCESS",
                when: str | None = None, extra: dict | None = None) -> dict:
        th = {"id": self._id(), "direction": direction, "status": status, "channel": "EMAIL",
              "fromEmailAddress": sender, "to": self.tickets[tid]["email"] if direction == "out" else "support",
              "summary": re.sub(r"<[^>]+>", " ", text)[:120], "plainText": re.sub(r"<[^>]+>", " ", text),
              "content": text, "createdTime": when or _now(), "isDescriptionThread": not self.threads[tid]}
        th.update(extra or {})
        self.threads[tid].append(th)
        self.tickets[tid]["modifiedTime"] = th["createdTime"]
        self.tickets[tid]["threadCount"] = len([x for x in self.threads[tid] if x["status"] != "DRAFT"])
        return th

    def _notify(self, tid: str, event: str) -> None:
        hook = self.webhook
        if not hook:
            return
        body = json.dumps({"ticketId": tid, "event": event, "firedAt": _now()}).encode()
        req = urllib.request.Request(hook["url"], data=body, method="POST",
                                     headers={"Content-Type": "application/json", hook["header"]: hook["secret"]})

        def go():
            try:
                urllib.request.urlopen(req, timeout=10).read()
            except Exception:  # noqa: BLE001 - a fake: delivery failures are visible in the hub's absence of work
                pass

        threading.Thread(target=go, daemon=True).start()

    def fail(self, method: str, pattern: str, status: int, times: int = 1, *, after: bool = False) -> None:
        """Answer the next matching calls with `status`. With after=True the
        call is carried out first and only its answer is lost."""
        self.failures.append({"method": method, "re": re.compile(pattern), "status": status, "times": times,
                              "after": after})

    def drafts(self, tid: str) -> list[dict]:
        return [t for t in self.threads.get(tid, []) if t["status"] == "DRAFT"]

    # -- server ---------------------------------------------------------------------------
    def start(self, port: int = 0) -> str:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                ctype = self.headers.get("Content-Type") or ""
                if "json" in ctype:
                    try:
                        return json.loads(raw or b"{}")
                    except ValueError:
                        return None
                if "x-www-form-urlencoded" in ctype:
                    return {k: v[0] for k, v in parse_qs(raw.decode()).items()}
                return raw

            def send(self, status, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else
                                                             json.dumps(body).encode())
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def handle_any(self):
                fake._route(self)

            do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = handle_any  # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def env(self, base: str) -> dict:
        return {"ZOHO_DESK_API_BASE": f"{base}/api/v1", "ZOHO_DESK_ACCOUNTS_BASE": base,
                "ZOHO_DESK_CLIENT_ID": "read-client", "ZOHO_DESK_CLIENT_SECRET": "read-secret",
                "ZOHO_DESK_REFRESH_TOKEN": "read-refresh", "ZOHO_DESK_WRITE_CLIENT_ID": "write-client",
                "ZOHO_DESK_WRITE_CLIENT_SECRET": "write-secret", "ZOHO_DESK_WRITE_REFRESH_TOKEN": "write-refresh"}

    # -- routing --------------------------------------------------------------------------
    def _route(self, h) -> None:
        url = urlparse(h.path)
        path, q = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        method = h.command
        body = h._body() if method in ("POST", "PATCH", "PUT") else None
        self.requests.append((method, path))
        if path.startswith("/_fake/") or path == "/" or path.startswith("/ui/"):
            return self._control(h, method, path, q, body)
        injected = None
        for rule in self.failures:
            if rule["times"] > 0 and rule["method"] == method and rule["re"].search(path):
                rule["times"] -= 1
                injected = rule
                break
        if injected and not injected["after"]:
            return h.send(injected["status"], {"errorCode": "INJECTED", "message": "injected failure"})
        if path == "/oauth/v2/token" and method == "POST":
            c = self.clients.get((body or {}).get("client_id"))
            if not c or c["secret"] != body.get("client_secret") or c["refresh"] != body.get("refresh_token"):
                return h.send(400, {"error": "invalid_client"})
            tok = f"1000.{secrets.token_hex(8)}.{secrets.token_hex(8)}"
            self.tokens[tok] = body["client_id"]
            return h.send(200, {"access_token": tok, "expires_in": 3600, "api_domain": "fake", "token_type": "Bearer"})
        auth = (h.headers.get("Authorization") or "").removeprefix("Zoho-oauthtoken ").strip()
        client = self.tokens.get(auth)
        if client is None:
            return h.send(401, {"errorCode": "INVALID_OAUTH", "message": "bad token"})
        if not path.startswith("/api/v1/"):
            return h.send(404, {"errorCode": "URL_NOT_FOUND"})
        api = path[len("/api/v1"):]
        if api == "/organizations" and method == "GET":
            return h.send(200, {"data": [{"id": ORG_ID, "companyName": "Synthetic Meridian Distribution"}]})
        if h.headers.get("orgId") != ORG_ID:
            return h.send(422, {"errorCode": "INVALID_ORG", "message": "orgId header missing"})
        scope = self.clients[client]["scope"]
        result = self._api(method, api, q, body, scope)
        if result is None:
            self.forbidden.append((method, api))
            return h.send(405, {"errorCode": "METHOD_NOT_ALLOWED", "message": "not part of the fake"})
        status, payload = result
        if injected and injected["after"]:
            return h.send(injected["status"], {"errorCode": "INJECTED", "message": "answer lost"})
        h.send(status, payload) if status != 204 else h.send(204, b"")

    def _api(self, method, api, q, body, scope):
        with self.lock:
            if api == "/tickets/search" and method == "GET":
                start, end = (q.get("modifiedTimeRange") or ",").split(",")
                rows = [t for t in self.tickets.values() if (not start or t["modifiedTime"] >= start)
                        and (not end or t["modifiedTime"] <= end)]
                rows.sort(key=lambda t: t["modifiedTime"])
                off, lim = int(q.get("from") or 0), int(q.get("limit") or 50)
                page = rows[off:off + lim]
                return (200, {"data": page, "count": len(rows)}) if page else (204, None)
            if api == "/uploads" and method == "POST":
                if "Desk.tickets.UPDATE" not in scope:
                    return 403, {"errorCode": "SCOPE_MISMATCH"}
                uid = self._id()
                self.uploads[uid] = {"id": uid, "size": len(body or b"")}
                self.writes.append((method, api, {"upload": uid}))
                return 200, {"id": uid, "size": len(body or b"")}
            m = re.fullmatch(r"/tickets/(\d+)(/.*)?", api)
            if not m:
                return None
            tid, rest = m.group(1), m.group(2) or ""
            if tid not in self.tickets:
                return 404, {"errorCode": "RESOURCE_NOT_FOUND"}
            t = self.tickets[tid]
            if rest == "" and method == "GET":
                return 200, t
            if rest == "/threads" and method == "GET":
                return 200, {"data": [{k: v for k, v in th.items() if k not in ("content", "plainText")}
                                      for th in sorted(self.threads[tid], key=lambda x: x["createdTime"], reverse=True)]}
            mt = re.fullmatch(r"/threads/(\d+)", rest)
            if mt and method == "GET":
                th = next((x for x in self.threads[tid] if x["id"] == mt.group(1)), None)
                return (200, th) if th else (404, {"errorCode": "RESOURCE_NOT_FOUND"})
            if rest == "/tags" and method == "GET":
                return 200, {"tags": [{"name": n} for n in sorted(self.tags[tid])]}
            if rest == "/comments" and method == "GET":
                return 200, {"data": self.comments[tid]}
            write_scope = {"/associateTag": "Desk.tickets.CREATE", "/comments": "Desk.tickets.CREATE",
                           "": "Desk.tickets.UPDATE", "/draftReply": "Desk.tickets.UPDATE"}
            if (rest, method) in (("/associateTag", "POST"), ("/comments", "POST"), ("", "PATCH"),
                                  ("/draftReply", "POST")):
                if write_scope[rest] not in scope:
                    return 403, {"errorCode": "SCOPE_MISMATCH", "message": "scope"}
                self.writes.append((method, api, body))
                if rest == "/associateTag":
                    self.tags[tid] |= set(body.get("tags") or [])
                    t["modifiedTime"] = _now()
                    return 200, {"data": [{"name": n} for n in sorted(self.tags[tid])]}
                if rest == "/comments":
                    c = {"id": self._id(), "isPublic": body.get("isPublic"), "content": body.get("content"),
                         "contentType": body.get("contentType"), "commentedTime": _now()}
                    self.comments[tid].append(c)
                    return 200, c
                if rest == "":
                    allowed = {"cf"}
                    if set(body or {}) - allowed:
                        return 422, {"errorCode": "INVALID_DATA"}
                    t["cf"].update(body.get("cf") or {})
                    t["modifiedTime"] = _now()
                    return 200, t
                th = self._thread(tid, direction="out", text=body.get("content") or "",
                                  sender=body.get("fromEmailAddress") or "", status="DRAFT",
                                  extra={"to": body.get("to"), "attachmentIds": body.get("attachmentIds") or []})
                return 200, th
            return None

    # -- the page and the controls -----------------------------------------------------
    def _control(self, h, method, path, q, body):
        if path == "/_fake/tickets" and method == "POST":
            b = body or {}
            t = self.add_ticket(subject=b["subject"], text=b["text"], email=b["email"], first=b.get("first", ""),
                                last=b.get("last", ""), notify=b.get("notify", True))
            return h.send(200, t)
        m = re.fullmatch(r"/_fake/tickets/(\d+)/reply", path)
        if m and method == "POST":
            return h.send(200, self.customer_reply(m.group(1), (body or {})["text"]))
        if path == "/_fake/webhook" and method == "POST":
            self.webhook = body
            return h.send(200, {"ok": True})
        if path == "/_fake/state" and method == "GET":
            return h.send(200, {"tickets": self.tickets, "drafts": {t: self.drafts(t) for t in self.tickets},
                                "tags": {t: sorted(v) for t, v in self.tags.items()}, "comments": self.comments,
                                "writes": self.writes, "forbidden": self.forbidden})
        if path == "/" and method == "GET":
            return h.send(200, self._page(None), "text/html; charset=utf-8")
        m = re.fullmatch(r"/ui/tickets/(\d+)", path)
        if m and method == "GET" and m.group(1) in self.tickets:
            return h.send(200, self._page(m.group(1)), "text/html; charset=utf-8")
        return h.send(404, {"error": "not found"})

    def _page(self, tid: str | None) -> str:
        e = html.escape
        css = ("body{font:14px/1.45 system-ui,sans-serif;margin:0;background:#f4f5f7;color:#1f2430}"
               "header{background:#2c3e50;color:#fff;padding:10px 20px}header b{color:#ffcf5c}"
               "main{padding:16px 20px;max-width:1100px}table{border-collapse:collapse;width:100%;background:#fff}"
               "td,th{border-bottom:1px solid #e3e6ea;padding:8px;text-align:left;vertical-align:top}"
               ".card{background:#fff;border:1px solid #e3e6ea;border-radius:6px;padding:12px;margin:10px 0}"
               ".draft{border-left:4px solid #e6a700}.note{border-left:4px solid #8e44ad;background:#fbf6ff}"
               ".in{border-left:4px solid #2980b9}.tag{display:inline-block;background:#e8eef6;border-radius:10px;"
               "padding:1px 8px;margin:2px;font-size:12px}small{color:#667}pre{white-space:pre-wrap;margin:6px 0}")
        head = (f"<!doctype html><meta charset=utf-8><title>Fake Zoho Desk</title><style>{css}</style>"
                "<header><b>FAKE ZOHO DESK</b> &middot; a local test double for the Customer Desk hub. "
                "Not a real helpdesk. Synthetic data only.</header><main>")
        with self.lock:
            if tid is None:
                rows = "".join(
                    f"<tr><td><a href='/ui/tickets/{t['id']}'>#{e(t['ticketNumber'])}</a></td><td>{e(t['subject'])}</td>"
                    f"<td>{e(t['email'])}</td><td>{e(t['status'])}</td><td>{len(self.drafts(t['id']))}</td>"
                    f"<td>{' '.join(f'<span class=tag>{e(x)}</span>' for x in sorted(self.tags[t['id']]))}</td></tr>"
                    for t in self.tickets.values())
                return head + ("<h2>Tickets</h2><table><tr><th>#</th><th>Subject</th><th>Contact</th><th>Status</th>"
                               f"<th>Unsent drafts</th><th>Tags</th></tr>{rows}</table></main>")
            t = self.tickets[tid]
            parts = [f"<p><a href='/'>&larr; All tickets</a></p><h2>#{e(t['ticketNumber'])} {e(t['subject'])}</h2>",
                     f"<p><small>Contact {e(t['email'])} &middot; Status {e(t['status'])} &middot; Assignee "
                     f"{e(str(t['assigneeId'] or 'none'))} &middot; Fields {e(json.dumps(t['cf']))}</small></p>",
                     "<p>" + " ".join(f"<span class=tag>{e(x)}</span>" for x in sorted(self.tags[tid])) + "</p>"]
            items = [(th["createdTime"], "thread", th) for th in self.threads[tid]]
            items += [(c["commentedTime"], "note", c) for c in self.comments[tid]]
            for _, kind, x in sorted(items, key=lambda i: i[0]):
                if kind == "note":
                    parts.append(f"<div class='card note'><small>Private note (agents only) &middot; "
                                 f"{e(x['commentedTime'])}</small><pre>{e(x['content'] or '')}</pre></div>")
                elif x["status"] == "DRAFT":
                    att = f" &middot; {len(x.get('attachmentIds') or [])} attachment(s)" if x.get("attachmentIds") else ""
                    parts.append(f"<div class='card draft'><small><b>Unsent draft reply</b> to {e(str(x.get('to')))} "
                                 f"from {e(x['fromEmailAddress'])}{att} &middot; {e(x['createdTime'])} &middot; "
                                 f"a person edits and sends it</small><div class=html>{_safe_html(x.get('content') or '')}"
                                 "</div></div>")
                else:
                    parts.append(f"<div class='card {'in' if x['direction'] == 'in' else ''}'><small>"
                                 f"{'Customer' if x['direction'] == 'in' else 'Agent'} &middot; {e(x['fromEmailAddress'])} "
                                 f"&middot; {e(x['createdTime'])}</small><pre>{e(x['plainText'])}</pre></div>")
            return head + "".join(parts) + "</main>"


_ALLOWED = {"p", "br", "ul", "li", "table", "tr", "th", "td", "b", "strong", "em"}


def _safe_html(content: str) -> str:
    """Show a draft's HTML as a helpdesk would, keeping only plain formatting
    tags, without attributes. Everything else is escaped."""
    out = []
    for part in re.split(r"(<[^>]*>)", content):
        m = re.fullmatch(r"<(/?)([a-zA-Z]+)[^>]*>", part)
        if m and m.group(2).lower() in _ALLOWED:
            out.append(f"<{m.group(1)}{m.group(2).lower()}>")
        elif part.startswith("<!--"):
            continue
        else:                       # text between tags is already escaped HTML
            out.append(part.replace("<", "&lt;").replace(">", "&gt;"))
    return "".join(out)


def main() -> None:  # pragma: no cover - the local demo server
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Run the fake Zoho Desk on loopback (test double, synthetic data).")
    ap.add_argument("--port", type=int, default=8724)
    ap.add_argument("--webhook-url", default="")
    ap.add_argument("--webhook-secret-env", default="WEBHOOK_SECRET_ZOHO_DESK")
    args = ap.parse_args()
    fake = FakeZoho()
    base = fake.start(args.port)
    if args.webhook_url:
        fake.webhook = {"url": args.webhook_url, "header": "X-Webhook-Secret",
                        "secret": os.environ.get(args.webhook_secret_env, "")}
    print("FAKE ZOHO DESK (test double, synthetic data) at", base, flush=True)
    threading.Event().wait()


if __name__ == "__main__":  # pragma: no cover
    main()
