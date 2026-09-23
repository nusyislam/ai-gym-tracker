"""Generate and log 8 sessions of realistic history for every exercise.

Usage (server must be running for a real run):
    python generate_history.py            # log everything via POST /log
    python generate_history.py --dry-run  # print the generated sessions, log nothing

Exercises that already have logged sessions are skipped, so running this twice
(or after seed_data.py) doesn't create duplicates.
"""
import random
import sys
from datetime import date, timedelta

import requests

BASE_URL = "http://127.0.0.1:8000"
END_DATE = date(2026, 9, 23)
SESSIONS = 8
DOWN_SESSION_EXERCISES = 11  # at least half of the 20 generated exercises
OFF_DAY_CHANCE = 0.12        # chance a session has one set below the rep range

# Fixed seed so the generated history is the same on every run
rng = random.Random(20260923)


# --- Exercises with fixed, hand-written history ---

FIXED = [
    {
        "name": "Weighted Pull Ups", "category": "Back", "each_side_loaded": False,
        "sessions": [
            ("2026-08-01", "w/55 lbs", 55, [5, 5]),
            ("2026-08-05", "w/55 lbs", 55, [6, 5]),
            ("2026-08-08", "w/55 lbs", 55, [6, 6]),
            ("2026-08-12", "w/60 lbs", 60, [4, 4]),
            ("2026-08-15", "w/60 lbs", 60, [4, 4]),
            ("2026-08-19", "w/60 lbs", 60, [4, 3]),
            ("2026-08-22", "w/60 lbs", 60, [4, 4]),
            ("2026-08-26", "w/60 lbs", 60, [4, 4]),
        ],
    },
    {
        "name": "BB RDLs", "category": "Legs", "each_side_loaded": True,
        "sessions": [
            ("2026-08-01", "295 lbs", 295, [4, 3]),
            ("2026-08-05", "295 lbs", 295, [3, 3]),
            ("2026-08-08", "275 lbs", 275, [4, 3]),
            ("2026-08-12", "295 lbs", 295, [4, 4]),
            ("2026-08-15", "295 lbs", 295, [3, 3]),
            ("2026-08-19", "285 lbs", 285, [3, 3]),
            ("2026-08-22", "295 lbs", 295, [4, 3]),
            ("2026-08-26", "295 lbs", 295, [4, 4]),
        ],
    },
]


# --- Exercises whose history is generated, ending at their current state ---

def ex(name, category, jump, each_side_loaded, target, rep_range, final_reps, target_raw=None):
    return {
        "name": name, "category": category, "jump": jump, "each_side_loaded": each_side_loaded,
        "target": target, "rep_range": rep_range, "final_reps": final_reps,
        # Weight description for sessions at the target weight, where the plate breakdown was given
        "target_raw": target_raw,
    }


