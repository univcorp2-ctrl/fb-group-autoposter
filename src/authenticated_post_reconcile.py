"""Read-only reconciliation on the same authenticated transport; never resubmit."""
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from src.authenticated_post_transport import ROOT,run_authenticated_task


async def reconcile(settings, db):
    cutoff=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
    with db.connect() as conn:
        rows=conn.execute("""SELECT t.*,j.property_id FROM job_targets t JOIN jobs j USING(job_id)
            WHERE t.status='uncertain' AND t.posted_at>=? ORDER BY t.posted_at DESC LIMIT 3""",(cutoff,)).fetchall()
    summary={'checked':0,'confirmed':0,'still_uncertain':0,'transport':'authenticated_cdp','sent':0}
    for raw in rows:
        row=dict(raw); key='reconcile-'+uuid.uuid4().hex[:12]
        task={'task_id':key,'action':'find_post','group_id':row['group_id'],
              'group_url':'https://www.facebook.com/groups/'+row['group_id'],
              'body':row['body'],'images':[],'allow_images':False}
        result=await run_authenticated_task(task,ROOT/'data'/'extension_tasks'/(key+'.json'),timeout=90)
        summary['checked']+=1
        link=result.get('permalink')
        if result.get('status')=='posted' and db.is_valid_facebook_permalink(link):
            identity=hashlib.sha256((row['job_id']+row['group_id']+link).encode()).hexdigest()
            db.update_target_status_with_outbox(row['job_id'],row['group_id'],'posted',permalink=link,
                screenshot=result.get('screenshot'),event_key='verify-cdp:'+identity,event_type='verified_promotion',
                origin_run_id='verify_posts',subject_id=row['property_id'],
                payload={'text':'公開確認: '+link,'property_id':row['property_id'],'group_id':row['group_id'],'permalink':link})
            summary['confirmed']+=1
        else: summary['still_uncertain']+=1
    return summary
