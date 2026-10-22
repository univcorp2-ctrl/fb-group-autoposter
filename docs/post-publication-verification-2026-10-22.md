# Public post verified

- Property: eb-29625, 二棟一括売ビル（三崎町MKビル＋矢嶋ビル）, 55億円.
- Automatic submission: 2026-10-22 17:22:31 JST, attempt `7c406dc8-2ebf-4418-9c8c-93eef98a4aca`.
- Public URL: https://www.facebook.com/groups/674802419312579/posts/28386522904380491/
- Reconciliation opened the rendered own-posts list, followed the same-group permalink, expanded the post and matched the complete approved body. Decimal points and amounts are preserved during matching; invisible emoji and whitespace may differ.
- Production DB `C:\Users\t0015\AppData\Local\FBGroupAutoposter\data\jobs.db`: submission and target are now `posted`; verified-promotion outbox event saved. No post was resubmitted.
- The previous fetch-only own-post lookup missed the visible post. Added `src/authenticated_post_lookup.py` and connected read-only DOM verification to uncertain submissions and reconciliation in `authenticated_post_transport.py`, in both source and C runtime.
- Verification: five focused tests passed; actual `run_authenticated_task(action=find_post)` returned `posted`, `verification=own_posts_dom_full_body`. Screenshot: C runtime `screenshots/authenticated-reconcile-confirmed-20261022-1740.png`.
- Current 5-hour usage remaining: 67%. Other uncertain attempts were not replayed. Next action, if needed: read-only reconciliation of other attempts; do not call old clicks new successful submissions.
- KEEP: implementation, tests, receipt, runtime screenshots and backups under `tmp/2026-10-22-post-verification`. ARCHIVE / DELETE: none.
