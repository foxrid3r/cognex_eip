"""EtherNet/IP and CIP packet construction and parsing."""

import random
import struct

from .constants import (
    ASSEMBLY_CLASS,
    CIP_FORWARD_CLOSE,
    CIP_FORWARD_OPEN,
    CMD_REGISTER_SESSION,
    CMD_SEND_RR_DATA,
    CMD_UNREGISTER_SESSION,
    CONFIG_ASSEMBLY,
    CONNECTION_MANAGER_CLASS,
    CONNECTION_MANAGER_INSTANCE,
    CPF_CONNECTED_DATA,
    CPF_NULL_ADDRESS,
    CPF_SEQUENCED_ADDRESS,
    CPF_UNCONNECTED_DATA,
    INPUT_ASSEMBLY,
    INPUT_DATA_SIZE,
    OUTPUT_ASSEMBLY,
    OUTPUT_DATA_SIZE,
)

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
