# Triage Labels

The skills speak in terms of canonical triage roles. This file maps those roles to the actual label
strings used in this repo's issue tracker.

| Canonical role    | Label in our tracker | Meaning                                             |
| ----------------- | -------------------- | --------------------------------------------------- |
| `needs-triage`    | `needs-triage`       | Maintainer needs to evaluate this issue             |
| `needs-info`      | `needs-info`         | Waiting on reporter for more information            |
| `ready-for-agent` | `ready-for-agent`    | Fully specified, ready for an AFK agent             |
| `ready-for-human` | `ready-for-human`    | Requires human implementation                       |
| `wontfix`         | `wontfix`            | Will not be actioned                                |
| `bug`             | `bug`                | Category: something is broken                       |
| `enhancement`     | `enhancement`        | Category: new feature or improvement                |
| `spec`            | `spec`               | A parent spec issue (published by /spec) — NOT a ticket; never dispatch it |

When a skill mentions a role (e.g. "apply the agent-ready label"), use the corresponding label
string from this table. Edit the right-hand column to match whatever vocabulary you actually use.
