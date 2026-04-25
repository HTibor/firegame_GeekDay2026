TEAM_NAME = "Prometheus"
SERVER_IP = "10.4.4.59"
SERVER_PORT = 5001

MIN_ASSUMED_VISION = 2
STUCK_PATIENCE_GROUND = 4
STUCK_PATIENCE_AIR_SPAWN = 1
STUCK_PATIENCE_AIR = 2
BLOCKED_EXPIRY_SEC = 10
FIRE_CLUSTER_RADIUS = 3      # flood-fill neighbourhood radius for grouping fires
MAX_FIGHTER_RANGE = 80       # fighter won't walk further than this to a cluster

# estimated from observed speed (cells per server tick of 0.5 s, so 2x = cells/s)
UNIT_SPEEDS = {
    "firefighter": 1,
    "firetruck": 2,
    "firecopter": 4,
}

# damage per EXTINGUISH command
UNIT_DAMAGE = {
    "firefighter": 50,
    "firetruck": 200,
    "firecopter": 100,
}

UNIT_TYPES_DRONE   = ("cop", "copter", "drone")
UNIT_TYPES_TRUCK   = ("truck",)
# anything else → fighter
