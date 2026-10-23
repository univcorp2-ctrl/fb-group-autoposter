"""Noninteractive, bounded Daiwa Facebook 10-post campaign.
Uses seller-approved listing ONLY, one eligible PRIVATE group/day, same body.
Never opens Messenger tabs. No retry after an unverified Facebook click.
All evidence & state in PRIVATE Google Drive; only hashes/verified links on cloud.
"""
from __future__ import annotations
import argparse,asyncio,datetime,hashlib,json,os,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright

FB=Path(r'C:\Users\t0015\AppData\Local\FBGroupAutoposter\app')
DRIVE=Path(r'G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter')
DAIWA=Path(r'G:\マイドライブ\AI_Agents\Private\DAIWA')
ROOT=Path(r'G:\マイドライブ\AI_Agents\github\repos\EstateBoard')
ROOTFILE=DAIWA/'operational_inventory_20261023.json'
SOURCE_AUDIT=DRIVE/'daiwa_one_post_20261023.json'
STATE=DRIVE/'daiwa_facebook_ten_campaign.json'
LOCK=DRIVE/'daiwa_facebook_ten_campaign.lock'
LOG=DRIVE/'daiwa_facebook_ten_campaign_last.json'
PROPERTY='daiwa-hino-toyoda3-droom-2026'
SOURCE_ID='email-1a0f0370fa1cf6d3-0'
APPROVED_MESSAGE='1a10f92be1a245e9'
GOAL=10
GROUP_IDS=('1261566862455883','630451722001309','792499964217824',
 '628818327463444','2478498062317428','1911961896257757',
 '1092188554162022','674802419312579','2217518449046952',
 '350006781786522')
