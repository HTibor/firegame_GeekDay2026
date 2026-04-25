import time
import json
import map_info
from game_client import FireRaClient, Operation

# Import the modified WebViz
from web_viz import WebViz

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
TEAM_NAME = "Prometheus"
SERVER_IP = "10.4.4.59"
SERVER_PORT = 5001
DEBUG = False

# 1. Create your map
map = map_info.map_info()

# Variables for the patrol loop and speed tracking
unit_destinations = {} 
last_positions = {}
last_speed_check = time.time()
last_server_tick = 0.0


def handle_server_message(message):
    """
    Callback function triggered whenever the server sends data.
    Parses the JSON and updates our internal map.
    """
    global last_server_tick
    op = message.operation

    if op == "UnitsFromServer":
        # Measure Server Timing to ensure the server isn't lagging
        now = time.time()
        if last_server_tick > 0:
            tick_delta_ms = (now - last_server_tick) * 1000
            if tick_delta_ms > 600:
                print(f"[SERVER LAG WARNING] Tick took {tick_delta_ms:.1f} ms")
        last_server_tick = now

        # Parse JSON and update the map data
        if message.extraJson:
            units_data = json.loads(message.extraJson)
            for data in units_data:
                postion_data = data["Position"]
                
                # Update our units
                map.update_units(
                    postion_data["X"], 
                    postion_data["Y"], 
                    data["Id"],
                    data["UnitType"], 
                    data["CurrentWaterLevel"]
                )
                
                # Update map with fires we can see
                for fire in data["SeenFires"]:
                    map.update_fires(fire["X"], fire["Y"], hp=1000)
                    
                # Update map with water sources we can see
                for water in data["SeenWaters"]:
                    map.update_waters(water["X"], water["Y"], water["IsEmpty"])


def main():
    global last_speed_check, last_positions

    # --- LAUNCH WEB VISUALIZER ---
    viz = WebViz(map)  
    viz.start(port=5000)

    # --- CONNECT TO SERVER ---
    client = FireRaClient(
        team_name=TEAM_NAME, host=SERVER_IP, port=SERVER_PORT, secure=False
    )

    print(f"Connecting to {SERVER_IP}:{SERVER_PORT} as {TEAM_NAME}...")
    client.say_hello()
    client.start_stream(on_message_callback=handle_server_message)
    time.sleep(1) # Give the stream a second to establish

    # Send a dummy command to initialize the connection
    client.send_command(unit_id=25, operation=Operation.NOP)

    try:
        while True:
            # ==========================================
            # 1. DECIDE WHERE UNITS SHOULD GO
            # ==========================================
            for unit_id, (unit_x, unit_y, unit_type, units_water) in list(map.units.items()):
                
                # Simple Patrol Logic: Bounce between X=0 and X=189
                if unit_id not in unit_destinations:
                    unit_destinations[unit_id] = 189
                
                if unit_x >= 189:
                    unit_destinations[unit_id] = 0
                elif unit_x <= 0:
                    unit_destinations[unit_id] = 189
                
                # Tell the unit to move towards its destination
                goto(client, unit_id, unit_destinations[unit_id], unit_y)

            # ==========================================
            # 2. LOG FLEET SPEED (Every 1 second)
            # ==========================================
            current_time = time.time()
            dt = current_time - last_speed_check
            
            if dt >= 1.0: 
                print(f"\n--- FLEET SPEED REPORT ({time.strftime('%H:%M:%S')}) ---")
                for unit_id, (unit_x, unit_y, unit_type, _) in list(map.units.items()):
                    if unit_id in last_positions:
                        last_x, last_y = last_positions[unit_id]
                        # Pythagorean theorem to calculate exact distance moved
                        dist = ((unit_x - last_x)**2 + (unit_y - last_y)**2)**0.5
                        speed = dist / dt
                        print(f"  Unit[{unit_id}] ({unit_type}): {speed:.1f} c/s")
                        
                    last_positions[unit_id] = (unit_x, unit_y)
                
                print("----------------------------------------\n")
                last_speed_check = current_time

            # ==========================================
            # 3. SLEEP UNTIL NEXT SERVER TICK
            # ==========================================
            # The server processes movement every 500ms. 
            # We sleep to avoid spamming the CPU and network.
            time.sleep(0.5) 

    except KeyboardInterrupt:
        print("\nDisconnecting...")
        client.close()
        return


def goto(client, unit_id, dest_x, dest_y):
    """
    Sends a SINGLE directional command to the server.
    Because commands act as "Intents", the server will drive the unit 
    as far as its physical speed allows in that direction during the 500ms tick.
    """
    # Unpack the current unit's data from our map
    (unit_x, unit_y, unit_type, junk1) = map.units[unit_id]
    
    # Calculate Delta X and Delta Y (Difference between target and current position)
    dx = dest_x - unit_x 
    dy = dest_y - unit_y
    
    # If both are 0, we have arrived! Do nothing.
    if dx == 0 and dy == 0:
        return

    # Prioritize the axis that has the furthest distance left to travel.
    # abs() makes negative numbers positive so we can compare the raw distance.
    if abs(dx) > abs(dy):
        # We need to travel further horizontally
        if dx > 0:
            client.send_command(unit_id=unit_id, operation=Operation.RIGHT)
        else:
            client.send_command(unit_id=unit_id, operation=Operation.LEFT)
    else:
        # We need to travel further vertically
        if dy > 0:
            client.send_command(unit_id=unit_id, operation=Operation.DOWN)
        else:
            client.send_command(unit_id=unit_id, operation=Operation.UP)


if __name__ == "__main__":
    main()