from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from src.circuits import FailureKind
from src.post_quality import evaluate as evaluate_post_quality
from src.poster import FacebookPoster, PostNotVerified, SessionExpired, SubmissionAmbiguous


class ExtensionFacebookPoster(FacebookPoster):
    """Post through the unpacked extension running in the user's real Chrome Default profile."""

    @property
    def _task_dir(self) -> Path:
        root = Path(__file__).resolve().parents[1]
        path = Path(os.getenv("FB_EXTENSION_TASK_DIR", str(root / "data" / "extension_tasks")))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _image_root(images: list[str]) -> str:
        if not images:
            return ""
        resolved = [str(Path(item).resolve()) for item in images]
        common = Path(os.path.commonpath(resolved))
        if common.is_file() or common.suffix:
            common = common.parent
        return str(common)

    async def _dispatch_and_wait(
        self,
        *,
        attempt_id: str,
        target: dict[str, Any],
        group: dict[str, Any],
        timeout: int = 180,
    ) -> dict[str, Any]:
        task_path = self._task_dir / f"{attempt_id}.json"
        images = [str(item) for item in (target.get("images") or [])]
        payload = {
            "task_id": attempt_id,
            "status": "pending",
            "created_at_epoch": time.time(),
            "expires_at_epoch": time.time() + timeout,
            "group_id": str(target["group_id"]),
            "group_url": str(group["post_url"]),
            "body": str(target["body"]),
            "images": images,
            "image_root": self._image_root(images),
            "allow_images": bool(group.get("allow_images", True)),
        }
        self._atomic_json(task_path, payload)
        deadline = time.monotonic() + timeout
        click_marked = False
        while time.monotonic() < deadline:
            try:
                current = json.loads(task_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                await asyncio.sleep(1)
                continue
            if current.get("stage") == "click_started" and not click_marked:
                self.db.mark_click_started(attempt_id)
                click_marked = True
            if current.get("status") == "finished":
                result = current.get("result") or {}
                result["click_marked"] = click_marked
                return result
            await asyncio.sleep(1)
        if click_marked:
            raise SubmissionAmbiguous("extension result timeout after final click")
        raise RuntimeError("extension_dispatch_timeout_before_click")

    async def _post_job_real(self, job: dict[str, Any]) -> str:
        unbound = [
            target for target in self.db.get_targets(job["job_id"])
            if target["status"] in {"pending", "pending_approval", "approved", "failed"}
            and not self._target_has_approval_binding(target)
        ]
        if unbound:
            for target in unbound:
                self.db.update_target_status(
                    job["job_id"], target["group_id"], "pending_approval",
                    error="manual_reapproval_required",
                )
            self.db.update_job_status(job["job_id"], "pending")
            return "pending"

        blocking = self.circuits.blocking_circuit(environment=self._runtime_environment)
        if blocking:
            for target in self.db.unposted_targets(job["job_id"]):
                self.db.update_target_status(
                    job["job_id"], target["group_id"], "skipped",
                    error=f"circuit_open:{blocking['reason']}",
                )
            return self.db.finalize_job_from_targets(job["job_id"])

        for target in self.db.unposted_targets(job["job_id"]):
            group = self.groups_by_id.get(target["group_id"])
            if not group:
                self.db.update_target_status(job["job_id"], target["group_id"], "skipped", error="group not found")
                continue
            quality = evaluate_post_quality(str(target.get("body") or ""))
            if not quality.passes:
                # Last line of defence: never publish an unreadable/legacy body
                # (lost line breaks, rule spam, negative CF, missing facts).
                self.db.update_target_status(
                    job["job_id"], target["group_id"], "skipped",
                    error=f"quality_gate:{quality.summary()}"[:500],
                )
                continue
            reason = self._preflight_target(job, target, group)
            if reason:
                self.db.update_target_status(job["job_id"], target["group_id"], "skipped", error=reason)
                continue
            group_circuit = self.circuits.blocking_circuit(
                group_id=target["group_id"], environment=self._runtime_environment
            )
            if group_circuit:
                self.db.update_target_status(
                    job["job_id"], target["group_id"], "skipped",
                    error=f"circuit_open:{group_circuit['reason']}",
                )
                continue
            try:
                await self._post_target_via_extension(job, target, group)
            except PostNotVerified:
                # Already recorded as 'uncertain' (+ alert). Letting it escape
                # aborted the cycle, and ensure_posted_today immediately re-ran
                # it — posting to the next group ~2 min later and bypassing the
                # 15-35 min spacing. Treat it like the Playwright path: no re-post,
                # keep going, and let the orchestrator apply the normal interval.
                continue
        return self.db.finalize_job_from_targets(job["job_id"])

    async def _post_target_via_extension(
        self,
        job: dict[str, Any],
        target: dict[str, Any],
        group: dict[str, Any],
    ) -> None:
        attempt_id = self._begin_submission_if_bound(job, target)
        try:
            result = await self._dispatch_and_wait(
                attempt_id=attempt_id,
                target=target,
                group=group,
            )
        except BaseException:
            self._quarantine_or_abort_attempt(attempt_id)
            raise

        status = str(result.get("status") or "")
        error = str(result.get("error") or "")[:500]
        permalink = result.get("permalink")
        click_marked = bool(result.get("click_marked"))
        group_name = group.get("name", target["group_id"])

        if status == "posted" and click_marked and self.db.is_valid_facebook_permalink(permalink):
            self.db.mark_submission_response(attempt_id)
            self.db.mark_verification_started(attempt_id)
            self.db.resolve_submission(attempt_id, outcome="confirmed", permalink=permalink)
            self.db.update_target_status_with_outbox(
                job["job_id"], target["group_id"], "posted",
                permalink=permalink,
                event_key=f"telegram:{attempt_id}:verified",
                event_type="verified_post",
                origin_run_id=job["job_id"],
                attempt_id=attempt_id,
                subject_id=job["property_id"],
                payload={
                    "text": f"✅ 投稿を確認しました（{group_name}）\n物件: {job['property_id']}\n🔗 {permalink}",
                    "property_id": job["property_id"],
                    "group_id": target["group_id"],
                    "community": group_name,
                    "permalink": permalink,
                },
            )
            self.db.record_group_result(target["group_id"], success=True, threshold=self.settings.group_fail_threshold)
            return

        if status == "session_expired":
            if not click_marked:
                self.db.abort_submission_preclick(attempt_id, reason="extension_session_expired")
            else:
                self._quarantine_or_abort_attempt(attempt_id)
            self.circuits.record_failure(
                FailureKind.SESSION_EXPIRED,
                group_id=target["group_id"],
                environment=self._runtime_environment,
            )
            raise SessionExpired(error or "Facebook login required in Default Chrome profile")

        if status == "failed_before_click" or not click_marked:
            try:
                self.db.abort_submission_preclick(attempt_id, reason=error or "extension_failed_before_click")
            except ValueError:
                self._quarantine_or_abort_attempt(attempt_id)
            self.db.update_target_status(
                job["job_id"], target["group_id"], "failed",
                error=error or "extension_failed_before_click",
                increment_attempts=True,
            )
            self.db.record_group_result(
                target["group_id"], success=False, threshold=self.settings.group_fail_threshold
            )
            return

        if click_marked:
            try:
                self.db.mark_submission_response(attempt_id)
                self.db.mark_verification_started(attempt_id)
            except ValueError:
                pass
            self._quarantine_or_abort_attempt(attempt_id)
            self.db.update_target_status_with_outbox(
                job["job_id"], target["group_id"], "uncertain",
                error=error or "extension_post_not_verified",
                event_key=f"telegram:{attempt_id}:uncertain",
                event_type="uncertain_post",
                origin_run_id=job["job_id"],
                attempt_id=attempt_id,
                subject_id=job["property_id"],
                payload={
                    "text": (
                        f"⚠️ 投稿を確認できませんでした（{group_name}）。\n"
                        f"確認URL: {group['post_url']}\n物件: {job['property_id']}"
                    ),
                    "property_id": job["property_id"],
                    "group_id": target["group_id"],
                },
            )
            self.db.record_group_result(
                target["group_id"], success=False, threshold=self.settings.group_fail_threshold
            )
            raise PostNotVerified(error or f"post not verified live in group {target['group_id']}")

        raise RuntimeError(f"unexpected extension result: {status}")
