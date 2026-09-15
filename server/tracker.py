"""
Cross-frame object tracker for motion classification.

Frames arrive ~2 s apart from a head-mounted camera, so bbox positions jump a
lot; matching is deliberately loose and motion thresholds deliberately wide.

update(detections) annotates each detection dict (in place) with:
    'motion':   'static' | 'approaching' | 'receding'
    'track_id': int
"""

from collections import deque


def _area(box):
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


class Track:
    def __init__(self, tid, det):
        self.id = tid
        self.cls = det['class']
        self.box = det['box']
        self.position = det.get('position', 'center')
        self.areas = deque([_area(det['box'])], maxlen=3)
        self.age = 1        # frames seen
        self.missed = 0     # consecutive frames unmatched

    def update(self, det):
        self.box = det['box']
        self.position = det.get('position', self.position)
        self.areas.append(_area(det['box']))
        self.age += 1
        self.missed = 0

    def motion(self):
        # Need at least 2 sightings; compare newest area to mean of the rest.
        if self.age < 2 or len(self.areas) < 2:
            return 'static'
        prev = list(self.areas)[:-1]
        baseline = sum(prev) / len(prev)
        if baseline <= 0:
            return 'static'
        ratio = self.areas[-1] / baseline
        if ratio > 1.25:
            return 'approaching'
        if ratio < 0.80:
            return 'receding'
        return 'static'


class ObjectTracker:
    def __init__(self, iou_thresh=0.3, max_missed=2):
        self.iou_thresh = iou_thresh
        self.max_missed = max_missed
        self.tracks = []
        self._next_id = 1

    def update(self, detections):
        unmatched_dets = list(range(len(detections)))
        unmatched_tracks = list(self.tracks)

        # Pass 1: greedy IoU matching within the same class, best pairs first
        pairs = []
        for t in unmatched_tracks:
            for di in unmatched_dets:
                d = detections[di]
                if d['class'] != t.cls:
                    continue
                iou = _iou(t.box, d['box'])
                if iou >= self.iou_thresh:
                    pairs.append((iou, t, di))
        pairs.sort(key=lambda p: -p[0])

        matched = {}
        used_tracks, used_dets = set(), set()
        for iou, t, di in pairs:
            if id(t) in used_tracks or di in used_dets:
                continue
            used_tracks.add(id(t))
            used_dets.add(di)
            matched[di] = t

        # Pass 2: loose fallback — same class + same position + sane area ratio.
        # Handles fast lateral motion where IoU drops to 0 between 2 s frames.
        for t in unmatched_tracks:
            if id(t) in used_tracks:
                continue
            for di in unmatched_dets:
                if di in used_dets:
                    continue
                d = detections[di]
                if d['class'] != t.cls or d.get('position') != t.position:
                    continue
                a_new, a_old = _area(d['box']), self.areas_last(t)
                if a_old > 0 and 0.4 <= a_new / a_old <= 2.5:
                    used_tracks.add(id(t))
                    used_dets.add(di)
                    matched[di] = t
                    break

        # Apply matches, create tracks for new detections
        new_tracks = []
        for di, det in enumerate(detections):
            if di in matched:
                t = matched[di]
                t.update(det)
            else:
                t = Track(self._next_id, det)
                self._next_id += 1
                new_tracks.append(t)
            det['motion'] = t.motion()
            det['track_id'] = t.id

        # Age out tracks that vanished this frame
        for t in self.tracks:
            if id(t) not in used_tracks:
                t.missed += 1
        self.tracks = [t for t in self.tracks if t.missed <= self.max_missed]
        self.tracks.extend(new_tracks)

        return detections

    @staticmethod
    def areas_last(track):
        return track.areas[-1] if track.areas else 0.0
