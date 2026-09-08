# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Keep credentials out of the log stream.

⛔ THIS IS NOT DEFENSIVE POLISH. It closes a live leak found on 2026-09-08: the
production journal carried lines of the form

    INFO HTTP Request: GET https://data.oceannetworks.ca/api/scalardata/location
    ?method=getByLocation&locationCode=SEIR&…&token=<the real ONC token> "HTTP/1.1 200 "

on every single ONC call. Nobody wrote that line — `httpx` logs every request URL
at INFO, and the URL is where we put the token. `journalctl` is readable by any
account in the `systemd-journal` group and the entries persist on disk, so a
credential that reaches a log has effectively been published.

## Why two rules and not one

**Rule 1 — named query parameters.** `?token=…`, `&api_key=…`. Catches keys we do
not know about, including any added after this file was written.

**Rule 2 — the known secret VALUES.** Rule 1 alone is not enough, and FIRMS is the
proof: we build

    https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}/VIIRS/world/3

The key sits in a **path segment**. It has no parameter name, so no name-based rule
can ever see it — a path segment holding a secret is indistinguishable from one
holding a sensor code. Matching the value itself is the only thing that works, and
it has the bonus of covering tracebacks, exception strings and any place our own
code interpolates a key into a message.

⚠️ Rule 2 reads the environment ONCE, at install time, so `install()` must run
AFTER `load_dotenv()`. Installing it earlier silently gives you rule 1 only.

⛔ Nothing in this module ever logs, prints or returns a secret value. The set is
private and the only thing that leaves is the placeholder.
"""
from __future__ import annotations

import logging
import os
import re

PLACEHOLDER = "***REDACTED***"

# ⛔ Each name is written as a STRING LITERAL inside _collect_secrets() below rather
# than looped over from a tuple. That is not style: `test_env_example_completeness`
# scans for `os.getenv(<literal>)` and cannot see a name that arrives in a variable,
# so a loop makes every credential here invisible to the gate that checks each one is
# documented in .env.example. The first version of this file used a loop and the gate
# caught it — which is also how the list below grew from 10 guesses to the real set.

_MIN_SECRET_LEN = 12

# A query parameter whose NAME looks like a credential. Anchored on `?` or `&` so it
# only ever fires inside a query string — `locationCode=SEIR` and `deviceCategoryCode`
# are untouched because neither contains one of these words.
_SECRET_PARAM = re.compile(
    r"(?i)([?&][^?&=\s]*(?:token|key|secret|passwd|password|signature|credential)[^?&=\s]*=)"
    r"[^&\s\"'<>]+"
)

_secret_values: tuple[str, ...] = ()


def _collect_secrets() -> tuple[str, ...]:
    """Env values worth hiding, longest first.

    Longest-first matters: if one secret is a prefix of another, replacing the short
    one first would leave the tail of the long one exposed in the line.

    ⚠️ The webhook URLs belong here even though they look like plain addresses — a
    Discord/alert webhook URL IS the credential; anyone holding it can post as us.
    FEEDBACK_IP_SALT belongs here because without it the stored IP hashes are just
    hashes, and with it they are reversible.
    """
    candidates = (
        os.getenv("ONC_TOKEN"),
        os.getenv("FIRMS_MAP_KEY"),
        os.getenv("OPENAQ_API_KEY"),
        os.getenv("ABYSSAL_API_KEY"),
        os.getenv("AISSTREAM_API_KEY"),
        os.getenv("LINZ_API_KEY"),
        os.getenv("INDEXNOW_KEY"),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        os.getenv("CDSE_CLIENT_SECRET"),
        os.getenv("DRYAD_CLIENT_SECRET"),
        os.getenv("CMEMS_PASSWORD"),
        os.getenv("MEMENTO_PASSWORD"),
        os.getenv("PGPASSWORD"),
        os.getenv("ADMIN_DASHBOARD_TOKEN"),
        os.getenv("ADMIN_BOOTSTRAP_PASSWORD"),
        os.getenv("FEEDBACK_IP_SALT"),
        os.getenv("DISCORD_FEEDBACK_WEBHOOK"),
        os.getenv("ALERT_WEBHOOK_URL"),
    )
    found = {v for c in candidates if (v := (c or "").strip()) and len(v) >= _MIN_SECRET_LEN}

    # The database password, which lives inside a URL rather than on its own.
    dsn = os.getenv("DATABASE_URL") or ""
    if (m := re.match(r"^[a-z+]+://[^:/@]+:([^@]+)@", dsn)) and len(m.group(1)) >= _MIN_SECRET_LEN:
        found.add(m.group(1))
    return tuple(sorted(found, key=len, reverse=True))


def redact(text: str) -> str:
    """Both rules, values first. Safe to call on any string."""
    for secret in _secret_values:
        if secret in text:
            text = text.replace(secret, PLACEHOLDER)
    return _SECRET_PARAM.sub(r"\1" + PLACEHOLDER, text)


class SecretRedactingFilter(logging.Filter):
    """Rewrites a record in place before any handler formats it.

    Attached to the ROOT logger, so it covers `httpx`, our own modules and anything
    a dependency logs — a filter on one named logger would have closed the ONC leak
    and left the next one open.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if isinstance(record.msg, str):
            cleaned = redact(record.msg)
            if cleaned != record.msg:
                record.msg = cleaned

        args = record.args
        if isinstance(args, tuple):
            # ⚠️ Replace an argument ONLY when redaction actually changed it. A record
            # can mix `%s` with `%d`, and turning an untouched int into a str would
            # make the handler raise while formatting — trading a leak for a crash.
            new_args = tuple(_redact_arg(a) for a in args)
            if new_args != args:
                record.args = new_args
        elif isinstance(args, dict):
            new_map = {k: _redact_arg(v) for k, v in args.items()}
            if new_map != args:
                record.args = new_map
        return True


def _redact_arg(value):
    """Redact one logging argument, preserving its object when nothing changed."""
    if isinstance(value, str):
        cleaned = redact(value)
        return cleaned if cleaned != value else value
    # httpx passes an `httpx.URL`; a DSN may arrive as a URL-ish object too. Anything
    # that is not a plain scalar gets rendered and checked, and is only replaced (by a
    # str) when it genuinely carried a secret.
    if isinstance(value, (int, float, bool, type(None))):
        return value
    rendered = str(value)
    cleaned = redact(rendered)
    return cleaned if cleaned != rendered else value


def install() -> int:
    """Attach the filter to the root logger. Idempotent. Returns how many secret
    values were loaded, so a caller can log THAT number — never the values."""
    global _secret_values
    _secret_values = _collect_secrets()
    root = logging.getLogger()
    if not any(isinstance(f, SecretRedactingFilter) for f in root.filters):
        root.addFilter(SecretRedactingFilter())
    # ⚠️ A filter on a Logger is consulted for records logged THROUGH that logger, not
    # for records that merely propagate up to it. So the same filter goes on every
    # handler as well, which is what actually catches `httpx`'s own logger.
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactingFilter) for f in handler.filters):
            handler.addFilter(SecretRedactingFilter())
    return len(_secret_values)
