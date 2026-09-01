import json
import random
import socket
import struct
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import ttk, messagebox, filedialog


# ============================================================
# EtherNet/IP Configuration
# ============================================================

ENIP_PORT = 44818
IO_PORT = 2222

CMD_REGISTER_SESSION = 0x0065
CMD_UNREGISTER_SESSION = 0x0066
CMD_SEND_RR_DATA = 0x006F

CPF_NULL_ADDRESS = 0x0000
CPF_UNCONNECTED_DATA = 0x00B2
CPF_CONNECTED_DATA = 0x00B1
CPF_SEQUENCED_ADDRESS = 0x8002

CIP_FORWARD_OPEN = 0x54
CIP_FORWARD_CLOSE = 0x4E

CONNECTION_MANAGER_CLASS = 0x06
CONNECTION_MANAGER_INSTANCE = 0x01

ASSEMBLY_CLASS = 0x04
INPUT_ASSEMBLY = 13
OUTPUT_ASSEMBLY = 22
CONFIG_ASSEMBLY = 1

INPUT_DATA_SIZE = 496
OUTPUT_DATA_SIZE = 496

# With a 496-byte Class 1 input connection:
#   bytes 0..15   = Cognex status / standard fields
#   bytes 16..495 = 480 received inspection-result bytes
INPUT_RESULTS_OFFSET = 16
INPUT_RESULTS_SIZE = INPUT_DATA_SIZE - INPUT_RESULTS_OFFSET

# Output Assembly 22:
#   bytes 0..7   = control / command area
#   bytes 8..495 = 488 User Data bytes
OUTPUT_USER_OFFSET = 8
OUTPUT_USER_SIZE = OUTPUT_DATA_SIZE - OUTPUT_USER_OFFSET

DEFAULT_CAMERA_IP = "192.168.1.50"
DEFAULT_RPI_MS = 10.0

GUI_REFRESH_MS = 100
HEX_REFRESH_MS = 500
IO_TIMEOUT_SECONDS = 1.0


# ============================================================
# Audited Cognex Input Assembly 13
# ============================================================

INPUT_BITS = [
    # Byte 0
    (0, 0, "Trigger Ready"),
    (0, 1, "Trigger Ack"),
    (0, 3, "Acq Error"),
    (0, 7, "Online"),

    # Byte 1
    (1, 1, "Inspection Completed"),
    (1, 2, "Results Buffer Overrun"),
    (1, 3, "Results Valid"),
    (1, 4, "Command Executing"),
    (1, 5, "Command Completed"),
    (1, 6, "Command Failed"),
    (1, 7, "Error"),

    # Byte 2
    (2, 0, "Set User Data Acknowledge"),
    (2, 3, "Exposure Complete"),
    (2, 4, "Job Pass"),
    (2, 5, "System Validated"),

    # Byte 3
    (3, 0, "External Event Ack 0"),
    (3, 1, "External Event Ack 1"),
    (3, 2, "External Event Ack 2"),
    (3, 3, "External Event Ack 3"),
    (3, 4, "External Event Ack 4"),
    (3, 5, "External Event Ack 5"),
    (3, 6, "External Event Ack 6"),
    (3, 7, "External Event Ack 7"),
]

NUMERIC_FIELDS = [
    ("Error ID", 4),
    ("Command Result Code", 6),
    ("Current Job ID", 8),
    ("Acquisition ID", 10),
    ("Inspection ID", 12),
    ("Inspection Result Code", 14),
]


# ============================================================
# Audited Cognex Output Assembly 22
# ============================================================

OUTPUT_BITS = [
    # Byte 0
    (0, 0, "Trigger Enable"),
    (0, 1, "Trigger"),
    (0, 2, "Buffer Results Enable"),
    (0, 3, "Inspection Results Ack"),
    (0, 4, "Execute Command"),
    (0, 7, "Set Offline"),

    # Byte 2
    (2, 0, "Set User Data"),
    (2, 2, "Clear Error"),
    (2, 3, "Clear Exposure Complete"),

    # Byte 3
    (3, 0, "External Event 0"),
    (3, 1, "External Event 1"),
    (3, 2, "External Event 2"),
    (3, 3, "External Event 3"),
    (3, 4, "External Event 4"),
    (3, 5, "External Event 5"),
    (3, 6, "External Event 6"),
    (3, 7, "External Event 7"),
]


# ============================================================
# PLC Data Types
# EtherNet/IP is treated as little-endian.
# ============================================================

DATA_TYPES = {
    "SINT": {"size": 1, "fmt": "<b"},
    "INT":  {"size": 2, "fmt": "<h"},
    "DINT": {"size": 4, "fmt": "<i"},
    "REAL": {"size": 4, "fmt": "<f"},
}


# ============================================================
# Helpers
# ============================================================

def get_bit(data, byte_number, bit_number):
    if byte_number >= len(data):
        return False
    return bool(data[byte_number] & (1 << bit_number))


def set_bit(data, byte_number, bit_number, value):
    mask = 1 << bit_number
    if value:
        data[byte_number] |= mask
    else:
        data[byte_number] &= ~mask


def get_bits(data, byte_number, first_bit, count):
    if byte_number >= len(data):
        return 0
    return (data[byte_number] >> first_bit) & ((1 << count) - 1)


def uint16_le(data, offset):
    if offset + 2 > len(data):
        return 0
    return struct.unpack_from("<H", data, offset)[0]


def set_uint16_le(data, offset, value):
    struct.pack_into("<H", data, offset, value)


def hex_dump(data, width=16):
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset:offset + width]
        hex_part = " ".join(f"{v:02X}" for v in chunk)
        ascii_part = "".join(chr(v) if 32 <= v <= 126 else "." for v in chunk)
        lines.append(f"{offset:04X}  {hex_part:<48} {ascii_part}")
    return "\n".join(lines)


def format_display_value(value, data_type):
    if data_type == "REAL":
        return f"{value:.6g}"
    return str(value)


# ============================================================
# Configurable Data Layout
# ============================================================

