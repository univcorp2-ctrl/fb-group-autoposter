"""Project confirmed Daiwa group permalink into *both* posting ledgers.
Proof only; must never submit a Facebook post.
"""
from pathlib import Path
import json,sqlite3,uuid,datetime
PR=Path(r'G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\daiwa_one_post_20261023.json')
INV=Path(r'G:\マイドライブ\AI_Agents\Private\DAIWA\operational_inventory_20261023.json')
DB=Path(r'C:\Users\t0015\AppData\Local\FBGroupAutoposter\app\data\jobs.db')
BACKUP=Path(r'G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\jobs_before_verified_daiwa_20261023.db')
SQL=Path(r'G:\マイドライブ\AI_Agents\Private\DAIWA\verified_fb_post_register_20261023.sql')
PROPERTY='daiwa-hino-toyoda3-droom-2026'
JOB='daiwa-hino-toyoda3-verified-20261023'
GID='1281008662437696'
SRC='email-1a0f0370fa1cf6d3-0'
PERMALINK='https://www.facebook.com/groups/1281008662437696/posts/2558127764725773/'
def quote(s):
 return "'"+str(s).replace("'","''")+"'"
def main():
 a=json.loads(PR.read_text(encoding='utf-8'))
 source=json.loads(INV.read_text(encoding='utf-8'))['rows']
 matched=[x for x in source if x.get('id')==SRC and x.get('permission_status')=='allowed']
 assert len(matched)==1
 assert a.get('confirmed_permalink')==PERMALINK,a
 assert a.get('click_started_at') and a.get('confirmed_at'),a
 assert a.get('group_id')==GID and a.get('consent_gmail_message_id')=='1a10f92be1a245e9'
 body=a['body']
 assert '駐車場5台すべて満車の想定' in body and '10月15日' in body
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 row={'property_id':PROPERTY,'title':'日野市豊田3丁目 D-room豊田','location':'東京都日野市豊田3丁目',
      'price':'3億7,500万円','yield_pct':'5.5%','url':'','source':'Daiwa verified permission'}
 with sqlite3.connect(DB,timeout=10) as db:
  db.execute('PRAGMA busy_timeout=10000')
  if not BACKUP.exists():
   with sqlite3.connect(BACKUP) as dst:db.backup(dst)
  old=db.execute('SELECT job_id FROM jobs WHERE job_id=?',(JOB,)).fetchone()
  if not old:
   db.execute('INSERT INTO jobs(job_id,property_id,status,created_at,updated_at,degraded,payload_json) VALUES(?,?,?,?,?,?,?)',
      (JOB,PROPERTY,'done',a['click_started_at'],now,0,json.dumps(row,ensure_ascii=False)))
   db.execute('INSERT INTO job_targets(job_id,group_id,body,status,attempts,posted_at,screenshot,permalink) VALUES(?,?,?,?,?,?,?,?)',
      (JOB,GID,body,'posted',1,a['confirmed_at'],a.get('last_screenshot'),PERMALINK))
   db.commit()
  else:
   saved=db.execute('SELECT status,permalink FROM job_targets WHERE job_id=? AND group_id=?',(JOB,GID)).fetchone()
   assert saved and saved[0]=='posted' and saved[1]==PERMALINK
  db.execute('PRAGMA integrity_check')
 def sql_uuid():return uuid.uuid4().hex
 raw=json.dumps({'source':'DaiwaHouse','approved_message_id':'1a10f92be1a245e9','inventory_id':SRC},ensure_ascii=False)
 statements=[
  f"INSERT OR IGNORE INTO properties(id,external_id,title,source_url,raw_json,created_at,updated_at) VALUES({quote(sql_uuid())},{quote(PROPERTY)},{quote('日野市豊田3丁目 D-room豊田')},NULL,{quote(raw)},{quote(now)},{quote(now)});",
  f"INSERT OR IGNORE INTO facebook_groups(id,external_id,name,url,created_at,updated_at) VALUES({quote(sql_uuid())},{quote(GID)},{quote('不動産取引の情報交換')},{quote('https://www.facebook.com/groups/'+GID)},{quote(now)},{quote(now)});",
  f"INSERT OR IGNORE INTO posting_runs(id,external_id,started_at,completed_at,status,source,created_at,updated_at) VALUES({quote(sql_uuid())},{quote(JOB)},{quote(a['click_started_at'])},{quote(a['confirmed_at'])},'completed','fb-group-autoposter',{quote(now)},{quote(now)});",
  f"INSERT OR IGNORE INTO facebook_posts(id,post_key,job_id,property_id,group_id,run_id,status,posted_at,facebook_post_id,post_url,body_excerpt,attempts,error_detail,created_at,updated_at) VALUES({quote(sql_uuid())},{quote(JOB+':'+GID)},{quote(JOB)},(SELECT id FROM properties WHERE external_id={quote(PROPERTY)}),(SELECT id FROM facebook_groups WHERE external_id={quote(GID)}),(SELECT id FROM posting_runs WHERE external_id={quote(JOB)}),'posted',{quote(a['confirmed_at'])},{quote('2558127764725773')},{quote(PERMALINK)},{quote(body[:1000])},1,'',{quote(now)},{quote(now)});",
  f"UPDATE daiwa_inventory SET facebook_property_id={quote(PROPERTY)},posted_verification='permalink_verified_20261023',updated_at=CURRENT_TIMESTAMP WHERE id={quote(SRC)} AND permission_status='allowed';"
 ]
 SQL.parent.mkdir(parents=True,exist_ok=True)
 SQL.write_text('\n'.join(statements)+'\n',encoding='utf-8')
 print('LOCAL_VERIFIED_ROW',JOB,'POST',PERMALINK,'DB_BACKUP',BACKUP.exists(),'D1_SQL',len(statements),'SQL_BYTES',SQL.stat().st_size)
if __name__=='__main__':main()
