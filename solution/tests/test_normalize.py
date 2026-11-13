"""Tests for the mechanical normalisation helpers (solution/normalize.py).

These should all PASS — they pin down the spec-exact parsing rules.
"""
from datetime import date, datetime, timezone

from solution.normalize import (
    map_headers, normalize_enum, normalize_header, normalize_phone,
    parse_date, parse_decimal, parse_event_ts, parse_field,
)

FIELDS = [
    {"name": "customer_name", "type": "string", "required": True,
     "aliases": ["name", "customer name", "insured name"]},
    {"name": "phone", "type": "phone", "required": True,
     "aliases": ["mobile", "mobile no", "phone number", "contact"]},
    {"name": "policy_number", "type": "string", "required": True,
     "reference": True, "aliases": ["policy no", "policy"]},
    {"name": "policy_expiry", "type": "date", "required": False,
     "aliases": ["expiry date", "expiry"]},
    {"name": "premium_amount", "type": "decimal", "required": False,
     "aliases": ["premium"]},
    {"name": "preferred_language", "type": "enum", "required": False,
     "values": ["en", "hi", "ta"], "default": "en",
     "aliases": ["language"]},
]


def test_normalize_header():
    assert normalize_header("  Mobile No ") == "mobile no"
    assert normalize_header("POLICY__NUMBER") == "policy number"
    assert normalize_header("order\t id") == "order id"


def test_map_headers_aliases_and_unknowns():
    mapping = map_headers(
        ["Language", "Insured Name", "Policy No", "Mobile No",
         "Expiry Date", "Premium", "agent_notes"], FIELDS)
    assert mapping == {
        "preferred_language": "Language",
        "customer_name": "Insured Name",
        "policy_number": "Policy No",
        "phone": "Mobile No",
        "policy_expiry": "Expiry Date",
        "premium_amount": "Premium",
    }


def test_normalize_phone_formats():
    assert normalize_phone("9876543210") == "+919876543210"
    assert normalize_phone("+91 98765 43210") == "+919876543210"
    assert normalize_phone("91-98765-43210") == "+919876543210"
    assert normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("(+91) 9876543210") == "+919876543210"
    assert normalize_phone("98765 43210") == "+919876543210"


def test_normalize_phone_invalid():
    assert normalize_phone("987654321") is None          # 9 digits
    assert normalize_phone("5876543210") is None         # bad prefix
    assert normalize_phone("022-2000-1000") is None      # landline
    assert normalize_phone("N/A") is None
    assert normalize_phone("+1 415 555 0134") is None    # not Indian
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_parse_date_formats():
    assert parse_date("2026-12-01") == date(2026, 12, 1)
    assert parse_date("01/12/2026") == date(2026, 12, 1)  # day-first
    assert parse_date("01-12-2026") == date(2026, 12, 1)
    assert parse_date("01-Dec-2026") == date(2026, 12, 1)
    assert parse_date("01-dec-2026") == date(2026, 12, 1)  # case-insensitive


def test_parse_date_impossible():
    assert parse_date("31/02/2026") is None
    assert parse_date("2026-13-01") is None
    assert parse_date("soon") is None
    assert parse_date("TBD") is None
    assert parse_date("") is None


def test_parse_decimal_formats():
    assert parse_decimal("1234.50") == 1234.50
    assert parse_decimal("₹1,234") == 1234.0
    assert parse_decimal("Rs. 12000") == 12000.0
    assert parse_decimal("INR 1234.5") == 1234.5
    assert parse_decimal("rs 500") == 500.0
    assert parse_decimal("0") == 0.0


def test_parse_decimal_invalid():
    assert parse_decimal("N/A") is None
    assert parse_decimal("-") is None
    assert parse_decimal("twelve thousand") is None
    assert parse_decimal("-100") is None  # must be >= 0
    assert parse_decimal("") is None


def test_normalize_enum():
    assert normalize_enum("TA", ["en", "hi", "ta"]) == "ta"
    assert normalize_enum(" ta ", ["en", "hi", "ta"]) == "ta"
    assert normalize_enum("Hindi", ["en", "hi", "ta"]) is None
    assert normalize_enum("english", ["en", "hi", "ta"]) is None
    assert normalize_enum("", ["en", "hi", "ta"]) is None


def test_parse_field_string_trims():
    field = {"name": "customer_name", "type": "string"}
    assert parse_field("string", "  Aarav Sharma ", field) == "Aarav Sharma"


def test_parse_event_ts_forms():
    utc = datetime(2026, 10, 5, 7, 50, 21, tzinfo=timezone.utc)
    assert parse_event_ts("2026-10-05T07:50:21Z") == utc
    assert parse_event_ts("2026-10-05T13:20:21+05:30") == utc
    # naive means IST
    assert parse_event_ts("2026-10-05 13:20:21") == utc
    assert parse_event_ts("garbage") is None
