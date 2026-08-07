import sqlite3
import json

conn = sqlite3.connect('data/jobs.db')
conn.row_factory = sqlite3.Row

print("Pending/posting jobs:")
for r in conn.execute("SELECT job_id, property_id, status FROM jobs WHERE status IN ('pending', 'posting')"):
    print(dict(r))

print("\nTargets causing click boundary error:")
# Find targets that have status pending/pending_approval/approved/submitting 
# but their property_id and group_id combination already has a click_started_at in submission_attempts
bad_targets = conn.execute("""
    SELECT j.property_id, t.job_id, t.group_id, t.status 
    FROM job_targets t 
    JOIN jobs j ON j.job_id = t.job_id 
    WHERE t.status IN ('pending', 'pending_approval', 'approved', 'submitting') 
    AND EXISTS (
        SELECT 1 FROM submission_attempts sa 
        WHERE sa.property_id = j.property_id AND sa.group_id = t.group_id AND sa.click_started_at IS NOT NULL
    )
""").fetchall()

for r in bad_targets:
    print(dict(r))
