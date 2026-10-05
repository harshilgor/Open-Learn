# Material v2 implementation and local acceptance

Checked 5 October 2026. Index version 2 stores immutable material SHA-256 source revisions, physical page indexes separately from printed page labels, page metadata, measured PDF quads, crop/media boxes and rotation transforms. Text geometry from PyMuPDF is measured; old font-metric/OCR hints remain explicitly estimated, and unavailable geometry has no highlight. Figure/equation captions and chapter/section labels are extracted evidence, not verified visual understanding or executable instructions.

`MaterialIndexService.lookup` filters the current owner, exact course, material readiness and teaching role before querying indexed lexical postings or cue/page ledgers. General references require current session attachment. It returns bounded candidates and explicit ambiguity. Optional embedding reranking uses the existing opt-in provider and cache with lexical fallback; access and source hashes are checked again after provider work. Lookup opens references without importing or automatically attaching materials.

Migrations 0068/0069 create page, cue, lexical posting, extraction-checkpoint and OCR-work ledgers. Legacy passages are backfilled in 200-row keyset batches. New ingestion checkpoints each extracted page under its current worker lease and immutable source hash; retries skip completed extraction. OCR after the initial bounded pass is processed as one independently leased page per material-worker tick, with a maximum of three attempts, source/owner/deletion fences and deterministic span IDs. Failed pages can be retried through `POST /v1/material-versions/{id}/ocr-pages/{page}/retry`; `GET /v1/material-versions/{id}/index-pages?after=...` provides bounded page status/provenance. PDF manifests include aggregate index/OCR progress. Explicitly disabled OCR does not enqueue background processing.

The 1,000-page, 5-million-character and 200,000-character-per-page processing limits remain. A 500-MiB upload is not a promise that an arbitrary document at that size can be indexed. Raster OCR remains bounded by pixel count and timeout. Extraction checkpoints are removed after successful settlement; all derived ledgers are removed with material deletion. Source-span fetch now uses one indexed row rather than loading all blocks in the document.

## Local scale measurements

Command: `python -m backend.scripts.benchmark_material_v2`. Windows, SQLite, LocalObjectStore and PyMuPDF; OCR and providers disabled for this probe. Search p50/p90 comes from 20 repeated authorized course-library queries. Python heap excludes native PDF allocations.

| Shape | File size | Index time | Python peak heap | Lookup p50 / p90 |
| --- | ---: | ---: | ---: | ---: |
| 20 text pages | 12,805 bytes | 0.817 s | 1.18 MiB | 12.49 / 14.62 ms |
| 1,000 text pages | 629,379 bytes | 37.321 s | 41.70 MiB | 20.41 / 24.74 ms |
| 200 scanned image pages, OCR disabled | 786,071 bytes | 2.527 s | 1.77 MiB | 17.85 / 20.79 ms |
| 499-MiB streamed binary storage admission | 523,239,424 bytes | 1.487 s | 2.02 MiB | n/a |

The scanned shape correctly reports `needs_attention` and 200 `disabled` pages rather than pretending text was processed. The near-cap measurement verifies bounded local streaming storage and cleanup; it is not a searchable near-cap PDF or hosted storage result.

Focused deterministic tests cover exact-course library cues outside the current snapshot, owner/private-role/course/deletion exclusion, figure/equation ambiguity, printed label versus physical page, 90-degree geometry, independently resumed 22-page OCR and duplicate settlement, optional provider failure fallback, and migration downgrade/upgrade legacy backfill. Real OCR engine quality/timeouts, rotated/cropped real-world document corpora, native allocation peak measurements and hosted PostgreSQL/cloud storage acceptance still need their respective environments. Local measurements do not substitute for them.
