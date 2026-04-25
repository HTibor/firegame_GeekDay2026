import time
from game_client import FireRaClient, Operation
from web_viz import WebViz
from world.world_state import WorldState
from coordinator import Coordinator
import config


def main():
    world = WorldState()
    coordinator = Coordinator(world)

    viz = WebViz(world)
    viz.start(port=5000)

    client = FireRaClient(
        team_name=config.TEAM_NAME,
        host=config.SERVER_IP,
        port=config.SERVER_PORT,
        secure=False,
    )

    print(f"Connecting to {config.SERVER_IP}:{config.SERVER_PORT} as {config.TEAM_NAME}...")
    client.say_hello()
    client.start_stream(on_message_callback=world.ingest)
    time.sleep(1)

    # bootstrap stream
    client.send_command(unit_id=0, operation=Operation.NOP)

    try:
        while True:
            coordinator.tick(client)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nDisconnecting...")
        client.close()


if __name__ == "__main__":
    main()
