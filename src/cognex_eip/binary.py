"""Binary assembly helpers."""

import struct

from .constants import DATA_TYPES

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
