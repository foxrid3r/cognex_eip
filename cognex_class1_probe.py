import argparse
import random
import socket
import struct
import threading
import time


# ============================================================
# EtherNet/IP constants
# ============================================================

ENIP_PORT = 44818
IO_PORT = 2222

CMD_REGISTER_SESSION = 0x0065
CMD_UNREGISTER_SESSION = 0x0066
CMD_SEND_RR_DATA = 0x006F

CPF_NULL_ADDRESS = 0x0000
CPF_UNCONNECTED_DATA = 0x00B2
CPF_SEQUENCED_ADDRESS = 0x8002
CPF_CONNECTED_DATA = 0x00B1

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

DEFAULT_RPI_MS = 10.0


# ============================================================
# Small utilities
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
        0,              # status
        b"\x00" * 8,    # sender context
        0               # options
    )


def send_enip(sock, command, payload=b"", session=0):
    packet = enip_header(
        command,
        len(payload),
        session
    ) + payload

    sock.sendall(packet)

    header = recv_exact(sock, 24)

    (
        reply_command,
        reply_length,
        reply_session,
        reply_status,
        _context,
        _options
    ) = struct.unpack("<HHII8sI", header)

    body = recv_exact(sock, reply_length)

    if reply_status != 0:
        raise RuntimeError(
            f"EtherNet/IP encapsulation error: "
            f"0x{reply_status:08X}"
        )

    return reply_command, reply_session, body


# ============================================================
# Session handling
# ============================================================

def register_session(sock):
    payload = struct.pack(
        "<HH",
        1,      # protocol version
        0
    )

    command, session, _ = send_enip(
        sock,
        CMD_REGISTER_SESSION,
        payload,
        0
    )

    if command != CMD_REGISTER_SESSION:
        raise RuntimeError(
            f"Unexpected RegisterSession reply: "
            f"0x{command:04X}"
        )

    return session


def unregister_session(sock, session):
    packet = enip_header(
        CMD_UNREGISTER_SESSION,
        0,
        session
    )

    try:
        sock.sendall(packet)
    except Exception:
        pass


# ============================================================
# CPF
# ============================================================

def build_rr_data(cip_payload):
    """
    Build SendRRData payload:

        Interface Handle
        Timeout
        CPF:
            Null Address
            Unconnected Data
    """

    cpf = bytearray()

    # Interface handle + timeout
    cpf += struct.pack("<IH", 0, 0)

    # Number of CPF items
    cpf += struct.pack("<H", 2)

    # Null address item
    cpf += struct.pack(
        "<HH",
        CPF_NULL_ADDRESS,
        0
    )

    # Unconnected data item
    cpf += struct.pack(
        "<HH",
        CPF_UNCONNECTED_DATA,
        len(cip_payload)
    )

    cpf += cip_payload

    return bytes(cpf)


def parse_rr_data(body):
    """
    Extract CIP data from a SendRRData response.
    """

    if len(body) < 8:
        raise RuntimeError(
            "SendRRData response too short"
        )

    offset = 6

    item_count = struct.unpack_from(
        "<H",
        body,
        offset
    )[0]

    offset += 2

    for _ in range(item_count):

        if offset + 4 > len(body):
            break

        item_type, item_length = struct.unpack_from(
            "<HH",
            body,
            offset
        )

        offset += 4

        item_data = body[
            offset:
            offset + item_length
        ]

        offset += item_length

        if item_type in (
            CPF_UNCONNECTED_DATA,
            CPF_CONNECTED_DATA
        ):
            return item_data

    raise RuntimeError(
        "No CIP data item found in response"
    )


# ============================================================
# Network connection parameters
# ============================================================

def make_connection_parameters(
    pure_data_size,
    realtime_overhead,
    point_to_point=True
):
    """
    Standard Forward_Open uses a 16-bit Network Connection
    Parameters field.

    Bits:
      15      Redundant Owner
      14-13   Connection Type
      11-10   Priority
      9       Variable Size
      8-0     Connection Size
    """

    size = pure_data_size + realtime_overhead

    if size > 0x1FF:
        raise ValueError(
            f"Connection size {size} exceeds "
            "standard Forward_Open limit"
        )

    redundant_owner = 0
    variable_size = 0

    # 2 = point-to-point, 1 = multicast
    connection_type = (
        2 if point_to_point else 1
    )

    # 2 = Scheduled
    priority = 2

    value = (
        size
        | (variable_size << 9)
        | (priority << 10)
        | (connection_type << 13)
        | (redundant_owner << 15)
    )

    return value


