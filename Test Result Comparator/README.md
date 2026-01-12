# Test Report Comparator

Client-side web app for comparing multiple JSON test reports. Drop runs, pick a baseline and a comparison, and review regressions with transcript diffs and CSV export.

## Requirements

- Node.js 18+

## Getting started

```bash
npm install
npm run dev
```

Open the local Vite URL (usually `http://localhost:5173`).

## Docker

Build and run a production container from this folder:

```bash
docker build -t test-report-comparator .
docker run --rm -p 8080:80 test-report-comparator
```

Then open `http://localhost:8080`.

Alternatively, use Docker Compose:

```bash
docker-compose up --build
```

## Features

- Drag-and-drop multiple JSON reports (or click to upload)
- Baseline vs compare selectors with per-run cards
- Overview table with filters, regressions-first sorting, and output-change detection
- Detail view with turn-level diffs, JSON diff paths, and scorer summaries
- CSV export for filtered regressions

## Notes

- Parsing is fully client-side and tolerant of per-file errors.
- Test matching uses the normalized objective name as the key.
- Assistant envelopes are parsed without `eval` and keep raw JSON strings when parsing fails.
