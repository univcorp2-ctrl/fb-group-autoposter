import json
import scripts.community_manager as community_manager
from config import load_groups
def _groups_yaml():return '''
_shared: &shared
  tone: "プロフェッショナル"
  max_chars: 1200
  active_hours: [7, 23]
  allow_links: false
  allow_images: true
  forbidden: ["保証", "絶対", "確実"]
  signature: ""
  contact: "contact"
groups:
  - <<: *shared
    id: "100"
    name: "Manual Group"
    post_url: "https://www.facebook.com/groups/100"
    selection_order: "newest"
    enabled: true
'''
def test_strict_name_fit_rejects_irrelevant_sales_crypto_and_mlm():
 assert community_manager._strict_name_fit('不動産投資情報ラウンジ');assert community_manager._strict_name_fit('収益物件・不動産情報交換');assert not community_manager._strict_name_fit('売買掲示板 自動車・トラック・重機');assert not community_manager._strict_name_fit('暗号資産FX投資情報交換');assert not community_manager._strict_name_fit('MLMビジネス友達募集')
def test_save_auto_group_is_separate_from_yaml_and_load_groups_merges_shared(tmp_path,monkeypatch):
 groups_path=tmp_path/'groups.yaml';auto_path=tmp_path/'data'/'auto_groups.json';groups_path.write_text(_groups_yaml(),encoding='utf-8');monkeypatch.setattr(community_manager,'GROUPS_YAML',groups_path);monkeypatch.setattr(community_manager,'AUTO_GROUPS_JSON',auto_path);before=groups_path.read_text(encoding='utf-8');assert community_manager._save_auto_group({'group_id':'2217518449046952','name':'不動産物件情報コミュニティ'});assert groups_path.read_text(encoding='utf-8')==before;stored=json.loads(auto_path.read_text(encoding='utf-8'));assert stored['groups'][0]['enabled'] is True;merged=load_groups(groups_path);by_id={str(g['id']):g for g in merged};assert set(by_id)=={'100','2217518449046952'};assert by_id['2217518449046952']['active_hours']==[7,23]
def test_pipeline_busy_refuses_live_owner(tmp_path,monkeypatch):
 lock=tmp_path/'pipeline.lock';lock.write_text('12345',encoding='utf-8');monkeypatch.setattr(community_manager,'_pid_is_running',lambda pid:pid==12345);busy,reason=community_manager._pipeline_busy(lock);assert busy is True;assert 'active' in reason
def test_state_preserves_join_history_across_days(tmp_path,monkeypatch):
 state=tmp_path/'state.json';state.write_text(json.dumps({'date':'2000-01-01','promoted':[{'group_id':'old'}],'join_attempts':[{'group_id':'old'}],'join_history':[{'group_id':'keep'}]}),encoding='utf-8');monkeypatch.setattr(community_manager,'STATE_JSON',state);current=community_manager._load_state();assert current['promoted']==[];assert current['join_attempts']==[];assert current['join_history']==[{'group_id':'keep'}]
def test_production_browser_contract_is_headed():
 source=community_manager.Path(community_manager.__file__).read_text(encoding='utf-8');assert 'BrowserContract.from_settings' in source;assert 'build_launch_kwargs' in source;assert 'headless=True' not in source
