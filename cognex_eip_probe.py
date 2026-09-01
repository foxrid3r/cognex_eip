import argparse
import struct
import time

from pycomm3 import CIPDriver


# ============================================================
# Cognex In-Sight EtherNet/IP
# ============================================================

ASSEMBLY_CLASS = 0x04
INPUT_ASSEMBLY = 13
ASSEMBLY_DATA_ATTRIBUTE = 3

POLL_INTERVAL = 0.100     # 100 ms


# ============================================================
# Helpers
# ============================================================

def bit(value, number):
    return bool(value & (1 << number))


def uint16_le(data, offset):
    if len(data) < offset + 2:
        return None

    return struct.unpack_from("<H", data, offset)[0]


def bool_text(value):
    return "TRUE " if value else "FALSE"


# ============================================================
# Cognex Input Assembly 13 decoder
# ============================================================

def decode_assembly(data):

    if len(data) < 16:
        raise ValueError(
            f"Expected at least 16 bytes, received {len(data)}"
        )

    b0 = data[0]
    b1 = data[1]
    b2 = data[2]
    b3 = data[3]

    # --------------------------------------------------------
    # Byte 0
    #
    # Bit 0     Trigger Ready
    # Bit 1     Trigger Ack
    # Bit 2     Reserved
    # Bit 3     Acq Error
    # Bits 4-6  Offline Reason
    # Bit 7     Online
    # --------------------------------------------------------

    trigger_ready = bit(b0, 0)
    trigger_ack = bit(b0, 1)
    acq_error = bit(b0, 3)
    offline_reason = (b0 >> 4) & 0x07
    online = bit(b0, 7)

    # --------------------------------------------------------
    # Byte 1
    # --------------------------------------------------------

    inspection_completed = bit(b1, 1)
    results_buffer_overrun = bit(b1, 2)
    results_valid = bit(b1, 3)
    command_executing = bit(b1, 4)
    command_completed = bit(b1, 5)
    command_failed = bit(b1, 6)
    error = bit(b1, 7)

    # --------------------------------------------------------
    # Byte 2
    # --------------------------------------------------------

    set_user_data_ack = bit(b2, 0)
    exposure_complete = bit(b2, 4)
    job_pass = bit(b2, 5)
    test_run_ready = bit(b2, 6)

    # --------------------------------------------------------
    # Byte 3
    # --------------------------------------------------------

    external_event_ack = [
        bit(b3, n)
        for n in range(8)
    ]

    # --------------------------------------------------------
    # 16-bit values
    # --------------------------------------------------------

    error_id = uint16_le(data, 4)
    command_result_code = uint16_le(data, 6)
    current_job_id = uint16_le(data, 8)
    acquisition_id = uint16_le(data, 10)
    inspection_id = uint16_le(data, 12)
    inspection_result_code = uint16_le(data, 14)

    return {
        "raw": data,

        "byte0": b0,
        "byte1": b1,
        "byte2": b2,
        "byte3": b3,

        "trigger_ready": trigger_ready,
        "trigger_ack": trigger_ack,
        "acq_error": acq_error,
        "offline_reason": offline_reason,
        "online": online,

        "inspection_completed": inspection_completed,
        "results_buffer_overrun": results_buffer_overrun,
        "results_valid": results_valid,
        "command_executing": command_executing,
        "command_completed": command_completed,
        "command_failed": command_failed,
        "error": error,

        "set_user_data_ack": set_user_data_ack,
        "exposure_complete": exposure_complete,
        "job_pass": job_pass,
        "test_run_ready": test_run_ready,

        "external_event_ack": external_event_ack,

        "error_id": error_id,
        "command_result_code": command_result_code,
        "current_job_id": current_job_id,
        "acquisition_id": acquisition_id,
        "inspection_id": inspection_id,
        "inspection_result_code": inspection_result_code,
    }


# ============================================================
# Display
# ============================================================

