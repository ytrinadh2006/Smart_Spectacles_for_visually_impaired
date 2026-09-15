"""
Phrase table for spoken announcements.

Labels-driven: any class in labels.txt that has no entry here falls back to
DEFAULT templates, so swapping in the 10-class model needs no code change.

Clip naming: {class}_{position}_{motion}.pcm
Positions: left / center / right   Motions: static / approaching / receding
Pruned combos (no entry for a motion) fall back to the 'static' sentence,
so every (class, position, motion) resolves to an existing clip.
"""

# {pos} renders via POSITION_TEXT below.
PHRASES = {
    'pothole': {
        'static':      'Pothole {pos}',
        'approaching': 'Pothole {pos}, getting close',
    },
    'vehicle': {
        'static':      'Vehicle {pos}',
        'approaching': 'Caution, vehicle {pos}, coming towards you',
        'receding':    'Vehicle {pos}, moving away',
    },
    'obstacle': {
        'static':      'Obstacle {pos}',
        'approaching': 'Obstacle {pos}, getting close',
    },
    'stairs': {
        'static':      'Stairs {pos}',
        'approaching': 'Stairs {pos}, getting close',
    },
    'safe_path': {
        'static':      'Path is clear',
    },
    'person': {
        'static':      'Person {pos}',
        'approaching': 'Person {pos}, coming towards you',
        'receding':    'Person {pos}, moving away',
    },
    'traffic_light': {
        'static':      'Traffic light ahead',
    },
    'speed_bump': {
        'static':      'Speed bump {pos}',
        'approaching': 'Speed bump {pos}, getting close',
    },
    'door': {
        'static':      'Door {pos}',
    },
    'animal': {
        'static':      'Animal {pos}',
        'approaching': 'Animal {pos}, coming towards you',
        'receding':    'Animal {pos}, moving away',
    },
}

DEFAULT_PHRASES = {
    'static':      '{cls} {pos}',
    'approaching': '{cls} {pos}, getting close',
}

POSITION_TEXT = {
    'left':   'on your left',
    'center': 'ahead',
    'right':  'on your right',
}

# Classes whose announcement ignores position (single clip, keyed as 'center')
POSITIONLESS = {'safe_path', 'traffic_light'}

PRIORITY = {
    'vehicle': 3, 'pothole': 3, 'stairs': 3,
    'speed_bump': 2, 'obstacle': 2, 'person': 2, 'animal': 2,
    'door': 1, 'traffic_light': 1,
    'safe_path': 0,
}
DEFAULT_PRIORITY = 2

MOTIONS = ('static', 'approaching', 'receding')
POSITIONS = ('left', 'center', 'right')


def priority_of(cls):
    return PRIORITY.get(cls, DEFAULT_PRIORITY)


def _templates(cls):
    return PHRASES.get(cls, DEFAULT_PHRASES)


def resolve(cls, pos, motion):
    """Map any (class, position, motion) to the (pos, motion) actually spoken,
    collapsing pruned combos. Returns (pos, motion) of the real clip."""
    if cls in POSITIONLESS:
        pos = 'center'
    t = _templates(cls)
    if motion not in t:
        motion = 'static'
    return pos, motion


def clip_name(cls, pos, motion):
    pos, motion = resolve(cls, pos, motion)
    return f'{cls}_{pos}_{motion}'


def sentence_for(cls, pos, motion):
    pos, motion = resolve(cls, pos, motion)
    template = _templates(cls)[motion]
    spoken_cls = cls.replace('_', ' ')
    return template.format(pos=POSITION_TEXT[pos], cls=spoken_cls)


def all_clips(labels):
    """Yield (clip_name, sentence) for every distinct clip needed for these labels."""
    seen = set()
    for cls in labels:
        for pos in POSITIONS:
            for motion in MOTIONS:
                name = clip_name(cls, pos, motion)
                if name not in seen:
                    seen.add(name)
                    yield name, sentence_for(cls, pos, motion)
