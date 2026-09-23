import requests

LOG_URL = "http://127.0.0.1:8000/log"


def entry(exercise_name, category, weight_raw, weight_lbs, reps_per_set, log_date):
    return {
        "exercise_name": exercise_name,
        "category": category,
        "weight_raw": weight_raw,
        "weight_lbs": weight_lbs,
        "reps_per_set": reps_per_set,
        "each_side_loaded": False,
        "log_date": log_date,
    }


ENTRIES = [
    entry("BB RDLs", "Legs", "295 lbs", 295, [4, 3], "2026-08-01"),
    entry("BB RDLs", "Legs", "295 lbs", 295, [3, 3], "2026-08-05"),
    entry("BB RDLs", "Legs", "275 lbs", 275, [4, 3], "2026-08-08"),
    entry("BB RDLs", "Legs", "295 lbs", 295, [4, 4], "2026-08-12"),
    entry("BB RDLs", "Legs", "295 lbs", 295, [3, 3], "2026-08-15"),
    entry("BB RDLs", "Legs", "285 lbs", 285, [3, 3], "2026-08-19"),
    entry("BB RDLs", "Legs", "295 lbs", 295, [4, 3], "2026-08-22"),
    entry("BB RDLs", "Legs", "295 lbs", 295, [4, 4], "2026-08-26"),
    entry("Weighted Pull Ups", "Back", "w/55 lbs", 55, [5, 5], "2026-08-01"),
    entry("Weighted Pull Ups", "Back", "w/55 lbs", 55, [6, 5], "2026-08-05"),
    entry("Weighted Pull Ups", "Back", "w/55 lbs", 55, [6, 6], "2026-08-08"),
    entry("Weighted Pull Ups", "Back", "w/60 lbs", 60, [4, 4], "2026-08-12"),
    entry("Weighted Pull Ups", "Back", "w/60 lbs", 60, [4, 4], "2026-08-15"),
    entry("Weighted Pull Ups", "Back", "w/60 lbs", 60, [4, 3], "2026-08-19"),
    entry("Weighted Pull Ups", "Back", "w/60 lbs", 60, [4, 4], "2026-08-22"),
    entry("Weighted Pull Ups", "Back", "w/60 lbs", 60, [4, 4], "2026-08-26"),
]


def main():
    for e in ENTRIES:
        label = f"{e['exercise_name']} on {e['log_date']} ({e['weight_raw']}, reps {e['reps_per_set']})"
        try:
            resp = requests.post(LOG_URL, json=e, timeout=10)
        except requests.ConnectionError:
            print(f"Could not connect to {LOG_URL}. Is the server running? (uvicorn main:app --reload)")
            return
        if resp.ok:
            print(f"Logged: {label}")
        else:
            print(f"FAILED ({resp.status_code}): {label} -> {resp.text}")


if __name__ == "__main__":
    main()
