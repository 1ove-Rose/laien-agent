# App Review Insights Frontend

This is the first frontend slice for the `app-review-insights` assessment. It is a runnable static workspace inspired by modern app-review analysis products: a strong App Store URL entry point, visible generation pipeline, evidence-first findings, PRD output, and traceable QA cases.

## Run locally

Open `index.html` in a browser. In this workspace the file is:

`file:///C:/Users/27295/Documents/ChatGPT/laien/index.html`

Or run the optional local preview server:

```bash
node serve.js
```

Then open `http://127.0.0.1:8765/`.

No dependency install is required for this first slice.

## What is included

- Modern analysis console for a U.S. App Store URL and analysis goal.
- Pipeline progress for scope, collection, cleaning, analysis, critique, and planning.
- Live execution events with stage outputs, validation results, errors, and revisions.
- Separate views for raw reviews, cleaned data, and semantic classification results.
- Evidence-backed findings with support counts, conflicts, and confidence.
- PRD drafts mapped to source findings.
- Test case drafts mapped to requirements and findings.
- Example app shortcuts for quick demos.

## Next implementation step

Replace the simulated analysis in `app.js` with a real backend pipeline:

1. App Store U.S. review provider.
2. Deterministic cleaning, deduplication, normalization, and validation.
3. Model-driven Insight Agent.
4. Evidence Critic that validates citations, conflicts, and confidence.
5. PRD Planner and Test Designer with traceability checks.
