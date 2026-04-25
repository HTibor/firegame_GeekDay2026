import time
from config import (
    STUCK_PATIENCE_GROUND,
    STUCK_PATIENCE_AIR,
    STUCK_PATIENCE_AIR_SPAWN,
    BLOCKED_EXPIRY_SEC,
)


class StuckDetector:
    def __init__(self):
        self.histories = {}  # {unit_id: [(x, y), ...]}

    def record(self, unit_id, x, y):
        hist = self.histories.setdefault(unit_id, [])
        hist.append((x, y))
        # keep only as many entries as the longest patience window
        if len(hist) > STUCK_PATIENCE_GROUND + 2:
            self.histories[unit_id] = hist[-(STUCK_PATIENCE_GROUND + 2):]

    def is_stuck(self, unit_id, is_air=False, is_spawn=False):
        hist = self.histories.get(unit_id, [])
        if is_air:
            window = STUCK_PATIENCE_AIR_SPAWN if is_spawn else STUCK_PATIENCE_AIR
        else:
            window = STUCK_PATIENCE_GROUND
        if len(hist) < window:
            return False
        last_n = hist[-window:]
        return len(set(last_n)) == 1  # all same position

    def mark_blocked(self, world, unit_x, unit_y, intended_dx, intended_dy):
        """Mark the cell we tried to enter as temporarily blocked."""
        tx = unit_x + (1 if intended_dx > 0 else -1 if intended_dx < 0 else 0)
        ty = unit_y + (1 if intended_dy > 0 else -1 if intended_dy < 0 else 0)
        world.suspected_blocked[(tx, ty)] = time.time() + BLOCKED_EXPIRY_SEC

    def clear_history(self, unit_id):
        self.histories.pop(unit_id, None)
