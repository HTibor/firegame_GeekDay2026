from units.unit_brain import UnitBrain
from navigation.pathfinding import direct_step, direction_to_operation
from navigation.stuck_detector import StuckDetector
from game_client import Operation


class DroneBrain(UnitBrain):
    """
    FIND_BOUNDS → SWEEP → SNIPE → PATROL

    FIND_BOUNDS: fly right until east wall, drop until south wall.
                 As soon as both bounds known, compute full sweep plan.
    SWEEP:       follow precomputed waypoints covering every strip of the map.
                 Strips already behind us at the time bounds were found are skipped.
    SNIPE:       beeline to fires, extinguish, refill, repeat.
    PATROL:      explore when no fires visible.
    """

    def __init__(self, unit_id):
        super().__init__(unit_id)
        self.state = "FIND_BOUNDS"
        self._stuck = StuckDetector()

        # FIND_BOUNDS state
        self._prev_x = None
        self._prev_y = None
        self._same_x_count = 0
        self._same_y_count = 0
        self._dropping = False
        self._drop_remaining = 0
        self._sweep_dir = 1          # 1=right, -1=left during bounds search

        # SWEEP state
        self.waypoints = []          # list of (x, y) to visit in order

        # SNIPE state
        self.snipe_target = None
        self.going_to_water = False

    # ── FIND_BOUNDS ────────────────────────────────────────────────────────────

    def _on_FIND_BOUNDS(self, world, client):
        # if fires already visible, no need to finish bounds first
        if world.fires:
            self._build_sweep(world, *self.pos(world)) if (world.east_bound and world.south_bound) else None
            self.transition("SNIPE")
            return

        p = self.pos(world)
        if p is None:
            return
        x, y = p

        # detect east wall: sent RIGHT but x didn't change
        if self._prev_x is not None and self._sweep_dir == 1 and not self._dropping:
            if x == self._prev_x:
                self._same_x_count += 1
            else:
                self._same_x_count = 0

        # detect south wall: sent DOWN but y didn't change
        if self._prev_y is not None and self._dropping:
            if y == self._prev_y:
                self._same_y_count += 1
            else:
                self._same_y_count = 0

        self._prev_x, self._prev_y = x, y

        if self._same_x_count >= 2 and world.east_bound is None:
            world.east_bound = x
            print(f"[Drone:{self.unit_id}] east_bound={x}  starting drop")
            self._same_x_count = 0
            self._start_drop(world)

        if self._same_y_count >= 2 and world.south_bound is None:
            world.south_bound = y
            print(f"[Drone:{self.unit_id}] south_bound={y}")
            self._same_y_count = 0

        # both walls known — build sweep plan and go
        if world.east_bound is not None and world.south_bound is not None:
            self._build_sweep(world, x, y)
            self.transition("SWEEP")
            return

        # keep probing
        if self._dropping:
            if self._drop_remaining > 0:
                self.send_move(client, Operation.DOWN)
                self._drop_remaining -= 1
                if self._drop_remaining == 0:
                    self._dropping = False
            else:
                self._dropping = False
        elif self._sweep_dir == 1:
            self.send_move(client, Operation.RIGHT)
        else:
            if x <= 0:
                self._start_drop(world)
            else:
                self.send_move(client, Operation.LEFT)

    def _start_drop(self, world):
        r = world.vision_calibrator.get_radius(self.unit_id)
        self._drop_remaining = max(1, int(r * 2 + 1))
        self._dropping = True
        self._sweep_dir = -self._sweep_dir

    # ── SWEEP ──────────────────────────────────────────────────────────────────

    def _build_sweep(self, world, drone_x, drone_y):
        """
        Compute zigzag waypoints for full map coverage from top to bottom.
        Never skips strips — the drone may have found bounds by dropping straight
        down without sweeping, so we always do the whole map.
        """
        east  = world.east_bound
        south = world.south_bound
        r     = world.vision_calibrator.get_radius(self.unit_id)
        h     = max(1, int(r * 2 + 1))

        # strip centres from top to bottom
        strip_ys = list(range(h // 2, south + 1, h))
        if not strip_ys or strip_ys[-1] < south - h // 2:
            strip_ys.append(south)

        # first waypoint: go toward whichever wall is farther from current x
        go_left = drone_x >= east // 2

        waypoints = []
        for sy in strip_ys:
            target_x = 0 if go_left else east
            waypoints.append((target_x, sy))
            go_left = not go_left

        self.waypoints = waypoints
        print(f"[Drone:{self.unit_id}] sweep plan: {len(waypoints)} waypoints"
              f"  map={east+1}×{south+1}  strip_h={h}")

    def _on_SWEEP(self, world, client):
        # if we discover fires during sweep, snipe immediately, then resume
        if world.fires:
            self.transition("SNIPE")
            return

        p = self.pos(world)
        if p is None:
            return
        x, y = p

        if not self.waypoints:
            self.transition("SNIPE")
            return

        wx, wy = self.waypoints[0]
        dist = abs(x - wx) + abs(y - wy)

        # close enough to waypoint — advance
        r = world.vision_calibrator.get_radius(self.unit_id)
        arrive_threshold = max(2, int(r))
        if dist <= arrive_threshold:
            self.waypoints.pop(0)
            print(f"[Drone:{self.unit_id}] waypoint reached, {len(self.waypoints)} remaining")
            if not self.waypoints:
                self.transition("SNIPE")
                return
            wx, wy = self.waypoints[0]

        dx, dy = direct_step(x, y, wx, wy)
        self.send_move(client, direction_to_operation(dx, dy))

    # ── SNIPE ──────────────────────────────────────────────────────────────────

    def _on_SNIPE(self, world, client):
        p = self.pos(world)
        if p is None:
            return
        x, y = p
        w = self.water(world)

        if w == 0 or self.going_to_water:
            self._fly_to_water(world, client, x, y)
            return

        if self.snipe_target and self.snipe_target not in world.fires:
            self.snipe_target = None

        if self.snipe_target is None:
            utype = world.units.get(self.unit_id, (0, 0, "firecopter", 0))[2]
            damage = self._get_damage(utype)
            targets = world.fire_tracker.get_snipeable(w, damage, x, y)
            if targets:
                self.snipe_target = targets[0]
            elif world.fires:
                self.snipe_target = min(
                    world.fires.keys(),
                    key=lambda p: abs(p[0] - x) + abs(p[1] - y)
                )
            else:
                # no fires — resume sweep if waypoints remain, else patrol
                if self.waypoints:
                    self.transition("SWEEP")
                else:
                    self.transition("PATROL")
                return

        tx, ty = self.snipe_target
        if abs(x - tx) <= 1 and abs(y - ty) <= 1:
            self.send_move(client, Operation.EXTINGUISH)
            if w <= 1:
                self.going_to_water = True
                self.snipe_target = None
        else:
            dx, dy = direct_step(x, y, tx, ty)
            self.send_move(client, direction_to_operation(dx, dy))

    def _fly_to_water(self, world, client, x, y):
        water_pos = world.nearest_water(x, y)
        if water_pos is None:
            self.send_move(client, Operation.NOP)
            return
        wx, wy = water_pos
        if abs(x - wx) <= 1 and abs(y - wy) <= 1:
            self.send_move(client, Operation.REFILL)
            self.going_to_water = False
        else:
            dx, dy = direct_step(x, y, wx, wy)
            self.send_move(client, direction_to_operation(dx, dy))

    # ── PATROL ─────────────────────────────────────────────────────────────────

    def _on_PATROL(self, world, client):
        if world.fires:
            self.transition("SNIPE")
        else:
            # seed drone explore opposite to ground units so it covers different area
            if not hasattr(self, "_explore_dir"):
                self._explore_dir = (self.unit_id + 2) % 4
                self._explore_prev = None
                self._explore_stuck = 0
            self.explore(world, client)

    # ── helpers ────────────────────────────────────────────────────────────────

    def _get_damage(self, utype):
        from config import UNIT_DAMAGE
        t = utype.lower()
        for k, v in UNIT_DAMAGE.items():
            if k in t:
                return v
        return 100
