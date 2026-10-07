"""Turn each kind of incoming message into the desk's one intake shape.

Sources: an IntakeEnvelope v1 line (the synthetic sample channels), a Hubzoid
intake item (the SDK email and WhatsApp channels), a helpdesk ticket thread,
and teammate requests from chat, Slack and transcripts. Whatever the source,
the text is data. Trust comes only from the channel, never from the message.
"""
from __future__ import annotations

import re

SAMPLE_CHANNELS = {"sample-email": ("email", "email"), "sample-whatsapp": ("whatsapp", "whatsapp")}
#: The distributor-v1 dataset's channel ids, delivered to the desk's sample channels.
DATASET_CHANNELS = {"email-inbox": "sample-email", "whatsapp": "sample-whatsapp"}
SUBJECT = re.compile(r"^Subject: ([^\n]{1,300})\n\n", re.I)


def split_subject(text: str, subject: str | None = None) -> tuple[str | None, str]:
    """(subject, body). The dataset writes an email's subject as a leading
    "Subject:" line of its text. A subject given separately wins."""
    m = SUBJECT.match(text or "")
    if m and subject is None:
        return m.group(1).strip(), text[m.end():]
    return subject, text


def from_envelope(env: dict) -> dict:
    """An IntakeEnvelope v1 line from the synthetic dataset (or a test). An
    email's subject may lead its text as a "Subject:" line, as the dataset
    writes it."""
    channel = DATASET_CHANNELS.get(env["channel_id"], env["channel_id"])
    surface, kind = SAMPLE_CHANNELS.get(channel, ("email", "email"))
    text, subject = env["text"], env.get("subject")
    subject, text = split_subject(text, subject)
    return {"source_kind": "sample", "source_ref": env["provider_event_id"], "surface": surface,
            "channel_id": channel, "provider": env.get("provider") or channel, "thread_key": env.get("thread_key"),
            "sender": {"kind": kind, "address": env["sender"]["external_id"],
                       "display": env["sender"].get("display_name")},
            "subject": subject, "text": text, "attachments": env.get("attachments") or [],
            "received_at": env.get("received_at"), "synthetic": bool(env.get("synthetic", True)),
            "message_id": env.get("provider_message_id")}


def from_intake_item(inp: dict) -> dict:
    """The input of a work item the SDK's email or WhatsApp channel started."""
    provider = inp.get("provider") or "email"
    surface = "whatsapp" if "whatsapp" in provider else "email"
    sender = inp.get("sender") or {}
    return {"source_kind": "intake", "source_ref": inp["intake_id"], "surface": surface,
            "channel_id": inp.get("channel"), "provider": provider, "thread_key": inp.get("thread_id"),
            "intake_id": inp["intake_id"],
            "sender": {"kind": surface, "address": sender.get("external_id") or "", "display": sender.get("display")},
            "subject": inp.get("subject"), "text": inp.get("text") or "",
            "attachments": [{k: a.get(k) for k in ("attachment_id", "filename", "media_type", "bytes", "sha256")}
                            for a in inp.get("attachments") or []],
            "synthetic": False}


def from_helpdesk(ticket: dict, thread: dict, *, provider: str = "zoho_desk", synthetic: bool = False) -> dict:
    """One inbound helpdesk thread, reread from the helpdesk API."""
    contact = ticket.get("contact") or {}
    return {"source_kind": "helpdesk", "source_ref": f"{provider}:{ticket['id']}:{thread['id']}", "surface": "helpdesk",
            "channel_id": provider, "provider": provider, "thread_key": f"{provider}:{ticket['id']}",
            "helpdesk_ticket_id": str(ticket["id"]),
            "sender": {"kind": "helpdesk", "address": thread.get("fromEmailAddress") or ticket.get("email") or "",
                       "display": " ".join(x for x in (contact.get("firstName"), contact.get("lastName")) if x)
                       or None},
            "subject": ticket.get("subject"), "text": thread.get("plainText") or thread.get("summary") or "",
            "received_at": thread.get("createdTime"), "synthetic": synthetic}


def internal(*, surface: str, customer_id: str, text: str, opened_by: str, source_ref: str,
             attachments=None) -> dict:
    """A teammate's request about a named customer: chat, Slack or a transcript."""
    return {"source_kind": surface, "source_ref": source_ref, "surface": surface, "channel_id": surface,
            "provider": surface, "thread_key": None, "customer_id": customer_id, "opened_by": opened_by,
            "sender": {"kind": surface, "address": opened_by, "display": None}, "text": text,
            "attachments": attachments or []}
