# Security Policy

## Reporting a vulnerability

Please report security issues **privately** by email to:

**m.mazurowski@ai-wall.com** (subject line prefix: `[SECURITY] abyssal-claims`)

Or use GitHub's private vulnerability reporting: **Security → Report a vulnerability** on
this repository.

**Do not open a public GitHub Issue for a security report.** Public Issues are a general
contact channel and are visible to everyone.

## What to include

- A description of the issue and its impact.
- Steps to reproduce, or a proof of concept.
- The affected component (frontend, backend API, tile server, API-key subsystem, deploy
  path) and, if known, the file/endpoint.

## Scope

This is a single-maintainer, non-commercial project. There is **no bug-bounty and no
monetary reward.** Responsible disclosure is genuinely appreciated and reporters will be
credited if they wish.

## Response

I aim to acknowledge a report within a few days and to fix confirmed, exploitable issues in
the live platform as a priority. There is no formal SLA.

## Out of scope

- Findings that require access to the private production server, its systemd units, or its
  credentials (these are not part of this repository).
- Rate-limiting / volumetric issues against the public demo without a concrete security
  impact.
- Reports generated solely by automated scanners without a demonstrated, exploitable path.