# ============================================================
# Forward Open
# ============================================================

class ConnectionIdentity:

    def __init__(self):
        self.o_to_t_connection_id = random.randint(
            0x10000000,
            0x7FFFFFFF
        )

        self.t_to_o_connection_id = random.randint(
            0x10000000,
            0x7FFFFFFF
        )

        self.connection_serial = random.randint(
            1,
            0xFFFF
        )

        # Arbitrary originator identity.
        # This is not Cognex's vendor ID.
        self.originator_vendor_id = 0x00FF

        self.originator_serial = random.randint(
            1,
            0xFFFFFFFF
        )


def build_connection_path():
    """
    Application path:

        Class 4       Assembly Object
        Instance 1    Configuration Assembly
        Connection Point 22   O->T
        Connection Point 13   T->O

    20 04
    24 01
    2C 16
    2C 0D
    """

    return bytes([
        0x20, ASSEMBLY_CLASS,
        0x24, CONFIG_ASSEMBLY,
        0x2C, OUTPUT_ASSEMBLY,
        0x2C, INPUT_ASSEMBLY,
    ])


def forward_open(
    tcp_sock,
    session,
    identity,
    rpi_ms
):
    rpi_us = int(
        rpi_ms * 1000
    )

    path = build_connection_path()

    # --------------------------------------------------------
    # Real-time format overhead
    #
    # O->T:
    #   2-byte sequence count
    #   4-byte Run/Idle header
    #
    # T->O:
    #   2-byte sequence count
    #   Modeless payload
    # --------------------------------------------------------

    o_to_t_params = make_connection_parameters(
        OUTPUT_DATA_SIZE,
        realtime_overhead=6,
        point_to_point=True
    )

    t_to_o_params = make_connection_parameters(
        INPUT_DATA_SIZE,
        realtime_overhead=2,
        point_to_point=True
    )

    cip = bytearray()

    # Forward Open service
    cip += bytes([
        CIP_FORWARD_OPEN,

        # Request path size = 2 words
        0x02,

        # Connection Manager Class 6, Instance 1
        0x20, CONNECTION_MANAGER_CLASS,
        0x24, CONNECTION_MANAGER_INSTANCE,
    ])

    # Priority / tick time
    cip += bytes([
        0x03,
        0xFA
    ])

    # Requested connection IDs
    cip += struct.pack(
        "<II",
        identity.o_to_t_connection_id,
        identity.t_to_o_connection_id
    )

    # Connection identity triplet
    cip += struct.pack(
        "<HHI",
        identity.connection_serial,
        identity.originator_vendor_id,
        identity.originator_serial
    )

    # Connection timeout multiplier + reserved
    cip += bytes([
        3,
        0,
        0,
        0
    ])

    # O->T RPI and parameters
    cip += struct.pack(
        "<IH",
        rpi_us,
        o_to_t_params
    )

    # T->O RPI and parameters
    cip += struct.pack(
        "<IH",
        rpi_us,
        t_to_o_params
    )

    # --------------------------------------------------------
    # Transport Type / Trigger
    #
    # 0x81:
    #   Server direction
    #   Cyclic production
    #   Transport Class 1
    #
    # This is appropriate for the target-produced T->O I/O.
    # --------------------------------------------------------

    cip += bytes([
        0x81,
        len(path) // 2
    ])

    cip += path

    rr = build_rr_data(
        bytes(cip)
    )

    _, _, response_body = send_enip(
        tcp_sock,
        CMD_SEND_RR_DATA,
        rr,
        session
    )

    response = parse_rr_data(
        response_body
    )

    if len(response) < 4:
        raise RuntimeError(
            "Forward Open response too short"
        )

    reply_service = response[0]
    general_status = response[2]
    additional_status_words = response[3]

    offset = 4

    additional_status = []

    for _ in range(
        additional_status_words
    ):
        additional_status.append(
            struct.unpack_from(
                "<H",
                response,
                offset
            )[0]
        )

        offset += 2

    if general_status != 0:

        extra = ", ".join(
            f"0x{x:04X}"
            for x in additional_status
        )

        raise RuntimeError(
            "Forward Open failed\n"
            f"  General Status: 0x{general_status:02X}\n"
            f"  Extended Status: {extra or 'none'}"
        )

    # Successful Forward Open reply data begins after
    # CIP status fields.

    if len(response) < offset + 8:
        raise RuntimeError(
            "Forward Open success response missing "
            "connection IDs"
        )

    actual_o_to_t_id, actual_t_to_o_id = (
        struct.unpack_from(
            "<II",
            response,
            offset
        )
    )

    identity.o_to_t_connection_id = (
        actual_o_to_t_id
    )

    identity.t_to_o_connection_id = (
        actual_t_to_o_id
    )

    return response


