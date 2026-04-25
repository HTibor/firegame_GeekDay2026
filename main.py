import time
import json
import map_info
from game_client import FireRaClient, Operation

# Import the modified WebViz
from web_viz import WebViz

our_units = []
our_commands = []
DEBUG = True

# 1. Create your map
map = map_info.map_info()


def handle_server_message(message):
    """Callback function triggered whenever the server sends data."""
    op = message.operation

    if op == "UnitsFromServer":
        if message.extraJson:
            units_data = json.loads(message.extraJson)
            for data in units_data:
                postion_data = data["Position"]
                map.update_units(
                    postion_data["X"],
                    postion_data["Y"],
                    data["Id"],
                    data["UnitType"],
                    data["CurrentWaterLevel"],
                )

                fire_data = data["SeenFires"]
                for fire in fire_data:
                    map.update_fires(fire["X"], fire["Y"], hp=1000)

                water_data = data["SeenWaters"]
                for water in water_data:
                    map.update_waters(
                        water["X"],
                        water["Y"],
                        water["IsEmpty"],
                    )
        if DEBUG:
            print(units_data)


def main():
    # --- LAUNCH WEB VISUALIZER ---
    viz = WebViz(map)  # Pass the map directly!
    viz.start(port=5000)
    # -----------------------------

    client = FireRaClient(
        team_name="Prometheus", host="10.4.4.59", port=5001, secure=False
    )

    print("Testing connection...")
    client.say_hello()
    client.start_stream(on_message_callback=handle_server_message)
    time.sleep(1)

    client.send_command(unit_id=25, operation=Operation.NOP)

    while True:
        for unit_id, (x, y, unit_type, units_water) in list(map.units.items()):
            try:
                print(f"Moving Unit[{unit_id}]")
                goto(client, unit_id, 100, 29)
                time.sleep(0.5)

            except KeyboardInterrupt:
                print("\nDisconnecting...")
                client.close()
                return


def goto(client, unit_id, dest_x, dest_y):
    (unit_x, unit_y, unit_type, junk1) = map.units[unit_id]
    # 1. Fix the X axis (Left / Right)
    if unit_x < dest_x:
        client.send_command(unit_id=unit_id, operation=Operation.RIGHT)
    elif unit_x > dest_x:
        client.send_command(unit_id=unit_id, operation=Operation.LEFT)
        
    # 2. Fix the Y axis (Up / Down)
    elif unit_y < dest_y:
        # If the unit's Y is smaller than destination, it is higher up. It needs to move DOWN.
        client.send_command(unit_id=unit_id, operation=Operation.DOWN)
    elif unit_y > dest_y:
        # If the unit's Y is larger than destination, it is lower down. It needs to move UP.
        client.send_command(unit_id=unit_id, operation=Operation.UP)


if __name__ == "__main__":
    main()
