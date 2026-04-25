import json
import time

from world.vision_calibrator import VisionCalibrator
from world.fire_tracker import FireTracker
from config import BLOCKED_EXPIRY_SEC

_RAW_DUMP_TICKS = 3   # print full JSON for this many ticks at startup


class WorldState:
    """
    Single source of truth for everything we know about the map.
    Designed to be drop-in compatible with web_viz (exposes .fires,
    .water_sources, .obsticles, .units in the same formats).
    """

    def __init__(self):
        # web-viz–compatible dicts
        self.units = {}           # {id: (x, y, type, water)}
        self.fires = {}           # {(x,y): True}  — presence only, HP is in fire_tracker
        self.water_sources = {}   # {(x,y): is_empty_bool}
        self.obsticles = {}       # unused for now; kept for web_viz compat

        # rich world knowledge
        self.explored = set()     # (x,y) confirmed empty
        self.east_bound = None    # rightmost X discovered
        self.south_bound = None   # bottommost Y discovered
        self.suspected_blocked = {}  # {(x,y): expiry_float}

        self.fire_tracker = FireTracker()
        self.vision_calibrator = VisionCalibrator()
        self._tick = 0

    # ── ingestion ──────────────────────────────────────────────────────────────

    def ingest(self, message):
        if message.operation != "UnitsFromServer" or not message.extraJson:
            return

        self._tick += 1
        units_data = json.loads(message.extraJson)

        # dump raw JSON for the first few ticks so we can see exact field names
        if True: 
            print(f"\n[RAW tick={self._tick}] {json.dumps(units_data, indent=2)}\n")

        prev_fire_count = len(self.fires)

        for data in units_data:
            pos = data["Position"]
            uid = data["Id"]
            ux, uy = pos["X"], pos["Y"]
            utype = data["UnitType"]
            uwater = data.get("CurrentWaterLevel", 0)

            self.units[uid] = (ux, uy, utype, uwater)

            # vision radius hint from server (may not be present)
            if "VisionRadius" in data:
                r = data["VisionRadius"]
                if r > self.vision_calibrator.per_unit_max.get(uid, 0):
                    self.vision_calibrator.per_unit_max[uid] = float(r)

            seen_cells = []
            seen_fires_raw = data.get("SeenFires", [])
            seen_waters_raw = data.get("SeenWaters", [])

            for fire in seen_fires_raw:
                fx, fy = fire["X"], fire["Y"]
                hp = fire.get("Hp", fire.get("HP", fire.get("CurrentHp", 1000)))
                self.fires[(fx, fy)] = True
                self.fire_tracker.update_tile(fx, fy, hp, self._tick)
                seen_cells.append((fx, fy))
                self.explored.add((fx, fy))   # remember we've seen this cell

            for water in seen_waters_raw:
                wx, wy = water["X"], water["Y"]
                is_empty = water.get("IsEmpty", False)
                self.water_sources[(wx, wy)] = is_empty
                seen_cells.append((wx, wy))
                self.explored.add((wx, wy))   # remember we've seen this cell

            self.vision_calibrator.record(uid, ux, uy, seen_cells)

            # sweep the vision circle and mark every cell inside as explored
            radius = self.vision_calibrator.get_radius(uid)
            r = int(radius) + 1
            r2 = radius * radius
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if dx * dx + dy * dy <= r2:
                        nx, ny = ux + dx, uy + dy
                        if nx >= 0 and ny >= 0:
                            self.explored.add((nx, ny))

        # remove fires no longer seen
        self.fire_tracker.remove_stale(self._tick)
        # rebuild fires presence dict to match fire_tracker
        self.fires = {k: True for k in self.fire_tracker.fire_tiles}
        # recluster every tick
        self.fire_tracker.recluster()

        if len(self.fires) != prev_fire_count:
            print(f"[World tick={self._tick}] fires changed: {prev_fire_count} → {len(self.fires)}"
                  f"  waters={len(self.water_sources)}")

    # ── passability ────────────────────────────────────────────────────────────

    def is_passable_ground(self, x, y):
        if self.east_bound is not None and x > self.east_bound:
            return False
        if self.south_bound is not None and y > self.south_bound:
            return False
        if x < 0 or y < 0:
            return False
        if (x, y) in self.fires:
            return False
        if (x, y) in self.water_sources and not self.water_sources[(x, y)]:
            # non-empty water tile is still water (you can't walk on it)
            return False
        if (x, y) in self.water_sources:
            return False
        now = time.time()
        if self.suspected_blocked.get((x, y), 0) > now:
            return False
        return True

    def is_passable_air(self, x, y):
        if self.east_bound is not None and x > self.east_bound:
            return False
        if self.south_bound is not None and y > self.south_bound:
            return False
        if x < 0 or y < 0:
            return False
        return True

    # ── helpers ────────────────────────────────────────────────────────────────

    def cleanup_expired_blocks(self):
        now = time.time()
        expired = [k for k, t in self.suspected_blocked.items() if t <= now]
        for k in expired:
            del self.suspected_blocked[k]

    def find_approach_cell(self, target_x, target_y, unit_type="ground"):
        """Return nearest passable cell adjacent to (target_x, target_y)."""
        passable = self.is_passable_ground if "air" not in unit_type.lower() else self.is_passable_air
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = target_x + dx, target_y + dy
            if passable(nx, ny):
                return (nx, ny)
        return None

    def nearest_water(self, unit_x, unit_y):
        """Return (x, y) of nearest non-empty water tile, or None."""
        best, best_dist = None, float("inf")
        for (wx, wy), is_empty in self.water_sources.items():
            if is_empty:
                continue
            dist = abs(wx - unit_x) + abs(wy - unit_y)
            if dist < best_dist:
                best_dist = dist
                best = (wx, wy)
        return best
