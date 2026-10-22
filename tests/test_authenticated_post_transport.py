import asyncio
import json
import pytest
from src.authenticated_post_transport import TaskBridge


def task():
    return {'task_id':'bound-1', 'action':'post', 'status':'leased', 'images':[], 'image_root':''}


def test_click_is_committed_before_content_script_can_continue(tmp_path):
    calls=[]
    bridge=TaskBridge(task(), tmp_path/'task.json', lambda: calls.append('committed'))
    result=asyncio.run(bridge.receive({'type':'FB_BRIDGE_EVENT','taskId':'bound-1','stage':'click_started'}))
    assert calls == ['committed'] and result['ok']
    assert json.loads((tmp_path/'task.json').read_text())['stage']=='click_started'


def test_wrong_task_or_failed_click_commit_cannot_continue(tmp_path):
    def failed(): raise RuntimeError('commit failed')
    bridge=TaskBridge(task(),tmp_path/'task.json',failed)
    with pytest.raises(ValueError):
        asyncio.run(bridge.receive({'type':'FB_BRIDGE_GET_TASK','taskId':'other'}))
    with pytest.raises(RuntimeError):
        asyncio.run(bridge.receive({'type':'FB_BRIDGE_EVENT','taskId':'bound-1','stage':'click_started'}))
    assert not bridge.clicked


def test_pause_blocks_a_real_click_and_images_cannot_escape_root(tmp_path):
    pause=tmp_path/'pause'; pause.touch()
    bridge=TaskBridge(task(),tmp_path/'task.json',lambda:None,pause_path=pause)
    with pytest.raises(RuntimeError):
        asyncio.run(bridge.receive({'type':'FB_BRIDGE_EVENT','taskId':'bound-1','stage':'click_started'}))
    outside=tmp_path/'private.jpg';outside.write_bytes(b'private')
    inside=tmp_path/'images';inside.mkdir()
    bridge=TaskBridge({**task(),'images':[str(outside)],'image_root':str(inside)},tmp_path/'other.json')
    with pytest.raises(ValueError):
        asyncio.run(bridge.receive({'type':'FETCH_IMAGE','taskId':'bound-1','index':0}))
