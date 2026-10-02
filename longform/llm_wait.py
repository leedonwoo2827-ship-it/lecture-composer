"""Claude 사용 한도(5시간 창 등)에 걸리면 **기다렸다가 이어서** 한다 — 퇴근 후 무인 제작용.

    is_limit(text)       응답·오류가 한도 메시지인가
    reset_at(text)       메시지에서 재설정 시각(epoch) 읽기 — 「limit reached|1759…」, 「resets 3pm」, 「reset at 15:30」
    wait_for_claude(job) 짧은 확인 질문을 던져 한도가 풀릴 때까지 기다린다(최대 llm.limit_wait_hours, 기본 6시간)
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import time
from typing import Optional

from longform.util import log, warn

LIMIT_RE = re.compile(r"usage limit|limit reached|hour limit|rate limit|rate_limit|overloaded|too many requests|"
                      r"resets? (at )?\d|한도", re.I)


def is_limit(text: str) -> bool:
    return bool(LIMIT_RE.search(text or ""))


def reset_at(text: str) -> Optional[float]:
    t = text or ""
    m = re.search(r"\|(\d{10})\b", t)                        # 「Claude AI usage limit reached|1759380000」
    if m:
        return float(m.group(1))
    m = re.search(r"reset[s]?\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t, re.I)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        now = dt.datetime.now()
        r = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
        if r <= now:
            r += dt.timedelta(days=1)
        return r.timestamp()
    return None


def sleep_until(ts: float, reason: str) -> None:
    left = max(0.0, ts - time.time()) + 60
    log(f"Claude 한도 — {dt.datetime.fromtimestamp(ts + 60):%H:%M} 까지 기다렸다 이어서 합니다({reason}, 약 {left / 60:.0f}분)")
    time.sleep(left)


def _probe(job) -> str:
    from longform.s2_manuscript import find_claude
    env = dict(os.environ, ANTHROPIC_API_KEY="", ANTHROPIC_AUTH_TOKEN="", ANTHROPIC_BASE_URL="")
    try:
        p = subprocess.run([find_claude(job), "-p", "--output-format", "text"], input="ok 라고만 답하십시오.",
                           text=True, encoding="utf-8", errors="replace", capture_output=True, env=env, timeout=180)
        out = (p.stdout or "") + (p.stderr or "")
        return "" if (p.returncode == 0 and not is_limit(out)) else (out or f"exit {p.returncode}")
    except Exception as e:  # noqa: BLE001
        return str(e)


def wait_for_claude(job, first_text: str = "") -> bool:
    """한도가 풀릴 때까지 기다린다. 풀리면 True, 최대 시간을 넘기면 False."""
    max_h = float(job.get("llm.limit_wait_hours", 6))
    deadline = time.time() + max_h * 3600
    text = first_text or _probe(job)
    if not text:
        return True
    while time.time() < deadline:
        ts = reset_at(text)
        if ts and ts < deadline:
            sleep_until(ts, "재설정 시각")
        else:
            log("Claude 한도로 보입니다 — 30분 뒤 다시 확인합니다")
            time.sleep(30 * 60)
        text = _probe(job)
        if not text:
            log("Claude 한도가 풀렸습니다 — 이어서 합니다")
            return True
    warn(f"Claude 한도가 {max_h:.0f}시간 안에 풀리지 않았습니다")
    return False
