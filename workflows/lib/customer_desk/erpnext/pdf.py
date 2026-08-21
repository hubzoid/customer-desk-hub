"""A tiny, dependency-free PDF writer for the sample backend's invoice prints.

The sample and fake REST backends return a deterministic PDF for each
submitted invoice, clearly labelled synthetic, so the desk attaches a real
file with a stable SHA-256 without a live ERPNext.
"""
from __future__ import annotations


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(lines: list[str], *, title: str = "Synthetic document") -> bytes:
    """A one-page PDF with the given lines in Helvetica. Same input, same bytes."""
    y = 780
    ops = ["BT", "/F1 11 Tf"]
    for line in lines[:60]:
        ops.append(f"1 0 0 1 56 {y} Tm ({_escape(line[:110])}) Tj")
        y -= 16
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Title (" + _escape(title).encode("latin-1", "replace") + b") /Producer (Hubzoid Customer Desk sample) >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def invoice_pdf(invoice: dict, customer_name: str, company: str, print_format: str) -> bytes:
    lines = ["SYNTHETIC DATA. Not a real invoice.", "", f"{company}", f"Invoice {invoice['name']}",
             f"Print format: {print_format}", "", f"Customer: {customer_name} ({invoice.get('customer')})",
             f"Posting date: {invoice.get('posting_date')}", f"Due date: {invoice.get('due_date')}",
             f"Customer PO: {invoice.get('po_no') or '-'}", ""]
    for row in invoice.get("items") or []:
        lines.append(f"{row.get('item_code')}  {row.get('item_name')}  qty {row.get('qty')}  "
                     f"rate {row.get('rate')}  amount {row.get('amount')}")
    lines += ["", f"Grand total: {invoice.get('currency')} {invoice.get('grand_total')}",
              f"Outstanding: {invoice.get('currency')} {invoice.get('outstanding_amount')}"]
    return text_pdf(lines, title=f"Synthetic invoice {invoice['name']}")
