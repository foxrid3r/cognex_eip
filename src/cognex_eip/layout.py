"""Configurable packed PLC data layouts."""

import struct

from .constants import DATA_TYPES

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
