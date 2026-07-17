const labels={posted:'投稿済',uncertain:'要確認',failed:'失敗',pending:'待機',skipped:'スキップ'};
const fmt=v=>v?new Intl.DateTimeFormat('ja-JP',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Tokyo'}).format(new Date(v)):'—';
async function load(){
  const res=await fetch(`data/status.json?t=${Date.now()}`,{cache:'no-store'}); const data=await res.json();
  document.getElementById('updated').textContent=`最終更新 ${fmt(data.generated_at)}`;
  const health=document.getElementById('health'); health.dataset.state=data.health;
  document.getElementById('health-label').textContent=({healthy:'正常',warning:'注意',stalled:'停止疑い',error:'エラー',not_initialized:'未初期化'})[data.health]||data.health;
  document.getElementById('message').textContent=data.message||'';
  const counts=data.counts||{}; const cards=[['最終投稿',fmt(data.last_post_at)],['投稿済',counts.posted||0],['要確認',counts.uncertain||0],['失敗',counts.failed||0]];
  document.getElementById('cards').innerHTML=cards.map(([k,v])=>`<article><span>${k}</span><strong>${v}</strong></article>`).join('');
  document.getElementById('recent').innerHTML=(data.recent||[]).map(r=>`<tr><td>${fmt(r.posted_at||r.updated_at)}</td><td>${escapeHtml(r.property_id)}</td><td>${escapeHtml(r.group_id)}</td><td><span class="badge ${r.status}">${labels[r.status]||r.status}</span></td><td>${r.permalink?`<a href="${encodeURI(r.permalink)}" target="_blank" rel="noreferrer">投稿を確認</a>`:escapeHtml(r.last_error||'—')}</td></tr>`).join('')||'<tr><td colspan="5">履歴はまだありません。</td></tr>';
}
function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
load().catch(e=>{document.getElementById('message').textContent=`読込エラー: ${e.message}`;});
