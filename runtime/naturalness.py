import random


class NaturalnessPolicy:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.click_delay_range = (200, 800)
        self.interaction_delay_range = (500, 1500)
        self.transition_jitter_ms = 1000
        self.sprint_duration_variance = 0.15
        self.correction_interval_variance = 0.2
        self.max_continuous_rotate_s = 3
        self.max_retry = {"interaction": 2, "portal": 2, "movement": 3}
        self.require_manual_after_limit = True
        self.max_continuous_runtime_min = 60
        self.idle_break = (3, 10)

    def click_delay(self):
        return self._delay(*self.click_delay_range)

    def interaction_delay(self):
        return self._delay(*self.interaction_delay_range)

    def transition_wait(self, base_seconds):
        if not self.enabled:
            return base_seconds
        return max(0.5, base_seconds + random.uniform(-1, 1) * self.transition_jitter_ms / 1000.0)

    def sprint_duration(self, base_seconds):
        if not self.enabled:
            return base_seconds
        v = random.uniform(-1, 1) * self.sprint_duration_variance * base_seconds
        return max(0.3, base_seconds + v)

    def rotate_duration(self):
        if not self.enabled:
            return 1.0
        return random.uniform(0.5, min(self.max_continuous_rotate_s, 1.2))

    def _delay(self, lo, hi):
        if not self.enabled:
            return (lo + hi) / 2.0 / 1000.0
        return random.uniform(lo, hi) / 1000.0
