import heapq
from game_client import Operation


def bfs_next_step(world, start_x, start_y, goal_x, goal_y, max_search=40000, air=False):
    """
    A* with Manhattan heuristic.
    Kept as bfs_next_step so all callers work unchanged.
    max_search caps the number of nodes popped (not visited),
    which is enough to find paths across the full 190×190 map
    even with moderate obstacle density.
    """
    if start_x == goal_x and start_y == goal_y:
        return None

    passable = world.is_passable_air if air else world.is_passable_ground

    def h(x, y):
        return abs(x - goal_x) + abs(y - goal_y)

    # heap entries: (f, g, x, y)
    start = (h(start_x, start_y), 0, start_x, start_y)
    open_heap = [start]
    came_from = {(start_x, start_y): None}
    g_score = {(start_x, start_y): 0}
    popped = 0

    while open_heap and popped < max_search:
        f, g, cx, cy = heapq.heappop(open_heap)
        popped += 1

        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in came_from:
                continue

            if nx == goal_x and ny == goal_y:
                came_from[(nx, ny)] = (cx, cy)
                # trace back to the first step
                node = (goal_x, goal_y)
                while came_from[node] != (start_x, start_y):
                    node = came_from[node]
                return node

            if passable(nx, ny):
                ng = g + 1
                if ng < g_score.get((nx, ny), 10**9):
                    g_score[(nx, ny)] = ng
                    came_from[(nx, ny)] = (cx, cy)
                    heapq.heappush(open_heap, (ng + h(nx, ny), ng, nx, ny))

    return None


def direction_to_operation(dx, dy):
    if dx > 0:
        return Operation.RIGHT
    if dx < 0:
        return Operation.LEFT
    if dy > 0:
        return Operation.DOWN
    return Operation.UP


def direct_step(start_x, start_y, goal_x, goal_y):
    """Beeline step: move along the axis with greater remaining distance."""
    dx = goal_x - start_x
    dy = goal_y - start_y
    if dx == 0 and dy == 0:
        return (0, 0)
    if abs(dx) >= abs(dy):
        return (1 if dx > 0 else -1, 0)
    return (0, 1 if dy > 0 else -1)
