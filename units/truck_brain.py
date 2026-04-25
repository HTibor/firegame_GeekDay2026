from units.unit_brain import UnitBrain
from navigation.pathfinding import bfs_next_step, direction_to_operation
from navigation.stuck_detector import StuckDetector
from game_client import Operation


class TruckBrain(UnitBrain):
    """
    Water loop: GOTO_FIRE → FIGHT → GOTO_WATER → REFILL
    Each tick also checks for an opportunistic snipe on the way.
    """

    def __init__(self, unit_id):
        super().__init__(unit_id)
        self.state = "GOTO_FIRE"
        self._stuck = StuckDetector()
        self.fire_target = None      # (x, y) assigned fire tile
        self.water_target = None     # (x, y) water tile to refill at
        self._last_dx = 0
        self._last_dy = 0

    # ── GOTO_FIRE ──────────────────────────────────────────────────────────────

    def _on_GOTO_FIRE(self, world, client):
        p = self.pos(world)
        if p is None:
            return
        x, y = p
        self._stuck.record(self.unit_id, x, y)

        # pick or validate target
        if self.fire_target is None or self.fire_target not in world.fires:
            self.fire_target = self._pick_fire(world, x, y)
        if self.fire_target is None:
            self.explore(world, client)
            return

        fx, fy = self.fire_target

        # arrived adjacent?
        if abs(x - fx) + abs(y - fy) <= 1:
            self.transition("FIGHT")
            return

        # opportunistic snipe check
        snipe = self._check_opportunistic_snipe(world, x, y, fx, fy)
        if snipe:
            self.send_move(client, Operation.EXTINGUISH)
            return

        # approach cell — path to adjacent passable cell
        goal = world.find_approach_cell(fx, fy)
        if goal is None:
            # fire is surrounded; skip it
            self.fire_target = None
            return

        gx, gy = goal
        nxt = bfs_next_step(world, x, y, gx, gy)
        if nxt is None:
            if self._stuck.is_stuck(self.unit_id):
                self._stuck.mark_blocked(world, x, y, self._last_dx, self._last_dy)
                self._stuck.clear_history(self.unit_id)
                self.fire_target = None
            self.send_move(client, Operation.NOP)
            return

        nx, ny = nxt
        dx, dy = nx - x, ny - y
        self._last_dx, self._last_dy = dx, dy
        self.send_move(client, direction_to_operation(dx, dy))

    # ── FIGHT ──────────────────────────────────────────────────────────────────

    def _on_FIGHT(self, world, client):
        p = self.pos(world)
        if p is None:
            return
        x, y = p
        w = self.water(world)

        if w == 0:
            self.transition("GOTO_WATER")
            return

        # fire gone?
        if self.fire_target not in world.fires:
            self.fire_target = None
            self.transition("GOTO_FIRE")
            return

        self.send_move(client, Operation.EXTINGUISH)

    # ── GOTO_WATER ─────────────────────────────────────────────────────────────

    def _on_GOTO_WATER(self, world, client):
        p = self.pos(world)
        if p is None:
            return
        x, y = p
        self._stuck.record(self.unit_id, x, y)

        if self.water_target is None or world.water_sources.get(self.water_target, False):
            # target gone/empty — re-pick
            self.water_target = world.nearest_water(x, y)
        if self.water_target is None:
            # no water known yet — explore until we find some
            self.explore(world, client)
            return

        wx, wy = self.water_target
        if abs(x - wx) + abs(y - wy) <= 1:
            self.transition("REFILL")
            return

        goal = world.find_approach_cell(wx, wy)
        if goal is None:
            self.water_target = None
            return

        gx, gy = goal
        nxt = bfs_next_step(world, x, y, gx, gy)
        if nxt is None:
            if self._stuck.is_stuck(self.unit_id):
                self._stuck.mark_blocked(world, x, y, self._last_dx, self._last_dy)
                self._stuck.clear_history(self.unit_id)
                self.water_target = None
            self.send_move(client, Operation.NOP)
            return

        nx, ny = nxt
        dx, dy = nx - x, ny - y
        self._last_dx, self._last_dy = dx, dy
        self.send_move(client, direction_to_operation(dx, dy))

    # ── REFILL ─────────────────────────────────────────────────────────────────

    def _on_REFILL(self, world, client):
        entry = world.units.get(self.unit_id)
        if entry is None:
            return
        _, _, utype, water = entry

        # detect full tank by checking if water stopped changing — simple: just refill once then go
        # In practice, send REFILL until full (server will cap it)
        from config import UNIT_DAMAGE
        # approximate max water by type; we re-check each tick
        if water > 0 and self._refill_count() >= 3:
            self.transition("GOTO_FIRE")
            return

        self.send_move(client, Operation.REFILL)
        self._refill_ticks = getattr(self, "_refill_ticks", 0) + 1

    def _refill_count(self):
        return getattr(self, "_refill_ticks", 0)

    # ── helpers ────────────────────────────────────────────────────────────────

    def _pick_fire(self, world, x, y):
        """Ask coordinator for a fire; fall back to nearest."""
        from coordinator import Coordinator
        coord = Coordinator.instance
        if coord:
            t = coord.get_fire_target(self.unit_id, "truck", x, y, world)
            if t:
                return t
        if not world.fires:
            return None
        return min(world.fires.keys(), key=lambda p: abs(p[0] - x) + abs(p[1] - y))

    def _check_opportunistic_snipe(self, world, x, y, dest_x, dest_y):
        """
        Return True if a nearly-dead fire is within 3 tiles of our current
        path straight-line (cheap distance check to midpoint of journey).
        """
        w = self.water(world)
        if w == 0:
            return False
        from config import UNIT_DAMAGE
        utype = world.units.get(self.unit_id, (0, 0, "firetruck", 0))[2]
        damage = 200
        for k, v in UNIT_DAMAGE.items():
            if k in utype.lower():
                damage = v
                break
        killable_hp = w * damage
        for (fx, fy), info in world.fire_tracker.fire_tiles.items():
            if info["hp"] > killable_hp:
                continue
            # within 2 tiles of us right now?
            if abs(fx - x) + abs(fy - y) <= 2:
                return True
        return False

    def transition(self, new_state):
        # reset refill counter on leaving REFILL
        if self.state == "REFILL":
            self._refill_ticks = 0
        super().transition(new_state)
