class map_info:
    def __init__(self):
        # Key: (x, y) tuple
        # Value: Fire HP (int)
        self.fires = {}

        # Key: (x, y) tuple
        # Value: Water amount available (int) or True if infinite
        self.water_sources = {}

        self.obsticles = {}

        self.units = {}

    def update_fires(self, x, y, hp):
        self.fires[(x, y)] = hp

    def update_waters(self, x, y, value):
        self.water_sources[(x, y)] = value

    def update_obsticles(self, x, y):
        self.obsticles[(x, y)] = True

    def update_units(self, x, y, id, unit_type, unit_water):
        self.units[id] = (x, y, unit_type, unit_water)
