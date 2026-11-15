"""Causal, time-weighted score averaging. No ROS, camera or future samples."""
import math
from collections import deque


class TemporalScores:
    def __init__(self, window=.5, hold=.2, confidence=.55, margin=.15,
                 max_gap=.35, min_samples=3):
        if (not all(math.isfinite(x) for x in (window, hold, confidence, margin, max_gap))
                or window <= 0 or hold < 0 or max_gap <= 0
                or not 0 <= confidence <= 1 or not 0 <= margin <= 1
                or type(min_samples) is not int or min_samples < 2):
            raise ValueError("Invalid temporal filter parameters")
        self.window, self.hold = window, hold
        self.confidence, self.margin = confidence, margin
        self.max_gap, self.min_samples = max_gap, min_samples
        self.reset()

    def reset(self):
        self.samples = deque()
        self.candidate = self.since = None
        self.snapshot = {}

    def add(self, stamp, scores):
        if self.samples and stamp <= self.samples[-1][0]:
            raise ValueError("Temporal samples must have increasing capture times")
        if self.samples and stamp - self.samples[-1][0] > self.max_gap:
            self.reset()
        self.samples.append((stamp, dict(scores)))
        left = stamp - self.window
        # Keep one sample before the boundary for clipping/interpolation.
        while len(self.samples) > 2 and self.samples[1][0] <= left:
            self.samples.popleft()
        start = max(left, self.samples[0][0])
        span = stamp - start
        mean = dict.fromkeys(scores, 0.)
        pairs = list(self.samples)
        for (ta, a), (tb, b) in zip(pairs, pairs[1:]):
            lo = max(start, ta)
            if tb <= lo:
                continue
            fraction = (lo - ta) / (tb - ta)
            for k in mean:
                at_left = a[k] + (b[k] - a[k]) * fraction
                mean[k] += (at_left + b[k]) * .5 * (tb - lo)
        mean = {k: v / span for k, v in mean.items()} if span else dict(scores)
        order = sorted(mean, key=mean.get, reverse=True)
        label = order[0]
        gap = mean[label] - mean[order[1]]
        ready = span + 1e-9 >= self.window and len(pairs) >= self.min_samples
        eligible = (ready and mean[label] >= self.confidence and gap >= self.margin
                    and max(scores, key=scores.get) == label)
        if not eligible:
            self.candidate = self.since = None
        elif self.candidate != label:
            self.candidate, self.since = label, stamp
        stable = stamp - self.since if self.since is not None else 0.
        confirmed = bool(eligible and stable + 1e-9 >= self.hold)
        self.snapshot = dict(scores=mean, label=label, margin=gap, ready=ready,
                             confirmed=confirmed, stable_seconds=stable,
                             coverage_seconds=span, window_seconds=self.window,
                             start_capture=start, end_capture=stamp,
                             sample_count=len(pairs))
        return self.snapshot
