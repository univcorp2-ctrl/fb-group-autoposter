"""One-shot, audited Facebook community post for the *one* seller-permitted Daiwa property.
Owner explicitly requested an actual Facebook community post 2026-10-23.
Uses guarded CDP background transport only. No new Messenger tabs. Do not retry
after any click-start without a manual live permalink reconciliation.
"""
from __future__ import annotations
import argparse,asyncio,datetime,hashlib,json,os,sys,time,uuid
from pathlib import Path

ROOT=Path(r'C:\Users\t0015\AppData\Local\FBGroupAutoposter\app')
sys.path.insert(0,str(ROOT))
from src.authenticated_post_transport import run_authenticated_task
from config import Settings,load_groups

INVENTORY=Path(r'G:\マイドライブ\AI_Agents\Private\DAIWA\operational_inventory_20261023.json')
PRIVATE=Path(r'G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\daiwa_one_post_20261023.json')
GID='1281008662437696'
SOURCE_ID='email-1a0f0370fa1cf6d3-0'
CONSENT_ID='1a10f92be1a245e9'
POST_BODY=(
'【東京都日野市｜収益一棟物件のご紹介】\n'
'日野市豊田3丁目「D-room豊田」\n'
'・JR中央線「豊田」駅 徒歩約7分\n'
'・3階建／12世帯・駐車場5台\n'
'・価格：3億7,500万円（税込／2026年10月15日確認）\n'
'・資料上の想定利回り：約5.5％（駐車場5台すべて満車の想定）\n'
'・2026年9月30日時点：住戸満室、駐車場は5台中4台契約\n'
'※価格、利回りの前提、販売継続や稼働状況は変動します。最新状況は個別に確認します。\n'
'※詳細資料はSNS上には掲載せず、ご希望の方へ個別にご案内します。\n'
'資料をご希望の方はMessengerにてお問い合わせください。'
)

def audit_save(row):
    PRIVATE.parent.mkdir(parents=True,exist_ok=True)
    temp=PRIVATE.with_suffix('.tmp')
    temp.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temp,PRIVATE)

def ensure_authorized():
    data=json.loads(INVENTORY.read_text(encoding='utf-8'))
    matches=[x for x in data['rows'] if x.get('id')==SOURCE_ID]
    if len(matches)!=1:raise RuntimeError('source_not_unique')
    x=matches[0]
    if x.get('permission_status')!='allowed' or CONSENT_ID not in x.get('permission_evidence',''):
        raise RuntimeError('seller_consent_not_confirmed')
    if str(x.get('price_man'))!='37500' or str(x.get('yield_pct'))!='5.5':
        raise RuntimeError('source_price_yield_changed')
    if not any(z in x.get('title','') for z in ('豊田','D-room')):
        raise RuntimeError('incorrect_property')
    settings=Settings.load(ROOT/'.env')
    os.chdir(ROOT)
    groups=[x for x in load_groups() if str(x.get('id'))==GID]
    if len(groups)!=1 or not groups[0].get('enabled',True):
        raise RuntimeError('group_not_enabled')
    if len(POST_BODY)>groups[0]['max_chars']:raise RuntimeError('post_over_max_chars')
    if settings.dry_run:raise RuntimeError('dry_run_mode')
    return groups[0]

async def main(phase):
    group=ensure_authorized()
    prior=json.loads(PRIVATE.read_text(encoding='utf-8')) if PRIVATE.exists() else {}
    if prior.get('click_started_at') and phase in ('layout','submit'):
        raise RuntimeError('send_attempt_exists_reconcile_only')
    if prior.get('confirmed_permalink') and phase in ('layout','submit'):
        raise RuntimeError('already_posted_do_not_duplicate')
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    row={**prior,'source_id':SOURCE_ID,'consent_gmail_message_id':CONSENT_ID,
         'group_id':GID,'group_name':group['name'],'body_sha256':hashlib.sha256(POST_BODY.encode()).hexdigest(),
         'body':POST_BODY,'updated_at':now}
    os.environ['FB_POST_TRANSPORT']='authenticated_cdp'
    action={'probe':'find_post','layout':'layout_check','submit':'post','reconcile':'find_post'}[phase]
    task_id='daiwa-'+phase+'-'+uuid.uuid4().hex[:12]
    task={'task_id':task_id,'action':action,'status':'leased',
          'group_id':GID,'group_url':group['post_url'],'body':POST_BODY,
          'images':[],'image_root':'','image_count':0,'allow_images':False,
          'created_at_epoch':time.time(),'expires_at_epoch':time.time()+220}
    def before_click():
        if PRIVATE.exists():
            current=json.loads(PRIVATE.read_text(encoding='utf-8'))
            if current.get('click_started_at'):raise RuntimeError('duplicate_send_blocked')
        row['click_started_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        row['click_task_id']=task_id
        audit_save(row)
    if phase=='submit':row['submit_initiated_at']=now
    row['last_phase']=phase
    audit_save(row)
    result=await run_authenticated_task(task,
           ROOT/'data'/'extension_tasks'/(task_id+'.json'),
           before_click if phase=='submit' else None,timeout=190)
    row['last_phase']=phase
    row['last_status']=str(result.get('status'))
    row['last_error']=str(result.get('error') or '')[:350]
    row['last_checked_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    row['last_screenshot']=result.get('screenshot')
    if phase in ('probe','reconcile','submit') and result.get('status')=='posted':
        link=str(result.get('permalink') or '')
        if link.startswith('https://www.facebook.com/groups/'+GID+'/'):
            row['confirmed_permalink']=link
            row['confirmed_at']=row['last_checked_at']
    if phase=='submit' and result.get('click_marked'):
        row.setdefault('click_started_at',row['last_checked_at'])
    audit_save(row)
    print('RESULT',json.dumps({'phase':phase,'status':row['last_status'],
        'permalink':row.get('confirmed_permalink'),'clicked':bool(row.get('click_started_at')),
        'error':row['last_error'],'screenshot':row['last_screenshot']},ensure_ascii=False))
    if row.get('confirmed_permalink'):return 0
    return 0 if phase in ('probe','layout') and row['last_status'] in ('layout_ok','not_found','uncertain','not_posted') else 2

if __name__=='__main__':
    cli=argparse.ArgumentParser();cli.add_argument('phase',choices=['probe','layout','submit','reconcile'])
    args=cli.parse_args()
    raise SystemExit(asyncio.run(main(args.phase)))
