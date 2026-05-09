---
id: blog-atom-feed-valid
title: Blog Atom feed exists, validates, and is discoverable
status: ready
tags: blog, seo, smoke
stakeholder: rss-reader
---

The Markland blog publishes an Atom 1.0 feed at `/blog/feed.xml`. SEO and
RSS-reader users find it via a `<link rel="alternate" type="application/atom+xml">`
tag in the `<head>` of `/blog`. A regression in either the feed itself or the
discovery link breaks every subscribed reader.

This card checks both: the feed is well-formed Atom, AND the discovery link
on `/blog` points at it.

Use the `eval` tool with `fetch(...)` to retrieve the feed XML directly so
you can inspect its first few hundred characters. Use `extract` or `eval` on
the rendered `/blog` page to find the `<link rel="alternate">` tag.

## Acceptance Criteria

- `GET https://markland.dev/blog/feed.xml` returns HTTP 200
- The response body starts with `<?xml` and contains `<feed xmlns="http://www.w3.org/2005/Atom">`
- The feed contains at least one `<entry>` element
- The `/blog` HTML page contains a `<link rel="alternate" type="application/atom+xml">` tag whose `href` resolves to `https://markland.dev/blog/feed.xml`