# ============================================================
# Forward Close
# ============================================================

def forward_close(
    tcp_sock,
    session,
    identity
):
    path = build_connection_path()

    cip = bytearray([
        CIP_FORWARD_CLOSE,
        0x02,

        0x20,
        CONNECTION_MANAGER_CLASS,

        0x24,
        CONNECTION_MANAGER_INSTANCE,

        0x03,
        0xFA
    ])

    cip += struct.pack(
        "<HHI",
        identity.connection_serial,
        identity.originator_vendor_id,
        identity.originator_serial
    )

    cip += bytes([
        len(path) // 2,
        0
    ])

    cip += path

    rr = build_rr_data(
        bytes(cip)
    )

    try:
        send_enip(
            tcp_sock,
            CMD_SEND_RR_DATA,
            rr,
            session
        )
    except Exception:
        pass


# ============================================================
# Class 1 UDP
# ============================================================

def build_o_to_t_packet(
    connection_id,
    packet_sequence,
    transport_sequence,
    output_data
):
    """
    UDP Class 1 CPF packet.

    Item 1:
        Sequenced Address Item

    Item 2:
        Connected Data Item

    Output real-time payload:
        16-bit transport sequence
        32-bit Run/Idle header
        Output Assembly 22
    """

    connected_payload = bytearray()

    # 16-bit transport sequence
    connected_payload += struct.pack(
        "<H",
        transport_sequence & 0xFFFF
    )

    # 32-bit Run/Idle header:
    # bit 0 = Run
    connected_payload += struct.pack(
        "<I",
        1
    )

    connected_payload += output_data

    packet = bytearray()

    packet += struct.pack(
        "<H",
        2
    )

    packet += struct.pack(
        "<HHII",
        CPF_SEQUENCED_ADDRESS,
        8,
        connection_id,
        packet_sequence
    )

    packet += struct.pack(
        "<HH",
        CPF_CONNECTED_DATA,
        len(connected_payload)
    )

    packet += connected_payload

    return bytes(packet)


def parse_t_to_o_packet(packet):
    """
    Return:

        connection_id
        packet_sequence
        transport_sequence
        assembly_data
    """

    if len(packet) < 2:
        return None

    item_count = struct.unpack_from(
        "<H",
        packet,
        0
    )[0]

    offset = 2

    connection_id = None
    packet_sequence = None
    connected_data = None

    for _ in range(item_count):

        if offset + 4 > len(packet):
            break

        item_type, item_length = (
            struct.unpack_from(
                "<HH",
                packet,
                offset
            )
        )

        offset += 4

        item_data = packet[
            offset:
            offset + item_length
        ]

        offset += item_length

        if (
            item_type == CPF_SEQUENCED_ADDRESS
            and len(item_data) >= 8
        ):
            (
                connection_id,
                packet_sequence
            ) = struct.unpack_from(
                "<II",
                item_data,
                0
            )

        elif (
            item_type == CPF_CONNECTED_DATA
        ):
            connected_data = item_data

    if (
        connection_id is None
        or connected_data is None
        or len(connected_data) < 2
    ):
        return None

    transport_sequence = (
        struct.unpack_from(
            "<H",
            connected_data,
            0
        )[0]
    )

    # Cognex T->O is treated as modeless:
    # two-byte sequence then Assembly 13 data.
    assembly_data = connected_data[2:]

    return (
        connection_id,
        packet_sequence,
        transport_sequence,
        assembly_data
    )


# ============================================================
# Cognex decoder
# ============================================================

def bit(value, number):
    return bool(
        value & (1 << number)
    )


