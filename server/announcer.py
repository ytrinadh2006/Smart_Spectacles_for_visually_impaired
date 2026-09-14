"""
Decides what (if anything) to announce for a frame of tracked detections.

Rules:
- At most one announcement per frame (2 s cadence, ~2.5 s clips — no queue;
  the next frame re-decides from live data).
- Effective priority = class priority (+0.5 if approaching).
- Per-(class, position) cooldown, waived once on static→approaching escalation.
- Global minimum gap between announcements; shorter for urgent events.
- safe_path only speaks when there's been silence and nothing else to say.
"""

import phrases
from tracker import _area


COOLDOWN_BY_PRIO = {3: 6.0, 2: 10.0, 1: 15.0, 0: 30.0}
GLOBAL_GAP = 3.0     # min seconds between any two announcements
URGENT_GAP = 2.0     # allowed gap when eff_prio >= URGENT_PRIO
URGENT_PRIO = 3.5    # danger class + approaching
SAFE_PATH_SILENCE = 10.0


class Announcer:
    def __init__(self):
        self.last_by_key = {}       # (class, position) -> (time, motion)
        self.last_announce_time = 0.0

    def choose(self, detections, now):
        """Return (clip_name, prio) or (None, 0)."""
        best = None
        best_score = None

        for det in detections:
            cls = det['class']
            pos = det.get('position', 'center')
            motion = det.get('motion', 'static')
            prio = phrases.priority_of(cls)
            eff = prio + (0.5 if motion == 'approaching' else 0.0)

            if cls == 'safe_path':
                continue  # handled separately below

            key = (cls, pos)
            last = self.last_by_key.get(key)
            if last is not None:
                last_t, last_motion = last
                escalated = (last_motion != 'approaching' and motion == 'approaching')
                if not escalated and now - last_t < COOLDOWN_BY_PRIO.get(prio, 10.0):
                    continue

            score = (eff, det.get('confidence', 0.0), _area(det['box']))
            if best_score is None or score > best_score:
                best_score = score
                best = (cls, pos, motion, eff)

        # safe_path fallback: only when nothing else and it's been quiet
        if best is None:
            for det in detections:
                if det['class'] != 'safe_path':
                    continue
                if now - self.last_announce_time < SAFE_PATH_SILENCE:
                    break
                key = ('safe_path', 'center')
                last = self.last_by_key.get(key)
                if last is not None and now - last[0] < COOLDOWN_BY_PRIO[0]:
                    break
                best = ('safe_path', 'center', 'static', 0.0)
                break

        if best is None:
            return None, 0

        cls, pos, motion, eff = best
        gap = URGENT_GAP if eff >= URGENT_PRIO else GLOBAL_GAP
        if now - self.last_announce_time < gap:
            return None, 0

        self.last_by_key[(cls, pos)] = (now, motion)
        self.last_announce_time = now
        return phrases.clip_name(cls, pos, motion), int(phrases.priority_of(cls))
