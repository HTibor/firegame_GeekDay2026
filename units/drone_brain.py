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

        # FIND_BOUNDS state — two sequential phases: go RIGHT, then go DOWN
        self._prev_x = None
        self._prev_y = None
        self._same_x_count = 0
        self._same_y_count = 0

        # SWEEP state
        self.waypoints = []          # list of (x, y) to visit in order

        # SNIPE state
        self.snipe_target = None
        self.going_to_water = False
        self._snipe_ticks  = 0   # ticks spent on current snipe_target

    # ── FIND_BOUNDS ────────────────────────────────────────────────────────────
    # Two clean phases:
    #   Phase 1 — fly RIGHT until x stops changing (east wall found)
    #   Phase 2 — fly DOWN  until y stops changing (south wall found)
    # "didn't move for 2 consecutive ticks" = hit a wall

    def _on_FIND_BOUNDS(self, world, client):
        p = self.pos(world)
        if p is None:
            return
        x, y = p

        # ── Phase 1: find east wall ──────────────────────────────────────────
        if world.east_bound is None:
            if self._prev_x is not None:
                if x == self._prev_x:
                    self._same_x_count += 1
                else:
                    self._same_x_count = 0
            self._prev_x = x

            if self._same_x_count >= 2:
                world.east_bound = x
                self._same_x_count = 0
                self._prev_y = None   # reset for phase 2
                print(f"[Drone:{self.unit_id}] east_bound={x}  → now probing south")
            else:
                self.send_move(client, Operation.RIGHT)
            return

        # ── Phase 2: find south wall ─────────────────────────────────────────
        if world.south_bound is None:
            if self._prev_y is not None:
                if y == self._prev_y:
                    self._same_y_count += 1
                else:
                    self._same_y_count = 0
            self._prev_y = y

            if self._same_y_count >= 2:
                world.south_bound = y
                self._same_y_count = 0
                print(f"[Drone:{self.unit_id}] south_bound={y}  → building sweep")
            else:
                self.send_move(client, Operation.DOWN)
            return

        # ── Both walls known: build sweep and go ─────────────────────────────
        self._build_sweep(world, x, y)
        self.transition("SWEEP")

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
            self.snipe_target = self._pick_snipe_target(world, x, y, w, damage)
            if self.snipe_target is not None:
                tx, ty = self.snipe_target
                hp = world.fire_tracker.fire_tiles.get((tx, ty), {}).get("hp", "?")
                print(f"[Drone:{self.unit_id}] selected snipe_target=({tx},{ty}) hp={hp} available_damage={w*damage}")
            if self.snipe_target is None:
                if world.fires:
                    # nothing killable with current water but fires exist —
                    # go for nearest fire and do as much damage as possible
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

        tx, ty = self.snipe_agetarget
        if abs(x - tx) <= 1 and abs(y - ty) <= 1:
            hp = world.fire_tracker.fire_tiles.get((tx, ty), {}).get("hp", "?")
            print(f"[Drone:{self.unit_id}] EXTINGUISH fire({tx},{ty}) hp={hp}")
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

    def _pick_snipe_target(self, world, x, y, w, damage):
        """
        Pick the best fire tile to snipe, accounting for HP growth while travelling.

        For each fire tile:
          - growth_per_tick = max(0, current_hp - prev_hp)  (positive → fire is growing)
          - eta_ticks       ≈ manhattan_dist / DRONE_SPEED
          - projected_hp    = current_hp + growth_per_tick * eta_ticks

        Primary candidates: fires where projected_hp ≤ w * damage
                            (we can actually kill it with current water).
        Among candidates, pick the closest one.
        Returns None if no fire can be killed with current water.
        """
        DRONE_SPEED = 2.0   # ~4 cells/s ÷ 2 ticks/s = 2 cells/tick
        available_damage = w * damage

        best_dist = float("inf")
        best_tile = None

        for (fx, fy), info in world.fire_tracker.fire_tiles.items():
            hp      = info["hp"]
            prev_hp = info.get("prev_hp", hp)
            dist    = abs(fx - x) + abs(fy - y)

            growth_per_tick = max(0, hp - prev_hp)
            eta             = dist / max(1.0, DRONE_SPEED)
            projected_hp    = hp + growth_per_tick * eta

            if projected_hp <= available_damage and dist < best_dist:
                best_dist = dist
                best_tile = (fx, fy)

        return best_tile

    def _get_damage(self, utype):
        from config import UNIT_DAMAGE
        t = utype.lower()
        for k, v in UNIT_DAMAGE.items():
            if k in t:
                return v
        return 100
