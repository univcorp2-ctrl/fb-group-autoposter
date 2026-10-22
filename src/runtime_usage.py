"""Private, atomic per-invocation counters. Never store prompts or model output."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid


class UsageRun:
    def __init__(self, task_id, model):
        self.run_id = str(uuid.uuid4())
        directory = Path(os.getenv('AI_TASK_USAGE_DIR', r'C:\AI-Agent\state\ai-task-usage\events'))
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (self.run_id + '.json')
        self.record = {'schemaVersion': 1, 'runId': self.run_id, 'taskId': task_id,
                       'model': model, 'startedAt': self.now(), 'completedAt': None,
                       'status': 'unknown', 'source': 'codex.turn.completed',
                       'inputTokens': None, 'cachedInputTokens': None,
                       'outputTokens': None, 'totalTokens': None}
        self.save()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.record), encoding='utf-8')
        os.replace(temporary, self.path)

    def finish(self, stdout):
        totals = [0, 0, 0]
        measured = False
        invalid = False
        for line in str(stdout or '').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get('type') != 'turn.completed':
                continue
            usage = event.get('usage') or {}
            values = [usage.get(k) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')]
            if (any(type(n) is not int or n < 0 or n > 2**53 - 1 for n in values)
                    or values[1] > values[0]):
                invalid = True
                continue
            measured = True
            totals = [a + b for a, b in zip(totals, values)]
        self.record['completedAt'] = self.now()
        if measured and not invalid:
            self.record.update(status='measured', inputTokens=totals[0], cachedInputTokens=totals[1],
                               outputTokens=totals[2], totalTokens=totals[0] + totals[2])
        self.save()
