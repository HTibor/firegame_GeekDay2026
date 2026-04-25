from config import FIRE_CLUSTER_RADIUS


class FireTracker:
    def __init__(self):
        # {(x,y): {"hp": int, "prev_hp": int, "last_seen_tick": int}}
        self.fire_tiles = {}
        # list of cluster dicts; rebuilt each tick by recluster()
        self.clusters = []
        self._tick = 0

    # ── ingestion ──────────────────────────────────────────────────────────────

    def update_tile(self, x, y, hp, tick):
        key = (x, y)
        prev = self.fire_tiles.get(key, {}).get("hp", hp)
        self.fire_tiles[key] = {"hp": hp, "prev_hp": prev, "last_seen_tick": tick}

    def remove_stale(self, current_tick, stale_threshold=300): # may want to fine tune later
        """Drop tiles not seen for stale_threshold ticks."""
        dead = [k for k, v in self.fire_tiles.items()
                if current_tick - v["last_seen_tick"] >= stale_threshold]
        for k in dead:
            del self.fire_tiles[k]

    # ── clustering ─────────────────────────────────────────────────────────────

    def recluster(self):
        """Flood-fill grouping of fire tiles within FIRE_CLUSTER_RADIUS of each other."""
        remaining = set(self.fire_tiles.keys())
        clusters = []
        r = FIRE_CLUSTER_RADIUS

        while remaining:
            seed = next(iter(remaining))
            frontier = [seed]
            group = set()
            while frontier:
                cx, cy = frontier.pop()
                if (cx, cy) not in remaining:
                    continue
                remaining.discard((cx, cy))
                group.add((cx, cy))
                for nx in range(cx - r, cx + r + 1):
                    for ny in range(cy - r, cy + r + 1):
                        if (nx, ny) in remaining:
                            frontier.append((nx, ny))

            if not group:
                continue

            cx = sum(x for x, _ in group) / len(group)
            cy = sum(y for _, y in group) / len(group)

            # growth rate: fraction of tiles whose hp dropped since last seen
            shrinking = sum(1 for k in group
                            if self.fire_tiles[k]["hp"] < self.fire_tiles[k]["prev_hp"])
            growth = shrinking / len(group)  # 0‥1, higher = enemy is hitting it too

            clusters.append({
                "tiles": group,
                "centroid": (cx, cy),
                "size": len(group),
                "growth": growth,
                "is_enemy_contested": growth > 0.3,
            })

        self.clusters = sorted(clusters, key=lambda c: -c["size"])

    # ── queries ────────────────────────────────────────────────────────────────

    def get_snipeable(self, unit_water, unit_damage, unit_x, unit_y, max_dist=None):
        """Return list of (x,y) that this unit can kill in one pass."""
        killable_hp = unit_water * unit_damage
        result = []
        for (x, y), info in self.fire_tiles.items():
            if info["hp"] > killable_hp:
                continue
            if max_dist is not None:
                dist = abs(x - unit_x) + abs(y - unit_y)
                if dist > max_dist:
                    continue
            result.append((x, y))
        result.sort(key=lambda p: abs(p[0] - unit_x) + abs(p[1] - unit_y))
        return result

    def get_best_cluster(self, unit_x, unit_y, max_distance=None):
        """
        Score = cluster_size / max(1, manhattan_to_centroid).
        Returns cluster dict or None.
        """
        best, best_score = None, -1
        for c in self.clusters:
            cx, cy = c["centroid"]
            dist = abs(cx - unit_x) + abs(cy - unit_y)
            if max_distance is not None and dist > max_distance:
                continue
            score = c["size"] / max(1, dist)
            if score > best_score:
                best_score = score
                best = c
        return best

    def get_cluster_for_tile(self, x, y):
        """Return whichever cluster contains tile (x,y), or None."""
        for c in self.clusters:
            if (x, y) in c["tiles"]:
                return c
        return None
