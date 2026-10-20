"""Freshdesk v2. GET reader, namespaced tag/private-note writer, no send API.

Unsent replies use the separately authenticated native editor integration.
REST reply/note operations are never misrepresented as persisted drafts.
"""
from __future__ import annotations

import os
import re
import html
from pathlib import Path

import httpx

from . import zoho
from .retrieval import plain


def ticket_view(raw: dict) -> dict:
    return {**raw, "id": str(raw["id"]), "ticketNumber": str(raw["id"]),
            "departmentId": str(raw.get("group_id") or ""), "productId": str(raw.get("product_id") or ""),
            "statusType": {4: "resolved", 5: "closed"}.get(raw.get("status"), "open"),
            "modifiedTime": raw.get("updated_at"), "createdTime": raw.get("created_at"),
            "email": (raw.get("requester") or {}).get("email") or raw.get("email") or "",
            "contact": {"firstName": (raw.get("requester") or {}).get("name") or ""}}


def thread_view(raw: dict) -> dict:
    return {**raw, "id": str(raw["id"]), "direction": "in" if raw.get("incoming") else "out",
            "createdTime": raw.get("created_at"), "status": "SENT", "private": bool(raw.get("private")),
            "plainText": raw.get("body_text") or plain(raw.get("body") or ""),
            "content": raw.get("body") or raw.get("body_text") or "", "summary": raw.get("body_text") or "",
            "fromEmailAddress": raw.get("from_email") or ""}


