import sqlite3

conn = sqlite3.connect('gym_tracker.db')
conn.execute("DELETE FROM workout_logs WHERE id = 200")
conn.commit()

remaining = conn.execute(
    "SELECT COUNT(*) FROM workout_logs WHERE exercise_name = 'Hammer Strength Plate-Loaded Iso-Lateral Shoulder Press'"
).fetchone()[0]
print(f"Remaining sessions for this exercise: {remaining}")

conn.close()