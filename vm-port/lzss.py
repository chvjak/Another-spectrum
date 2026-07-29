"""Small 2 KiB-window LZSS format used by the Spectrum prototype.

Tokens are grouped in eights. A set flag bit denotes a literal byte. A clear
bit denotes a two-byte match:

    byte 0: distance_minus_one bits 10..3
    byte 1: distance_minus_one bits 2..0, then a five-bit length code

Lengths 3..33 use codes 0..30. Code 31 starts an extension where 255 bytes
mean "continue" and the final byte terminates the extension. This keeps the
Z80 decoder small while allowing long repeated attribute maps.
"""

from __future__ import annotations

from collections import defaultdict, deque


WINDOW = 2048
MAX_MATCH = 4096


def compress(data: bytes) -> bytes:
    positions: dict[bytes, deque[int]] = defaultdict(deque)
    tokens: list[tuple[str, int, int]] = []
    index = 0

    while index < len(data):
        best_length = 0
        best_distance = 0
        if index + 3 <= len(data):
            key = data[index : index + 3]
            candidates = positions[key]
            while candidates and index - candidates[0] > WINDOW:
                candidates.popleft()
            for candidate in reversed(candidates):
                length = 3
                while (
                    length < MAX_MATCH
                    and index + length < len(data)
                    and data[candidate + length] == data[index + length]
                ):
                    length += 1
                if length > best_length:
                    best_length = length
                    best_distance = index - candidate
                if length == MAX_MATCH:
                    break

        if best_length >= 3:
            tokens.append(("match", best_distance, best_length))
            end = index + best_length
            while index < end:
                if index + 3 <= len(data):
                    key = data[index : index + 3]
                    candidates = positions[key]
                    candidates.append(index)
                    while candidates and index - candidates[0] > WINDOW:
                        candidates.popleft()
                index += 1
        else:
            tokens.append(("literal", data[index], 1))
            if index + 3 <= len(data):
                key = data[index : index + 3]
                candidates = positions[key]
                candidates.append(index)
                while candidates and index - candidates[0] > WINDOW:
                    candidates.popleft()
            index += 1

    output = bytearray()
    for group_start in range(0, len(tokens), 8):
        group = tokens[group_start : group_start + 8]
        flags = 0
        payload = bytearray()
        for bit, token in enumerate(group):
            kind, value, length = token
            if kind == "literal":
                flags |= 1 << bit
                payload.append(value)
                continue

            distance = value - 1
            length_code = length - 3
            packed_length = min(length_code, 31)
            payload += bytes(
                (
                    distance >> 3,
                    ((distance & 7) << 5) | packed_length,
                )
            )
            if packed_length == 31:
                extension = length_code - 31
                while extension >= 255:
                    payload.append(255)
                    extension -= 255
                payload.append(extension)
        output.append(flags)
        output += payload
    return bytes(output)


def decompress(packed: bytes, output_size: int) -> bytes:
    output = bytearray()
    source = 0
    flags = 0
    flag_bits = 0
    while len(output) < output_size:
        if flag_bits == 0:
            flags = packed[source]
            source += 1
            flag_bits = 8
        literal = flags & 1
        flags >>= 1
        flag_bits -= 1
        if literal:
            output.append(packed[source])
            source += 1
            continue

        first = packed[source]
        second = packed[source + 1]
        source += 2
        distance = ((first << 3) | (second >> 5)) + 1
        length_code = second & 31
        if length_code == 31:
            while True:
                extension = packed[source]
                source += 1
                length_code += extension
                if extension != 255:
                    break
        length = length_code + 3
        for _ in range(length):
            output.append(output[-distance])
            if len(output) == output_size:
                break
    return bytes(output)
