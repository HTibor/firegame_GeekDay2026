import time
import json
import map_info
from game_client import FireRaClient, Operation

# Import the modified WebViz
from web_viz import WebViz

our_units = []
our_commands = []

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
                    postion_data["X"], postion_data["Y"], data["Id"], data["UnitType"]
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
        for unit_id, position in list(map.units.items()):
            try:
                print(f"Moving Unit[{unit_id}] RIGHT...")
                client.send_command(unit_id=unit_id, operation=Operation.RIGHT)
                time.sleep(0.5)

            except KeyboardInterrupt:
                print("\nDisconnecting...")
                client.close()
                return


if __name__ == "__main__":
    main()

