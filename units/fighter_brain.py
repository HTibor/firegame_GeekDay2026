from units.unit_brain import UnitBrain
from navigation.pathfinding import bfs_next_step, direction_to_operation
from navigation.stuck_detector import StuckDetector
from game_client import Operation
from config import MAX_FIGHTER_RANGE


class FighterBrain(UnitBrain):
    """
    Infinite-water bulldozer.
    GOTO_CLUSTER → GRIND (park in cluster centroid and extinguish outward).
    Never refills because water is infinite.
    """

    def __init__(self, unit_id):
        super().__init__(unit_id)
        self.state = "GOTO_CLUSTER"
        self._stuck = StuckDetector()
        self.cluster_target = None   # (centroid_x, centroid_y)
        self.grind_target = None     # (x, y) specific fire tile to extinguish next
        self._last_dx = 0
        self._last_dy = 0
        self._stale_fire_max_age = 4

    # ── GOTO_CLUSTER ───────────────────────────────────────────────────────────

    def _on_GOTO_CLUSTER(self, world, client):
        p = self.pos(world)
        if p is None:
            return
        x, y = p
        self._stuck.record(self.unit_id, x, y)

        if self.cluster_target is None or not world.fires or not self._cluster_still_alive(world):
            self._pick_cluster(world, x, y)
        if self.cluster_target is None:
            self.explore(world, client)
            return

        cx, cy = self.cluster_target
        cx, cy = int(cx), int(cy)

        if abs(x - cx) + abs(y - cy) <= 2:
            self.transition("GRIND")
            return

        goal = world.find_approach_cell(cx, cy)
        if goal is None:
            goal = (cx, cy)  # try to get close even if centroid is a fire cell

        gx, gy = goal
        nxt = bfs_next_step(world, x, y, gx, gy)
        if nxt is None:
            if self._stuck.is_stuck(self.unit_id):
                self._stuck.mark_blocked(world, x, y, self._last_dx, self._last_dy)
                self._stuck.clear_history(self.unit_id)
                self.cluster_target = None
            #self.send_move(client, Operation.NOP)
            return

        nx, ny = nxt
        self._last_dx, self._last_dy = nx - x, ny - y
        self.send_move(client, direction_to_operation(nx - x, ny - y))

    # ── GRIND ──────────────────────────────────────────────────────────────────

    def _on_GRIND(self, world, client):
        p = self.pos(world)
        if p is None:
            return
        x, y = p

        # Check if the cluster is still alive
        if not self._cluster_still_alive(world):
            print(f"[Fighter:{self.unit_id}] cluster stale/empty at {self.cluster_target} -> retarget")
            self.cluster_target = None
            self.transition("GOTO_CLUSTER")
            return

        # pick nearest adjacent fire tile
        self.grind_target = self._nearest_adjacent_fire(world, x, y)

        if self.grind_target is not None:
            tx, ty = self.grind_target
            info = world.fire_tracker.fire_tiles.get((tx, ty))
            hp = info.get("hp") if info else None
            last_seen = info.get("last_seen_tick") if info else None
            age = world._tick - last_seen if last_seen is not None else None
            if hp is None or hp <= 0:
                print(f"[Fighter:{self.unit_id}] adjacent target invalid fire({tx},{ty}) hp={hp}")
                self.grind_target = None
            elif age is not None and age > self._stale_fire_max_age:
                print(f"[Fighter:{self.unit_id}] adjacent target stale fire({tx},{ty}) hp={hp} age={age}")
                self.grind_target = None
            else:
                print(f"[Fighter:{self.unit_id}] EXTINGUISH fire({tx},{ty}) hp={hp} age={age if age is not None else '?'}")
                self.send_move(client, Operation.EXTINGUISH)
                return

        # no adjacent fire — move toward nearest fire in cluster
        nearest_fire = self._nearest_fire_in_cluster(world, x, y)
        if nearest_fire is None:
            # cluster is dead; re-assign
            self.cluster_target = None
            self.transition("GOTO_CLUSTER")
            return

        fx, fy = nearest_fire
        goal = world.find_approach_cell(fx, fy)
        if goal is None:
            goal = (fx, fy)
        gx, gy = goal
        nxt = bfs_next_step(world, x, y, gx, gy)
        if nxt is None:
            #self.send_move(client, Operation.NOP)
            return
        self.send_move(client, direction_to_operation(nxt[0] - x, nxt[1] - y))

    # ── helpers ────────────────────────────────────────────────────────────────

    def _pick_cluster(self, world, x, y):
        from coordinator import Coordinator
        coord = Coordinator.instance
        if coord:
            t = coord.get_fire_target(self.unit_id, "fighter", x, y, world)
            if t:
                cluster = world.fire_tracker.get_cluster_for_tile(*t)
                if cluster:
                    self.cluster_target = cluster["centroid"]
                    print(f"[Fighter:{self.unit_id}] coordinator → cluster centroid {self.cluster_target}")
                    return

        # Try within preferred range first, then fall back to globally biggest cluster
        best = world.fire_tracker.get_best_cluster(x, y, max_distance=MAX_FIGHTER_RANGE)
        if best is None:
            best = world.fire_tracker.get_best_cluster(x, y, max_distance=None)
            if best:
                print(f"[Fighter:{self.unit_id}] no cluster within {MAX_FIGHTER_RANGE} cells"
                      f" — targeting global best at {best['centroid']} (size={best['size']})")
        elif best:
            print(f"[Fighter:{self.unit_id}] targeting cluster at {best['centroid']} (size={best['size']})")

        self.cluster_target = best["centroid"] if best else None

    def _cluster_still_alive(self, world):
        if self.cluster_target is None:
            return False
        cx, cy = int(self.cluster_target[0]), int(self.cluster_target[1])
        from config import FIRE_CLUSTER_RADIUS
        return any(
            abs(fx - cx) + abs(fy - cy) <= FIRE_CLUSTER_RADIUS * 3
            and world._tick - world.fire_tracker.fire_tiles[(fx, fy)]["last_seen_tick"] <= self._stale_fire_max_age
            for fx, fy in world.fire_tracker.fire_tiles.keys()
        )

    def _nearest_adjacent_fire(self, world, x, y):
        best, best_dist = None, float("inf")
        for (fx, fy) in list(world.fires.keys()):
            dist = abs(fx - x) + abs(fy - y)
            if dist <= 1 and dist < best_dist:
                best_dist = dist
                best = (fx, fy)

        if best is None:
            for (fx, fy), info in world.fire_tracker.fire_tiles.items():
                if world._tick - info["last_seen_tick"] > self._stale_fire_max_age:
                    continue
                dist = abs(fx - x) + abs(fy - y)
                if dist <= 1 and dist < best_dist:
                    best_dist = dist
                    best = (fx, fy)

        return best

    def _nearest_fire_in_cluster(self, world, x, y):
        if self.cluster_target is None:
            return None
        # Look up the cluster that contains our target centroid, not just any nearby cluster
        cx, cy = int(self.cluster_target[0]), int(self.cluster_target[1])
        cluster = world.fire_tracker.get_cluster_for_tile(cx, cy)
        if cluster is None:
            # centroid tile may not be a fire — find the cluster closest to centroid
            cluster = world.fire_tracker.get_best_cluster(cx, cy, max_distance=None)
        if cluster is None or not cluster["tiles"]:
            return None
        return min(cluster["tiles"], key=lambda p: abs(p[0] - x) + abs(p[1] - y))