# Exclude news-only and broad entrepreneurship groups, where promotional property
# ads could be unwelcome. Private membership is positively checked at runtime.
sys.path.insert(0,str(FB))
from config import Settings,load_groups
from src.authenticated_post_transport import run_authenticated_task
from src.queue_db import QueueDB

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def local_date():return datetime.datetime.now(ZoneInfo('Asia/Tokyo')).date()
def save(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.tmp')
 tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 os.replace(tmp,path)
def read(path):return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
def quoted(value):return "'"+str(value).replace("'","''")+"'"

def current_consent():
 src=read(ROOTFILE)
 rows=[x for x in src.get('rows',[]) if x.get('id')==SOURCE_ID]
 if len(rows)!=1:raise ValueError('seller_record_missing_or_ambiguous')
 item=rows[0]
 if item.get('permission_status')!='allowed' or APPROVED_MESSAGE not in item.get('permission_evidence',''):
  raise ValueError('seller_rights_not_confirmed')
 if item.get('price_man')!='37500' or item.get('yield_pct')!='5.5':
  raise ValueError('facts_changed_requires_new_review')
 latest=datetime.date.fromisoformat('2026-10-15')
 # A newer source ZIP is not itself proof of continued offering. Require direct
 # seller reconfirmation if last explicit quotation is older than 14 days.
 if (local_date()-latest).days>14:raise ValueError('seller_price_confirmation_stale_request_reconfirmation')
 return item

def groups_by_id():
 os.chdir(FB);configured={str(g['id']):g for g in load_groups()}
 return {id:configured[id] for id in GROUP_IDS if id in configured and configured[id].get('enabled',True)}

def existing_posts(db):
 with db.connect() as conn:
  rows=conn.execute("""SELECT t.group_id,t.status,t.permalink,t.posted_at
    FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
    WHERE j.property_id=? ORDER BY t.posted_at DESC""",(PROPERTY,)).fetchall()
 return [dict(r) for r in rows]

async def check_private_membership(group):
 prof=Path(r'C:\AI-Agent\chrome-profile-authenticated\DevToolsActivePort')
 if not prof.exists():raise ValueError('dedicated_authenticated_chrome_not_running')
 endpoint='http://127.0.0.1:'+prof.read_text(encoding='ascii').splitlines()[0]
 async with async_playwright() as p:
  browser=await p.chromium.connect_over_cdp(endpoint,timeout=12000)
  ctx=browser.contexts[0]
  session=await browser.new_browser_cdp_session()
  try:
   async with ctx.expect_page(timeout=13000) as pending:
    await session.send('Target.createTarget',{'url':'about:blank','background':True})
   page=await pending.value
  finally:await session.detach()
  try:
   await page.goto(group['post_url'],wait_until='domcontentloaded',timeout=38000)
   await page.wait_for_timeout(1700)
   head=(await page.locator('body').first.inner_text(timeout=15000))[:1300]
   return ('プライベートグループ' in head and '参加済み' in head
       and 'テキストを入力' in head and str(group['id']) in page.url)
  finally:await page.close()

async def bound_task(group,body,phase,state):
 task_id='daiwa10-'+phase+'-'+uuid.uuid4().hex[:12]
 task={'task_id':task_id,'action':{'reconcile':'find_post','layout':'layout_check','submit':'post'}[phase],
  'group_id':str(group['id']),'group_url':group['post_url'],'body':body,
  'allow_images':False,'images':[],'image_count':0,'image_root':'',
  'created_at_epoch':time.time(),'expires_at_epoch':time.time()+220}
 target=state['groups'].setdefault(str(group['id']),{})
 if phase=='submit':
  if target.get('click_started_at'):raise ValueError('duplicate_click_guard')
  target['attempted_at']=now()
  save(STATE,state)
 def mark_click():
  if target.get('click_started_at'):raise RuntimeError('duplicate_click')
  target['click_started_at']=now()
  target['click_task_id']=task_id
  save(STATE,state)
 result=await run_authenticated_task(task,FB/'data'/'extension_tasks'/(task_id+'.json'),
     mark_click if phase=='submit' else None,timeout=190)
 target['last_checked_at']=now()
 target['last_status']=str(result.get('status') or '')
 target['error']=str(result.get('error') or '')[:250]
 if result.get('status')=='posted':
  url=str(result.get('permalink') or '')
  if url.startswith('https://www.facebook.com/groups/'+str(group['id'])+'/'):
   target['confirmed_permalink']=url;target['confirmed_at']=now()
 save(STATE,state)
 return result

def register_verified(group,body,state):
 target=state['groups'][str(group['id'])]
 link=target.get('confirmed_permalink','')
 gid=str(group['id'])
 if not link.startswith('https://www.facebook.com/groups/'+gid+'/'):return False
 job='daiwa-hino-toyoda3-'+gid
 db=QueueDB(FB/'data'/'jobs.db')
 with db.connect() as conn:
  found=conn.execute('SELECT job_id FROM jobs WHERE job_id=?',(job,)).fetchone()
  if not found:
   t=now()
   meta={'property_id':PROPERTY,'title':'日野市豊田3丁目 D-room豊田',
      'location':'東京都日野市豊田3丁目','price':'3億7,500万円','yield_pct':'5.5%','url':''}
   conn.execute('INSERT INTO jobs(job_id,property_id,status,created_at,updated_at,degraded,payload_json) VALUES(?,?,?,?,?,?,?)',
      (job,PROPERTY,'done',target.get('attempted_at',t),t,0,json.dumps(meta,ensure_ascii=False)))
   conn.execute('INSERT INTO job_targets(job_id,group_id,body,status,attempts,posted_at,permalink) VALUES(?,?,?,?,?,?,?)',
      (job,gid,body,'posted',1,target.get('confirmed_at',t),link))
  else:
   actual=conn.execute('SELECT status,permalink FROM job_targets WHERE job_id=? AND group_id=?',(job,gid)).fetchone()
   if not actual or actual['status']!='posted' or actual['permalink']!=link:
    raise ValueError('local_post_conflict')
 # Cloudflare D1 idempotent source-backed projection. DB failures never re-post.
 t=now();proof=json.dumps({'source':'DaiwaHouse','inventory_id':SOURCE_ID},ensure_ascii=False)
 stamp=target.get('confirmed_at',t)
 sql=[
 f"INSERT OR IGNORE INTO properties(id,external_id,title,raw_json,created_at,updated_at) VALUES({quoted(uuid.uuid4().hex)},{quoted(PROPERTY)},{quoted('日野市豊田3丁目 D-room豊田')},{quoted(proof)},{quoted(t)},{quoted(t)});",
 f"INSERT OR IGNORE INTO facebook_groups(id,external_id,name,url,created_at,updated_at) VALUES({quoted(uuid.uuid4().hex)},{quoted(gid)},{quoted(group['name'])},{quoted(group['post_url'])},{quoted(t)},{quoted(t)});",
 f"INSERT OR IGNORE INTO posting_runs(id,external_id,started_at,completed_at,status,source,created_at,updated_at) VALUES({quoted(uuid.uuid4().hex)},{quoted(job)},{quoted(target.get('attempted_at',stamp))},{quoted(stamp)},'completed','fb-group-autoposter',{quoted(t)},{quoted(t)});",
 f"INSERT OR IGNORE INTO facebook_posts(id,post_key,job_id,property_id,group_id,run_id,status,posted_at,post_url,body_excerpt,attempts,created_at,updated_at) VALUES({quoted(uuid.uuid4().hex)},{quoted(job+':'+gid)},{quoted(job)},(SELECT id FROM properties WHERE external_id={quoted(PROPERTY)}),(SELECT id FROM facebook_groups WHERE external_id={quoted(gid)}),(SELECT id FROM posting_runs WHERE external_id={quoted(job)}),'posted',{quoted(stamp)},{quoted(link)},{quoted(body[:990])},1,{quoted(t)},{quoted(t)});",
 f"UPDATE daiwa_inventory SET facebook_property_id={quoted(PROPERTY)},posted_verification='permalink_verified_campaign',updated_at=CURRENT_TIMESTAMP WHERE id={quoted(SOURCE_ID)} AND permission_status='allowed';"
 ]
 sql_file=DAIWA/('campaign_post_'+gid+'.sql')
 save_path=sql_file.with_suffix('.tmp')
 save_path.write_text('\n'.join(sql)+'\n',encoding='utf-8')
 os.replace(save_path,sql_file)
 npx='npx.cmd' if os.name=='nt' else 'npx'
 flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
 run=subprocess.run([npx,'--no-install','wrangler','d1','execute','estateboard-analytics',
    '--remote','--file',str(sql_file),'--yes'],cwd=ROOT,text=True,
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=170,creationflags=flags)
 if run.returncode:raise RuntimeError('remote_d1_sync_failure')
 target['cloud_synced_at']=now()
 save(STATE,state)
 return True

async def cycle(probe=False):
 current_consent()
 conf=groups_by_id()
 body=read(SOURCE_AUDIT).get('body')
 if not body or '駐車場5台すべて満車の想定' not in body:raise ValueError('approved_post_copy_missing')
 state=read(STATE)
 state.setdefault('goal',GOAL)
 state.setdefault('groups',{})
 state['checked_at']=now()
 db=QueueDB(FB/'data'/'jobs.db')
 posts=existing_posts(db)
 verified={r['group_id'] for r in posts if r['status']=='posted'
    and str(r.get('permalink') or '').startswith('https://www.facebook.com/groups/')}
 state['verified_count']=len(verified);state['remaining']=max(0,GOAL-len(verified))
 save(STATE,state)
 if len(verified)>=GOAL:return {'status':'goal_reached','verified':len(verified)}
 if probe:return {'status':'preview_only','verified':len(verified),'remaining':GOAL-len(verified),
    'next_groups':[conf[g]['name'] for g in GROUP_IDS if g in conf and g not in verified][:4]}
 # Any uncertain prior click must be reconciled before considering a new group.
 for gid,record in state['groups'].items():
  if record.get('click_started_at') and not record.get('confirmed_permalink'):
   group=conf.get(gid)
   if group:
    await bound_task(group,body,'reconcile',state)
    if state['groups'][gid].get('confirmed_permalink'):
     register_verified(group,body,state)
     return {'status':'prior_unverified_post_reconciled','group':gid}
   return {'status':'blocked_unconfirmed_prior_click','group':gid}
 # Respect group operating hours even when Windows runs a missed task late.
 hour=datetime.datetime.now(ZoneInfo('Asia/Tokyo')).hour
 if not 7 <= hour < 23:
  return {'status':'outside_group_hours_safe_hold','local_hour':hour}
 # One property max one community per day; group-specific cooldown also applies.
 today=str(local_date())
 if any(str(row.get('posted_at') or '')[:10]==today for row in posts):
  return {'status':'one_post_per_day_guard','verified':len(verified)}
 for gid in GROUP_IDS:
  if gid not in conf or gid in verified:continue
  group=conf[gid]
  if db.posted_same_group_today(gid):continue
  try:
   if not await check_private_membership(group):
    state['groups'].setdefault(gid,{})['hold']='private_membership_or_composer_not_confirmed'
    save(STATE,state)
    continue
  except Exception as e:
   state['groups'].setdefault(gid,{})['hold']='preflight_'+type(e).__name__
   save(STATE,state);continue
  preview=await bound_task(group,body,'reconcile',state)
  if state['groups'][gid].get('confirmed_permalink'):
   register_verified(group,body,state)
   return {'status':'old_post_reconciled','group':gid}
  layout=await bound_task(group,body,'layout',state)
  if layout.get('status')!='layout_ok':
   return {'status':'layout_not_ready','group':gid,'reason':layout.get('error','')[:100]}
  posted=await bound_task(group,body,'submit',state)
  if state['groups'][gid].get('confirmed_permalink'):
   register_verified(group,body,state)
   return {'status':'verified_new_post','group':gid,
      'permalink':state['groups'][gid]['confirmed_permalink']}
  return {'status':'submitted_unverified_or_failed','group':gid,
    'clicked':bool(state['groups'][gid].get('click_started_at')),
    'reason':str(posted.get('error'))[:120]}
 return {'status':'no_eligible_private_group','verified':len(verified)}
def main():
 cli=argparse.ArgumentParser();cli.add_argument('--check',action='store_true')
 args=cli.parse_args()
 os.chdir(FB)
 LOCK.parent.mkdir(parents=True,exist_ok=True)
 with LOCK.open('a+') as lock:
  import msvcrt
  try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
  except OSError:print('BUSY another_campaign_cycle');return 0
  try:
   result=asyncio.run(cycle(probe=args.check))
   save(LOG,{'checked_at':now(),**result})
   print(json.dumps(result,ensure_ascii=False))
   return 0 if result.get('status') not in ('submitted_unverified_or_failed','layout_not_ready') else 2
  except Exception as e:
   save(LOG,{'checked_at':now(),'status':'blocked','error_type':type(e).__name__,'reason':str(e)[:150]})
   print('BLOCKED',type(e).__name__,str(e)[:150])
   return 2
  finally:msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':raise SystemExit(main())
