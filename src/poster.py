from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Any

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential_jitter

from src.healer import heal_locate
from src.post_verify import cookie_user_id, find_my_post
from src.queue_db import QueueDB
from src.selectors import SELECTORS
from src.session import challenge_message, classify_challenge, is_logged_in, login_required_message
from src.verifier import dry_run_screenshot_path, save_screenshot, verify_post_visible

log = logging.getLogger(__name__)

# Characters typed key-by-key (human feel) before the rest of the body is
# inserted in one fast operation. Keep small: long char-by-char typing exceeds
# Playwright's action timeout on long posts.
HUMAN_TYPED_PREFIX_CHARS = 18


class PostingBlocked(RuntimeError):
    pass


class SessionExpired(RuntimeError):
    pass


class PostNotVerified(RuntimeError):
    """The post was submitted but could not be confirmed live on the group (no
    permalink found) — e.g. an approval-gated group holding it for moderation, or
    a silent block. NOT retried (re-submitting would create duplicate pending
    posts) and NEVER counted as 投稿済."""


class CheckpointRequired(SessionExpired):
    """A login challenge (checkpoint / captcha / 2FA) that a profile restore can
    never fix — only a human re-login resolves it. Subclasses SessionExpired so
    the recovery path still bounds restores and stops, but the `kind` lets the
    caller alert with the specific cause (the operator's action differs)."""

    def __init__(self, message: str, kind: str = "checkpoint"):
        super().__init__(message)
        self.kind = kind


