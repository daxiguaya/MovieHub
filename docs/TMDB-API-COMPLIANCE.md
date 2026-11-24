# TMDB API attribution and data-retention review

**Review date:** 2026-11-24  
**Status:** Attribution requirements identified; synopsis persistence remains on hold.

## What the current official developer FAQ says

The official [TMDB developer FAQ](https://developer.themoviedb.org/docs/faq) currently states:

- Free API use is for non-commercial purposes, with attribution to TMDB as the source of data and/or images.
- The application must prominently display: "This product uses the TMDB API but is not endorsed or certified by TMDB."
- The TMDB logo must identify API use, be less prominent than the application's primary brand, and attribution belongs in an About/Credits-type section.
- Only an approved TMDB logo should be used; logo styling must follow TMDB's branding requirements.

The FAQ distinguishes commercial projects by whether the primary purpose is to generate revenue for the owner's benefit, and directs commercial projects to TMDB sales.

## MovieHub implementation implications

Before enabling any TMDB-derived metadata in the user-facing application:

1. Add a dedicated About/Credits section containing the exact required notice and an approved TMDB logo, subject to the current terms.
2. Keep TMDB branding subordinate to MovieHub's own branding and link to https://www.themoviedb.org.
3. Confirm the project's use is non-commercial under the current terms. If that is not clear, obtain permission/license guidance from TMDB.
4. Review the full Terms of Use accepted for the API key. The terms page is linked from the official Getting Started page; the page could not be retrieved during this review.
5. Obtain explicit confirmation of whether storing/caching localized overview text in a persistent SQLite database is allowed, and if so, for how long, with what refresh/deletion requirements and redistribution restrictions.

## Current decision

- Read-only matching/coverage audits may continue.
- Do not persist, seed, export, or redistribute TMDB overview/synopsis text yet.
- Do not interpret the FAQ's general attribution statement as permission for indefinite persistent caching.
- The existing TMDB token remains server-side only; never expose it to the frontend or commit it.

This is an engineering compliance gate, not legal advice. The official FAQ does not, by itself, answer the retention period or all persistent-storage conditions for overview text.
