"""PII protection for Assignment A.

Spec: fields marked ``"pii": true`` must not be stored in plaintext. We
still need to match events to leads by phone number, so the phone is stored
only as a salted SHA-256 hash, plus a masked form (``+91******1234``) for
reports. The salt comes from the ``AGENTIC_PII_SALT`` environment variable;
the default below is for local development only — set a real secret salt in
any shared/production run and never commit it.

Customer names are PII too: they are stored only as the same salted hash
(``name_hash``), never in plaintext.
"""
from __future__ import annotations

import hashlib
import os

DEFAULT_SALT = "dev-salt-change-me"  # local dev only; set AGENTIC_PII_SALT


def _salt() -> str:
    return os.environ.get("AGENTIC_PII_SALT", DEFAULT_SALT)


def phone_hash(canonical_phone: str) -> str:
    """Salted SHA-256 of the canonical phone (``+91XXXXXXXXXX``).

    The same canonical phone always hashes the same way, so events can be
    matched to leads without ever storing the number itself.
    """
    return hashlib.sha256(
        (_salt() + "|" + canonical_phone).encode("utf-8")).hexdigest()


def name_hash(name: str) -> str:
    """Salted SHA-256 of a trimmed customer name."""
    return hashlib.sha256(
        (_salt() + "|" + name.strip()).encode("utf-8")).hexdigest()


def mask_phone(canonical_phone: str) -> str:
    """Report form: ``+91******`` + last 4 digits."""
    return "+91******" + canonical_phone[-4:]