GENERATED = [
    ex("Hammer Strength MTS Iso-Lateral Row", "Back", 5, True, 100, (5, 5), [5, 5]),
    ex("Precor Smith Machine Chest Supported Upper Back Rows", "Back", 5, True, 65, (5, 6), [5, 6]),
    ex("Atlantis Unilateral Lat Pulldowns", "Back", 10, True, 205, (5, 5), [5], "4 plates and a 25"),
    ex("Atlantis Converging Incline Bench Press", "Chest", 5, True, 115, (5, 6), [5, 6], "2 plates and a 25"),
    ex("Hammer Strength Plate-Loaded Pullovers", "Back", 5, True, 100, (5, 5), [5, 5], "2 plates and a 10"),
    ex("Atlantis Standing Lateral Raises", "Shoulders", 5, False, 135, (5, 6), [5, 6]),
    ex("Cable Rear Delt Flies", "Shoulders", 5, False, 65, (5, 6), [5, 6]),
    ex("Hammer Strength Plate-Loaded Iso-Lateral Shoulder Press", "Shoulders", 5, True, 70, (5, 6), [5, 6], "1 plate and a 25"),
    ex("Seated Incline DB Curl", "Arms", 5, True, 30, (6, 7), [6, 7]),
    ex("Atlantis Selectorized French Press", "Arms", 5, False, 130, (5, 6), [5, 6]),
    ex("Hammer Strength Plate-Loaded Seated Biceps Machine", "Arms", 5, False, 65, (5, 6), [5, 6], "1 plate and 2 10s"),
    ex("Atlantis Incline Tricep Pushdowns", "Arms", 5, False, 170, (5, 6), [5, 6]),
    ex("Decline Crunches", "Abs", 5, False, 20, (5, 6), [5, 6]),
    ex("Back Supported Leg Raises", "Abs", 5, False, 25, (6, 7), [6, 7]),
    ex("Atlantis Pivot Press", "Legs", 10, True, 270, (5, 6), [5, 6], "6 plates"),
    ex("Hammer Strength Plate-Loaded Super Horizontal Calf Raise", "Legs", 10, True, 135, (5, 6), [5, 6], "3 plates"),
    ex("Precor Glutebuilder Hip Thrust Elite", "Legs", 10, True, 205, (5, 6), [5, 6], "4 plates and a 25"),
    ex("Hammer Strength MTS Kneeling Leg Curl", "Legs", 5, True, 75, (5, 6), [5, 6]),
    ex("Atlantis Leg Extensions", "Legs", 5, False, 205, (5, 6), [5, 6]),
    ex("Glutebuilder Pendulum Kickbacks", "Legs", 10, False, 180, (5, 6), [6], "4 plates"),
]


def session_dates():
    """8 dates ending on END_DATE, 3-4 days apart, oldest first."""
    dates = [END_DATE]
    for _ in range(SESSIONS - 1):
        dates.append(dates[-1] - timedelta(days=rng.choice([3, 4])))
    return list(reversed(dates))


def working_reps(rep_range, sets, progress):
    """Reps for a normal session: low end early in a weight phase, high end later, with an
    occasional off day where one set falls below the range."""
    low, high = rep_range
    reps = [high if rng.random() < 0.2 + 0.6 * progress else low for _ in range(sets)]
    if rng.random() < OFF_DAY_CHANCE:
        reps[rng.randrange(sets)] = low - 1
    return reps


def down_session_reps(rep_range, sets):
    """A lighter auto-regulation day: reps at the top of the range, sometimes one more."""
    high = rep_range[1]
    return [high + rng.choice([0, 1])] + [high] * (sets - 1)


def generate(exercise, down_position):
    """Build 8 sessions ending exactly at the exercise's target weight and reps.

    down_position is the 1-based session (2-6) that's a down session, or None.
    """
    target, jump, rep_range = exercise["target"], exercise["jump"], exercise["rep_range"]
    sets = len(exercise["final_reps"])

    # Either a plateau at the target weight the whole way, or one increment below
    # for the early sessions, moving up to the target partway through (never on session 1)
    if rng.random() < 0.4:
        weights = [target] * SESSIONS
    else:
        first_at_target = rng.randint(2, SESSIONS)  # 1-based
        weights = [target - jump if i < first_at_target else target for i in range(1, SESSIONS + 1)]

    down_weight = min(weights) - jump

    # Progress within each run of sessions at the same weight, so reps restart low after a jump
    progress = []
    for i in range(SESSIONS):
        start = end = i
        while start > 0 and weights[start - 1] == weights[i]:
            start -= 1
        while end < SESSIONS - 1 and weights[end + 1] == weights[i]:
            end += 1
        progress.append((i - start) / (end - start) if end > start else 0.5)

    sessions = []
    for i, day in enumerate(session_dates()):
        number = i + 1
        if number == SESSIONS:
            weight, reps = target, list(exercise["final_reps"])
        elif number == down_position:
            weight, reps = down_weight, down_session_reps(rep_range, sets)
        else:
            weight, reps = weights[i], working_reps(rep_range, sets, progress[i])

        if weight == target and exercise["target_raw"]:
            weight_raw = exercise["target_raw"]
        else:
            weight_raw = f"{weight} lbs"
        sessions.append((day.isoformat(), weight_raw, weight, reps))
    return sessions


