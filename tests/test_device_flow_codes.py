"""Reduced-alphabet user_code generator: no ambiguous glyphs, 8 chars, formatted XXXX-XXXX."""

import re

from markland.service.device_flow import (
    USER_CODE_ALPHABET,
    format_user_code,
    generate_user_code,
)


def test_alphabet_excludes_ambiguous_characters():
    # Must not include 0/O, 1/I/L or their lowercase — spec §4.1.
    for ch in "0O1IL":
        assert ch not in USER_CODE_ALPHABET
    # Pick one concrete recommended set; guard against silent shrinkage.
    assert len(USER_CODE_ALPHABET) >= 28


def test_alphabet_has_no_duplicates():
    assert len(set(USER_CODE_ALPHABET)) == len(USER_CODE_ALPHABET)


def test_generate_user_code_is_eight_chars_from_alphabet():
    for _ in range(200):
        code = generate_user_code()
        assert len(code) == 8
        assert all(c in USER_CODE_ALPHABET for c in code)


def test_format_user_code_adds_hyphen():
    assert format_user_code("ABCD1234") == "ABCD-1234"


def test_format_user_code_rejects_wrong_length():
    import pytest
    with pytest.raises(ValueError):
        format_user_code("ABC")


def test_generate_user_code_has_entropy():
    codes = {generate_user_code() for _ in range(500)}
    # With 28^8 ≈ 3.8e11 possibilities, 500 draws should collide ~never.
    assert len(codes) == 500


def test_format_user_code_round_trip_regex():
    code = generate_user_code()
    formatted = format_user_code(code)
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", formatted)
