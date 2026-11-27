# 2025 annual chart artifact review

Review date: 2026-11-23  
Source workflow: [GitHub Actions run #325](https://github.com/daxiguaya/MovieHub/actions/runs/45166104334)  
Source commit: [2a3600502e2e29129614e2857afceb53fddd1836](https://github.com/daxiguaya/MovieHub/commit/2a3600502e2e29129614e2857afceb53fddd1836)  
Artifact: `moviehub-douban-annual-2025` (artifact ID `14814588795`; expires 2026-12-07 11:32 UTC)

## Contents

| Built-in chart slug | Entries | Media type | Rank range |
| --- | ---: | --- | --- |
| `annual-2025-chinese-movies` | 8 | movie | 1–8 |
| `annual-2025-international-movies` | 10 | movie | 1–10 |
| `annual-2025-hidden-gems` | 10 | movie | 1–10 |
| `annual-2025-chinese-tv` | 10 | tv | 1–10 |
| **Total** | **38** | | |

The Chinese-film list has eight entries because the official source marks positions 9 and 10 empty. Those positions are not synthesized or renumbered.

## Independent artifact checks

The downloaded ZIP was inspected without connecting to Scout or a MovieHub database.

- All four files parse as UTF-8 JSON and carry the expected built-in slug, `annual` category, capture date `2026-11-23`, and 2025 period metadata.
- All 38 rows contain a Douban subject ID, rank, title, media type and source rating.
- All 38 Douban IDs are unique within and across the four lists.
- No rank is duplicated within a list; ranks are ascending and match the source positions represented in the files.
- The three film lists contain only `movie`; the Chinese TV list contains only `tv`.
- The official 8/10/10/10 counts match the collector documentation and CI dry-run result.

## Metadata coverage and limits

The collector intentionally captures ranking-level information, not a full movie catalogue. In this artifact, source ratings and director names are present for all 38 rows, while year, rating count, original title, overview, actors, genres, regions and poster URLs are not populated. These fields must be enriched from a separately staged, consistent Scout copy or another approved metadata source; they must not be guessed.

This review is a structural and cross-list consistency check. It does not independently prove that every title, rank or rating is semantically correct against the live source, and it is not a Scout coverage audit.

## Safety and next step

- The generated JSON remains a temporary Actions artifact and is intentionally not committed to Git.
- No MovieHub database was opened or initialized.
- No Scout database was opened or modified.
- No annual snapshot was imported.
- The next data-quality step is to run the existing read-only Scout coverage audit against a separately staged, consistent Scout copy. Any later snapshot import remains a separate deliberate operation after the independent MovieHub database is explicitly initialized.


## Production follow-up — 2026-11-26

The statements above that no annual snapshot had been imported describe the state at the time of this artifact review (2026-11-23). They are historical, not the current production state. The four lists were subsequently imported into the production MovieHub database and confirmed by the production audit: four annual snapshots, 38 entries total (8/10/10/10). The imported data remains separate from this temporary Actions artifact; the artifact itself was not committed to Git.
