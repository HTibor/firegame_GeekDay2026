import time
import json
import map_info
from game_client import FireRaClient, Operation


our_units = []
our_commands = []
map = map_info.map_info()


def handle_server_message(message):
    """Callback function triggered whenever the server sends data."""
    op = message.operation

    if op == "UnitsFromServer":
        print(f"\n[SERVER] Received unit data! (Counter: {message.counter})")
        # Load the extraJson payload containing your unit states
        if message.extraJson:
            units_data = json.loads(message.extraJson)
            for data in units_data:
                postion_data = data["Position"]
                map.update_units(postion_data["X"], postion_data["Y"], data["Id"])

                fire_data = data["SeenFires"]
                for fire in fire_data:
                    fire_postion_data = fire["Position"]
                    map.update_fires(
                        fire_postion_data["X"], fire_postion_data["Y"], hp=1000
                    )

                water_data = data["SeenWaters"]
                for water in water_data:
                    water_postion_data = water["Position"]
                    map.update_waters(
                        water_postion_data["X"],
                        water_postion_data["Y"],
                        water_postion_data["IsEmpty"],
                    )
                print(map)
            # print(units_data)


def main():
    # 1. Initialize client (Replace host with the actual IP)
    # Using secure=False for local/test networks if SSL certs aren't strictly validated
    client = FireRaClient(
        team_name="Prometheus", host="10.4.4.59", port=5001, secure=False
    )

    # 2. Test Connection
    print("Testing connection...")
    client.say_hello()

    # 3. Start receiving streaming data
    client.start_stream(on_message_callback=handle_server_message)

    # Allow a moment for the stream to establish
    time.sleep(1)

    client.send_command(unit_id=25, operation=Operation.NOP)
    while True:
        for unit in our_units:
            try:
                # 4. Issue commands to units
                unit_to_move = unit  # Example unit ID

                print(f"Moving Unit[{unit_to_move}] 1 UP...")
                client.send_command(unit_id=unit_to_move, operation=Operation.RIGHT)
                time.sleep(0.5)

                # Keep the main thread alive while background stream thread does its work
                # while True:
                #   time.sleep(1)

            except KeyboardInterrupt:
                print("\nDisconnecting...")
                client.close()
                return
            # finally:
            #   client.close()
            #  return


if __name__ == "__main__":
    main()
