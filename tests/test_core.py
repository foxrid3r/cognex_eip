import struct
import unittest

from cognex_eip.binary import get_bit, get_bits, set_bit
from cognex_eip.layout import DataLayout
from cognex_eip.protocol import build_o_to_t_packet, parse_t_to_o_packet


class BinaryHelperTests(unittest.TestCase):
    def test_bit_helpers(self):
        data = bytearray(1)

        set_bit(data, 0, 3, True)

        self.assertTrue(get_bit(data, 0, 3))
        self.assertEqual(get_bits(data, 0, 2, 3), 2)


class DataLayoutTests(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        layout = DataLayout(
            8,
            [
                {"name": "count", "type": "INT"},
                {"name": "score", "type": "REAL"},
            ],
        )

        encoded = layout.encode({"count": "42", "score": "1.5"})
        decoded = dict((field["name"], value) for field, value in layout.decode(encoded))

        self.assertEqual(decoded["count"], 42)
        self.assertAlmostEqual(decoded["score"], 1.5)
        self.assertEqual(len(encoded), 8)

    def test_rejects_duplicate_fields(self):
        with self.assertRaisesRegex(ValueError, "Duplicate field name"):
            DataLayout(
                4,
                [
                    {"name": "value", "type": "INT"},
                    {"name": "value", "type": "INT"},
                ],
            )

    def test_rejects_layout_larger_than_buffer(self):
        with self.assertRaisesRegex(ValueError, "only 2 bytes"):
            DataLayout(2, [{"name": "value", "type": "DINT"}])


class ProtocolTests(unittest.TestCase):
    def test_connected_packet_round_trip(self):
        packet = build_o_to_t_packet(
            connection_id=0x12345678,
            packet_sequence=7,
            transport_sequence=9,
            output_data=b"payload",
        )

        connection_id, assembly = parse_t_to_o_packet(packet)

        self.assertEqual(connection_id, 0x12345678)
        self.assertEqual(assembly, struct.pack("<I", 1) + b"payload")

    def test_malformed_packet_is_ignored(self):
        self.assertIsNone(parse_t_to_o_packet(b""))
        self.assertIsNone(parse_t_to_o_packet(b"\x01\x00"))


if __name__ == "__main__":
    unittest.main()
