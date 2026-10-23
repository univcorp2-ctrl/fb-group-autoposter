"""Guardrail tests for Daiwa Facebook multi-community daily posting."""
from __future__ import annotations
import datetime,importlib.util
from pathlib import Path
MOD=Path(__file__).resolve().parents[1]/"scripts"/"continue_daiwa_approved_daily.py"
spec=importlib.util.spec_from_file_location("daiwa_daily_rules",MOD)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
UTC=datetime.timezone.utc
AT=datetime.datetime(2026,10,24,3,0,tzinfo=UTC)
URL='https://www.facebook.com/groups/123/posts/999/'

def post(gid,stamp,status="posted",url=URL):
 return {"group_id":gid,"status":status,"posted_at":stamp,"permalink":url}

def test_multi_group_same_day_allowed():
 rate=m.posting_rate_status([
  post("100","2026-10-24T00:30:00+00:00")],moment=AT)
 assert rate['today_groups']==1 and rate['wait_seconds']==0
 assert rate['daily_minimum']==2 and rate['daily_maximum']==3

def test_two_groups_can_proceed_to_third():
 rate=m.posting_rate_status([
  post("100","2026-10-24T00:30:00+00:00"),
  post("101","2026-10-24T01:30:00+00:00")],moment=AT)
 assert rate['today_groups']==2 and rate['wait_seconds']==0

def test_max_three_distinct_communities_per_day():
 rate=m.posting_rate_status([
  post("100","2026-10-24T00:00:00+00:00"),
  post("101","2026-10-24T01:00:00+00:00"),
  post("102","2026-10-24T02:00:00+00:00")],moment=AT)
 assert rate['today_groups']==3

def test_cooldown_before_another_community():
 rate=m.posting_rate_status([post("100","2026-10-24T02:30:00+00:00")],moment=AT)
 assert rate['today_groups']==1 and rate['wait_seconds']==1800

def test_utc_previous_date_counts_in_jst_today():
 at=datetime.datetime(2026,10,24,0,5,tzinfo=UTC)
 rate=m.posting_rate_status([post("100","2026-10-23T15:50:00+00:00")],moment=at)
 assert rate['today_groups']==1

def test_duplicate_and_unverified_cannot_inflate_daily_count():
 rate=m.posting_rate_status([
  post("100","2026-10-24T00:00:00+00:00"),
  post("100","2026-10-24T01:00:00+00:00"),
  post("101","2026-10-24T02:00:00+00:00",status="uncertain"),
  post("102","2026-10-24T01:00:00+00:00",url="https://evil.invalid/")],moment=AT)
 assert rate['today_groups']==1