class DataLayout:
    """
    Ordered packed field layout.

    Fields are contiguous: changing the order automatically changes offsets.
    Each field is:
        {"name": "...", "type": "SINT|INT|DINT|REAL"}
    """

    def __init__(self, max_size, fields=None):
        self.max_size = max_size
        self.fields = [dict(f) for f in (fields or [])]
        self.validate()

    def copy_fields(self):
        return [dict(field) for field in self.fields]

    def offsets(self):
        result = []
        offset = 0

        for field in self.fields:
            data_type = field["type"]
            size = DATA_TYPES[data_type]["size"]

            result.append({
                "name": field["name"],
                "type": data_type,
                "offset": offset,
                "size": size,
            })

            offset += size

        return result

    def total_size(self):
        return sum(
            DATA_TYPES[field["type"]]["size"]
            for field in self.fields
        )

    def validate(self):
        seen = set()

        for field in self.fields:
            if field["type"] not in DATA_TYPES:
                raise ValueError(
                    f"Unsupported data type: {field['type']}"
                )

            name = field["name"].strip()
            if not name:
                raise ValueError("Field names cannot be empty.")

            if name in seen:
                raise ValueError(
                    f"Duplicate field name: {name}"
                )

            seen.add(name)

        if self.total_size() > self.max_size:
            raise ValueError(
                f"Layout uses {self.total_size()} bytes, "
                f"but only {self.max_size} bytes are available."
            )

    def add(self, name, data_type):
        name = name.strip() or f"Value{len(self.fields) + 1}"

        if any(
            field["name"] == name
            for field in self.fields
        ):
            raise ValueError(
                f"A field named '{name}' already exists."
            )

        self.fields.append({
            "name": name,
            "type": data_type,
        })

        try:
            self.validate()
        except Exception:
            self.fields.pop()
            raise

    def remove(self, index):
        if 0 <= index < len(self.fields):
            self.fields.pop(index)

    def move(self, index, delta):
        new_index = index + delta

        if (
            0 <= index < len(self.fields)
            and 0 <= new_index < len(self.fields)
        ):
            item = self.fields.pop(index)
            self.fields.insert(new_index, item)
            return new_index

        return index

    def decode(self, data):
        values = []

        for item in self.offsets():
            end = item["offset"] + item["size"]

            if end > len(data):
                value = None
            else:
                value = struct.unpack_from(
                    DATA_TYPES[item["type"]]["fmt"],
                    data,
                    item["offset"],
                )[0]

            values.append((item, value))

        return values

    def encode(self, values):
        """
        Encode current configured fields into a full-sized zero-filled buffer.
        """
        self.validate()

        result = bytearray(self.max_size)

        for item in self.offsets():
            name = item["name"]
            data_type = item["type"]
            raw_value = values.get(name, "0")

            try:
                if data_type == "REAL":
                    value = float(raw_value)
                else:
                    value = int(str(raw_value).strip(), 0)

            except Exception as exc:
                raise ValueError(
                    f"{name}: '{raw_value}' is not a valid {data_type} value."
                ) from exc

            try:
                struct.pack_into(
                    DATA_TYPES[data_type]["fmt"],
                    result,
                    item["offset"],
                    value,
                )

            except struct.error as exc:
                raise ValueError(
                    f"{name}: value {value} is outside the valid "
                    f"range for {data_type}."
                ) from exc

        return bytes(result)


# ============================================================
# EtherNet/IP TCP
# ============================================================

def recv_exact(sock, count):
    data = bytearray()

    while len(data) < count:
        chunk = sock.recv(count - len(data))

        if not chunk:
            raise ConnectionError("TCP connection closed")

        data.extend(chunk)

    return bytes(data)


def enip_header(command, payload_length, session=0):
    return struct.pack(
        "<HHII8sI",
        command,
        payload_length,
        session,
        0,
        b"\x00" * 8,
        0,
    )


def send_enip(sock, command, payload=b"", session=0):
    sock.sendall(
        enip_header(
            command,
            len(payload),
            session,
        ) + payload
    )

    header = recv_exact(sock, 24)

    (
        reply_command,
        reply_length,
        reply_session,
        reply_status,
        _context,
        _options,
    ) = struct.unpack(
        "<HHII8sI",
        header,
    )

    body = recv_exact(
        sock,
        reply_length,
    )

    if reply_status != 0:
        raise RuntimeError(
            f"EtherNet/IP encapsulation error 0x{reply_status:08X}"
        )

    return (
        reply_command,
        reply_session,
        body,
    )


def register_session(sock):
    payload = struct.pack(
        "<HH",
        1,
        0,
    )

    command, session, _ = send_enip(
        sock,
        CMD_REGISTER_SESSION,
        payload,
    )

    if command != CMD_REGISTER_SESSION:
        raise RuntimeError(
            "Unexpected RegisterSession response"
        )

    return session


def unregister_session(sock, session):
    try:
        sock.sendall(
            enip_header(
                CMD_UNREGISTER_SESSION,
                0,
                session,
            )
        )
    except Exception:
        pass


# ============================================================
# CPF
# ============================================================

def build_rr_data(cip_payload):
    cpf = bytearray()

    cpf += struct.pack(
        "<IH",
        0,
        0,
    )

    cpf += struct.pack(
        "<H",
        2,
    )

    cpf += struct.pack(
        "<HH",
        CPF_NULL_ADDRESS,
        0,
    )

    cpf += struct.pack(
        "<HH",
        CPF_UNCONNECTED_DATA,
        len(cip_payload),
    )

    cpf += cip_payload
    return bytes(cpf)


def parse_rr_data(body):
    offset = 6

    item_count = struct.unpack_from(
        "<H",
        body,
        offset,
    )[0]

    offset += 2

    for _ in range(item_count):
        item_type, item_length = struct.unpack_from(
            "<HH",
            body,
            offset,
        )

        offset += 4

        item_data = body[
            offset:
            offset + item_length
        ]

        offset += item_length

        if item_type in (
            CPF_UNCONNECTED_DATA,
            CPF_CONNECTED_DATA,
        ):
            return item_data

    raise RuntimeError(
        "No CIP response item found"
    )


# ============================================================
# Class 1 Forward Open / Close
# ============================================================

def make_connection_parameters(
    data_size,
    overhead,
    point_to_point=True,
):
    size = data_size + overhead
    connection_type = 2 if point_to_point else 1
    priority = 2

    return (
        size
        | (priority << 10)
        | (connection_type << 13)
    )


