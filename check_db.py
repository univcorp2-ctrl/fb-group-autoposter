import sqlite3
conn = sqlite3.connect('data/jobs.db')
conn.row_factory = sqlite3.Row
print("job_targets:")
for row in conn.execute("SELECT job_id, group_id, status FROM job_targets WHERE status IN ('submitting', 'pending_approval', 'approved', 'pending')"):
    print(dict(row))
print("\nsubmission_attempts:")
for row in conn.execute("SELECT * FROM submission_attempts WHERE click_started_at IS NOT NULL"):
    print(dict(row))
