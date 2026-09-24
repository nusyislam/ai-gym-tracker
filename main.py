from dotenv import load_dotenv
load_dotenv()

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
import sqlite3
import json
import os
import re
import requests
from datetime import date, datetime
from typing import Any

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-6"

WEIGHT_PARSE_PROMPT = """Convert this gym weight description into a total weight in pounds.

Rules:
- Plain weights like "60 lbs", "60", or "w/60 lbs" are just that number (60).
- "N plates" means N x 45 lbs (standard Olympic plate). "4 plates" = 180.
- "N plates and a X" means N x 45 + X, where X is an add-on plate size (35, 25, 10, or 5). "4 plates and a 25" = 205.
- "N plates and M Xs" means N x 45 + M x X. "4 plates and 2 10s" = 200.

Respond with ONLY a JSON object in exactly this form, and nothing else (no explanation, no code fences):
{{"weight_lbs": 205}}

Weight description: {weight_text}"""

DB_FILE = "gym_tracker.db"

# Initial exercise list, used only to seed the exercises table when it's empty.
# After that, the exercises table is the source of truth (add new movements via POST /exercises).
EXERCISES = {
    "Back": [
        {"name": "Weighted Pull Ups", "each_side_loaded": False, "jump": 5},
        {"name": "Hammer Strength MTS Iso-Lateral Row", "each_side_loaded": True, "jump": 5},
        {"name": "Precor Smith Machine Chest Supported Upper Back Rows", "each_side_loaded": True, "jump": 5},
        {"name": "Atlantis Unilateral Lat Pulldowns", "each_side_loaded": True, "jump": 10},
        {"name": "Hammer Strength Plate-Loaded Pullovers", "each_side_loaded": True, "jump": 5},
    ],
    "Chest": [
        {"name": "Atlantis Converging Incline Bench Press", "each_side_loaded": True, "jump": 5},
    ],
    "Arms": [
        {"name": "Seated Incline DB Curl", "each_side_loaded": True, "jump": 5},
        {"name": "Atlantis Selectorized French Press", "each_side_loaded": False, "jump": 5},
        {"name": "Hammer Strength Plate-Loaded Seated Biceps Machine", "each_side_loaded": False, "jump": 5},
        {"name": "Atlantis Incline Tricep Pushdowns", "each_side_loaded": False, "jump": 5},
    ],
    "Shoulders": [
        {"name": "Atlantis Standing Lateral Raises", "each_side_loaded": False, "jump": 5},
        {"name": "Cable Rear Delt Flies", "each_side_loaded": False, "jump": 5},
        {"name": "Hammer Strength Plate-Loaded Iso-Lateral Shoulder Press", "each_side_loaded": True, "jump": 5},
    ],
    "Abs": [
        {"name": "Decline Crunches", "each_side_loaded": False, "jump": 5},
        {"name": "Back Supported Leg Raises", "each_side_loaded": False, "jump": 5},
    ],
    "Legs": [
        {"name": "BB RDLs", "each_side_loaded": True, "jump": 10},
        {"name": "Atlantis Pivot Press", "each_side_loaded": True, "jump": 10},
        {"name": "Hammer Strength Plate-Loaded Super Horizontal Calf Raise", "each_side_loaded": True, "jump": 10},
        {"name": "Precor Glutebuilder Hip Thrust Elite", "each_side_loaded": True, "jump": 10},
        {"name": "Hammer Strength MTS Kneeling Leg Curl", "each_side_loaded": True, "jump": 5},
        {"name": "Atlantis Leg Extensions", "each_side_loaded": False, "jump": 5},
        {"name": "Glutebuilder Pendulum Kickbacks", "each_side_loaded": False, "jump": 10},
    ],
}
DEFAULT_WEIGHT_JUMP = 5


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workout_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exercise_name TEXT NOT NULL,
            category TEXT NOT NULL,
            weight_raw TEXT NOT NULL,
            weight_lbs REAL NOT NULL,
            reps_per_set TEXT NOT NULL,
            each_side_loaded INTEGER NOT NULL,
            log_date TEXT NOT NULL
        )
    """)
    # Databases created before unilateral was removed still have the column (NOT NULL),
    # which would make every insert fail, so drop it
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(workout_logs)")]
    if "unilateral" in columns:
        conn.execute("ALTER TABLE workout_logs DROP COLUMN unilateral")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS exercises (
            name TEXT PRIMARY KEY,
            category TEXT,
            each_side_loaded INTEGER,
            jump REAL
        )
    """)
    if conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO exercises (name, category, each_side_loaded, jump) VALUES (?, ?, ?, ?)",
            [
                (ex["name"], category, int(ex["each_side_loaded"]), ex["jump"])
                for category, exercises in EXERCISES.items()
                for ex in exercises
            ],
        )
    conn.commit()
    conn.close()


