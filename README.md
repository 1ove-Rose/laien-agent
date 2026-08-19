# App Review Insights

This project is a runnable App Store review analysis workspace. The collection and cleaning stages use real App Store review data from a selected storefront; later semantic analysis, PRD, and test-case stages are still simulated pending the multi-agent implementation.

## Run locally

Node.js 18 or newer is required. Start the local server:

```bash
node serve.js
```

Then open `http://127.0.0.1:8765/`.

No dependency install or API key is required. Opening `index.html` through `file://` only renders the UI; real collection and cleaning require the local server.

Run the automated tests with:

```bash
node --test
```

## Review data source

The server extracts the numeric App ID from a validated `https://apps.apple.com/.../id...` URL, then requests the selected storefront RSS JSON feed:

```text
https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={appId}/sortby=mostrecent/json
```

- Requests are server-side and currently support the U.S. (`us`) and China (`cn`) storefronts.
- Each page contains up to about 50 recent reviews; this project requests at most 10 pages.
- Pages are fetched sequentially with a small delay, a 10-second timeout, and up to two retries for retryable errors.
- Empty RSS pages are skipped and later pages are still attempted because Apple can return sparse review pages.
- Raw Apple responses are cached under `data/cache/` for one hour. Stale cache may be used when Apple is temporarily unavailable, and the UI labels that fallback.
- The RSS feed is a public Apple endpoint rather than a guaranteed, versioned product API. Availability, history depth, page size, and response shape can change.

## API

`POST /api/reviews/collect`

```json
{
  "appUrl": "https://apps.apple.com/us/app/example/id839285684",
  "country": "us",
  "maxReviews": 200
}
```

`POST /api/reviews/clean`

```json
{
  "appId": "839285684",
  "reviews": []
}
```

Cleaning is deterministic: Unicode NFKC normalization, whitespace cleanup, rating and empty-text validation, ISO date normalization, stable generated IDs, source-ID deduplication, and exact normalized-content deduplication. Similar but non-identical reviews are retained.

## What is included

- Real App Store RSS review collection with cache, retries, selected storefronts, and transparent warnings.
- Deterministic cleaning with a detailed removal and normalization report.
- Modern analysis console for an App Store URL and analysis goal.
- Pipeline progress for scope, collection, cleaning, analysis, critique, and planning.
- Live execution events with stage outputs, validation results, errors, and revisions.
- Separate views for raw reviews, cleaned data, and semantic classification results.
- Evidence-backed findings with support counts, conflicts, and confidence.
- PRD drafts mapped to source findings.
- Test case drafts mapped to requirements and findings.
- Example app shortcuts for quick demos.

## Next implementation steps

1. Add documented JSON and CSV review import.
2. Replace the simulated semantic stages in `app.js` with the multi-agent backend pipeline:

   - Model-driven Insight Agent.
   - Evidence Critic that validates citations, conflicts, and confidence.
   - PRD Planner and Test Designer with traceability checks.
