import sqlite3

conn = sqlite3.connect('data/jobs.db')
cursor = conn.cursor()

# Find and update bad targets
cursor.execute("""
    UPDATE job_targets
    SET status = 'skipped', last_error = 'skipped_due_to_click_boundary_conflict'
    WHERE status IN ('pending', 'pending_approval', 'approved', 'submitting')
    AND EXISTS (
        SELECT 1 FROM submission_attempts sa
        JOIN jobs j ON j.job_id = job_targets.job_id
        WHERE sa.property_id = j.property_id 
        AND sa.group_id = job_targets.group_id 
        AND sa.click_started_at IS NOT NULL
    )
""")

print(f"Updated {cursor.rowcount} blocked targets to 'skipped'")
conn.commit()

# Ensure jobs with all skipped/posted targets are finalized
cursor.execute("""
    UPDATE jobs
    SET status = 'finished'
    WHERE status IN ('pending', 'posting')
    AND NOT EXISTS (
        SELECT 1 FROM job_targets t 
        WHERE t.job_id = jobs.job_id 
        AND t.status NOT IN ('posted', 'skipped', 'failed', 'uncertain')
    )
""")
print(f"Finalized {cursor.rowcount} jobs")
conn.commit()
conn.close()
