"""SEO meta tags appear on every marketing page."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="http://testserver")
    return TestClient(app)


# /quickstart is a standalone template that does not extend base.html yet; Task 7
# rewrites it to extend base.html, at which point these xfails will flip to pass.
_QUICKSTART_XFAIL = pytest.mark.xfail(
    reason="quickstart.html becomes base-extending in Task 7",
    strict=True,
)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        pytest.param("/quickstart", marks=_QUICKSTART_XFAIL),
        "/explore",
        "/alternatives",
    ],
)
def test_pages_have_meta_description(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert '<meta name="description"' in r.text


@pytest.mark.parametrize(
    "path",
    [
        "/",
        pytest.param("/quickstart", marks=_QUICKSTART_XFAIL),
        "/explore",
        "/alternatives",
    ],
)
def test_pages_have_canonical(client, path):
    r = client.get(path)
    text = r.text
    assert '<link rel="canonical"' in text
    assert f'href="http://testserver{path}"' in text


@pytest.mark.parametrize(
    "path",
    [
        "/",
        pytest.param("/quickstart", marks=_QUICKSTART_XFAIL),
        "/alternatives",
    ],
)
def test_pages_have_og_and_twitter_tags(client, path):
    r = client.get(path)
    text = r.text
    assert 'property="og:title"' in text
    assert 'property="og:description"' in text
    assert 'property="og:type"' in text
    assert 'property="og:url"' in text
    assert 'name="twitter:card"' in text


def test_homepage_includes_softwareapplication_jsonld(client):
    r = client.get("/")
    text = r.text
    assert '"@type": "SoftwareApplication"' in text
    assert '"@type": "Organization"' in text
    assert '"@type": "WebSite"' in text
