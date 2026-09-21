"""A fake Frappe REST server over the synthetic dataset, for tests and the
`fake_rest` backend. Loopback only, clearly labelled, never a production ERP.

It answers the GET routes the read adapter uses: resource read, resource list
with Frappe-style filters, `download_pdf` and `get_logged_user`. Every other
method is answered 405 and recorded in `refused`, so a test can assert the
desk never tried to write. Failures can be injected per path.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import pdf

DOCTYPES = {"Customer": "customers.json", "Item": "items.json", "Item Price": "prices.json", "Bin": "availability.json",
            "Sales Order": "sales_orders.json", "Sales Invoice": "sales_invoices.json"}
TOKEN = "fake-api-key:fake-api-secret"   # gitleaks:allow (a fixed loopback test value)


def _match(value, op, want) -> bool:
    if op == "=":
        return value == want
    if op == "!=":
        return value != want and str(value) != str(want) and not (_num(value) == _num(want))
    if op == "in":
        return value in want
    if op == "not in":
        return value not in want
    if op == ">=":
        return str(value or "") >= str(want)
    if op == "<=":
        return str(value or "") <= str(want)
    if op == "like":
        pattern = "^" + re.escape(str(want)).replace("%", ".*") + "$"
        return re.match(pattern, str(value or ""), re.I) is not None
    return False


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class FakeFrappe:
    def __init__(self, dataset_dir: Path, *, company: str = "Synthetic Meridian Distribution"):
        self.dir = Path(dataset_dir)
        self.company = company
        self.data = {dt: json.loads((self.dir / f).read_text()) for dt, f in DOCTYPES.items()}
        self.requests: list[tuple[str, str]] = []
        self.refused: list[tuple[str, str]] = []
        self.failures: list[dict] = []
        self.lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None

    # -- control --------------------------------------------------------------------
    def fail(self, pattern: str, status: int, times: int = 1, *, delay: float = 0.0) -> None:
        self.failures.append({"pattern": re.compile(pattern), "status": status, "times": times, "delay": delay})

    def set_field(self, doctype: str, name: str, key: str, value) -> None:
        with self.lock:
            for row in self.data[doctype]:
                if row["name"] == name:
                    row[key] = value
                    row["modified"] = "2000-01-15T10:30:00Z"

    def start(self, port: int = 0) -> str:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):   # quiet
                pass

            def _send(self, status, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                fake._handle(self)

            def _refuse(self):
                fake.refused.append((self.command, self.path))
                self._send(405, {"exc_type": "MethodNotAllowed"})

            do_POST = do_PUT = do_PATCH = do_DELETE = _refuse  # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    # -- routing --------------------------------------------------------------------
    def _handle(self, h) -> None:
        import time

        self.requests.append(("GET", h.path))
        for rule in self.failures:
            if rule["times"] > 0 and rule["pattern"].search(h.path):
                rule["times"] -= 1
                if rule["delay"]:
                    time.sleep(rule["delay"])
                return h._send(rule["status"], {"exc_type": "Injected"})
        if h.headers.get("Authorization") != f"token {TOKEN}":
            return h._send(401, {"exc_type": "AuthenticationError"})
        url = urlparse(h.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = unquote(url.path)
        if path == "/api/method/frappe.auth.get_logged_user":
            return h._send(200, {"message": "desk-reader@synthetic-meridian.example"})
        if path == "/api/method/frappe.utils.print_format.download_pdf":
            inv = self._find("Sales Invoice", q.get("name", ""))
            if inv is None or inv.get("docstatus") != 1:
                return h._send(404, {"exc_type": "DoesNotExistError"})
            cust = self._find("Customer", inv.get("customer")) or {}
            return h._send(200, pdf.invoice_pdf(inv, cust.get("customer_name", ""), self.company,
                                                q.get("format", "Standard")), "application/pdf")
        m = re.fullmatch(r"/api/resource/([^/]+)(?:/(.+))?", path)
        if not m or m.group(1) not in DOCTYPES:
            return h._send(404, {"exc_type": "DoesNotExistError"})
        doctype, name = m.group(1), m.group(2)
        if name:
            row = self._find(doctype, name)
            return h._send(200, {"data": row}) if row else h._send(404, {"exc_type": "DoesNotExistError"})
        filters = json.loads(q.get("filters") or "[]")
        rows = []
        with self.lock:
            for row in self.data[doctype]:
                if all(_match(row.get(f[1]), f[2], f[3]) for f in filters):
                    rows.append({"name": row["name"]})
        limit = int(q.get("limit_page_length") or 20)
        start = int(q.get("limit_start") or 0)
        return h._send(200, {"data": sorted(rows, key=lambda r: r["name"])[start:start + limit]})

    def _find(self, doctype, name):
        with self.lock:
            return next((dict(r) for r in self.data[doctype] if r["name"] == name), None)


def main() -> None:  # pragma: no cover - a developer convenience
    import argparse

    ap = argparse.ArgumentParser(description="Serve the synthetic ERP over a fake Frappe REST API (loopback only).")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--port", type=int, default=8729)
    args = ap.parse_args()
    fake = FakeFrappe(Path(args.dataset))
    print("FAKE FRAPPE (synthetic data, loopback only) at", fake.start(args.port), flush=True)
    threading.Event().wait()


if __name__ == "__main__":  # pragma: no cover
    main()
