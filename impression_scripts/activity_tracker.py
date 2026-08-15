# impression_scripts/tracker.py
import time
from collections import defaultdict, deque
from typing import Dict, Deque


class ChannelTracker:
    def __init__(self, window_seconds: float = 10.0, burst_threshold: int = 5):
        self.window_seconds = window_seconds
        self.burst_message_count: int = burst_threshold

        self._message_history: Dict[int, Deque[float]] = defaultdict(deque)
        self._last_burst_triggered: Dict[int, float] = defaultdict(float)


    def log_message(self, channel_id: int) -> bool:
        now = time.time()
        history = self._message_history[channel_id]
        history.append(now)

        cutoff = now - self.window_seconds
        while history and history[0] < cutoff:
            history.popleft()

        if len(history) >= self.burst_message_count:
            self._last_burst_triggered[channel_id] = now
            return True

        return False