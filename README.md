# 🏋️ AI Gym Tracker

An AI-powered strength training tracker that logs workouts in plain English, detects real plateaus (not just "did the number go up"), and recommends exactly how much weight to add next.

Built solo in under a week using FastAPI, SQLite, the Claude API, and Claude Code as an active pair-programming collaborator.

## Why this exists

Most fitness apps treat "plateaued" as "same weight as last time." That's wrong for anyone training long-term: performance naturally dips for a hundred reasons (sleep, stress, timing, a bad grip day), and a single off session shouldn't get flagged as a real stall. This app tries to model that more honestly.

## What it does

- **Log a workout in natural language.** Type `"4 plates and a 25"` or `"1 plate and 30"` and Claude parses it into an exact weight, no manual plate math.
- **Real plateau detection.** Looks at your last 8 sessions per exercise (not just the most recent one), and automatically excludes "down sessions" — days below your established working weight — from the analysis, so an off day doesn't get miscounted as a stall.
- **Exercise-specific progression.** Every exercise has its own realistic weight-jump amount (5 lbs for a dumbbell curl, 10 lbs for a barbell lift with plates on both sides, etc.), not a one-size-fits-all increment.
- **PR celebrations.** Detects both all-time max weight PRs and rep PRs (more reps than ever at a given weight), each with its own visual treatment.
- **Two ways to browse history.** A flat chronological log, and a spreadsheet-style grid showing your last 10 sessions per exercise side by side, oldest to newest, with Category and Exercise pinned in place while you scroll through sessions.
- **Mobile-friendly.** The sidebar collapses into a top bar, tables reflow into stacked cards on narrow screens, and the History Grid stays a real scrollable table with its key columns pinned, so it's genuinely usable from a phone, not just squeezed to fit.
- **Export / import.** Download your full training history and exercise list as a JSON file, and merge it back into any instance of the app. History isn't locked to one local SQLite database.

## Tech stack

- **Backend:** FastAPI + SQLite
- **AI:** Claude API (`claude-sonnet-4-6`) for natural-language weight parsing
- **Frontend:** Vanilla HTML/CSS/JS, no framework, no build step
- **Dev workflow:** Built iteratively with Claude Code — every backend endpoint and frontend view was scoped, specified, and reviewed by hand before merging, including catching and fixing real logic bugs Claude Code introduced (see below)

## Design decisions worth knowing about

- **8-session plateau window, not 3.** An early draft used a shorter window, but at 2x/week training frequency, a short window flags noise as a real plateau. 8 sessions (~1 month) gives a more honest signal, especially for someone with years of training experience, where progress is naturally slower and less linear than for a beginner.
- **Auto-regulation handling.** A session below your established max weight for that exercise is treated as a deliberate "down session" (bad sleep, timing, whatever) and excluded from the plateau calculation, rather than breaking the streak.
- **Per-exercise weight jumps, derived from real mechanics.** A barbell lift with plates on both ends uses double the "per side" increment (since the logged number is the total). A machine with independent unilateral handles does not, since the logged number is already what's loaded on one handle. Getting this distinction right required catching and correcting a bug where every "each side" exercise was initially doubled incorrectly, a good example of why AI-generated logic still needs a human who understands the actual domain to verify it.
- **Import is additive, not destructive.** Importing merges new exercises and logs into whatever's already there instead of overwriting it, and the whole import runs in one transaction, so a malformed file can't leave the database half-updated.

## Running it locally

```bash
python -m venv venv
venv\Scripts\Activate.ps1        # Windows
pip install fastapi uvicorn python-multipart requests python-dotenv

# add your own Anthropic API key to a .env file:
echo ANTHROPIC_API_KEY=your-key-here > .env

uvicorn main:app --reload
```

Then open `http://127.0.0.1:8000/`.

To use it from your phone on the same Wi-Fi network, run `uvicorn main:app --reload --host 0.0.0.0` instead, and visit `http://<your-computer's-local-IP>:8000` from your phone's browser.

## What I'd build next

- Deload week detection (rather than just excluding down sessions, actively suggest a lighter week after a genuine plateau)
- Multi-user support with real authentication, instead of one shared local database
- A "compare two exercises" view for tracking correlated lifts (e.g., squat and RDL progress side by side)