class Reader:
    def __init__(self, hub_dir: Path, values: dict, *, transport=None):
        from ..secrets import resolve

        self.hub_dir, self.values = Path(hub_dir), values
        self.base = str(values.get("FRESHDESK_API_BASE") or "").rstrip("/")
        url = httpx.URL(self.base)
        if url.scheme != "https" and not (transport or url.host in ("localhost", "127.0.0.1", "::1")):
            raise ValueError("Freshdesk API base requires HTTPS")
        if os.environ.get("DESK_LOOPBACK_ONLY") == "1" and url.host not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("DESK_LOOPBACK_ONLY refuses external Freshdesk")
        self.http = httpx.Client(timeout=30, follow_redirects=False, transport=transport,
                                 auth=(resolve(hub_dir, "FRESHDESK_API_KEY"), "X"))
        self._threads = {}
        self._candidates = {}

    def _guard(self, method, path, body):
        if method != "GET":
            raise zoho.WriteRefused("Freshdesk reader sends GET only")

    def _request(self, method, path, *, params=None, body=None):
        self._guard(method, path, body)
        try:
            resp = self.http.request(method, self.base + path, params=params, json=body)
        except httpx.HTTPError as exc:
            raise zoho.ZohoError(0, "freshdesk_unavailable", type(exc).__name__, path=path) from None
        if resp.status_code >= 400:
            # Never expose response bodies containing customer text or tokens.
            raise zoho.ZohoError(resp.status_code, "freshdesk_error", "Freshdesk request failed", path=path)
        return resp.json() if resp.content else None

    def ticket(self, ticket_id):
        return ticket_view(self._request("GET", f"/tickets/{int(ticket_id)}", params={"include": "requester"}))

    def all_threads(self, ticket_id, *, pages=10):
        ticket = self.ticket(ticket_id)
        initial = {"id": "description", "direction": "in", "status": "SENT", "createdTime": ticket.get("created_at"),
                   "plainText": ticket.get("description_text") or plain(ticket.get("description") or ""),
                   "content": ticket.get("description") or "", "summary": ticket.get("description_text") or "",
                   "fromEmailAddress": ticket.get("email")}
        out, complete = [initial], False
        for page in range(1, pages + 1):
            rows = self._request("GET", f"/tickets/{int(ticket_id)}/conversations", params={"page": page, "per_page": 100}) or []
            out.extend(thread_view(r) for r in rows)
            if len(rows) < 100:
                complete = True
                break
        self._threads[str(ticket_id)] = out
        return out, complete

    def threads(self, ticket_id):
        out, complete = self.all_threads(ticket_id)
        if not complete:
            raise zoho.ZohoError(0, "conversation_incomplete", "Review this long ticket manually")
        return out

    def thread(self, ticket_id, thread_id):
        rows = self._threads.get(str(ticket_id)) or self.threads(ticket_id)
        return next(t for t in rows if str(t["id"]) == str(thread_id))

    def tags(self, ticket_id):
        return self.ticket(ticket_id).get("tags") or []

    def all_comments(self, ticket_id, *, pages=10):
        rows, complete = self.all_threads(ticket_id, pages=pages)
        return [r for r in rows if r.get("private")], complete

    def search_resolved(self, term, *, department_id):
        if not re.fullmatch(r"[a-z]{3,30}", term):
            raise ValueError("Unsafe search term")
        # Freshdesk's documented filter API does not support arbitrary subject
        # full-text queries. Fetch bounded native facets, rank lexically here.
        key = str(department_id)
        if key not in self._candidates:
            query = f'"(status:4 OR status:5) AND group_id:{int(department_id)}"'
            rows = []
            for page in range(1, 4):
                body = self._request("GET", "/search/tickets", params={"query": query, "page": page}) or {}
                batch = body.get("results") or []
                rows.extend(ticket_view(r) for r in batch)
                if len(batch) < 30:
                    break
            self._candidates[key] = rows
        return [r for r in self._candidates[key] if term in plain(str(r.get("subject", "")) + " " + str(r.get("description", ""))).lower()]

    def modified(self, start, end, *, offset=0, limit=100, department_id=None):
        rows = self._request("GET", "/tickets", params={"updated_since": start, "order_by": "updated_at",
                            "order_type": "asc", "per_page": limit, "page": offset // limit + 1}) or []
        # Preserve full pages for pagination. Scope is enforced before intake.
        return [ticket_view(r) for r in rows]

    def agent(self, agent_id):
        return self._request("GET", f"/agents/{int(agent_id)}")


class Writer(Reader):
    def __init__(self, hub_dir, values, *, transport=None):
        super().__init__(hub_dir, values, transport=transport)
        from dataclasses import replace

        policy = zoho.policy_from(values)
        self.policy = replace(policy, case_field=None) if policy else None

    def _guard(self, method, path, body):
        if method == "GET":
            return
        from .. import config

        policy = zoho.policy_from(config.settings(self.hub_dir))
        if zoho.stop_switch(self.hub_dir) or policy is None or self.policy is None or policy.mode != self.policy.mode:
            raise zoho.WritesBlocked("Freshdesk writes are stopped or mode changed")
        if method == "PUT" and re.fullmatch(r"/tickets/\d+", path) and set(body or {}) == {"tags"}:
            # Body contains existing unrelated tags, but every added tag must
            # belong to this integration. Callers cannot set arbitrary fields.
            current = set(self.tags(path.split("/")[-1]))
            wanted = set(body["tags"])
            if current <= wanted and all(t.startswith(policy.effective_prefix) and zoho.TAG_RE.fullmatch(t)
                                         for t in wanted - current):
                return
        if method == "POST" and re.fullmatch(r"/tickets/\d+/notes", path) and policy.mode == "live":
            if set(body or {}) == {"body", "private"} and body["private"] is True and zoho.MARKER_RE.search(body["body"]):
                return
        raise zoho.WriteRefused(f"Customer Desk never calls {method} {path}")

    def associate_tags(self, ticket_id, tags):
        current = self.tags(ticket_id)
        if any(not t.startswith(self.policy.effective_prefix) for t in tags):
            raise zoho.WriteRefused("Only namespaced tags can be added")
        return self._request("PUT", f"/tickets/{int(ticket_id)}", body={"tags": sorted(set(current) | set(tags))})

    def private_note(self, ticket_id, content):
        return self._request("POST", f"/tickets/{int(ticket_id)}/notes", body={"body": "<pre>" + html.escape(content) + "</pre>", "private": True})