def decode_status(data):
    if len(data) < 4:
        return None

    b0 = data[0]
    b1 = data[1]
    b2 = data[2]
    b3 = data[3]

    return {
        "byte0": b0,
        "byte1": b1,
        "byte2": b2,
        "byte3": b3,

        "trigger_ready": bit(b0, 0),
        "trigger_ack": bit(b0, 1),
        "acq_error": bit(b0, 3),
        "offline_reason": (
            (b0 >> 4) & 0x07
        ),
        "online": bit(b0, 7),

        "inspection_completed": bit(b1, 1),
        "results_overrun": bit(b1, 2),
        "results_valid": bit(b1, 3),
        "command_executing": bit(b1, 4),
        "command_completed": bit(b1, 5),
        "command_failed": bit(b1, 6),
        "error": bit(b1, 7),

        "set_user_data_ack": bit(b2, 0),
        "exposure_complete": bit(b2, 4),
        "job_pass": bit(b2, 5),
        "system_validated": bit(b2, 6),
    }


# ============================================================
# Output sender thread
# ============================================================

class IOSender(threading.Thread):

    def __init__(
        self,
        udp_socket,
        camera_ip,
        connection_id,
        rpi_ms
    ):
        super().__init__(
            daemon=True
        )

        self.udp_socket = udp_socket
        self.camera_ip = camera_ip
        self.connection_id = connection_id

        self.period = (
            rpi_ms / 1000.0
        )

        self.running = True

        self.packet_sequence = 0
        self.transport_sequence = 0

        # IMPORTANT:
        # All Cognex output/control data remains zero.
        self.output_data = bytes(
            OUTPUT_DATA_SIZE
        )

    def run(self):

        next_time = time.perf_counter()

        while self.running:

            packet = build_o_to_t_packet(
                self.connection_id,
                self.packet_sequence,
                self.transport_sequence,
                self.output_data
            )

            try:
                self.udp_socket.sendto(
                    packet,
                    (
                        self.camera_ip,
                        IO_PORT
                    )
                )

            except OSError:
                break

            self.packet_sequence = (
                self.packet_sequence + 1
            ) & 0xFFFFFFFF

            self.transport_sequence = (
                self.transport_sequence + 1
            ) & 0xFFFF

            next_time += self.period

            delay = (
                next_time
                - time.perf_counter()
            )

            if delay > 0:
                time.sleep(delay)

            else:
                next_time = (
                    time.perf_counter()
                )

    def stop(self):
        self.running = False


# ============================================================
# Display
# ============================================================