init_db()


class WorkoutEntry(BaseModel):
    exercise_name: str
    category: str
    weight_raw: str
    weight_lbs: float
    reps_per_set: list[int]
    each_side_loaded: bool = False
    log_date: str = Field(default_factory=lambda: str(date.today()))


@app.post("/log")
def log_workout(entry: WorkoutEntry):
    # PR detection against the history before this entry. A first-ever session is neither:
    # there's nothing to beat yet.
    history = fetch_history(entry.exercise_name)
    is_new_max = bool(history) and entry.weight_lbs > max(s["weight_lbs"] for s in history)

    # A rep PR means beating the best set at a weight that's been logged before
    reps_at_weight = [rep for s in history if s["weight_lbs"] == entry.weight_lbs for rep in s["reps_per_set"]]
    is_rep_pr = (
        not is_new_max
        and bool(reps_at_weight)
        and bool(entry.reps_per_set)
        and max(entry.reps_per_set) > max(reps_at_weight)
    )

    conn = get_db()
    conn.execute(
        """INSERT INTO workout_logs
           (exercise_name, category, weight_raw, weight_lbs, reps_per_set, each_side_loaded, log_date)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.exercise_name,
            entry.category,
            entry.weight_raw,
            entry.weight_lbs,
            json.dumps(entry.reps_per_set),
            int(entry.each_side_loaded),
            entry.log_date,
        ),
    )
    conn.commit()
    conn.close()
    return {
        "status": "logged",
        "exercise": entry.exercise_name,
        "is_new_max": is_new_max,
        "is_rep_pr": is_rep_pr,
    }


def log_row_to_dict(row):
    return {
        "id": row["id"],
        "exercise_name": row["exercise_name"],
        "category": row["category"],
        "weight_raw": row["weight_raw"],
        "weight_lbs": row["weight_lbs"],
        "reps_per_set": json.loads(row["reps_per_set"]),
        "each_side_loaded": bool(row["each_side_loaded"]),
        "log_date": row["log_date"],
    }


def fetch_history(exercise_name: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM workout_logs WHERE exercise_name = ? ORDER BY log_date ASC",
        (exercise_name,),
    ).fetchall()
    conn.close()
    return [log_row_to_dict(row) for row in rows]


@app.get("/history/{exercise_name}")
def get_history(exercise_name: str):
    return fetch_history(exercise_name)


@app.get("/all-logs")
def all_logs():
    conn = get_db()
    rows = conn.execute("SELECT * FROM workout_logs ORDER BY log_date DESC, id DESC").fetchall()
    conn.close()
    return [log_row_to_dict(row) for row in rows]


HISTORY_GRID_SESSIONS = 10


@app.get("/history-grid")
def history_grid():
    conn = get_db()
    # Each exercise's most recent sessions, newest first
    rows = conn.execute("""
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY exercise_name ORDER BY log_date DESC, id DESC
            ) AS rn
            FROM workout_logs
        )
        WHERE rn <= ?
        ORDER BY exercise_name, rn
    """, (HISTORY_GRID_SESSIONS,)).fetchall()
    known_categories = {row["name"]: row["category"] for row in conn.execute("SELECT name, category FROM exercises")}
    conn.close()

    exercises = {}
    for row in rows:
        if row["exercise_name"] not in exercises:
            # rn = 1 comes first: the most recent session, whose category is the fallback
            exercises[row["exercise_name"]] = {
                "category": known_categories.get(row["exercise_name"], row["category"]),
                "sessions": [],
            }
        exercises[row["exercise_name"]]["sessions"].append({
            "weight_lbs": format_lbs(row["weight_lbs"]),
            "weight_raw": row["weight_raw"],
            "reps_per_set": json.loads(row["reps_per_set"]),
            "log_date": row["log_date"],
        })

    # Most recently trained exercise first within each category (sessions[0] is still the
    # most recent here, which this sort and the category fallback above rely on)
    ordered = sorted(exercises.items(), key=lambda item: item[1]["sessions"][0]["log_date"], reverse=True)
    grouped = {}
    for name, info in ordered:
        grouped.setdefault(info["category"], []).append({
            "exercise_name": name,
            # Oldest first in the response, so Session 1 is the oldest of the 10 and the last is the latest
            "sessions": info["sessions"][::-1],
        })
    return grouped


class NewExercise(BaseModel):
    name: str
    category: str
    each_side_loaded: bool
    jump: float = Field(gt=0)


@app.get("/exercises")
def list_exercises():
    conn = get_db()
    rows = conn.execute("SELECT * FROM exercises ORDER BY rowid").fetchall()
    conn.close()

    grouped = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append({
            "name": row["name"],
            "each_side_loaded": bool(row["each_side_loaded"]),
            "jump": format_lbs(row["jump"]),
        })
    return grouped


@app.post("/exercises")
def add_exercise(exercise: NewExercise):
    name = exercise.name.strip()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO exercises (name, category, each_side_loaded, jump) VALUES (?, ?, ?, ?)",
            (name, exercise.category.strip(), int(exercise.each_side_loaded), exercise.jump),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"An exercise named '{name}' already exists.")
    finally:
        conn.close()
    return {"status": "added", "exercise": name}


@app.get("/current-bests")
def current_bests():
    conn = get_db()
    # For each logged exercise: its max weight, and the earliest date that max was logged.
    # Category comes from the exercises table; exercises missing from it fall back to
    # the category of their most recent log entry.
    rows = conn.execute("""
        WITH bests AS (
            SELECT exercise_name, MAX(weight_lbs) AS best_weight_lbs
            FROM workout_logs
            GROUP BY exercise_name
        )
        SELECT
            b.exercise_name,
            b.best_weight_lbs,
            (SELECT MIN(w.log_date) FROM workout_logs w
             WHERE w.exercise_name = b.exercise_name AND w.weight_lbs = b.best_weight_lbs) AS date_hit,
            COALESCE(
                e.category,
                (SELECT w.category FROM workout_logs w
                 WHERE w.exercise_name = b.exercise_name
                 ORDER BY w.log_date DESC, w.id DESC LIMIT 1)
            ) AS category
        FROM bests b
        LEFT JOIN exercises e ON e.name = b.exercise_name
        ORDER BY e.rowid IS NULL, e.rowid, b.exercise_name
    """).fetchall()
    conn.close()

    grouped = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append({
            "exercise_name": row["exercise_name"],
            "best_weight_lbs": format_lbs(row["best_weight_lbs"]),
            "date_hit": row["date_hit"],
        })
    return grouped


@app.get("/export")
def export_data():
    conn = get_db()
    exercises = conn.execute("SELECT * FROM exercises ORDER BY rowid").fetchall()
    logs = conn.execute("SELECT * FROM workout_logs ORDER BY log_date, id").fetchall()
    conn.close()

    data = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "exercises": [
            {
                "name": row["name"],
                "category": row["category"],
                "each_side_loaded": bool(row["each_side_loaded"]),
                "jump": format_lbs(row["jump"]),
            }
            for row in exercises
        ],
        "workout_logs": [
            {key: value for key, value in log_row_to_dict(row).items() if key != "id"}
            for row in logs
        ],
    }
    filename = f"gym-tracker-export-{date.today()}.json"
    # Indented so the downloaded file is readable, one field per line
    return Response(
        content=json.dumps(data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ImportedLog(WorkoutEntry):
    # Unlike /log, an imported entry must carry its own date instead of defaulting to today
    log_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class ImportData(BaseModel):
    exercises: list[NewExercise]
    workout_logs: list[ImportedLog]


def describe_validation_error(error: ValidationError):
    """Turn Pydantic errors into readable lines like 'workout_logs[3].weight_lbs: Field required'."""
    lines = []
    for err in error.errors()[:5]:
        path = ""
        for part in err["loc"]:
            path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
        message = err["msg"]
        if err["type"] == "string_pattern_mismatch" and err["loc"][-1] == "log_date":
            message = "should be a date like 2026-09-23"
        lines.append(f"{path}: {message}")
    more = len(error.errors()) - len(lines)
    return "; ".join(lines) + (f" (and {more} more)" if more > 0 else "")


@app.post("/import")
def import_data(payload: Any = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Not a Gym Tracker export: expected a JSON object.")
    missing = [key for key in ("exercises", "workout_logs") if key not in payload]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Not a Gym Tracker export: missing {' and '.join(repr(k) for k in missing)}.",
        )
    # Validate everything before touching the database
    try:
        data = ImportData.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"Invalid import file: {describe_validation_error(e)}")

    conn = get_db()
    try:
        # One transaction: commits only if every insert succeeds, otherwise rolls back entirely
        with conn:
            exercises_added = 0
            for exercise in data.exercises:
                # Existing exercises are left untouched, since their jump/each_side_loaded
                # may have been corrected locally
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO exercises (name, category, each_side_loaded, jump) VALUES (?, ?, ?, ?)",
                    (exercise.name.strip(), exercise.category.strip(), int(exercise.each_side_loaded), exercise.jump),
                )
                exercises_added += cursor.rowcount

            # Additive: logs are always inserted, never deduplicated against existing ones
            conn.executemany(
                """INSERT INTO workout_logs
                   (exercise_name, category, weight_raw, weight_lbs, reps_per_set, each_side_loaded, log_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        log.exercise_name,
                        log.category,
                        log.weight_raw,
                        log.weight_lbs,
                        json.dumps(log.reps_per_set),
                        int(log.each_side_loaded),
                        log.log_date,
                    )
                    for log in data.workout_logs
                ],
            )
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Import failed and was rolled back, nothing was changed: {e}")
    finally:
        conn.close()

    return {
        "exercises_added": exercises_added,
        "exercises_skipped": len(data.exercises) - exercises_added,
        "workout_logs_added": len(data.workout_logs),
    }


