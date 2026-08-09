# MootOS Design Decisions

## Purpose

This document records important architectural and design decisions made during the development of MootOS.

The goal is to preserve the reasoning behind major choices so future development remains consistent.

If a decision changes later, the original decision should remain documented along with the reason for the change.

This document is not a task list.

It is a record of why MootOS was designed the way it was.

---

# Decision 001

## Title

MootOS is a Personal AI Operating System

## Status

Accepted

## Date

July 2026

## Decision

MootOS will be developed as a personal AI operating system rather than a single-purpose application.

## Reason

The long-term goal is one AI that grows with Moot over time instead of many disconnected assistants.

Studio work, coding, social media, vehicles, finances, and future projects should all exist within the same system.

This reduces duplicated information and creates one consistent experience.

---

# Decision 002

## Title

Conversation Before Features

## Status

Accepted

## Date

July 2026

## Decision

Version 0.1 will focus on conversation and memory instead of adding many features.

## Reason

Without reliable conversation and memory, every future feature becomes harder to build.

A strong foundation is more valuable than a large feature list.

---

# Decision 003

## Title

Memory is a Core System

## Status

Accepted

## Date

July 2026

## Decision

Long-term memory will be treated as a core component of MootOS rather than an optional feature.

## Reason

Remembering useful information across conversations is one of the defining characteristics of MootOS.

Without memory, MootOS becomes another temporary chatbot.

---

# Decision 004

## Title

Projects Organize Information

## Status

Accepted

## Date

July 2026

## Decision

Memories should be organized into projects whenever appropriate.

## Reason

As MootOS grows, information from different parts of life should remain organized while still allowing useful connections between related projects.

---

# Decision 005

## Title

The AI Model Must Be Replaceable

## Status

Accepted

## Date

July 2026

## Decision

The AI model should never be permanently tied to one provider.

## Reason

AI technology changes rapidly.

Separating MootOS from the underlying model allows future upgrades without rebuilding the application.

---

# Decision 006

## Title

Human Approval for High-Risk Actions

## Status

Accepted

## Date

July 2026

## Decision

High-risk actions require explicit approval.

Examples include:

- Sending messages
- Publishing content
- Spending money
- Deleting important files
- Merging code
- Sharing private information

## Reason

The AI should assist with decisions, not replace the user's authority.

---

# Decision 007

## Title

Web First

## Status

Accepted

## Date

July 2026

## Decision

The first interface will be a mobile-friendly web application.

## Reason

A web application allows development and testing from almost any device.

Native mobile applications can be added after the foundation is complete.

---

# Decision 008

## Title

Simple Technology First

## Status

Accepted

## Date

July 2026

## Decision

Version 0.1 will prioritize simple, proven technologies.

Examples include:

- Python
- FastAPI
- SQLite
- GitHub

## Reason

Reducing technical complexity allows more time to improve the AI itself.

Complex infrastructure can be introduced later if needed.

---

# Decision 009

## Title

Coding Agent Assists, Not Controls

## Status

Accepted

## Date

July 2026

## Decision

The coding agent may propose, write, and test code, but it may not silently modify the live system.

## Reason

The coding agent should increase development speed without removing human oversight.

---

# Decision 010

## Title

Build in Small Versions

## Status

Accepted

## Date

July 2026

## Decision

MootOS will be developed through small, stable releases.

## Reason

Small releases are easier to test, easier to understand, and easier to improve than large, infrequent updates.

Every version should leave the project in a working state.

---

# Decision 011

## Title

Tool Foundation Before Scheduler/Reminders

## Status

Draft (branch `claude/motos-v0.2a-tool-foundation-u46ew4`, not merged to `main`)

## Date

August 2026

## Decision

MootOS V0.2A adds a small, explicit, fail-closed Tool System (registry,
risk-classified permissions, centralized executor, call budget, Run
audit trail, and a human-approval gate for any write) before building
Scheduler/Reminder v0.1, even though the roadmap previously named the
scheduler as the next feature after documentation synchronization.

Exactly four tools are registered: `projects.list`, `memory.search`, and
`tasks.list` (read-only, auto-execute), and `tasks.create`
(internal-write, requires explicit human approval of the model's exact
request). No external service, calendar, email, GitHub, filesystem, or
shell access was added.

## Reason

Real V0.1 usage showed that a scheduler/reminder loop is only useful once
MootOS can already take some controlled action safely — a reminder that
fires into a system with no action boundary just becomes another chat
message. A working Tool System is also the shared prerequisite most other
planned integrations (Calendar, Gmail, GitHub, files, studio work, and
eventually reminders themselves) will need, so building it first means
those integrations plug into one already-proven safety boundary instead of
each inventing their own permission and approval logic.

See ADR-027 for the full architecture and `ROADMAP.md`'s "Immediate
sequence" section, which keeps the original scheduler-first reasoning
intact rather than deleting it.

---

# Future Decisions

As MootOS grows, every major architectural decision should be added to this document.

Examples include:

- Database changes
- New AI providers
- Security architecture
- Local AI strategy
- Memory redesigns
- Major UI changes
- Plugin system
- Automation framework
- Deployment strategy
- Multi-device synchronization
