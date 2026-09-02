"""Cognex assembly definitions and application defaults."""

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
