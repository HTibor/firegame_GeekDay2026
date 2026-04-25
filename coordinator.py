import time
from config import UNIT_TYPES_DRONE, UNIT_TYPES_TRUCK


def _classify(unit_type):
    t = unit_type.lower()
    for kw in UNIT_TYPES_DRONE:
        if kw in t:
            return "drone"
    for kw in UNIT_TYPES_TRUCK:
        if kw in t:
            return "truck"
    return "fighter"


class Coordinator:
    instance = None  # singleton reference used by brains

    def __init__(self, world):
        Coordinator.instance = self
        self.world = world
        self.unit_brains = {}       # {unit_id: UnitBrain}
        self.fire_assignments = {}  # {unit_id: (fx, fy)}
        self._last_log = 0.0

    # ── brain assignment ───────────────────────────────────────────────────────

    def assign_brain(self, unit_id, unit_type):
        kind = _classify(unit_type)
        if kind == "drone":
            from units.drone_brain import DroneBrain
            brain = DroneBrain(unit_id)
        elif kind == "truck":
            from units.truck_brain import TruckBrain
            brain = TruckBrain(unit_id)
        else:
            from units.fighter_brain import FighterBrain
            brain = FighterBrain(unit_id)
        self.unit_brains[unit_id] = brain
        print(f"[Coordinator] assigned {kind} brain to unit {unit_id} ({unit_type})")
        return brain

    # ── main tick ──────────────────────────────────────────────────────────────

    def tick(self, client):
        world = self.world
        world.cleanup_expired_blocks()

        # assign brains to newly seen units
        for uid, (x, y, utype, water) in list(world.units.items()):
            if uid not in self.unit_brains:
                self.assign_brain(uid, utype)

        # tick every brain
        for uid, brain in list(self.unit_brains.items()):
            if uid in world.units:
                brain.tick(world, client)

        if time.time() - self._last_log >= 2.0:
            self._log_status()
            self._last_log = time.time()

    # ── fire target assignment ─────────────────────────────────────────────────

    def get_fire_target(self, unit_id, unit_kind, unit_x, unit_y, world):
        """
        Returns (fx, fy) of recommended fire tile, avoiding double-assignment.
        trucks: pick cluster best scored by size/(dist + water_dist)
        fighters: pick biggest cluster within MAX_FIGHTER_RANGE
        """
        in_use = set(self.fire_assignments.values())

        if unit_kind == "truck":
            best_tile, best_score = None, -1
            for c in world.fire_tracker.clusters:
                cx, cy = c["centroid"]
                dist_to_cluster = abs(cx - unit_x) + abs(cy - unit_y)
                water = world.nearest_water(int(cx), int(cy))
                if water:
                    dist_to_water = abs(water[0] - cx) + abs(water[1] - cy)
                else:
                    dist_to_water = 0
                score = c["size"] / max(1, dist_to_cluster + dist_to_water)
                # pick a representative tile from cluster not already assigned
                tile = self._pick_unassigned_tile(c["tiles"], in_use)
                if tile and score > best_score:
                    best_score = score
                    best_tile = tile
            if best_tile:
                self.fire_assignments[unit_id] = best_tile
            return best_tile

        elif unit_kind == "fighter":
            from config import MAX_FIGHTER_RANGE
            best = world.fire_tracker.get_best_cluster(unit_x, unit_y, MAX_FIGHTER_RANGE)
            if best:
                tile = self._pick_unassigned_tile(best["tiles"], in_use)
                if tile:
                    self.fire_assignments[unit_id] = tile
                    return tile
            return None

        return None

    def _pick_unassigned_tile(self, tiles, in_use):
        for t in tiles:
            if t not in in_use:
                return t
        # all assigned — still return first (better two trucks on same cluster than nothing)
        return next(iter(tiles)) if tiles else None

    # ── logging ────────────────────────────────────────────────────────────────

    def _log_status(self):
        world = self.world
        n_fires = len(world.fires)
        n_clusters = len(world.fire_tracker.clusters)
        n_units = len(world.units)
        print(f"[Status] tick={world._tick}  fires={n_fires}  clusters={n_clusters}"
              f"  east={world.east_bound}  south={world.south_bound}"
              f"  waters={len(world.water_sources)}")
        for uid, (x, y, utype, water) in world.units.items():
            brain = self.unit_brains.get(uid)
            state = brain.state if brain else "?"
            vision = world.vision_calibrator.get_radius(uid)
            target = ""
            if brain and hasattr(brain, "fire_target") and brain.fire_target:
                target = f" → fire{brain.fire_target}"
            elif brain and hasattr(brain, "cluster_target") and brain.cluster_target:
                cx, cy = brain.cluster_target
                target = f" → cluster({int(cx)},{int(cy)})"
            print(f"  [{uid}] {utype:12s} pos=({x:3d},{y:3d})"
                  f"  water={water}  vision={vision:.1f}"
                  f"  state={state}{target}")
