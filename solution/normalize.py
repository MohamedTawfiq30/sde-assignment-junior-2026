"""Mechanical value normalisation for Assignment A.

These are the parts of the spec that are pure functions with no judgement
calls — header matching, phone/date/decimal/enum parsing, event timestamps.
Fully implemented and tested (see tests/test_normalize.py). The assessed
thinking (merging, linking, dispositions, buckets) lives in rules.py.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

IST = timezone(timedelta(hours=5, minutes=30))

_MONTHS = {m.lower(): i for i, m in
           enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def normalize_header(header: str) -> str:
    """Spec: lower-case, trim, replace every run of ``_`` or whitespace
    with a single space."""
    return re.sub(r"[_\s]+", " ", header.strip().lower()).strip()


def map_headers(raw_headers, fields):
    """Map CSV column headers to schema field names.

    Each field matches on its ``name`` or any of its ``aliases``,
    normalised the same way. Columns that match nothing are ignored.

    Returns ``{field_name: raw_header}``.
    """
    lookup = {}
    for field in fields:
        for candidate in [field["name"]] + field.get("aliases", []):
            lookup[normalize_header(candidate)] = field["name"]
    mapping = {}
    for header in raw_headers or []:
        if header is None:
            continue
        field_name = lookup.get(normalize_header(header))
        if field_name is not None:
            mapping[field_name] = header
    return mapping


def normalize_phone(raw) -> str | None:
    """Spec: strip every non-digit. If 12 digits starting with ``91``,
    drop the ``91``. If 11 digits starting with ``0``, drop the ``0``.
    Valid only if exactly 10 digits starting with 6, 7, 8 or 9.
    Stored canonically as ``+91XXXXXXXXXX``. Returns None if invalid."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return None


def parse_date(raw) -> date | None:
    """Spec: accept ``YYYY-MM-DD``, ``DD/MM/YYYY``, ``DD-MM-YYYY`` and
    ``DD-Mon-YYYY`` (month name case-insensitive). Dates are day-first.
    Impossible dates (e.g. 31/02) are invalid -> None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3,9})-(\d{4})$", s)
    if m:
        month = _MONTHS.get(m.group(2).lower()[:3])
        if month is not None:
            try:
                return date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    return None


def parse_decimal(raw) -> float | None:
    """Spec: optionally prefixed by ``₹``, ``Rs``, ``Rs.`` or ``INR``
    (case-insensitive, optional space). Commas are thousands separators.
    Must be >= 0. Rounded to 2 places. Returns None if invalid."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = re.sub(r"^(₹|rs\.?|inr)\s*", "", s, flags=re.IGNORECASE)
    s = s.replace(",", "")
    if not s:
        return None
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    if value < 0:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalize_enum(raw, values) -> str | None:
    """Spec: compared case-insensitively against ``values`` and stored
    lower-case. Returns None if not a valid value."""
    if raw is None:
        return None
    value = str(raw).strip().lower()
    return value if value in values else None


def parse_field(field_type: str, raw, field: dict):
    """Parse one raw cell value according to its schema field type.
    Returns the parsed value, or None if the value is invalid.
    (For ``string`` any non-empty trimmed value is valid.)"""
    if field_type == "string":
        return str(raw).strip()
    if field_type == "phone":
        return normalize_phone(raw)
    if field_type == "date":
        parsed = parse_date(raw)
        return parsed.isoformat() if parsed is not None else None
    if field_type == "decimal":
        return parse_decimal(raw)
    if field_type == "enum":
        return normalize_enum(raw, field.get("values", []))
    raise ValueError(f"unknown field type: {field_type!r}")


def parse_event_ts(raw) -> datetime | None:
    """Event timestamps come in three forms: UTC (``...Z``), offset
    (``...+05:30``), and naive (``2026-10-03 10:01:00``). Naive means IST.
    Returns an aware datetime in UTC, or None if unparseable."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.strptime(
                s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if re.search(r"[+-]\d{2}:\d{2}$", s):
            return datetime.fromisoformat(s).astimezone(timezone.utc)
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=IST).astimezone(timezone.utc)
    except ValueError:
        return None


def ist_date(utc_dt: datetime) -> date:
    """IST date of an aware UTC datetime (all report dates are IST)."""
    return utc_dt.astimezone(IST).date()


def ist_iso(utc_dt: datetime) -> str:
    """ISO-8601 in IST, e.g. ``2026-10-14T17:55:24+05:30``."""
    return utc_dt.astimezone(IST).isoformat(timespec="seconds")
