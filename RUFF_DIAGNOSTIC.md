# Ruff diagnostic

```text
E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:338:34
    |
336 |             _record_challenge(circuits, challenge, environment)
337 |             result.update({"ok": False, "reason": f"challenge:{challenge}"})
338 |             await context.close(); _save_state(state); print(json.dumps(result, ensure_ascii=False)); return result
    |                                  ^
339 |         if not await is_logged_in(page):
340 |             circuits.record_failure(FailureKind.SESSION_EXPIRED, environment=environment, metadata={"source": "community_manager"})
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:338:54
    |
336 |             _record_challenge(circuits, challenge, environment)
337 |             result.update({"ok": False, "reason": f"challenge:{challenge}"})
338 |             await context.close(); _save_state(state); print(json.dumps(result, ensure_ascii=False)); return result
    |                                                      ^
339 |         if not await is_logged_in(page):
340 |             circuits.record_failure(FailureKind.SESSION_EXPIRED, environment=environment, metadata={"source": "community_manager"})
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:338:101
    |
336 |             _record_challenge(circuits, challenge, environment)
337 |             result.update({"ok": False, "reason": f"challenge:{challenge}"})
338 |             await context.close(); _save_state(state); print(json.dumps(result, ensure_ascii=False)); return result
    |                                                                                                     ^
339 |         if not await is_logged_in(page):
340 |             circuits.record_failure(FailureKind.SESSION_EXPIRED, environment=environment, metadata={"source": "community_manager"})
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:342:34
    |
340 |             circuits.record_failure(FailureKind.SESSION_EXPIRED, environment=environment, metadata={"source": "community_manager"})
341 |             result.update({"ok": False, "reason": "facebook session not logged in"})
342 |             await context.close(); _save_state(state); print(json.dumps(result, ensure_ascii=False)); return result
    |                                  ^
343 |         joined = await _refresh_joined(page, known)
344 |         strict_pool = _joined_strict_candidates(joined, known)
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:342:54
    |
340 |             circuits.record_failure(FailureKind.SESSION_EXPIRED, environment=environment, metadata={"source": "community_manager"})
341 |             result.update({"ok": False, "reason": "facebook session not logged in"})
342 |             await context.close(); _save_state(state); print(json.dumps(result, ensure_ascii=False)); return result
    |                                                      ^
343 |         joined = await _refresh_joined(page, known)
344 |         strict_pool = _joined_strict_candidates(joined, known)
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:342:101
    |
340 |             circuits.record_failure(FailureKind.SESSION_EXPIRED, environment=environment, metadata={"source": "community_manager"})
341 |             result.update({"ok": False, "reason": "facebook session not logged in"})
342 |             await context.close(); _save_state(state); print(json.dumps(result, ensure_ascii=False)); return result
    |                                                                                                     ^
343 |         joined = await _refresh_joined(page, known)
344 |         strict_pool = _joined_strict_candidates(joined, known)
    |

E701 Multiple statements on one line (colon)
   --> scripts/community_manager.py:347:41
    |
345 |         remaining_promotions = max(0, promotions_per_day - len(state.get("promoted", [])))
346 |         for group in strict_pool:
347 |             if remaining_promotions <= 0: break
    |                                         ^
348 |             promotable, why = await _probe_promotable(page, group)
349 |             if why.startswith("challenge:"):
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:350:49
    |
348 | …     promotable, why = await _probe_promotable(page, group)
349 | …     if why.startswith("challenge:"):
350 | …         challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "reason"…
    |                                           ^
351 | …     if promotable and _save_auto_group(group):
352 | …         gid = str(group["group_id"]); item = {"group_id": gid, "name": group.get("name", ""), "reason": why}
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:350:102
    |
348 | …     promotable, why = await _probe_promotable(page, group)
349 | …     if why.startswith("challenge:"):
350 | …         challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "reason"…
    |                                                                                                ^
351 | …     if promotable and _save_auto_group(group):
352 | …         gid = str(group["group_id"]); item = {"group_id": gid, "name": group.get("name", ""), "reason": why}
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:350:147
    |
348 | …
349 | …
350 | …llenge, environment); result.update({"ok": False, "reason": why}); break
    |                                                                   ^
351 | …
352 | …oup.get("name", ""), "reason": why}
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:352:45
    |
350 | …             challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "rea…
351 | …         if promotable and _save_auto_group(group):
352 | …             gid = str(group["group_id"]); item = {"group_id": gid, "name": group.get("name", ""), "reason": why}
    |                                           ^
353 | …             state.setdefault("promoted", []).append(item); result["promoted"].append(item); known.add(gid); remaining_promotions -=…
354 | …     attempts_today = state.get("join_attempts", []); history = state.get("join_history", [])
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:353:62
    |
351 | …         if promotable and _save_auto_group(group):
352 | …             gid = str(group["group_id"]); item = {"group_id": gid, "name": group.get("name", ""), "reason": why}
353 | …             state.setdefault("promoted", []).append(item); result["promoted"].append(item); known.add(gid); remaining_promotions -=…
    |                                                            ^
354 | …     attempts_today = state.get("join_attempts", []); history = state.get("join_history", [])
355 | …     if result["ok"] and len(attempts_today) < joins_per_day:
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:353:95
    |
351 | …         if promotable and _save_auto_group(group):
352 | …             gid = str(group["group_id"]); item = {"group_id": gid, "name": group.get("name", ""), "reason": why}
353 | …             state.setdefault("promoted", []).append(item); result["promoted"].append(item); known.add(gid); remaining_promotions -=…
    |                                                                                             ^
354 | …     attempts_today = state.get("join_attempts", []); history = state.get("join_history", [])
355 | …     if result["ok"] and len(attempts_today) < joins_per_day:
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:353:111
    |
351 | …         if promotable and _save_auto_group(group):
352 | …             gid = str(group["group_id"]); item = {"group_id": gid, "name": group.get("name", ""), "reason": why}
353 | …             state.setdefault("promoted", []).append(item); result["promoted"].append(item); known.add(gid); remaining_promotions -=…
    |                                                                                                             ^
354 | …     attempts_today = state.get("join_attempts", []); history = state.get("join_history", [])
355 | …     if result["ok"] and len(attempts_today) < joins_per_day:
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:354:56
    |
352 | …             gid = str(group["group_id"]); item = {"group_id": gid, "name": group.get("name", ""), "reason": why}
353 | …             state.setdefault("promoted", []).append(item); result["promoted"].append(item); known.add(gid); remaining_promotions -=…
354 | …     attempts_today = state.get("join_attempts", []); history = state.get("join_history", [])
    |                                                      ^
355 | …     if result["ok"] and len(attempts_today) < joins_per_day:
356 | …         attempted_ids = {str(item.get("group_id", "")) for item in [*attempts_today, *history] if isinstance(item, dict)}
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:360:42
    |
358 | …     candidates = _load_search_candidates(known, joined_ids, attempted_ids)
359 | …     if candidates:
360 | …         candidate = candidates[0]; submitted, why = await _submit_one_simple_join(page, candidate)
    |                                    ^
361 | …         entry = {"at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "group_id": str(candidate.get("group_id", "")), "name": ca…
362 | …         state.setdefault("join_attempts", []).append(entry); state.setdefault("join_history", []).append(entry); state["join_histor…
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:362:68
    |
360 | …     candidate = candidates[0]; submitted, why = await _submit_one_simple_join(page, candidate)
361 | …     entry = {"at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "group_id": str(candidate.get("group_id", "")), "name": candid…
362 | …     state.setdefault("join_attempts", []).append(entry); state.setdefault("join_history", []).append(entry); state["join_history"] …
    |                                                          ^
363 | …     if why.startswith("challenge:"):
364 | …         challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "reason"…
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:362:120
    |
360 | …     candidate = candidates[0]; submitted, why = await _submit_one_simple_join(page, candidate)
361 | …     entry = {"at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "group_id": str(candidate.get("group_id", "")), "name": candid…
362 | …     state.setdefault("join_attempts", []).append(entry); state.setdefault("join_history", []).append(entry); state["join_history"] …
    |                                                                                                              ^
363 | …     if why.startswith("challenge:"):
364 | …         challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "reason"…
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:362:174
    |
360 | …
361 | …et("group_id", "")), "name": candidate.get("name", ""), "submitted": submitted, "reason": why}
362 | …pend(entry); state["join_history"] = state["join_history"][-500:]; result["join"] = entry
    |                                                                   ^
363 | …
364 | …esult.update({"ok": False, "reason": why})
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:364:53
    |
362 | …     state.setdefault("join_attempts", []).append(entry); state.setdefault("join_history", []).append(entry); state["join_history"] …
363 | …     if why.startswith("challenge:"):
364 | …         challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "reason"…
    |                                           ^
365 | …     elif submitted and why == "joined immediately":
366 | …         promoted = {"group_id": str(candidate.get("group_id", "")), "name": candidate.get("name", "")}
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:364:106
    |
362 | …     state.setdefault("join_attempts", []).append(entry); state.setdefault("join_history", []).append(entry); state["join_history"] …
363 | …     if why.startswith("challenge:"):
364 | …         challenge = why.split(":", 1)[1]; _record_challenge(circuits, challenge, environment); result.update({"ok": False, "reason"…
    |                                                                                                ^
365 | …     elif submitted and why == "joined immediately":
366 | …         promoted = {"group_id": str(candidate.get("group_id", "")), "name": candidate.get("name", "")}
    |

E701 Multiple statements on one line (colon)
   --> scripts/community_manager.py:367:50
    |
365 |                 elif submitted and why == "joined immediately":
366 |                     promoted = {"group_id": str(candidate.get("group_id", "")), "name": candidate.get("name", "")}
367 |                     if _save_auto_group(promoted): result["promoted"].append({**promoted, "reason": "joined immediately"})
    |                                                  ^
368 |             else:
369 |                 result["join"] = {"submitted": False, "reason": "no unused safe candidate"}
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:376:61
    |
374 |             from scripts.build_group_registry import build_registry
375 |             from scripts.sync_groups_web import sync_groups_web
376 |             result["registry"] = build_registry()["summary"]; result["web_sync"] = sync_groups_web()
    |                                                             ^
377 |         except Exception as exc:
378 |             result["registry_error"] = f"{type(exc).__name__}: {exc}"
    |

E702 Multiple statements on one line (semicolon)
   --> scripts/community_manager.py:380:60
    |
378 |             result["registry_error"] = f"{type(exc).__name__}: {exc}"
379 |     result["strict_joined_unused"] = len(_joined_strict_candidates(joined, _known_group_ids()))
380 |     print(json.dumps(result, ensure_ascii=False, indent=2)); return result
    |                                                            ^

Found 24 errors.
```
