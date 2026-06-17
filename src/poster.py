from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Any

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential_jitter

from src.healer import heal_locate
from src.queue_db import QueueDB
from src.selectors import SELECTORS
from src.session import is_logged_in, login_required_message
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


class FacebookPoster:
    def __init__(self, settings: Any, db: QueueDB, groups: list[dict[str, Any]], notifier: Any | None = None):
        self.settings = settings
        self.db = db
        self.groups_by_id = {g["id"]: g for g in groups}
        self.notifier = notifier

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
        if self.db.posted_same_group_recently(target["group_id"], self.settings.min_same_group_hours):
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
                timeout=self.settings.page_hard_timeout * 1000,
            )
            page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
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
        await page.mouse.wheel(0, random.randint(100, 400))
        await page.wait_for_timeout(random.randint(500, 1800))

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
        prefix, rest = self._split_body_for_typing(body)
        await textbox.click()
        await page.wait_for_timeout(random.randint(300, 900))
        await textbox.type(prefix, delay=random.randint(40, 110), timeout=20000)
        if rest:
            await page.keyboard.insert_text(rest)
        await page.wait_for_timeout(random.randint(400, 1200))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8),
        retry=retry_if_not_exception_type((SessionExpired, PostingBlocked)),
        reraise=True,
    )
    async def _post_one(self, page: Any, job: dict[str, Any], target: dict[str, Any], group: dict[str, Any]) -> None:
        await page.goto(group["post_url"], wait_until="domcontentloaded", timeout=self.settings.page_hard_timeout * 1000)
        if not await is_logged_in(page):
            raise SessionExpired(login_required_message())
        await self._detect_blocking_markers(page)
        await self._human_pause(page)
        await self._click_first(page, "open_composer", "投稿コンポーザを開くボタン")
        textbox = await self._wait_first(page, "composer_textbox", "投稿本文入力欄")
        await self._enter_body(page, textbox, target["body"])
        await self._attach_images(page, group, target)
        await self._detect_blocking_markers(page)
        await self._verify_composer_contains(page, target["body"])
        await self._click_first(page, "post_button", "投稿を確定するボタン", strict_after=True)
        ok = await verify_post_visible(page, target["body"])
        screenshot = await save_screenshot(page, prefix="posted" if ok else "uncertain", job_id=job["job_id"], group_id=target["group_id"])
        if ok:
            self.db.update_target_status(job["job_id"], target["group_id"], "posted", screenshot=screenshot)
        else:
            self.db.update_target_status(job["job_id"], target["group_id"], "uncertain", error="post result could not be verified", screenshot=screenshot)
            if self.notifier:
                self.notifier.alert(f"投稿成否が曖昧です。重複防止のため再投稿しません: job={job['job_id']} group={target['group_id']}")

    async def _detect_blocking_markers(self, page: Any) -> None:
        url = page.url.lower()
        if "checkpoint" in url or "login" in url:
            raise SessionExpired(login_required_message())
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
