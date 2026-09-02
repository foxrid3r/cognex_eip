"""Threaded Cognex Class 1 I/O connection service."""

import socket
import threading
import time
from collections import deque

from .binary import set_bit, set_uint16_le
from .constants import DEFAULT_RPI_MS, ENIP_PORT, IO_PORT, OUTPUT_DATA_SIZE, OUTPUT_USER_OFFSET, OUTPUT_USER_SIZE
from .protocol import ConnectionIdentity, build_o_to_t_packet, forward_close, forward_open, parse_t_to_o_packet, register_session, unregister_session

# Communication Engine
# ============================================================

class CognexConnection:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None

        self.camera_ip = None
        self.rpi_ms = DEFAULT_RPI_MS

        self.state = "Disconnected"
        self.error = None

        self.input_data = b""
        self.output_data = bytearray(
            OUTPUT_DATA_SIZE
        )

        self.packet_count = 0
        self.packet_times = deque()
        self.last_packet_time = None

    def start(
        self,
        camera_ip,
        rpi_ms,
    ):
        if (
            self.thread
            and self.thread.is_alive()
        ):
            return

        self.camera_ip = camera_ip
        self.rpi_ms = rpi_ms

        self.stop_event.clear()

        with self.lock:
            self.state = "Connecting"
            self.error = None

            self.input_data = b""
            self.output_data = bytearray(
                OUTPUT_DATA_SIZE
            )

            self.packet_count = 0
            self.packet_times.clear()
            self.last_packet_time = None

        self.thread = threading.Thread(
            target=self._worker,
            daemon=True,
        )

        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def set_output_bit(
        self,
        byte_number,
        bit_number,
        value,
    ):
        with self.lock:
            set_bit(
                self.output_data,
                byte_number,
                bit_number,
                value,
            )

    def pulse_output_bit(
        self,
        byte_number,
        bit_number,
        duration=0.1,
    ):
        self.set_output_bit(
            byte_number,
            bit_number,
            True,
        )

        timer = threading.Timer(
            duration,
            self.set_output_bit,
            args=(
                byte_number,
                bit_number,
                False,
            ),
        )

        timer.daemon = True
        timer.start()

    def set_command_id(
        self,
        command_id,
    ):
        if not 0 <= command_id <= 65535:
            raise ValueError(
                "Command ID must be 0..65535"
            )

        with self.lock:
            set_uint16_le(
                self.output_data,
                4,
                command_id,
            )

    def set_user_data(
        self,
        user_data,
    ):
        if len(user_data) > OUTPUT_USER_SIZE:
            raise ValueError(
                f"Maximum User Data size is "
                f"{OUTPUT_USER_SIZE} bytes"
            )

        with self.lock:
            self.output_data[
                OUTPUT_USER_OFFSET:
                OUTPUT_USER_OFFSET + OUTPUT_USER_SIZE
            ] = bytes(
                OUTPUT_USER_SIZE
            )

            self.output_data[
                OUTPUT_USER_OFFSET:
                OUTPUT_USER_OFFSET + len(user_data)
            ] = user_data

    def clear_outputs(self):
        with self.lock:
            self.output_data[:] = bytes(
                OUTPUT_DATA_SIZE
            )

    def snapshot(self):
        with self.lock:
            now = time.monotonic()

            while (
                self.packet_times
                and self.packet_times[0]
                < now - 1
            ):
                self.packet_times.popleft()

            age = (
                None
                if self.last_packet_time is None
                else now - self.last_packet_time
            )

            return {
                "state": self.state,
                "error": self.error,
                "input": bytes(
                    self.input_data
                ),
                "output": bytes(
                    self.output_data
                ),
                "packet_count": self.packet_count,
                "packet_rate": len(
                    self.packet_times
                ),
                "packet_age": age,
            }

    def _set_state(
        self,
        state,
        error=None,
    ):
        with self.lock:
            self.state = state
            self.error = error

    def _worker(self):
        tcp_sock = None
        udp_sock = None

        session = 0
        opened = False

        identity = ConnectionIdentity()

        packet_sequence = 0
        transport_sequence = 0

        try:
            # TCP / RegisterSession
            tcp_sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM,
            )

            tcp_sock.settimeout(
                5
            )

            tcp_sock.connect(
                (
                    self.camera_ip,
                    ENIP_PORT,
                )
            )

            session = register_session(
                tcp_sock
            )

            # UDP / Class 1
            udp_sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM,
            )

            udp_sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )

            udp_sock.bind(
                (
                    "0.0.0.0",
                    IO_PORT,
                )
            )

            udp_sock.settimeout(
                0.002
            )

            self._set_state(
                "Forward Open"
            )

            forward_open(
                tcp_sock,
                session,
                identity,
                self.rpi_ms,
            )

            opened = True

            self._set_state(
                "Waiting for I/O"
            )

            period = (
                self.rpi_ms / 1000
            )

            next_send = (
                time.perf_counter()
            )

            while not self.stop_event.is_set():
                now_perf = (
                    time.perf_counter()
                )

                # O -> T
                if now_perf >= next_send:
                    with self.lock:
                        output = bytes(
                            self.output_data
                        )

                    packet = build_o_to_t_packet(
                        identity.o_to_t_connection_id,
                        packet_sequence,
                        transport_sequence,
                        output,
                    )

                    udp_sock.sendto(
                        packet,
                        (
                            self.camera_ip,
                            IO_PORT,
                        ),
                    )

                    packet_sequence = (
                        packet_sequence + 1
                    ) & 0xFFFFFFFF

                    transport_sequence = (
                        transport_sequence + 1
                    ) & 0xFFFF

                    next_send += period

                    if (
                        next_send
                        < now_perf - period
                    ):
                        next_send = (
                            now_perf + period
                        )

                # T -> O
                try:
                    packet, _ = (
                        udp_sock.recvfrom(
                            2048
                        )
                    )

                except socket.timeout:
                    continue

                parsed = (
                    parse_t_to_o_packet(
                        packet
                    )
                )

                if parsed is None:
                    continue

                (
                    connection_id,
                    assembly,
                ) = parsed

                if (
                    connection_id
                    != identity.t_to_o_connection_id
                ):
                    continue

                receive_time = (
                    time.monotonic()
                )

                with self.lock:
                    self.input_data = bytes(
                        assembly
                    )

                    self.packet_count += 1
                    self.last_packet_time = (
                        receive_time
                    )

                    self.packet_times.append(
                        receive_time
                    )

                    self.state = (
                        "I/O Running"
                    )

        except Exception as exc:
            self._set_state(
                "Error",
                str(exc),
            )

        finally:
            if opened:
                try:
                    forward_close(
                        tcp_sock,
                        session,
                        identity,
                    )
                except Exception:
                    pass

            if session and tcp_sock:
                unregister_session(
                    tcp_sock,
                    session,
                )

            if udp_sock:
                udp_sock.close()

            if tcp_sock:
                tcp_sock.close()

            if self.state != "Error":
                self._set_state(
                    "Disconnected"
                )


# ============================================================