def print_status(status, read_count, read_ms):

    print("\033[2J\033[H", end="")

    print("Cognex EtherNet/IP Assembly 13 Probe")
    print("=" * 68)

    print(
        f"Reads: {read_count:,}    "
        f"Last read: {read_ms:6.1f} ms    "
        f"Assembly bytes: {len(status['raw'])}"
    )

    print()

    print("RAW STATUS BYTES")
    print("-" * 68)

    for n in range(4):
        value = status[f"byte{n}"]

        print(
            f"Byte {n}:  "
            f"0x{value:02X}    "
            f"{value:3d}    "
            f"{value:08b}"
        )

    print()
    print("BYTE 0")
    print("-" * 68)

    print(
        f"Bit 0   Trigger Ready       "
        f"{bool_text(status['trigger_ready'])}"
    )

    print(
        f"Bit 1   Trigger Ack         "
        f"{bool_text(status['trigger_ack'])}"
    )

    print(
        f"Bit 3   Acq Error           "
        f"{bool_text(status['acq_error'])}"
    )

    print(
        f"Bits4-6 Offline Reason      "
        f"{status['offline_reason']} "
        f"(0b{status['offline_reason']:03b})"
    )

    print(
        f"Bit 7   Online              "
        f"{bool_text(status['online'])}"
    )

    print()
    print("BYTE 1")
    print("-" * 68)

    print(
        f"Bit 1   Inspection Complete "
        f"{bool_text(status['inspection_completed'])}"
    )

    print(
        f"Bit 2   Results Overrun     "
        f"{bool_text(status['results_buffer_overrun'])}"
    )

    print(
        f"Bit 3   Results Valid       "
        f"{bool_text(status['results_valid'])}"
    )

    print(
        f"Bit 4   Command Executing   "
        f"{bool_text(status['command_executing'])}"
    )

    print(
        f"Bit 5   Command Completed   "
        f"{bool_text(status['command_completed'])}"
    )

    print(
        f"Bit 6   Command Failed      "
        f"{bool_text(status['command_failed'])}"
    )

    print(
        f"Bit 7   Error               "
        f"{bool_text(status['error'])}"
    )

    print()
    print("BYTE 2")
    print("-" * 68)

    print(
        f"Bit 0   Set User Data Ack   "
        f"{bool_text(status['set_user_data_ack'])}"
    )

    print(
        f"Bit 4   Exposure Complete   "
        f"{bool_text(status['exposure_complete'])}"
    )

    print(
        f"Bit 5   Job Pass            "
        f"{bool_text(status['job_pass'])}"
    )

    print(
        f"Bit 6   TestRun Ready       "
        f"{bool_text(status['test_run_ready'])}"
    )

    print()
    print("BYTE 3")
    print("-" * 68)

    for n, value in enumerate(status["external_event_ack"]):
        print(
            f"Bit {n}   External Event Ack {n}  "
            f"{bool_text(value)}"
        )

    print()
    print("16-BIT VALUES")
    print("-" * 68)

    print(
        f"Bytes  4-5   Error ID                 "
        f"{status['error_id']}"
    )

    print(
        f"Bytes  6-7   Command Result Code      "
        f"{status['command_result_code']}"
    )

    print(
        f"Bytes  8-9   Current Job ID           "
        f"{status['current_job_id']}"
    )

    print(
        f"Bytes 10-11  Acquisition ID           "
        f"{status['acquisition_id']}"
    )

    print(
        f"Bytes 12-13  Inspection ID            "
        f"{status['inspection_id']}"
    )

    print(
        f"Bytes 14-15  Inspection Result Code   "
        f"{status['inspection_result_code']}"
    )

    print()
    print("Ctrl+C to stop.")


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Cognex In-Sight EtherNet/IP Assembly 13 diagnostic probe"
        )
    )

    parser.add_argument(
        "ip",
        help="Camera IP address"
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=POLL_INTERVAL,
        help="Poll interval in seconds (default: 0.1)"
    )

    args = parser.parse_args()

    print(f"Connecting to {args.ip} ...")

    read_count = 0

    try:

        with CIPDriver(args.ip) as camera:

            print("EtherNet/IP session registered.")
            print("Reading Assembly 13...")

            time.sleep(0.25)

            while True:

                start = time.perf_counter()

                response = camera.generic_message(
                    service=0x0E,               # Get_Attribute_Single
                    class_code=ASSEMBLY_CLASS,
                    instance=INPUT_ASSEMBLY,
                    attribute=ASSEMBLY_DATA_ATTRIBUTE,

                    # IMPORTANT:
                    # This is intentionally an explicit UCMM request.
                    connected=False,
                    unconnected_send=False,
                    route_path=False,

                    # None = return raw response bytes
                    data_type=None,

                    name="Cognex Input Assembly 13",
                )

                elapsed_ms = (
                    time.perf_counter() - start
                ) * 1000.0

                if not response:

                    print()
                    print("CIP read failed:")
                    print(response.error)

                    time.sleep(1)
                    continue

                data = bytes(response.value)

                status = decode_assembly(data)

                read_count += 1

                print_status(
                    status,
                    read_count,
                    elapsed_ms
                )

                time.sleep(args.interval)

    except KeyboardInterrupt:

        print()
        print("Stopped.")

    except Exception as exc:

        print()
        print("ERROR")
        print("=" * 68)
        print(exc)


if __name__ == "__main__":
    main()