class FacebookPoster:
    def __init__(
        self,
        settings: Any,
        db: QueueDB,
        groups: list[dict[str, Any]],
        notifier: Any | None = None,
        freshness_checker: Any | None = None,
    ):
        self.settings = settings
        self.db = db
        self.groups_by_id = {g["id"]: g for g in groups}
        self.notifier = notifier
        # Optional pre-post freshness gate. When set, every job is re-validated
        # against the LATEST EstateBoard export right before posting so a listing
        # that has since been deleted/unpublished is never posted. None keeps the
        # original behavior (used by tests and dry runs without a source).
        self.freshness_checker = freshness_checker
        self._user_id: str | None = None  # logged-in bot user id (for verification)

    def _freshness_skip_reason(self, job: dict[str, Any]) -> str | None:
        """Return a skip reason when the property is no longer live on EstateBoard,
        else None. UNKNOWN (unverifiable / source missing) fails OPEN so a transient
        verification outage never halts posting — but a missing source still alerts."""
        if not self.freshness_checker:
            return None
        try:
            result = self.freshness_checker.check(job["property_id"])
        except Exception as exc:  # noqa: BLE001 - verification must never crash posting
            log.warning("freshness check errored for %s, allowing post: %s", job.get("property_id"), exc)
            return None
        if result.is_stale:
            return f"stale_property:{result.reason}"
        if getattr(result, "source_missing", False) and self.notifier:
            self.notifier.alert(
                f"⚠️ 物件の最新性を確認できませんでした（検証ソース未取得）: "
                f"{job['property_id']}（{result.reason}）。投稿は継続します。"
            )
        return None

    def _skip_job_as_stale(self, job: dict[str, Any], reason: str) -> str:
        """Mark every unposted target skipped (NOT posted) and alert — the listing
        is gone from EstateBoard, so posting it would send people to a dead link."""
        for target in self.db.unposted_targets(job["job_id"]):
            self.db.update_target_status(job["job_id"], target["group_id"], "skipped", error=reason)
        log.warning("skipping stale property %s: %s", job.get("property_id"), reason)
        if self.notifier:
            self.notifier.alert(
                f"⏭ 物件が最新でないため投稿をスキップしました: {job['property_id']}（{reason}）。"
                "EstateBoardから掲載が消えている/削除済みの可能性があります。"
            )
        return self.db.finalize_job_from_targets(job["job_id"])

    def _group_allowed_now(self, group: dict[str, Any]) -> bool:
        hours = group.get("active_hours", [0, 24])
        start, end = int(hours[0]), int(hours[1])
        try:
            from zoneinfo import ZoneInfo
            now_hour = datetime.now(ZoneInfo("Asia/Tokyo")).hour
        except Exception:
            from datetime import timezone, timedelta
            jst = timezone(timedelta(hours=9))
            now_hour = datetime.now(jst).hour
        return start <= now_hour < end if start <= end else now_hour >= start or now_hour < end

    def _preflight_target(self, job: dict[str, Any], target: dict[str, Any], group: dict[str, Any]) -> str | None:
        if self.db.count_posts_today() >= self.settings.max_posts_per_day:
            return "daily_limit"
        if not self._group_allowed_now(group):
            return "outside_active_hours"
        # One post per group per JST calendar day. This guarantees a post every
        # day (morning posts, evening skips) instead of an hours-based interval
        # that drifts later daily until it skips a whole day.
        if self.db.posted_same_group_today(target["group_id"]):
            return "same_group_interval"
        if self.db.duplicate_property_posted_ever(job["property_id"], target["group_id"]):
            return "duplicate_property_guard"
        if self.db.duplicate_property_recently(job["property_id"], target["group_id"]):
            return "duplicate_property_guard"
        return None

    @staticmethod
    def _has_more_targets(index: int, total: int) -> bool:
        return index < total - 1

    async def post_job(self, job: dict[str, Any]) -> str:
        self.db.update_job_status(job["job_id"], "posting")
        # Freshness gate (before anything else): if the property is no longer live
        # on EstateBoard, skip all targets and never post a dead listing.
        stale_reason = self._freshness_skip_reason(job)
        if stale_reason:
            return self._skip_job_as_stale(job, stale_reason)
        if self.settings.dry_run:
            for target in self.db.unposted_targets(job["job_id"]):
                group = self.groups_by_id.get(target["group_id"])
                if not group:
                    self.db.update_target_status(job["job_id"], target["group_id"], "skipped", error="group not found")
                    continue
                reason = self._preflight_target(job, target, group)
                if reason and reason != "same_group_interval":
                    self.db.update_target_status(job["job_id"], target["group_id"], "skipped", error=reason)
                    continue
                screenshot = dry_run_screenshot_path(job["job_id"], target["group_id"])
                self.db.update_target_status(job["job_id"], target["group_id"], "posted", screenshot=screenshot)
            return self.db.finalize_job_from_targets(job["job_id"])
        return await self._post_job_real(job)

    async def _post_job_real(self, job: dict[str, Any]) -> str:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            if self.settings.browser_backend != "playwright":
                raise NotImplementedError("BROWSER_BACKEND=adspower is reserved extension point")
            browser_context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.profile_dir),
                headless=False,
                viewport={"width": 1366, "height": 900},
                user_agent=self.settings.browser_user_agent,
                timeout=self.settings.page_hard_timeout * 1000,
            )
            page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
            # The bot's own user id (c_user cookie) lets us open
            # /groups/{gid}/user/{c_user} to verify each post actually published.
            self._user_id = await cookie_user_id(browser_context)
            if not self._user_id:
                log.warning("could not read c_user cookie; posts cannot be verified this run")
            try:
                posted_in_browser = 0
                targets = self.db.unposted_targets(job["job_id"])
                for index, target in enumerate(targets):
                    group = self.groups_by_id.get(target["group_id"])
                    if not group:
                        self.db.update_target_status(job["job_id"], target["group_id"], "skipped", error="group not found")
                        continue
                    reason = self._preflight_target(job, target, group)
                    if reason:
                        self.db.update_target_status(job["job_id"], target["group_id"], "skipped", error=reason)
                        continue
                    try:
                        await self._post_one(page, job, target, group)
                        self.db.record_group_result(target["group_id"], success=True, threshold=self.settings.group_fail_threshold)
                        posted_in_browser += 1
                    except SessionExpired:
                        if self.notifier:
                            self.notifier.alert(login_required_message())
                        raise
                    except PostNotVerified:
                        # Submitted but not confirmed live. _post_one already
                        # recorded it 'uncertain' (NOT 投稿済) and alerted with the
                        # group URL. Record the result for stats but do NOT re-post
                        # (avoid dup pending). No disable-suggestion alert: the
                        # operator opted to keep posting to approval-gated groups;
                        # the scheduled verify sweep promotes posts once approved.
                        self.db.record_group_result(target["group_id"], success=False, threshold=self.settings.group_fail_threshold)
                    except PostingBlocked as exc:
                        self.db.update_target_status(job["job_id"], target["group_id"], "failed", error=str(exc), increment_attempts=True)
                        if self.notifier:
                            self.notifier.alert(f"投稿制限検知。当日の残投稿を停止します: {exc}")
                        break
                    except Exception as exc:
                        screenshot = await save_screenshot(page, prefix="failed", job_id=job["job_id"], group_id=target["group_id"])
                        sanitized_error = f"{type(exc).__name__}: {exc}"[:500]
                        self.db.update_target_status(job["job_id"], target["group_id"], "failed", error=sanitized_error, screenshot=screenshot, increment_attempts=True)
                        suggest_disable = self.db.record_group_result(target["group_id"], success=False, threshold=self.settings.group_fail_threshold)
                        # Notify EVERY failure (not only at the threshold): the run
                        # will auto-retry this group on its next scheduled/logon
                        # trigger (the JST day-guard keeps that idempotent), so the
                        # operator is told both that it failed and that recovery is
                        # already in motion.
                        group_name = group.get("name", target["group_id"])
                        if self.notifier:
                            self.notifier.alert(
                                f"投稿失敗（自動リトライします）: {group_name}\n"
                                f"property={job['property_id']}\n{sanitized_error}"
                            )
                        if suggest_disable and self.notifier:
                            self.notifier.alert(f"連続失敗閾値到達。groups.yamlでenabled:false検討: {target['group_id']}")
                    if posted_in_browser >= self.settings.max_groups_per_browser:
                        await browser_context.close()
                        browser_context = await p.chromium.launch_persistent_context(
                            user_data_dir=str(self.settings.profile_dir),
                            headless=False,
                            viewport={"width": 1366, "height": 900},
                            timeout=self.settings.page_hard_timeout * 1000,
                        )
                        page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
                        posted_in_browser = 0
                    if self._has_more_targets(index, len(targets)):
                        await self._random_interval()
            finally:
                await browser_context.close()
        return self.db.finalize_job_from_targets(job["job_id"])

    async def _random_interval(self) -> None:
        seconds = random.randint(self.settings.min_interval_min * 60, self.settings.max_interval_min * 60)
        await asyncio.sleep(seconds)

    async def _human_pause(self, page: Any) -> None:
        if not self.settings.humanize:
            return
        await page.mouse.move(random.randint(100, 900), random.randint(100, 700), steps=random.randint(4, 12))
        await page.mouse.move(random.randint(100, 900), random.randint(100, 700), steps=random.randint(3, 9))
        await page.mouse.wheel(0, random.randint(100, 400))
        await page.wait_for_timeout(random.randint(800, 3200))

    @staticmethod
    def _split_body_for_typing(body: str) -> tuple[str, str]:
        """Split a body into a short human-typed prefix and a fast-inserted rest.

        Typing the whole body character-by-character with a human delay takes
        ~minutes on long posts and exceeds Playwright's action timeout, which is
        what made long bodies fail. We type only a short prefix to keep a natural
        feel, then insert the remainder in a single fast operation.
        """
        return body[:HUMAN_TYPED_PREFIX_CHARS], body[HUMAN_TYPED_PREFIX_CHARS:]

    async def _enter_body(self, page: Any, textbox: Any, body: str) -> None:
        # Type a short prefix with a human delay for natural feel, then type the
        # rest with no delay. Playwright's type() enters CJK via per-character
        # insertText events, which Facebook's Lexical editor accepts — unlike a
        # single keyboard.insert_text() of the whole remainder, which Lexical
        # drops. delay=0 keeps even long bodies well under the action timeout.
        prefix, rest = self._split_body_for_typing(body)
        await textbox.click()
        await page.wait_for_timeout(random.randint(500, 1600))
        await textbox.type(prefix, delay=random.randint(60, 160), timeout=20000)
        if rest:
            await textbox.type(rest, delay=0, timeout=60000)
        await page.wait_for_timeout(random.randint(700, 2000))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        retry=retry_if_not_exception_type((SessionExpired, PostingBlocked, PostNotVerified)),
        reraise=True,
    )
    async def _post_one(self, page: Any, job: dict[str, Any], target: dict[str, Any], group: dict[str, Any]) -> None:
        await page.goto(group["post_url"], wait_until="domcontentloaded", timeout=self.settings.page_hard_timeout * 1000)
        # Short randomized dwell so the first interaction after navigation does not
        # look robotically instant (a checkpoint trigger).
        await page.wait_for_timeout(random.randint(1200, 3500))
        if not await is_logged_in(page):
            await self._raise_session_challenge(page)
        await self._detect_blocking_markers(page)
        await self._human_pause(page)
        await self._click_first(page, "open_composer", "投稿コンポーザを開くボタン")
        textbox = await self._wait_first(page, "composer_textbox", "投稿本文入力欄")
        await self._enter_body(page, textbox, target["body"])
        await self._attach_images(page, group, target)
        await self._detect_blocking_markers(page)
        await self._verify_composer_contains(page, target["body"])
        await self._click_first(page, "post_button", "投稿を確定するボタン", strict_after=True)
        # Let the composer settle/close, then VERIFY for real: find this post's
        # direct permalink on the bot's in-group posts page. A closed composer is
        # NOT proof of publication (approval-gated groups close it but hold the
        # post) — only a found permalink is. This is the fix for false "posted".
        await verify_post_visible(page, target["body"])
        permalink = None
        if self._user_id:
            permalink = await find_my_post(
                page, target["group_id"], self._user_id, target["body"], post_url=group.get("post_url")
            )
        group_name = group.get("name", target["group_id"])
        if permalink:
            await self._open_permalink(page, permalink)
            screenshot = await save_screenshot(page, prefix="posted", job_id=job["job_id"], group_id=target["group_id"])
            self.db.update_target_status(job["job_id"], target["group_id"], "posted", screenshot=screenshot, permalink=permalink)
            if self.notifier:
                self.notifier.send_message(
                    f"✅ 投稿を確認しました（{group_name}）\n物件: {job['property_id']}\n🔗 {permalink}"
                )
            return
        # Submitted but not found live -> record 'uncertain' (blocks same-day
        # re-post to avoid duplicate pending submissions) but NOT counted as 投稿済.
        screenshot = await save_screenshot(page, prefix="uncertain", job_id=job["job_id"], group_id=target["group_id"])
        self.db.update_target_status(
            job["job_id"], target["group_id"], "uncertain",
            error="post not found live on group after submit (approval-gated/blocked?)",
            screenshot=screenshot,
        )
        if self.notifier:
            self.notifier.alert(
                f"⚠️ 投稿を確認できませんでした（{group_name}）。承認制グループ/制限の可能性があります。\n"
                f"確認URL: {group['post_url']}\n物件: {job['property_id']}（投稿済みにはカウントしません）"
            )
        raise PostNotVerified(f"post not verified live in group {target['group_id']}")

    async def _open_permalink(self, page: Any, permalink: str) -> None:
        """Open the confirmed post's permalink so the success screenshot shows the
        actual published post (double-check evidence)."""
        try:
            await page.goto(permalink, wait_until="domcontentloaded", timeout=self.settings.page_hard_timeout * 1000)
            await page.wait_for_timeout(2500)
        except Exception as exc:  # noqa: BLE001 - screenshot is best-effort
            log.warning("could not open permalink for screenshot: %s", exc)

    async def _raise_session_challenge(self, page: Any) -> None:
        """Raise the most specific session exception for the current page.

        A checkpoint/captcha/2FA is unrecoverable by a profile restore, so we
        raise CheckpointRequired (carrying the kind) to let the caller alert with
        the right operator action; a plain not-logged-in page raises SessionExpired.
        """
        kind = await classify_challenge(page)
        if kind:
            raise CheckpointRequired(challenge_message(kind), kind=kind)
        raise SessionExpired(login_required_message())

    async def _detect_blocking_markers(self, page: Any) -> None:
        url = page.url.lower()
        if "checkpoint" in url or "login" in url:
            await self._raise_session_challenge(page)
        for selector in SELECTORS["posting_block_markers"]:
            try:
                if await page.query_selector(selector):
                    raise PostingBlocked(f"blocking marker detected: {selector}")
            except PostingBlocked:
                raise
            except Exception:
                continue

    async def _click_first(self, page: Any, action: str, intent: str, *, strict_after: bool = False) -> None:
        for selector in SELECTORS[action]:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0:
                    await loc.click(timeout=8000)
                    return
            except Exception:
                continue
        if await self._text_click_fallback(page, action):
            if strict_after:
                await page.wait_for_timeout(1000)
            return
        healed = await heal_locate(page, intent, self.settings)
        if healed:
            await page.mouse.click(healed.x, healed.y)
            if strict_after:
                await page.wait_for_timeout(1000)
            return
        raise RuntimeError(f"selector and vision heal failed for {action}: {intent}")

    # Text phrases used as a no-API fallback when CSS selectors miss (FB DOM drift).
    _TEXT_FALLBACKS = {
        "open_composer": ["テキストを入力", "投稿を作成", "ディスカッションを書く", "その気持ち", "近況", "Write something", "Create post"],
        "post_button": ["投稿", "Post"],
    }

    async def _text_click_fallback(self, page: Any, action: str) -> bool:
        for phrase in self._TEXT_FALLBACKS.get(action, []):
            try:
                loc = page.get_by_text(phrase, exact=False).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=5000)
                    return True
            except Exception:
                continue
        return False

    async def _wait_first(self, page: Any, action: str, intent: str) -> Any:
        for selector in SELECTORS[action]:
            try:
                loc = page.locator(selector).first
                await loc.wait_for(state="visible", timeout=8000)
                return loc
            except Exception:
                continue
        healed = await heal_locate(page, intent, self.settings)
        if healed:
            await page.mouse.click(healed.x, healed.y)
            for selector in SELECTORS[action]:
                try:
                    loc = page.locator(selector).first
                    await loc.wait_for(state="visible", timeout=4000)
                    return loc
                except Exception:
                    continue
        raise RuntimeError(f"unable to locate {intent}")

    async def _attach_images(self, page: Any, group: dict[str, Any], target: dict[str, Any]) -> None:
        images = target.get("images") or []
        if not images or not group.get("allow_images", True):
            return
        for selector in SELECTORS["file_input"]:
            try:
                file_input = await page.query_selector(selector)
                if file_input:
                    await file_input.set_input_files(images)
                    await page.wait_for_timeout(3000)
                    return
            except Exception:
                continue

    async def _verify_composer_contains(self, page: Any, body: str) -> None:
        # Compare whitespace-squashed text: the composer renders each line as a
        # separate node, so raw newlines never appear contiguously in the HTML.
        needle = re.sub(r"\s+", "", body)[:30]
        if not needle:
            raise RuntimeError("empty post body")
        haystack = ""
        for selector in SELECTORS["composer_textbox"]:
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0:
                    haystack = await loc.inner_text()
                    if haystack.strip():
                        break
            except Exception:
                continue
        if needle in re.sub(r"\s+", "", haystack):
            return
        if needle not in re.sub(r"\s+", "", await page.content()):
            raise RuntimeError("composer body verification failed before final click")
