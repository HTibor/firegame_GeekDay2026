from game_client import Operation
from navigation.pathfinding import direction_to_operation


class UnitBrain:
    def __init__(self, unit_id):
        self.unit_id = unit_id
        self.state = "INIT"
        self._wander_target = None   # (x, y) used by explore()

    def tick(self, world, client):
        handler = getattr(self, f"_on_{self.state}", None)
        if handler:
            handler(world, client)
        else:
            print(f"[{self.__class__.__name__}:{self.unit_id}] unknown state {self.state}")

    def transition(self, new_state):
        print(f"[{self.__class__.__name__}:{self.unit_id}] {self.state} → {new_state}")
        self.state = new_state

    def send_move(self, client, operation):
        print(f"  [{self.unit_id}] {operation}")
        client.send_command(unit_id=self.unit_id, operation=operation)

    def pos(self, world):
        """Return (x, y) of this unit, or None if not in world."""
        entry = world.units.get(self.unit_id)
        if entry is None:
            return None
        return entry[0], entry[1]

    def water(self, world):
        entry = world.units.get(self.unit_id)
        return entry[3] if entry else 0

    def explore(self, world, client):
        """
        Move in a direction, rotate 90° clockwise when stuck (position didn't
        change for 2 ticks). No BFS, no map-size knowledge needed.
        Units fan out because they seed direction from their unit_id.
        """
        p = self.pos(world)
        if p is None:
            return
        x, y = p

        if not hasattr(self, "_explore_dir"):
            self._explore_dir = self.unit_id % 4   # seed from id → different start dirs
            self._explore_prev = None
            self._explore_stuck = 0

        # stuck check: position didn't change for 4 ticks (allows for server latency)
        if self._explore_prev == (x, y):
            self._explore_stuck += 1
            if self._explore_stuck >= 4:
                self._explore_dir = (self._explore_dir + 1) % 4  # rotate 90° CW
                self._explore_stuck = 0
        else:
            self._explore_stuck = 0
        self._explore_prev = (x, y)

        dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # R, D, L, U
        dx, dy = dirs[self._explore_dir]
        self.send_move(client, direction_to_operation(dx, dy))
