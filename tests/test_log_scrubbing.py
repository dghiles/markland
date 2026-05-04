"""Tests for access-log + Sentry redaction of magic-link / CSRF / share tokens."""

from __future__ import annotations

import logging

from markland.log_scrubbing import (
    RedactSensitiveQueryParamsFilter,
    build_uvicorn_log_config,
    redact_url,
    scrub_sentry_event,
)


# ---------------------------------------------------------------------------
# redact_url
# ---------------------------------------------------------------------------


def test_redact_url_masks_token_param():
    assert redact_url("/verify?token=abc123xyz") == "/verify?token=[REDACTED]"


def test_redact_url_masks_share_token_param():
    out = redact_url("/d/foo?share_token=s3cret&pretty=1")
    assert "s3cret" not in out
    assert "share_token=[REDACTED]" in out
    assert "pretty=1" in out


def test_redact_url_masks_csrf_and_magic_link_params():
    out = redact_url("/x?csrf=AAA&magic_link=BBB&keep=1")
    assert "AAA" not in out and "BBB" not in out
    assert "csrf=[REDACTED]" in out
    assert "magic_link=[REDACTED]" in out
    assert "keep=1" in out


def test_redact_url_is_case_insensitive_on_param_name():
    out = redact_url("/verify?Token=secret")
    assert "secret" not in out


def test_redact_url_preserves_other_params():
    out = redact_url("/x?keep=1&token=secret&also=2")
    assert "keep=1" in out
    assert "also=2" in out
    assert "secret" not in out


def test_redact_url_handles_full_url():
    url = "https://markland.dev/verify?token=abc123&utm=launch"
    out = redact_url(url)
    assert "abc123" not in out
    assert "utm=launch" in out


def test_redact_url_returns_input_when_no_sensitive_params():
    assert redact_url("/healthz") == "/healthz"
    assert redact_url("/d/foo?pretty=1") == "/d/foo?pretty=1"


def test_redact_url_passes_through_non_strings():
    assert redact_url(None) is None  # type: ignore[arg-type]
    assert redact_url("") == ""


# ---------------------------------------------------------------------------
# RedactSensitiveQueryParamsFilter
# ---------------------------------------------------------------------------


def _make_access_record(path: str) -> logging.LogRecord:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54321", "GET", path, "1.1", 200),
        exc_info=None,
    )
    return record


def test_filter_redacts_path_in_record_args():
    f = RedactSensitiveQueryParamsFilter()
    record = _make_access_record("/verify?token=abc123xyz")
    assert f.filter(record) is True
    assert isinstance(record.args, tuple)
    assert record.args[2] == "/verify?token=[REDACTED]"


def test_filter_leaves_clean_paths_unchanged():
    f = RedactSensitiveQueryParamsFilter()
    record = _make_access_record("/healthz")
    f.filter(record)
    assert record.args[2] == "/healthz"  # type: ignore[index]


def test_filter_never_drops_records():
    f = RedactSensitiveQueryParamsFilter()
    record = _make_access_record("/verify?token=x")
    assert f.filter(record) is True


def test_filter_handles_records_without_expected_args():
    """A logger.info without args= must not raise — filter just no-ops."""
    f = RedactSensitiveQueryParamsFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=None,
        exc_info=None,
    )
    assert f.filter(record) is True


# ---------------------------------------------------------------------------
# build_uvicorn_log_config
# ---------------------------------------------------------------------------


def test_log_config_attaches_filter_to_access_handler():
    cfg = build_uvicorn_log_config()
    assert "redact_sensitive" in cfg["filters"]
    assert "redact_sensitive" in cfg["handlers"]["access"]["filters"]
    # Ensure access logger uses the access handler.
    assert "access" in cfg["loggers"]["uvicorn.access"]["handlers"]


# ---------------------------------------------------------------------------
# scrub_sentry_event
# ---------------------------------------------------------------------------


def test_scrub_event_redacts_request_url_and_query():
    event = {
        "request": {
            "url": "https://markland.dev/verify?token=abc123",
            "query_string": "token=abc123&keep=1",
            "headers": {"Authorization": "Bearer xyz", "User-Agent": "ua"},
        }
    }
    out = scrub_sentry_event(event)
    assert "abc123" not in out["request"]["url"]
    assert "abc123" not in out["request"]["query_string"]
    assert "Authorization" not in out["request"]["headers"]
    assert out["request"]["headers"]["User-Agent"] == "ua"


def test_scrub_event_strips_authorization_case_insensitive():
    event = {
        "request": {"headers": {"authorization": "Bearer xyz", "x-keep": "1"}}
    }
    out = scrub_sentry_event(event)
    assert "authorization" not in out["request"]["headers"]
    assert out["request"]["headers"]["x-keep"] == "1"


def test_scrub_event_strips_authorization_from_list_headers():
    event = {
        "request": {
            "headers": [
                ["Authorization", "Bearer xyz"],
                ["User-Agent", "ua"],
            ]
        }
    }
    out = scrub_sentry_event(event)
    headers = out["request"]["headers"]
    assert all(pair[0].lower() != "authorization" for pair in headers)
    assert ["User-Agent", "ua"] in [list(p) for p in headers]


def test_scrub_event_redacts_breadcrumb_urls():
    event = {
        "breadcrumbs": {
            "values": [
                {
                    "type": "http",
                    "data": {
                        "url": "https://markland.dev/verify?token=abc123",
                        "method": "GET",
                    },
                },
                {
                    "type": "navigation",
                    "message": "navigated to /verify?token=abc123",
                },
            ]
        }
    }
    out = scrub_sentry_event(event)
    crumb = out["breadcrumbs"]["values"][0]
    assert "abc123" not in crumb["data"]["url"]
    assert "abc123" not in out["breadcrumbs"]["values"][1]["message"]


def test_scrub_event_redacts_breadcrumbs_when_top_level_list():
    event = {
        "breadcrumbs": [
            {"data": {"url": "/verify?token=abc"}},
        ]
    }
    out = scrub_sentry_event(event)
    assert "abc" not in out["breadcrumbs"][0]["data"]["url"]


def test_scrub_event_handles_missing_keys():
    # Missing request, missing breadcrumbs — must not raise.
    assert scrub_sentry_event({}) == {}
    assert scrub_sentry_event({"request": {}}) == {"request": {}}


def test_scrub_event_handles_non_dict_input():
    # Non-dict events pass through (Sentry would never send these but be
    # defensive).
    assert scrub_sentry_event(None) is None
    assert scrub_sentry_event("oops") == "oops"  # type: ignore[arg-type]


def test_scrub_event_returns_event_so_sentry_still_sends():
    """Returning ``None`` from before_send drops the event. Confirm we don't."""
    event = {"request": {"url": "/verify?token=abc"}}
    assert scrub_sentry_event(event) is event
