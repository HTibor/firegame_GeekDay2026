from config import MIN_ASSUMED_VISION


class VisionCalibrator:
    def __init__(self):
        self.per_unit_max = {}  # {unit_id: float}

    def record(self, unit_id, unit_x, unit_y, seen_cells):
        """seen_cells: iterable of (x, y). Returns True if max radius grew."""
        current = self.per_unit_max.get(unit_id, 0.0)
        changed = False
        for cx, cy in seen_cells:
            dist = ((cx - unit_x) ** 2 + (cy - unit_y) ** 2) ** 0.5
            if dist > current:
                current = dist
                changed = True
        if changed:
            self.per_unit_max[unit_id] = current
        return changed

    def get_radius(self, unit_id):
        return max(self.per_unit_max.get(unit_id, 0.0), float(MIN_ASSUMED_VISION))