class ConnectionIdentity:
    def __init__(self):
        self.o_to_t_connection_id = random.randint(
            0x10000000,
            0x7FFFFFFF,
        )

        self.t_to_o_connection_id = random.randint(
            0x10000000,
            0x7FFFFFFF,
        )

        self.connection_serial = random.randint(
            1,
            0xFFFF,
        )

        self.originator_vendor_id = 0x00FF

        self.originator_serial = random.randint(
            1,
            0xFFFFFFFF,
        )


def build_connection_path():
    return bytes([
        0x20, ASSEMBLY_CLASS,
        0x24, CONFIG_ASSEMBLY,
        0x2C, OUTPUT_ASSEMBLY,
        0x2C, INPUT_ASSEMBLY,
    ])


def forward_open(
    sock,
    session,
    identity,
    rpi_ms,
):
    rpi_us = int(
        rpi_ms * 1000
    )

    path = build_connection_path()

    o_to_t = make_connection_parameters(
        OUTPUT_DATA_SIZE,
        6,
        True,
    )

    t_to_o = make_connection_parameters(
        INPUT_DATA_SIZE,
        2,
        True,
    )

    cip = bytearray([
        CIP_FORWARD_OPEN,
        0x02,
        0x20, CONNECTION_MANAGER_CLASS,
        0x24, CONNECTION_MANAGER_INSTANCE,
        0x03,
        0xFA,
    ])

    cip += struct.pack(
        "<II",
        identity.o_to_t_connection_id,
        identity.t_to_o_connection_id,
    )

    cip += struct.pack(
        "<HHI",
        identity.connection_serial,
        identity.originator_vendor_id,
        identity.originator_serial,
    )

    cip += bytes([
        3,
        0,
        0,
        0,
    ])

    cip += struct.pack(
        "<IH",
        rpi_us,
        o_to_t,
    )

    cip += struct.pack(
        "<IH",
        rpi_us,
        t_to_o,
    )

    cip += bytes([
        0x81,
        len(path) // 2,
    ])

    cip += path

    _, _, body = send_enip(
        sock,
        CMD_SEND_RR_DATA,
        build_rr_data(bytes(cip)),
        session,
    )

    response = parse_rr_data(
        body
    )

    general_status = response[2]
    additional_words = response[3]
    offset = 4

    additional = []

    for _ in range(additional_words):
        additional.append(
            struct.unpack_from(
                "<H",
                response,
                offset,
            )[0]
        )

        offset += 2

    if general_status != 0:
        raise RuntimeError(
            "Forward Open failed: "
            f"status 0x{general_status:02X}, extended "
            f"{', '.join(hex(v) for v in additional)}"
        )

    (
        identity.o_to_t_connection_id,
        identity.t_to_o_connection_id,
    ) = struct.unpack_from(
        "<II",
        response,
        offset,
    )


def forward_close(
    sock,
    session,
    identity,
):
    path = build_connection_path()

    cip = bytearray([
        CIP_FORWARD_CLOSE,
        0x02,
        0x20, CONNECTION_MANAGER_CLASS,
        0x24, CONNECTION_MANAGER_INSTANCE,
        0x03,
        0xFA,
    ])

    cip += struct.pack(
        "<HHI",
        identity.connection_serial,
        identity.originator_vendor_id,
        identity.originator_serial,
    )

    cip += bytes([
        len(path) // 2,
        0,
    ])

    cip += path

    try:
        send_enip(
            sock,
            CMD_SEND_RR_DATA,
            build_rr_data(bytes(cip)),
            session,
        )
    except Exception:
        pass


# ============================================================
# UDP Class 1
# ============================================================

def build_o_to_t_packet(
    connection_id,
    packet_sequence,
    transport_sequence,
    output_data,
):
    connected = bytearray()

    connected += struct.pack(
        "<H",
        transport_sequence & 0xFFFF,
    )

    # 32-bit Run/Idle header; bit 0 = Run
    connected += struct.pack(
        "<I",
        1,
    )

    connected += output_data

    packet = bytearray()

    packet += struct.pack(
        "<H",
        2,
    )

    packet += struct.pack(
        "<HHII",
        CPF_SEQUENCED_ADDRESS,
        8,
        connection_id,
        packet_sequence,
    )

    packet += struct.pack(
        "<HH",
        CPF_CONNECTED_DATA,
        len(connected),
    )

    packet += connected

    return bytes(packet)


def parse_t_to_o_packet(packet):
    if len(packet) < 2:
        return None

    item_count = struct.unpack_from(
        "<H",
        packet,
        0,
    )[0]

    offset = 2
    connection_id = None
    connected = None

    for _ in range(item_count):
        if offset + 4 > len(packet):
            return None

        item_type, length = struct.unpack_from(
            "<HH",
            packet,
            offset,
        )

        offset += 4

        data = packet[
            offset:
            offset + length
        ]

        offset += length

        if (
            item_type == CPF_SEQUENCED_ADDRESS
            and len(data) >= 8
        ):
            connection_id = struct.unpack_from(
                "<I",
                data,
                0,
            )[0]

        elif item_type == CPF_CONNECTED_DATA:
            connected = data

    if (
        connection_id is None
        or connected is None
        or len(connected) < 2
    ):
        return None

    return (
        connection_id,
        connected[2:],
    )


# ============================================================
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
# GUI Widgets
# ============================================================

class BitIndicator(ttk.Frame):
    def __init__(
        self,
        parent,
        text,
    ):
        super().__init__(
            parent
        )

        self.canvas = tk.Canvas(
            self,
            width=20,
            height=20,
            highlightthickness=0,
        )

        self.canvas.pack(
            side=tk.LEFT,
            padx=(0, 7),
        )

        self.led = (
            self.canvas.create_oval(
                3,
                3,
                17,
                17,
                fill="#707070",
            )
        )

        ttk.Label(
            self,
            text=text,
        ).pack(
            side=tk.LEFT
        )

    def set(
        self,
        value,
    ):
        self.canvas.itemconfigure(
            self.led,
            fill=(
                "#22C55E"
                if value
                else "#707070"
            ),
        )


