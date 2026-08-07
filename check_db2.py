import sqlite3
import json

conn = sqlite3.connect('data/jobs.db')
conn.row_factory = sqlite3.Row

rows = conn.execute('''
    SELECT j.property_id, t.job_id, t.group_id, t.status, 
           t.approval_id, t.source_hash, t.normalized_body_hash, t.generation_fingerprint
    FROM job_targets t
    JOIN jobs j ON j.job_id = t.job_id
    WHERE t.status IN ('pending', 'pending_approval', 'approved', 'submitting')
''').fetchall()

print("Targets:")
for r in rows:
    print(dict(r))
