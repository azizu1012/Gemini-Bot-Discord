import asyncio
import datetime
import time
from collections import deque


class GeminiRateLimiter:
    def __init__(
        self,
        rpm: int = 15,
        tpm: int = 250000,
        rpd: int = 500,
        max_output_tokens: int = 2000,
        fixed_overhead: int = 80,
        safety_factor: float = 1.25,
    ):
        self.rpm_limit = rpm
        self.tpm_limit = tpm
        self.rpd_limit = rpd
        self.max_output_tokens = max_output_tokens
        self.fixed_overhead = fixed_overhead
        self.safety_factor = safety_factor

        self._minute_req_ts = deque()
        self._minute_tokens = deque()
        self._rpd_date = datetime.date.today()
        self._rpd_count = 0
        self._lock = asyncio.Lock()

    def estimate_text_tokens(self, text: str) -> int:
        if not text:
            return 1
        ascii_chars = sum(1 for ch in text if ord(ch) < 128)
        non_ascii_chars = len(text) - ascii_chars
        base_tokens = (ascii_chars / 3.6) + (non_ascii_chars / 1.6)
        return max(1, int(base_tokens + 0.999999))

    def estimate_request_tokens(self, prompt_text: str, max_output_tokens: int, image_count: int = 0) -> int:
        input_tokens = self.estimate_text_tokens(prompt_text)
        image_overhead = image_count * 20
        total = (input_tokens + max_output_tokens + self.fixed_overhead + image_overhead) * self.safety_factor
        return max(1, int(total + 0.999999))

    async def acquire_quota(self, reserved_tokens: int) -> bool:
        while True:
            async with self._lock:
                now = time.time()
                today = datetime.date.today()

                if today != self._rpd_date:
                    self._rpd_date = today
                    self._rpd_count = 0

                while self._minute_req_ts and now - self._minute_req_ts[0] >= 60:
                    self._minute_req_ts.popleft()

                while self._minute_tokens and now - self._minute_tokens[0][0] >= 60:
                    self._minute_tokens.popleft()

                if self.rpd_limit > 0 and self._rpd_count >= self.rpd_limit:
                    return False

                used_tokens = sum(item[1] for item in self._minute_tokens)
                if len(self._minute_req_ts) < self.rpm_limit and (used_tokens + reserved_tokens) <= self.tpm_limit:
                    self._minute_req_ts.append(now)
                    self._minute_tokens.append((now, reserved_tokens))
                    self._rpd_count += 1
                    return True

                wait_req = (60 - (now - self._minute_req_ts[0])) if self._minute_req_ts else 0.5
                wait_tok = (60 - (now - self._minute_tokens[0][0])) if self._minute_tokens else 0.5
                wait_time = max(0.3, min(wait_req, wait_tok))

            await asyncio.sleep(wait_time)

    def get_counters_snapshot(self) -> dict:
        now = time.time()
        req_ts_snapshot = list(self._minute_req_ts)
        token_snapshot = list(self._minute_tokens)

        rpm_used = sum(1 for ts in req_ts_snapshot if now - ts < 60)
        tpm_used = sum(tokens for ts, tokens in token_snapshot if now - ts < 60)
        rpd_used = self._rpd_count if datetime.date.today() == self._rpd_date else 0

        return {
            "rpm_used": rpm_used,
            "rpm_limit": self.rpm_limit,
            "tpm_used": tpm_used,
            "tpm_limit": self.tpm_limit,
            "rpd_used": rpd_used,
            "rpd_limit": self.rpd_limit,
        }
