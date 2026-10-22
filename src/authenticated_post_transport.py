"""Run the existing guarded extension content script in an owned CDP background tab.

The queue/approval/verification state machine remains ExtensionFacebookPoster.
Only the transport changes; no cookies are copied and no browser is launched.
"""
import asyncio
import base64
import hashlib
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def save_transport_status(result, task):
    path = ROOT/'data'/'authenticated_post_transport_status.json'
    status = {'transport':'authenticated_cdp','checked_at':datetime.now(timezone.utc).isoformat(),
              'last_action':task.get('action','post'), 'last_status':result.get('status'),
              'click_marked':bool(result.get('click_marked')), 'task_id':task['task_id'],
              'source_digest':hashlib.sha256((ROOT/'extension'/'content.js').read_bytes()).hexdigest()}
    temp=path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)


def cadence_remaining(last_click, minutes, *, now=None):
    if not last_click: return 0
    instant = now or datetime.now(timezone.utc)
    age = (instant-datetime.fromisoformat(last_click)).total_seconds()
    if age < -300: raise ValueError('future submission timestamp')
    return max(0, minutes*60-age)


class TaskBridge:
    def __init__(self, task, path, on_click=None, *, pause_path=None):
        self.task, self.path, self.on_click = task, Path(path), on_click
        self.pause = Path(pause_path or ROOT/'data'/'PAUSE_POSTING')
        self.clicked = False

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self.task, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, self.path)

    async def receive(self, message):
        if message.get('taskId') != self.task['task_id']:
            raise ValueError('wrong bound task')
        kind = message.get('type')
        if kind == 'FB_BRIDGE_GET_TASK':
            return {'ok':True, 'task':{**self.task, 'image_count':len(self.task.get('images') or [])}}
        if kind == 'FB_BRIDGE_EVENT':
            stage = message.get('stage')
            if stage not in {'composer_ready', 'click_started'}: raise ValueError('invalid stage')
            if stage == 'click_started' and not self.clicked:
                if self.pause.exists(): raise RuntimeError('posting paused')
                if self.on_click: self.on_click()
                self.clicked = True
            self.task['stage'] = stage
            self.task[stage+'_at_epoch'] = time.time()
            self.save()
            return {'ok':True}
        if kind == 'FB_BRIDGE_RESULT':
            self.task.update(status='finished', finished_at_epoch=time.time(), result=message['result'])
            self.save()
            return {'ok':True}
        if kind == 'FB_TASK_DONE': return {'ok':True}
        if kind == 'FETCH_IMAGE':
            index = message.get('index')
            images = self.task.get('images') or []
            if not isinstance(index, int) or not 0 <= index < len(images): raise ValueError('invalid image index')
            image, root = Path(images[index]).resolve(), Path(self.task['image_root']).resolve()
            if root != image and root not in image.parents: raise ValueError('image outside approved root')
            return {'ok':True, 'base64':base64.b64encode(image.read_bytes()).decode('ascii'),
                    'type':mimetypes.guess_type(image.name)[0] or 'application/octet-stream'}
        raise ValueError('unsupported bridge message')


def browser_helper():
    name = '_fb_authenticated_browser'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT/'messenger'/'src'/'authenticated_chrome.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


async def run_authenticated_task(task, path, on_click=None, *, timeout=180):
    from playwright.async_api import async_playwright
    bridge = TaskBridge(task, path, on_click)
    task.update(status='leased', leased_at_epoch=time.time(), transport='authenticated_cdp')
    content = (ROOT/'extension'/'content.js').read_text(encoding='utf-8')
    task['content_sha256'] = hashlib.sha256(content.encode()).hexdigest()
    bridge.save()
    page = None
    try:
        async with async_playwright() as playwright:
            try:
                settings = SimpleNamespace(profile_dir=Path(os.getenv('FB_AUTHENTICATED_PROFILE',
                    r'C:\AI-Agent\chrome-profile-authenticated')), chrome_profile_directory='Default', browser_display_mode='auto')
                attachment = await browser_helper().attach_authenticated_context(playwright, settings)
                context = attachment.context
                session = await context.browser.new_browser_cdp_session()
                try:
                    async with context.expect_page(timeout=15000) as pending:
                        await session.send('Target.createTarget', {'url':'about:blank','background':True})
                    page = await pending.value
                finally:
                    await session.detach()
                async def receive(source, message): return await bridge.receive(message)
                await page.expose_binding('__fbTaskBridge', receive)
                url = str(task['group_url'])
                if not url.startswith('https://www.facebook.com/groups/'):
                    raise ValueError('not an authorized Facebook group URL')
                await page.goto(url+'#fbautoposter_task='+task['task_id'], wait_until='domcontentloaded', timeout=45000)
                await page.evaluate("() => { window.name='FBGroupAutoposter-Posting-Background'; }")
                await page.wait_for_timeout(1800)
                shim = """async () => {
                  const chrome = {runtime:{onMessage:{addListener(){}},
                    sendMessage: async (message) => {
                      const response = await window.__fbTaskBridge(message);
                      if (!response?.ok) throw new Error(response?.error || 'bound_bridge_failed');
                      return response;
                    }}};
                """
                await page.evaluate(shim+content+'\n}')
                deadline = time.monotonic()+timeout
                while task.get('status') != 'finished' and time.monotonic() < deadline:
                    await asyncio.sleep(.5)
                if task.get('status') != 'finished':
                    raise TimeoutError('authenticated content result timeout')
                result = {**task['result'], 'click_marked':bridge.clicked}
                if result.get('status') not in {'posted','session_ok','layout_ok'}:
                    task['editor_diagnostics'] = await page.evaluate("""() => [...document.querySelectorAll('[contenteditable="true"]')].slice(0,8).map(e=>({
                      connected:e.isConnected, visible:e.offsetParent!==null, role:e.getAttribute('role'),
                      dialog:!!e.closest('[role="dialog"]'), article:!!e.closest('[role="article"]'),
                      ancestors:(()=>{let a=[],n=e;for(let i=0;i<7&&n;i++,n=n.parentElement)a.push({tag:n.tagName,role:n.getAttribute('role'),aria:n.getAttribute('aria-label'),visible:n.offsetParent!==null});return a;})()
                    }))""")
                    bridge.save()
                screenshot = ROOT/'screenshots'/('authenticated-'+task['task_id']+'.png')
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                try:
                    await page.screenshot(path=str(screenshot), full_page=False, timeout=10000)
                    result['screenshot'] = str(screenshot)
                except Exception: pass
                save_transport_status(result,task)
                return result
            finally:
                if page:
                    try: await page.close()
                    except Exception: pass
                    page = None

    except Exception as error:
        result = {'status':'uncertain' if bridge.clicked else 'failed_before_click',
                  'error':type(error).__name__+': '+str(error)[:240], 'click_marked':bridge.clicked}
        task.update(status='finished', result=result, finished_at_epoch=time.time())
        bridge.save()
        save_transport_status(result,task)
        return result
    finally:
        if page:
            try: await page.close()
            except Exception: pass