class ScrollableFrame(ttk.Frame):
    def __init__(
        self,
        parent,
    ):
        super().__init__(
            parent
        )

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
        )

        scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )

        self.content = ttk.Frame(
            self.canvas
        )

        self.window_id = (
            self.canvas.create_window(
                (0, 0),
                window=self.content,
                anchor="nw",
            )
        )

        self.canvas.configure(
            yscrollcommand=(
                scrollbar.set
            )
        )

        self.canvas.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
        )

        scrollbar.pack(
            side=tk.RIGHT,
            fill=tk.Y,
        )

        self.content.bind(
            "<Configure>",
            lambda _e:
                self.canvas.configure(
                    scrollregion=
                    self.canvas.bbox(
                        "all"
                    )
                ),
        )

        self.canvas.bind(
            "<Configure>",
            lambda e:
                self.canvas.itemconfigure(
                    self.window_id,
                    width=e.width,
                ),
        )

        self.canvas.bind(
            "<MouseWheel>",
            lambda e:
                self.canvas.yview_scroll(
                    int(
                        -e.delta / 120
                    ),
                    "units",
                ),
        )


# ============================================================
# Data Layout Editor
# ============================================================

class LayoutEditor(ttk.LabelFrame):
    def __init__(
        self,
        parent,
        title,
        layout,
        on_change,
    ):
        super().__init__(
            parent,
            text=title,
            padding=10,
        )

        self.layout = layout
        self.on_change = on_change

        self.tree = ttk.Treeview(
            self,
            columns=(
                "type",
                "offset",
                "size",
            ),
            show="tree headings",
            height=12,
        )

        self.tree.heading(
            "#0",
            text="Name",
        )

        self.tree.heading(
            "type",
            text="Type",
        )

        self.tree.heading(
            "offset",
            text="Offset",
        )

        self.tree.heading(
            "size",
            text="Bytes",
        )

        self.tree.column(
            "#0",
            width=190,
            stretch=True,
        )

        self.tree.column(
            "type",
            width=70,
            anchor="center",
        )

        self.tree.column(
            "offset",
            width=70,
            anchor="center",
        )

        self.tree.column(
            "size",
            width=60,
            anchor="center",
        )

        self.tree.pack(
            fill=tk.BOTH,
            expand=True,
        )

        controls = ttk.Frame(
            self
        )

        controls.pack(
            fill=tk.X,
            pady=(8, 0),
        )

        self.name_var = (
            tk.StringVar(
                value="Value1"
            )
        )

        self.type_var = (
            tk.StringVar(
                value="REAL"
            )
        )

        ttk.Entry(
            controls,
            textvariable=self.name_var,
            width=18,
        ).pack(
            side=tk.LEFT,
            padx=(0, 5),
        )

        ttk.Combobox(
            controls,
            textvariable=self.type_var,
            values=list(
                DATA_TYPES
            ),
            state="readonly",
            width=7,
        ).pack(
            side=tk.LEFT,
            padx=(0, 5),
        )

        ttk.Button(
            controls,
            text="Add",
            command=self._add,
        ).pack(
            side=tk.LEFT,
            padx=2,
        )

        ttk.Button(
            controls,
            text="Remove",
            command=self._remove,
        ).pack(
            side=tk.LEFT,
            padx=2,
        )

        ttk.Button(
            controls,
            text="↑",
            width=3,
            command=lambda:
                self._move(-1),
        ).pack(
            side=tk.LEFT,
            padx=2,
        )

        ttk.Button(
            controls,
            text="↓",
            width=3,
            command=lambda:
                self._move(1),
        ).pack(
            side=tk.LEFT,
            padx=2,
        )

        self.usage_label = ttk.Label(
            self,
            text="",
        )

        self.usage_label.pack(
            anchor="w",
            pady=(8, 0),
        )

        self.refresh()

    def selected_index(self):
        selected = (
            self.tree.selection()
        )

        if not selected:
            return None

        children = list(
            self.tree.get_children()
        )

        return children.index(
            selected[0]
        )

    def refresh(
        self,
        select_index=None,
    ):
        for item in (
            self.tree.get_children()
        ):
            self.tree.delete(
                item
            )

        inserted = []

        for field in (
            self.layout.offsets()
        ):
            item = self.tree.insert(
                "",
                tk.END,
                text=field["name"],
                values=(
                    field["type"],
                    field["offset"],
                    field["size"],
                ),
            )

            inserted.append(
                item
            )

        if (
            select_index is not None
            and 0 <= select_index
            < len(inserted)
        ):
            self.tree.selection_set(
                inserted[
                    select_index
                ]
            )

            self.tree.focus(
                inserted[
                    select_index
                ]
            )

        self.usage_label.configure(
            text=(
                f"Used: "
                f"{self.layout.total_size()} / "
                f"{self.layout.max_size} bytes"
            )
        )

    def _add(self):
        try:
            self.layout.add(
                self.name_var.get(),
                self.type_var.get(),
            )

        except Exception as exc:
            messagebox.showerror(
                "Layout",
                str(exc),
            )
            return

        self.name_var.set(
            f"Value"
            f"{len(self.layout.fields) + 1}"
        )

        self.refresh(
            len(self.layout.fields) - 1
        )

        self.on_change()

    def _remove(self):
        index = (
            self.selected_index()
        )

        if index is None:
            return

        self.layout.remove(
            index
        )

        self.refresh()
        self.on_change()

    def _move(
        self,
        delta,
    ):
        index = (
            self.selected_index()
        )

        if index is None:
            return

        new_index = (
            self.layout.move(
                index,
                delta,
            )
        )

        self.refresh(
            new_index
        )

        self.on_change()


# ============================================================
# Main GUI
# ============================================================

class CognexGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(
            "Cognex EtherNet/IP Monitor & Control"
        )

        self.geometry(
            "1350x850"
        )

        self.minsize(
            1000,
            650,
        )

        self.connection = (
            CognexConnection()
        )

        self.input_layout = (
            DataLayout(
                INPUT_RESULTS_SIZE
            )
        )

        self.output_layout = (
            DataLayout(
                OUTPUT_USER_SIZE
            )
        )

        self.input_indicators = {}
        self.output_vars = {}
        self.numeric_labels = {}

        self.input_value_labels = {}
        self.output_value_vars = {}

        self.last_hex_update = 0
        self.last_error = None

        self._build_gui()

        self.after(
            GUI_REFRESH_MS,
            self._refresh,
        )

        self.protocol(
            "WM_DELETE_WINDOW",
            self._close,
        )

    # ========================================================
    # Build GUI
    # ========================================================

    def _build_gui(self):
        self._build_connection_bar()

        self.notebook = ttk.Notebook(
            self
        )

        self.notebook.pack(
            fill=tk.BOTH,
            expand=True,
            padx=10,
            pady=5,
        )

        self.live_tab = ttk.Frame(
            self.notebook
        )

        self.layout_tab = ttk.Frame(
            self.notebook
        )

        self.raw_tab = ttk.Frame(
            self.notebook
        )

        self.notebook.add(
            self.live_tab,
            text="Live I/O",
        )

        self.notebook.add(
            self.layout_tab,
            text="Data Layout",
        )

        self.notebook.add(
            self.raw_tab,
            text="Raw I/O",
        )

        self._build_live_tab()
        self._build_layout_tab()
        self._build_raw_tab()
        self._build_bottom_bar()

    # ========================================================
    # Connection Bar
    # ========================================================

    def _build_connection_bar(self):
        frame = ttk.Frame(
            self,
            padding=10,
        )

        frame.pack(
            fill=tk.X
        )

        ttk.Label(
            frame,
            text="Camera IP:",
        ).pack(
            side=tk.LEFT
        )

        self.ip_var = (
            tk.StringVar(
                value=DEFAULT_CAMERA_IP
            )
        )

        self.ip_entry = ttk.Entry(
            frame,
            textvariable=self.ip_var,
            width=18,
        )

        self.ip_entry.pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Label(
            frame,
            text="RPI:",
        ).pack(
            side=tk.LEFT,
            padx=(15, 0),
        )

        self.rpi_var = (
            tk.StringVar(
                value=str(
                    DEFAULT_RPI_MS
                )
            )
        )

        self.rpi_entry = ttk.Entry(
            frame,
            textvariable=self.rpi_var,
            width=7,
        )

        self.rpi_entry.pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Label(
            frame,
            text="ms",
        ).pack(
            side=tk.LEFT
        )

        self.connect_button = (
            ttk.Button(
                frame,
                text="Connect",
                command=self._connect,
            )
        )

        self.connect_button.pack(
            side=tk.LEFT,
            padx=(20, 5),
        )

        self.disconnect_button = (
            ttk.Button(
                frame,
                text="Disconnect",
                command=self._disconnect,
                state=tk.DISABLED,
            )
        )

        self.disconnect_button.pack(
            side=tk.LEFT
        )

        self.connection_label = (
            ttk.Label(
                frame,
                text="Disconnected",
                font=(
                    "Segoe UI",
                    10,
                    "bold",
                ),
            )
        )

        self.connection_label.pack(
            side=tk.LEFT,
            padx=20,
        )

    # ========================================================
    # Live I/O
    # ========================================================

    def _build_live_tab(self):
        scroll = ScrollableFrame(
            self.live_tab
        )

        scroll.pack(
            fill=tk.BOTH,
            expand=True,
        )

        self.live_container = (
            scroll.content
        )

        self.live_container.columnconfigure(
            0,
            weight=1,
        )

        self.live_container.columnconfigure(
            1,
            weight=1,
        )

        # ----------------------------------------------------
        # Input status
        # ----------------------------------------------------

        input_frame = ttk.LabelFrame(
            self.live_container,
            text=(
                "Camera → PC | "
                "Input Assembly 13"
            ),
            padding=10,
        )

        input_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(10, 5),
            pady=(10, 5),
        )

        row = 0

        for (
            byte,
            bit,
            name,
        ) in INPUT_BITS:
            indicator = BitIndicator(
                input_frame,
                name,
            )

            indicator.grid(
                row=row,
                column=0,
                sticky="w",
                pady=2,
            )

            ttk.Label(
                input_frame,
                text=f"B{byte}.{bit}",
                foreground="#707070",
            ).grid(
                row=row,
                column=1,
                sticky="e",
                padx=(15, 0),
            )

            self.input_indicators[
                (byte, bit)
            ] = indicator

            row += 1

        ttk.Separator(
            input_frame
        ).grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=8,
        )

        row += 1

        ttk.Label(
            input_frame,
            text="Offline Reason",
        ).grid(
            row=row,
            column=0,
            sticky="w",
        )

        self.offline_label = (
            ttk.Label(
                input_frame,
                text="0 (0b000)",
                font=(
                    "Consolas",
                    10,
                    "bold",
                ),
            )
        )

        self.offline_label.grid(
            row=row,
            column=1,
            sticky="e",
        )

        row += 1

        ttk.Separator(
            input_frame
        ).grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=8,
        )

        row += 1

        for (
            name,
            offset,
        ) in NUMERIC_FIELDS:
            ttk.Label(
                input_frame,
                text=name,
            ).grid(
                row=row,
                column=0,
                sticky="w",
                pady=2,
            )

            label = ttk.Label(
                input_frame,
                text="0",
                font=("Consolas", 10),
            )

            label.grid(
                row=row,
                column=1,
                sticky="e",
            )

            self.numeric_labels[
                offset
            ] = label

            row += 1

        # ----------------------------------------------------
        # Output controls
        # ----------------------------------------------------

        output_frame = ttk.LabelFrame(
            self.live_container,
            text=(
                "PC → Camera | "
                "Output Assembly 22"
            ),
            padding=10,
        )

        output_frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(5, 10),
            pady=(10, 5),
        )

        ttk.Label(
            output_frame,
            text="Signal",
            font=(
                "Segoe UI",
                9,
                "bold",
            ),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            output_frame,
            text="Level",
            font=(
                "Segoe UI",
                9,
                "bold",
            ),
        ).grid(
            row=0,
            column=1,
        )

        ttk.Label(
            output_frame,
            text="Pulse",
            font=(
                "Segoe UI",
                9,
                "bold",
            ),
        ).grid(
            row=0,
            column=2,
        )

        for row, (
            byte,
            bit,
            name,
        ) in enumerate(
            OUTPUT_BITS,
            start=1,
        ):
            ttk.Label(
                output_frame,
                text=name,
            ).grid(
                row=row,
                column=0,
                sticky="w",
                pady=2,
            )

            var = tk.BooleanVar(
                value=False
            )

            ttk.Checkbutton(
                output_frame,
                variable=var,
                command=(
                    lambda b=byte,
                    n=bit,
                    v=var:
                    self.connection
                    .set_output_bit(
                        b,
                        n,
                        v.get(),
                    )
                ),
            ).grid(
                row=row,
                column=1,
                padx=12,
            )

            ttk.Button(
                output_frame,
                text="100 ms",
                command=(
                    lambda b=byte,
                    n=bit:
                    self.connection
                    .pulse_output_bit(
                        b,
                        n,
                        0.1,
                    )
                ),
            ).grid(
                row=row,
                column=2,
                padx=5,
            )

            self.output_vars[
                (byte, bit)
            ] = var

        row = (
            len(OUTPUT_BITS)
            + 2
        )

        ttk.Separator(
            output_frame
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=8,
        )

        row += 1

        ttk.Label(
            output_frame,
            text="Command ID",
        ).grid(
            row=row,
            column=0,
            sticky="w",
        )

        self.command_id_var = (
            tk.StringVar(
                value="0"
            )
        )

        ttk.Entry(
            output_frame,
            textvariable=
                self.command_id_var,
            width=12,
        ).grid(
            row=row,
            column=1,
            padx=5,
        )

        ttk.Button(
            output_frame,
            text="Apply",
            command=
                self._apply_command_id,
        ).grid(
            row=row,
            column=2,
            padx=5,
        )

        row += 1

        ttk.Button(
            output_frame,
            text="CLEAR ALL OUTPUTS",
            command=
                self._clear_outputs,
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(10, 0),
        )

        # ----------------------------------------------------
        # Formatted inspection results
        # ----------------------------------------------------

        self.formatted_input_frame = (
            ttk.LabelFrame(
                self.live_container,
                text=(
                    "Formatted Inspection Results "
                    "(Input byte 16+)"
                ),
                padding=10,
            )
        )

        self.formatted_input_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=(10, 5),
            pady=(5, 10),
        )

        # ----------------------------------------------------
        # Formatted output User Data
        # ----------------------------------------------------

        self.formatted_output_frame = (
            ttk.LabelFrame(
                self.live_container,
                text=(
                    "Formatted User Data "
                    "(Output byte 8+)"
                ),
                padding=10,
            )
        )

        self.formatted_output_frame.grid(
            row=1,
            column=1,
            sticky="nsew",
            padx=(5, 10),
            pady=(5, 10),
        )

        self._rebuild_formatted_panels()

    # ========================================================
    # Data Layout
    # ========================================================

    def _build_layout_tab(self):
        container = ttk.Frame(
            self.layout_tab,
            padding=10,
        )

        container.pack(
            fill=tk.BOTH,
            expand=True,
        )

        container.columnconfigure(
            0,
            weight=1,
        )

        container.columnconfigure(
            1,
            weight=1,
        )

        container.rowconfigure(
            0,
            weight=1,
        )

        self.input_editor = (
            LayoutEditor(
                container,
                (
                    "Inspection Results Layout "
                    f"({INPUT_RESULTS_SIZE} "
                    "bytes available)"
                ),
                self.input_layout,
                self._layout_changed,
            )
        )

        self.input_editor.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 5),
        )

        self.output_editor = (
            LayoutEditor(
                container,
                (
                    "User Data Layout "
                    f"({OUTPUT_USER_SIZE} "
                    "bytes available)"
                ),
                self.output_layout,
                self._layout_changed,
            )
        )

        self.output_editor.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(5, 0),
        )

        bottom = ttk.Frame(
            container
        )

        bottom.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Button(
            bottom,
            text="Save Layout...",
            command=self._save_layout,
        ).pack(
            side=tk.LEFT
        )

        ttk.Button(
            bottom,
            text="Load Layout...",
            command=self._load_layout,
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Label(
            bottom,
            text=(
                "Fields are packed sequentially; "
                "moving a field recalculates every "
                "following byte offset."
            ),
        ).pack(
            side=tk.LEFT,
            padx=15,
        )

    # ========================================================
    # Raw I/O
    # ========================================================

    def _make_text_with_scrollbars(
        self,
        parent,
    ):
        frame = ttk.Frame(
            parent
        )

        frame.pack(
            fill=tk.BOTH,
            expand=True,
        )

        text = tk.Text(
            frame,
            font=("Consolas", 10),
            wrap="none",
        )

        ybar = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=text.yview,
        )

        xbar = ttk.Scrollbar(
            frame,
            orient="horizontal",
            command=text.xview,
        )

        text.configure(
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )

        text.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        ybar.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        xbar.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        frame.rowconfigure(
            0,
            weight=1,
        )

        frame.columnconfigure(
            0,
            weight=1,
        )

        return text

    def _build_raw_tab(self):
        pane = ttk.Panedwindow(
            self.raw_tab,
            orient=tk.VERTICAL,
        )

        pane.pack(
            fill=tk.BOTH,
            expand=True,
            padx=10,
            pady=10,
        )

        input_frame = ttk.LabelFrame(
            pane,
            text="Input Assembly 13",
        )

        output_frame = ttk.LabelFrame(
            pane,
            text="Output Assembly 22",
        )

        pane.add(
            input_frame,
            weight=1,
        )

        pane.add(
            output_frame,
            weight=1,
        )

        self.raw_input_text = (
            self._make_text_with_scrollbars(
                input_frame
            )
        )

        self.raw_output_text = (
            self._make_text_with_scrollbars(
                output_frame
            )
        )

    # ========================================================
    # Bottom Bar
    # ========================================================

    def _build_bottom_bar(self):
        frame = ttk.Frame(
            self,
            padding=8,
        )

        frame.pack(
            fill=tk.X
        )

        self.packet_label = ttk.Label(
            frame,
            text="Packets: 0",
        )

        self.rate_label = ttk.Label(
            frame,
            text="Rate: 0 Hz",
        )

        self.age_label = ttk.Label(
            frame,
            text="Last Packet: --",
        )

        self.packet_label.pack(
            side=tk.LEFT
        )

        self.rate_label.pack(
            side=tk.LEFT,
            padx=20,
        )

        self.age_label.pack(
            side=tk.LEFT
        )

    # ========================================================
    # Dynamic Formatted Panels
    # ========================================================

    def _clear_children(
        self,
        widget,
    ):
        for child in (
            widget.winfo_children()
        ):
            child.destroy()

    def _rebuild_formatted_panels(self):
        old_output_values = {
            name: var.get()
            for (
                name,
                var,
            ) in self.output_value_vars.items()
        }

        # ----------------------------------------------------
        # Input inspection results
        # ----------------------------------------------------

        self._clear_children(
            self.formatted_input_frame
        )

        self.input_value_labels = {}

        input_fields = (
            self.input_layout.offsets()
        )

        if not input_fields:
            ttk.Label(
                self.formatted_input_frame,
                text=(
                    "No fields configured. "
                    "Add fields on the Data Layout tab."
                ),
            ).grid(
                row=0,
                column=0,
                sticky="w",
            )

        else:
            for column, heading in enumerate(
                (
                    "Name",
                    "Type",
                    "Offset",
                    "Value",
                )
            ):
                ttk.Label(
                    self.formatted_input_frame,
                    text=heading,
                    font=(
                        "Segoe UI",
                        9,
                        "bold",
                    ),
                ).grid(
                    row=0,
                    column=column,
                    sticky="w",
                    padx=(0, 12),
                )

            for row, field in enumerate(
                input_fields,
                start=1,
            ):
                ttk.Label(
                    self.formatted_input_frame,
                    text=field["name"],
                ).grid(
                    row=row,
                    column=0,
                    sticky="w",
                    pady=2,
                )

                ttk.Label(
                    self.formatted_input_frame,
                    text=field["type"],
                ).grid(
                    row=row,
                    column=1,
                    sticky="w",
                    padx=(0, 12),
                )

                ttk.Label(
                    self.formatted_input_frame,
                    text=str(
                        field["offset"]
                    ),
                ).grid(
                    row=row,
                    column=2,
                    sticky="w",
                    padx=(0, 12),
                )

                label = ttk.Label(
                    self.formatted_input_frame,
                    text="--",
                    font=(
                        "Consolas",
                        10,
                    ),
                )

                label.grid(
                    row=row,
                    column=3,
                    sticky="e",
                )

                self.input_value_labels[
                    field["name"]
                ] = label

        # ----------------------------------------------------
        # Output User Data
        # ----------------------------------------------------

        self._clear_children(
            self.formatted_output_frame
        )

        self.output_value_vars = {}

        output_fields = (
            self.output_layout.offsets()
        )

        if not output_fields:
            ttk.Label(
                self.formatted_output_frame,
                text=(
                    "No fields configured. "
                    "Add fields on the Data Layout tab."
                ),
            ).grid(
                row=0,
                column=0,
                sticky="w",
            )

        else:
            for column, heading in enumerate(
                (
                    "Name",
                    "Type",
                    "Offset",
                    "Value",
                )
            ):
                ttk.Label(
                    self.formatted_output_frame,
                    text=heading,
                    font=(
                        "Segoe UI",
                        9,
                        "bold",
                    ),
                ).grid(
                    row=0,
                    column=column,
                    sticky="w",
                    padx=(0, 12),
                )

            for row, field in enumerate(
                output_fields,
                start=1,
            ):
                ttk.Label(
                    self.formatted_output_frame,
                    text=field["name"],
                ).grid(
                    row=row,
                    column=0,
                    sticky="w",
                    pady=2,
                )

                ttk.Label(
                    self.formatted_output_frame,
                    text=field["type"],
                ).grid(
                    row=row,
                    column=1,
                    sticky="w",
                    padx=(0, 12),
                )

                ttk.Label(
                    self.formatted_output_frame,
                    text=str(
                        field["offset"]
                    ),
                ).grid(
                    row=row,
                    column=2,
                    sticky="w",
                    padx=(0, 12),
                )

                var = tk.StringVar(
                    value=old_output_values.get(
                        field["name"],
                        "0",
                    )
                )

                ttk.Entry(
                    self.formatted_output_frame,
                    textvariable=var,
                    width=16,
                ).grid(
                    row=row,
                    column=3,
                    sticky="ew",
                )

                self.output_value_vars[
                    field["name"]
                ] = var

            last_row = (
                len(output_fields)
                + 1
            )

            ttk.Button(
                self.formatted_output_frame,
                text="Apply User Data",
                command=
                    self._apply_formatted_user_data,
            ).grid(
                row=last_row,
                column=0,
                columnspan=2,
                sticky="ew",
                pady=(10, 0),
            )

            ttk.Button(
                self.formatted_output_frame,
                text=(
                    "Apply + Pulse "
                    "Set User Data"
                ),
                command=
                    self._apply_formatted_user_data_and_pulse,
            ).grid(
                row=last_row,
                column=2,
                columnspan=2,
                sticky="ew",
                padx=(5, 0),
                pady=(10, 0),
            )

    # ========================================================
    # Layout Handling
    # ========================================================

    def _layout_changed(self):
        self._rebuild_formatted_panels()

    def _save_layout(self):
        path = (
            filedialog.asksaveasfilename(
                title="Save Data Layout",
                defaultextension=".json",
                filetypes=[
                    (
                        "JSON files",
                        "*.json",
                    ),
                    (
                        "All files",
                        "*.*",
                    ),
                ],
            )
        )

        if not path:
            return

        data = {
            "inspection_results":
                self.input_layout
                .copy_fields(),

            "user_data":
                self.output_layout
                .copy_fields(),
        }

        with open(
            path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                indent=2,
            )

    def _load_layout(self):
        path = (
            filedialog.askopenfilename(
                title="Load Data Layout",
                filetypes=[
                    (
                        "JSON files",
                        "*.json",
                    ),
                    (
                        "All files",
                        "*.*",
                    ),
                ],
            )
        )

        if not path:
            return

        try:
            with open(
                path,
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(
                    file
                )

            new_input = DataLayout(
                INPUT_RESULTS_SIZE,
                data.get(
                    "inspection_results",
                    [],
                ),
            )

            new_output = DataLayout(
                OUTPUT_USER_SIZE,
                data.get(
                    "user_data",
                    [],
                ),
            )

            self.input_layout = (
                new_input
            )

            self.output_layout = (
                new_output
            )

            self.input_editor.layout = (
                self.input_layout
            )

            self.output_editor.layout = (
                self.output_layout
            )

            self.input_editor.refresh()
            self.output_editor.refresh()

            self._rebuild_formatted_panels()

        except Exception as exc:
            messagebox.showerror(
                "Load Layout",
                str(exc),
            )

    # ========================================================
    # Commands
    # ========================================================

    def _connect(self):
        try:
            rpi = float(
                self.rpi_var.get()
            )

            if rpi <= 0:
                raise ValueError

        except ValueError:
            messagebox.showerror(
                "RPI",
                "RPI must be a positive number.",
            )
            return

        camera_ip = (
            self.ip_var
            .get()
            .strip()
        )

        if not camera_ip:
            messagebox.showerror(
                "Camera IP",
                "Enter the camera IP address.",
            )
            return

        self.connection.start(
            camera_ip,
            rpi,
        )

        self.connect_button.configure(
            state=tk.DISABLED
        )

        self.disconnect_button.configure(
            state=tk.NORMAL
        )

    def _disconnect(self):
        self.connection.stop()

    def _apply_command_id(self):
        try:
            value = int(
                self.command_id_var.get(),
                0,
            )

            self.connection.set_command_id(
                value
            )

        except Exception as exc:
            messagebox.showerror(
                "Command ID",
                str(exc),
            )

    def _clear_outputs(self):
        self.connection.clear_outputs()

        for var in (
            self.output_vars.values()
        ):
            var.set(
                False
            )

        self.command_id_var.set(
            "0"
        )

        for var in (
            self.output_value_vars.values()
        ):
            var.set(
                "0"
            )

    def _apply_formatted_user_data(self):
        try:
            values = {
                name: var.get()
                for (
                    name,
                    var,
                ) in self.output_value_vars.items()
            }

            encoded = (
                self.output_layout
                .encode(
                    values
                )
            )

            self.connection.set_user_data(
                encoded[
                    :self.output_layout
                    .total_size()
                ]
            )

        except Exception as exc:
            messagebox.showerror(
                "User Data",
                str(exc),
            )
            return False

        return True

    def _apply_formatted_user_data_and_pulse(self):
        if (
            self._apply_formatted_user_data()
        ):
            self.connection.pulse_output_bit(
                2,
                0,
                0.1,
            )

    # ========================================================
    # Refresh
    # ========================================================

    def _refresh(self):
        snap = (
            self.connection.snapshot()
        )

        state = snap["state"]
        age = snap["packet_age"]

        if (
            state == "I/O Running"
            and age is not None
            and age
            > IO_TIMEOUT_SECONDS
        ):
            state_text = (
                "I/O TIMEOUT"
            )

        else:
            state_text = state

        self.connection_label.configure(
            text=state_text
        )

        self.packet_label.configure(
            text=(
                f"Packets: "
                f"{snap['packet_count']:,}"
            )
        )

        self.rate_label.configure(
            text=(
                f"Rate: "
                f"{snap['packet_rate']} Hz"
            )
        )

        if age is None:
            self.age_label.configure(
                text=(
                    "Last Packet: --"
                )
            )

        else:
            self.age_label.configure(
                text=(
                    f"Last Packet: "
                    f"{age * 1000:.1f} ms"
                )
            )

        data = snap["input"]

        # ----------------------------------------------------
        # Input status + standard fields
        # ----------------------------------------------------

        if data:
            for (
                byte,
                bit,
                _name,
            ) in INPUT_BITS:
                self.input_indicators[
                    (byte, bit)
                ].set(
                    get_bit(
                        data,
                        byte,
                        bit,
                    )
                )

            offline = get_bits(
                data,
                0,
                4,
                3,
            )

            self.offline_label.configure(
                text=(
                    f"{offline} "
                    f"(0b{offline:03b})"
                )
            )

            for (
                _name,
                offset,
            ) in NUMERIC_FIELDS:
                self.numeric_labels[
                    offset
                ].configure(
                    text=str(
                        uint16_le(
                            data,
                            offset,
                        )
                    )
                )

            # -----------------------------------------------
            # Configured Inspection Results
            # -----------------------------------------------

            result_buffer = data[
                INPUT_RESULTS_OFFSET:
                INPUT_RESULTS_OFFSET
                + INPUT_RESULTS_SIZE
            ]

            for (
                field,
                value,
            ) in self.input_layout.decode(
                result_buffer
            ):
                label = (
                    self.input_value_labels
                    .get(
                        field["name"]
                    )
                )

                if label is not None:
                    label.configure(
                        text=(
                            "--"
                            if value is None
                            else
                            format_display_value(
                                value,
                                field["type"],
                            )
                        )
                    )

        # ----------------------------------------------------
        # Output level controls
        # ----------------------------------------------------

        output = snap["output"]

        for (
            byte,
            bit,
            _name,
        ) in OUTPUT_BITS:
            self.output_vars[
                (byte, bit)
            ].set(
                get_bit(
                    output,
                    byte,
                    bit,
                )
            )

        # ----------------------------------------------------
        # Raw I/O at slower rate
        # ----------------------------------------------------

        now = (
            time.monotonic()
        )

        if (
            now
            - self.last_hex_update
            >= HEX_REFRESH_MS / 1000
        ):
            self.last_hex_update = (
                now
            )

            if data:
                self.raw_input_text.delete(
                    "1.0",
                    tk.END,
                )

                self.raw_input_text.insert(
                    tk.END,
                    hex_dump(
                        data
                    ),
                )

            self.raw_output_text.delete(
                "1.0",
                tk.END,
            )

            self.raw_output_text.insert(
                tk.END,
                hex_dump(
                    output
                ),
            )

        # ----------------------------------------------------
        # Errors / connection buttons
        # ----------------------------------------------------

        if (
            state == "Error"
            and snap["error"]
            and snap["error"]
            != self.last_error
        ):
            self.last_error = (
                snap["error"]
            )

            messagebox.showerror(
                "EtherNet/IP",
                snap["error"],
            )

        if state in (
            "Disconnected",
            "Error",
        ):
            self.connect_button.configure(
                state=tk.NORMAL
            )

            self.disconnect_button.configure(
                state=tk.DISABLED
            )

        self.after(
            GUI_REFRESH_MS,
            self._refresh,
        )

    # ========================================================
    # Close
    # ========================================================

    def _close(self):
        self.connection.stop()

        self.after(
            100,
            self.destroy,
        )


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    app = CognexGUI()
    app.mainloop()
