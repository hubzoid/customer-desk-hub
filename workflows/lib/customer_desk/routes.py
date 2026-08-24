"""The work item routes, shared by the workflow files."""
from hubzoid.work_items import Route

#: Unattended triage. It may save an unsent helpdesk draft (customer_reply.send in
#: draft mode) and annotate a helpdesk ticket. In approve mode nothing is sent,
#: because unattended work has no person to approve.
TRIAGE = Route(stages=None, actions=("customer_reply.send", "helpdesk.annotate"))
SEND = Route(stages=None, actions=("customer_reply.send",))
DRAFT = Route(stages=None, actions=("customer_reply.send",))