def build_plan():
    # Pick which exercises get a down session, and spread its position over sessions 2-6
    chosen = rng.sample(range(len(GENERATED)), DOWN_SESSION_EXERCISES)
    positions = []
    while len(positions) < len(chosen):
        batch = [2, 3, 4, 5, 6]
        rng.shuffle(batch)
        positions.extend(batch)
    down_positions = dict(zip(chosen, positions))

    plan = [dict(ex, generated=False) for ex in FIXED]
    for index, exercise in enumerate(GENERATED):
        plan.append({
            "name": exercise["name"],
            "category": exercise["category"],
            "each_side_loaded": exercise["each_side_loaded"],
            "sessions": generate(exercise, down_positions.get(index)),
            "down_session": down_positions.get(index),
            "generated": True,
        })
    return plan


def main():
    dry_run = "--dry-run" in sys.argv
    plan = build_plan()

    if dry_run:
        for exercise in plan:
            note = f"  (down session: #{exercise['down_session']})" if exercise.get("down_session") else ""
            print(f"\n{exercise['name']} [{exercise['category']}]{note}")
            for day, weight_raw, weight, reps in exercise["sessions"]:
                print(f"  {day}  {weight:>4} lbs  {str(reps):8}  ({weight_raw})")
        print(f"\nDry run: {sum(len(e['sessions']) for e in plan)} sessions for {len(plan)} exercises, nothing logged.")
        return

    # Skip exercises that already have history, so reruns don't duplicate anything
    try:
        existing = {e["name"]: len(requests.get(f"{BASE_URL}/history/{e['name']}", timeout=10).json()) for e in plan}
    except requests.ConnectionError:
        print(f"Could not connect to {BASE_URL}. Is the server running? (uvicorn main:app --reload)")
        return

    to_log = [e for e in plan if existing[e["name"]] == 0]
    skipped = [e for e in plan if existing[e["name"]] > 0]

    # Oldest first across all exercises, so PR detection sees each exercise's sessions in order
    entries = sorted(
        (
            (day, exercise, weight_raw, weight, reps)
            for exercise in to_log
            for day, weight_raw, weight, reps in exercise["sessions"]
        ),
        key=lambda entry: entry[0],
    )

    logged = {e["name"]: 0 for e in to_log}
    prs = {e["name"]: 0 for e in to_log}
    failures = []
    for day, exercise, weight_raw, weight, reps in entries:
        body = {
            "exercise_name": exercise["name"],
            "category": exercise["category"],
            "weight_raw": weight_raw,
            "weight_lbs": weight,
            "reps_per_set": reps,
            "each_side_loaded": exercise["each_side_loaded"],
            "log_date": day,
        }
        try:
            resp = requests.post(f"{BASE_URL}/log", json=body, timeout=10)
        except requests.RequestException as e:
            failures.append((exercise["name"], day, str(e)))
            continue
        if resp.ok:
            logged[exercise["name"]] += 1
            result = resp.json()
            if result.get("is_new_max") or result.get("is_rep_pr"):
                prs[exercise["name"]] += 1
        else:
            failures.append((exercise["name"], day, f"{resp.status_code}: {resp.text}"))

    print(f"{'Exercise':58} {'Logged':>6} {'PRs':>4}")
    for exercise in to_log:
        print(f"{exercise['name']:58} {logged[exercise['name']]:>6} {prs[exercise['name']]:>4}")
    for exercise in skipped:
        print(f"{exercise['name']:58} {'skipped':>6}  (already has {existing[exercise['name']]} sessions)")

    total = sum(logged.values())
    print(f"\nLogged {total} of {len(entries)} sessions for {len(to_log)} exercises.")
    if failures:
        print(f"{len(failures)} FAILED:")
        for name, day, error in failures:
            print(f"  {name} on {day}: {error}")
    else:
        print("No failures.")


if __name__ == "__main__":
    main()
