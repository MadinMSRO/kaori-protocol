# Kaori Dashboard — Visual Truth Feed

A React-based dashboard for monitoring Kaori truth states in real-time.

## Features

- 📊 **Live Truth Feed** — Real-time updates of truth states
- 🗺️ **Status Indicators** — Visual status badges (VERIFIED_TRUE, PENDING_HUMAN_REVIEW, etc.)
- 📈 **Confidence Display** — Confidence scores and breakdowns
- 🔍 **Detail View** — Click to see full truth state details

## Running

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173

## Tech Stack

- **React 18** + Vite
- **Lucide React** — Icons
- **Vanilla CSS** — Styling (no Tailwind)

## Screenshot

The dashboard displays:
- TruthKey (domain, topic, location, time)
- Status badge with color coding
- Confidence score
- AI and human verification flags
- Observation count

## See Also

- [flow/api/](../flow/api/) — Backend API the dashboard consumes
- [tools/demo_lifecycle.py](../tools/demo_lifecycle.py) — Demo script to generate data