def display_status(
    camera_ip,
    packet_count,
    packet_rate,
    packet_age_ms,
    data
):
    status = decode_status(
        data
    )

    if status is None:
        return

    print(
        "\033[2J\033[H",
        end=""
    )

    print("Cognex Class 1 EtherNet/IP Probe")
    print("=" * 64)

    print(
        f"Camera................... {camera_ip}"
    )

    print(
        f"Input Assembly........... {INPUT_ASSEMBLY}"
    )

    print(
        f"Output Assembly.......... {OUTPUT_ASSEMBLY}"
    )

    print(
        f"Payload bytes............ {len(data)}"
    )

    print(
        f"T→O packets.............. {packet_count:,}"
    )

    print(
        f"Packet rate.............. {packet_rate:6.1f} Hz"
    )

    print(
        f"Last packet.............. {packet_age_ms:6.1f} ms ago"
    )

    print()
    print("RAW STATUS")
    print("-" * 64)

    for n in range(4):
        value = status[
            f"byte{n}"
        ]

        print(
            f"Byte {n}:  "
            f"0x{value:02X}    "
            f"{value:08b}"
        )

    print()
    print("DECODED")
    print("-" * 64)

    print(
        f"Online................... "
        f"{status['online']}"
    )

    print(
        f"Offline Reason........... "
        f"{status['offline_reason']}"
    )

    print(
        f"Trigger Ready............ "
        f"{status['trigger_ready']}"
    )

    print(
        f"Trigger Ack.............. "
        f"{status['trigger_ack']}"
    )

    print(
        f"Acq Error................ "
        f"{status['acq_error']}"
    )

    print(
        f"Inspection Completed..... "
        f"{status['inspection_completed']}"
    )

    print(
        f"Results Valid............ "
        f"{status['results_valid']}"
    )

    print(
        f"Results Overrun.......... "
        f"{status['results_overrun']}"
    )

    print(
        f"Exposure Complete........ "
        f"{status['exposure_complete']}"
    )

    print(
        f"Job Pass................. "
        f"{status['job_pass']}"
    )

    print(
        f"System Validated......... "
        f"{status['system_validated']}"
    )

    print()
    print("Ctrl+C to stop.")


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Pure-Python Cognex EtherNet/IP "
            "Class 1 implicit-I/O probe"
        )
    )

    parser.add_argument(
        "ip",
        help="Cognex camera IP"
    )

    parser.add_argument(
        "--rpi",
        type=float,
        default=DEFAULT_RPI_MS,
        help=(
            "Requested Packet Interval "
            "in milliseconds (default 10)"
        )
    )

    args = parser.parse_args()

    camera_ip = args.ip
    rpi_ms = args.rpi

    identity = ConnectionIdentity()

    tcp_sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    tcp_sock.settimeout(
        5.0
    )

    udp_sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM
    )

    udp_sock.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    udp_sock.bind(
        ("0.0.0.0", IO_PORT)
    )

    udp_sock.settimeout(
        1.0
    )

    session = 0
    sender = None

    try:

        print(
            f"Connecting TCP/44818 to "
            f"{camera_ip}..."
        )

        tcp_sock.connect(
            (
                camera_ip,
                ENIP_PORT
            )
        )

        print(
            "Registering EtherNet/IP session..."
        )

        session = register_session(
            tcp_sock
        )

        print(
            f"Session: 0x{session:08X}"
        )

        print(
            "Opening Class 1 I/O connection..."
        )

        forward_open(
            tcp_sock,
            session,
            identity,
            rpi_ms
        )

        print(
            "Forward Open: OK"
        )

        print(
            f"O→T Connection ID: "
            f"0x{identity.o_to_t_connection_id:08X}"
        )

        print(
            f"T→O Connection ID: "
            f"0x{identity.t_to_o_connection_id:08X}"
        )

        # ----------------------------------------------------
        # Start sending zeroed Assembly 22 packets.
        # ----------------------------------------------------

        sender = IOSender(
            udp_sock,
            camera_ip,
            identity.o_to_t_connection_id,
            rpi_ms
        )

        sender.start()

        print(
            "Waiting for UDP/2222 input..."
        )

        packet_count = 0
        first_packet_time = None
        last_packet_time = None

        latest_data = None

        next_display = (
            time.monotonic()
        )

        while True:

            try:

                packet, source = (
                    udp_sock.recvfrom(
                        2048
                    )
                )

            except socket.timeout:

                now = time.monotonic()

                if (
                    last_packet_time is None
                ):
                    print(
                        "No T→O packet received yet..."
                    )

                elif (
                    now
                    - last_packet_time
                    > 1.0
                ):
                    print(
                        "I/O TIMEOUT: no packet "
                        "received for > 1 second"
                    )

                continue

            parsed = parse_t_to_o_packet(
                packet
            )

            if parsed is None:
                continue

            (
                connection_id,
                packet_sequence,
                transport_sequence,
                assembly
            ) = parsed

            # Ignore unrelated cyclic traffic.
            if (
                connection_id
                != identity.t_to_o_connection_id
            ):
                continue

            now = time.monotonic()

            packet_count += 1

            if first_packet_time is None:
                first_packet_time = now

            last_packet_time = now

            latest_data = assembly

            if now >= next_display:

                elapsed = (
                    now
                    - first_packet_time
                )

                packet_rate = (
                    packet_count / elapsed
                    if elapsed > 0
                    else 0
                )

                age_ms = (
                    now
                    - last_packet_time
                ) * 1000

                display_status(
                    camera_ip,
                    packet_count,
                    packet_rate,
                    age_ms,
                    latest_data
                )

                next_display = (
                    now + 0.2
                )

    except KeyboardInterrupt:

        print(
            "\nStopping..."
        )

    except Exception as exc:

        print()
        print("ERROR")
        print("=" * 64)
        print(exc)

    finally:

        if sender is not None:
            sender.stop()

        if (
            session
            and tcp_sock.fileno() >= 0
        ):
            try:
                forward_close(
                    tcp_sock,
                    session,
                    identity
                )

            except Exception:
                pass

            try:
                unregister_session(
                    tcp_sock,
                    session
                )

            except Exception:
                pass

        try:
            udp_sock.close()
        except Exception:
            pass

        try:
            tcp_sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()