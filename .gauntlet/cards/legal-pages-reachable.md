---
id: legal-pages-reachable
title: Footer legal links reach Terms and Privacy pages
status: ready
tags: legal, smoke
stakeholder: end-user
---

`/terms` and `/privacy` are required pages for a service that holds user
content. They're typically linked from the site footer. A 404 or a broken
footer link is both a UX bug and a legal-posture problem (the ToS page
explicitly references contact aliases like `legal@markland.dev`, so users
need to be able to find it).

This card checks the footer on the homepage exposes both links and that they
each render a real page (not a 404, not an empty page).

Don't try to read or grade the legal text — only check that the pages exist
and have meaningful content. As a heuristic, a real page should have more
than 500 characters of text content and should NOT contain the substring
"Page not found" or "404".

## Acceptance Criteria

- The footer on `https://markland.dev/` contains a link with href `/terms` (or absolute equivalent) and a link with href `/privacy` (or absolute equivalent)
- Navigating to `/terms` returns HTTP 200 and the page renders a heading containing the word "Terms"
- Navigating to `/privacy` returns HTTP 200 and the page renders a heading containing the word "Privacy"
- Neither page contains the strings "Page not found" or "404"
