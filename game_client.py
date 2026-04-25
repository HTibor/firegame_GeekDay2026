import grpc
import threading
import queue

# Import the generated gRPC classes
import file_pb2
import file_pb2_grpc


class Operation:
    """Helper class for valid game operations"""

    NOP = "NOP"
    UP = "Up"
    LEFT = "Left"
    RIGHT = "Right"
    DOWN = "Down"
    EXTINGUISH = "ExtinguishFire"
    REFILL = "RefillWithWater"


class FireRaClient:
    def __init__(self, team_name, host="10.x.y.z", port=5000, secure=True):
        self.team_name = team_name
        self.target = f"{host}:{port}"
        self.counter = 0
        self.channel = None
        self.stub = None

        # Used to handle the bidirectional streaming
        self._command_queue = queue.Queue()
        self._stream_thread = None
        self._is_running = False

        # Connect to the server
        # Note: If the server uses self-signed certs on an IP, you might need an insecure channel
        # or specific SSL credentials. We default to secure based on the 'https://' in your prompt.
        if secure:
            credentials = grpc.ssl_channel_credentials()
            self.channel = grpc.secure_channel(self.target, credentials)
        else:
            self.channel = grpc.insecure_channel(self.target)

        self.stub = file_pb2_grpc.FireRaServiceStub(self.channel)

    def say_hello(self):
        """Simple unary call to check server connection."""
        request = file_pb2.HelloRequest(teamName=self.team_name)
        try:
            response = self.stub.SayHello(request)
            print(f"Server replied: {response.message}")
            return response.message
        except grpc.RpcError as e:
            print(f"SayHello failed: {e.details()}")
            return None

    def _command_generator(self):
        """Yields commands from the queue to the gRPC stream."""
        while self._is_running:
            # Block until a command is put in the queue
            command = self._command_queue.get()
            if command is None:  # Sentinel value to stop
                break
            yield command

    def start_stream(self, on_message_callback):
        """
        Starts the bidirectional stream in a background thread.
        on_message_callback: A function that takes a single CommandMessage argument.
        """
        self._is_running = True

        def _stream_listener():
            try:
                # This initiates the stream. We pass our generator that yields queued commands.
                responses = self.stub.CommunicateWithStreams(self._command_generator())
                for response in responses:
                    on_message_callback(response)
            except grpc.RpcError as e:
                print(f"\nStream disconnected: {e.details()}")
            finally:
                self._is_running = False

        self._stream_thread = threading.Thread(target=_stream_listener, daemon=True)
        self._stream_thread.start()
        print("Bidirectional stream started.")

    def send_command(self, unit_id, operation):
        """Queues a command to be sent to the server."""
        if not self._is_running:
            print("Cannot send command. Stream is not running.")
            return

        self.counter += 1
        cmd = file_pb2.CommandMessage(
            teamName=self.team_name,
            counter=self.counter,
            unitId=unit_id,
            operation=operation
        )
        self._command_queue.put(cmd)

    def close(self):
        """Cleans up resources and stops threads."""
        self._is_running = False
        self._command_queue.put(None)  # Unblock the generator
        if self.channel:
            self.channel.close()