PLATEAU_WINDOW = 8
REP_TARGET = 7


def format_lbs(weight: float):
    return int(weight) if float(weight).is_integer() else weight


def get_weight_jump(exercise_name: str):
    conn = get_db()
    row = conn.execute("SELECT jump FROM exercises WHERE name = ?", (exercise_name,)).fetchone()
    conn.close()
    return row["jump"] if row else DEFAULT_WEIGHT_JUMP


@app.get("/plateau-check/{exercise_name}")
def plateau_check(exercise_name: str):
    history = fetch_history(exercise_name)

    if len(history) < PLATEAU_WINDOW:
        return {
            "exercise_name": exercise_name,
            "sessions_found": len(history),
            "sessions_needed": PLATEAU_WINDOW,
            "plateaued": None,
            "recommendation": f"Not enough data yet: {len(history)} of {PLATEAU_WINDOW} sessions logged.",
        }

    # A session is auto-regulated (a deliberate down session) if its weight is below
    # the heaviest weight logged in any earlier session, across the full history.
    auto_regulated = []
    max_so_far = None
    for s in history:
        auto_regulated.append(max_so_far is not None and s["weight_lbs"] < max_so_far)
        max_so_far = s["weight_lbs"] if max_so_far is None else max(max_so_far, s["weight_lbs"])

    recent = history[-PLATEAU_WINDOW:]
    evaluated = [s for s, down in zip(recent, auto_regulated[-PLATEAU_WINDOW:]) if not down]
    excluded_count = len(recent) - len(evaluated)
    current = recent[-1]
    current_weight = current["weight_lbs"]

    if not evaluated:
        return {
            "exercise_name": exercise_name,
            "sessions_analyzed": len(recent),
            "auto_regulated_sessions_excluded": excluded_count,
            "plateaued": None,
            "current_weight_lbs": format_lbs(current_weight),
            "recommendation": "Not enough non-adjusted sessions to evaluate.",
        }

    weights = [s["weight_lbs"] for s in evaluated]
    weight_increased = any(later > earlier for earlier, later in zip(weights, weights[1:]))
    hit_rep_target = any(rep >= REP_TARGET for s in evaluated for rep in s["reps_per_set"])
    hit_rep_target_at_current = any(
        rep >= REP_TARGET
        for s in evaluated
        if s["weight_lbs"] == current_weight
        for rep in s["reps_per_set"]
    )
    plateaued = not weight_increased and not hit_rep_target

    if plateaued:
        # Base the jump on the all-time max (max_so_far after the loop above), not the latest
        # session, so a down session doesn't drag the suggestion below the real working weight
        jump = get_weight_jump(exercise_name)
        next_weight = format_lbs(max_so_far + jump)
        recommendation = (
            f"No weight increase and no set of {REP_TARGET}+ reps in your last {PLATEAU_WINDOW} sessions. "
            f"Try increasing to {next_weight} lbs next session."
        )
    elif hit_rep_target_at_current:
        recommendation = (
            f"You've hit {REP_TARGET}+ reps at {format_lbs(current_weight)} lbs, "
            f"consider increasing weight next session."
        )
    else:
        recommendation = f"Still progressing, keep at {format_lbs(current_weight)} lbs."

    return {
        "exercise_name": exercise_name,
        "sessions_analyzed": len(recent),
        "auto_regulated_sessions_excluded": excluded_count,
        "plateaued": plateaued,
        "current_weight_lbs": format_lbs(current_weight),
        "recommendation": recommendation,
    }


class WeightText(BaseModel):
    weight_text: str


@app.post("/parse-weight")
def parse_weight(body: WeightText):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not set. Add it to your .env file.")

    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 100,
                "messages": [
                    {"role": "user", "content": WEIGHT_PARSE_PROMPT.format(weight_text=body.weight_text)}
                ],
            },
            timeout=30,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Could not reach the Claude API: {e}")

    if resp.status_code != 200:
        try:
            message = resp.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = resp.text
        raise HTTPException(status_code=502, detail=f"Claude API error ({resp.status_code}): {message}")

    try:
        data = resp.json()
        text = "".join(block["text"] for block in data["content"] if block.get("type") == "text")
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=502, detail="Unexpected response format from the Claude API.")

    # Pull out the {...} in case Claude wraps the JSON in code fences or extra words
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        weight = json.loads(match.group(0))["weight_lbs"] if match else None
        weight = float(weight)
    except (ValueError, KeyError, TypeError):
        weight = None

    if weight is None:
        raise HTTPException(
            status_code=422,
            detail=f"Could not parse a weight from '{body.weight_text}'. Claude responded: {text!r}",
        )

    return {"weight_lbs": int(weight) if weight.is_integer() else weight}