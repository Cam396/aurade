#!/usr/bin/env python3
"""Turn a short URL into a QR matrix, once, at authoring time.

You cannot type a URL from a machine that will not boot. You can point a
phone at it. That is the whole argument for a QR code on the failure screen,
and it is a good one.

What this deliberately is not is a runtime dependency. The URL is fixed, so
the matrix is a constant, and a constant belongs in the repository rather
than in an encoder shipped on the installation image and run at the worst
moment somebody has had all week. `qrencode` is a fine program and this
installer should not need it to tell somebody where to get help.

Byte mode, single Reed-Solomon block, versions 1 to 4. That covers anything
short enough to be worth putting on a screen and leaves out every part of the
specification that exists for longer payloads.

The encoder checks its own work. After building the matrix it reads the
matrix back: undoes the mask, walks the placement in reverse, recovers the
codewords, and confirms they are the ones that went in and that the
Reed-Solomon syndromes are zero. Placement and masking are where an encoder
written from the specification goes wrong, and they fail silently, producing
a tidy square nothing can read.

Usage: make-qr.py URL [OUTPUT]
"""

from __future__ import annotations

import sys

# --- GF(256), the field the error correction is computed in -----------------

EXP = [0] * 512
LOG = [0] * 256
_x = 1
for _i in range(255):
    EXP[_i] = _x
    LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D          # the QR generator polynomial for the field
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return EXP[LOG[a] + LOG[b]]


def rs_generator(degree: int) -> list[int]:
    """The generator polynomial for `degree` error correction codewords."""
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coefficient in enumerate(poly):
            nxt[j] ^= gf_mul(coefficient, 1)
            nxt[j + 1] ^= gf_mul(coefficient, EXP[i])
        poly = nxt
    return poly


def rs_remainder(data: list[int], degree: int) -> list[int]:
    generator = rs_generator(degree)
    remainder = [0] * degree
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        for i, coefficient in enumerate(generator[1:]):
            remainder[i] ^= gf_mul(coefficient, factor)
    return remainder


# --- the four versions this handles -----------------------------------------
#
# (data codewords, error correction codewords) for one block, at error
# correction level L and M. Everything here is a single block, which is why
# versions stop at 4: version 4 at level M is the first that splits.

CAPACITY = {
    (1, "L"): (19, 7),   (1, "M"): (16, 10),
    (2, "L"): (34, 10),  (2, "M"): (28, 16),
    (3, "L"): (55, 15),  (3, "M"): (44, 26),
    (4, "L"): (80, 20),
}

#: Where the alignment pattern goes, by version. Version 1 has none.
ALIGNMENT = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26]}

#: Error correction level, as the two bits the format information carries.
EC_BITS = {"L": 0b01, "M": 0b00}


def size_of(version: int) -> int:
    return version * 4 + 17


# --- encoding ---------------------------------------------------------------


def to_codewords(text: str, version: int, level: str) -> list[int]:
    """Mode, length, payload, terminator, padding."""
    payload = text.encode("utf-8")
    data_words, _ = CAPACITY[(version, level)]
    bits: list[int] = []

    def put(value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((value >> shift) & 1)

    put(0b0100, 4)               # byte mode
    put(len(payload), 8)         # one byte of length, for versions 1 to 9
    for byte in payload:
        put(byte, 8)

    capacity = data_words * 8
    if len(bits) > capacity:
        raise ValueError(f"{len(payload)} bytes does not fit in version "
                         f"{version}{level}")
    # Terminator, then out to a byte boundary, then the two alternating pad
    # codewords the specification names.
    put(0, min(4, capacity - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    words = [int("".join(str(b) for b in bits[i:i + 8]), 2)
             for i in range(0, len(bits), 8)]
    for pad in _cycle([0xEC, 0x11]):
        if len(words) >= data_words:
            break
        words.append(pad)
    return words


def _cycle(values):
    while True:
        for value in values:
            yield value


# --- the fixed patterns -----------------------------------------------------


def blank(version: int):
    n = size_of(version)
    return [[None] * n for _ in range(n)], [[False] * n for _ in range(n)]


def place_function_patterns(matrix, reserved, version: int) -> None:
    n = size_of(version)

    def finder(top: int, left: int) -> None:
        for dy in range(-1, 8):
            for dx in range(-1, 8):
                y, x = top + dy, left + dx
                if not (0 <= y < n and 0 <= x < n):
                    continue
                edge = max(abs(dy - 3), abs(dx - 3))
                matrix[y][x] = 1 if edge in (0, 1, 3) else 0
                reserved[y][x] = True

    finder(0, 0)
    finder(0, n - 7)
    finder(n - 7, 0)

    # Timing, the alternating run that tells a reader the module pitch.
    for i in range(8, n - 8):
        bit = 1 if i % 2 == 0 else 0
        matrix[6][i] = bit
        matrix[i][6] = bit
        reserved[6][i] = True
        reserved[i][6] = True

    for row in ALIGNMENT[version]:
        for col in ALIGNMENT[version]:
            # Not where it would sit on top of a finder pattern.
            if (row, col) in ((6, 6), (6, size_of(version) - 7),
                              (size_of(version) - 7, 6)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    matrix[row + dy][col + dx] = \
                        1 if max(abs(dy), abs(dx)) != 1 else 0
                    reserved[row + dy][col + dx] = True

    # The dark module, which is always dark, and the format information areas.
    matrix[n - 8][8] = 1
    reserved[n - 8][8] = True
    for i in range(9):
        if not reserved[8][i]:
            reserved[8][i] = True
        if not reserved[i][8]:
            reserved[i][8] = True
    for i in range(8):
        reserved[8][n - 1 - i] = True
        reserved[n - 1 - i][8] = True


def data_positions(version: int, reserved):
    """Every free module, in the order the specification writes them.

    Two columns at a time, right to left, alternating upward and downward,
    skipping the column the vertical timing pattern occupies.
    """
    n = size_of(version)
    upward = True
    col = n - 1
    while col > 0:
        if col == 6:                       # the timing column is not a column
            col -= 1
        rows = range(n - 1, -1, -1) if upward else range(n)
        for row in rows:
            for dx in (0, 1):
                x = col - dx
                if not reserved[row][x]:
                    yield row, x
        upward = not upward
        col -= 2


MASKS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def format_bits(level: str, mask: int) -> list[int]:
    value = (EC_BITS[level] << 3) | mask
    remainder = value << 10
    for i in range(4, -1, -1):
        if remainder & (1 << (i + 10)):
            remainder ^= 0b10100110111 << i
    bits = ((value << 10) | remainder) ^ 0b101010000010010
    return [(bits >> (14 - i)) & 1 for i in range(15)]


def place_format(matrix, level: str, mask: int, version: int) -> None:
    n = size_of(version)
    bits = format_bits(level, mask)
    # The first copy, around the top left finder.
    coords = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
              (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    for bit, (row, col) in zip(bits, coords):
        matrix[row][col] = bit
    # And the second, split between the other two, so that damage to one
    # corner cannot take the format information with it.
    for i in range(7):
        matrix[n - 1 - i][8] = bits[i]
    for i in range(8):
        matrix[8][n - 8 + i] = bits[7 + i]


def penalty(matrix) -> int:
    """How bad this mask looks, by the four rules in the specification."""
    n = len(matrix)
    score = 0

    def run_penalty(line):
        total = 0
        run = 1
        for i in range(1, len(line)):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    total += 3 + (run - 5)
                run = 1
        if run >= 5:
            total += 3 + (run - 5)
        return total

    for row in matrix:
        score += run_penalty(row)
    for col in zip(*matrix):
        score += run_penalty(list(col))

    for r in range(n - 1):
        for c in range(n - 1):
            block = {matrix[r][c], matrix[r][c + 1],
                     matrix[r + 1][c], matrix[r + 1][c + 1]}
            if len(block) == 1:
                score += 3

    finder = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    for line in list(matrix) + [list(col) for col in zip(*matrix)]:
        for i in range(len(line) - 10):
            window = list(line[i:i + 11])
            if window == finder or window == finder[::-1]:
                score += 40

    dark = sum(sum(row) for row in matrix)
    ratio = dark * 100 // (n * n)
    score += 10 * min(abs(ratio - 50) // 5, abs(ratio - 50 + 4) // 5)
    return score


def encode(text: str, level: str = "L"):
    for version in (1, 2, 3, 4):
        if (version, level) not in CAPACITY:
            continue
        data_words, ec_words = CAPACITY[(version, level)]
        if len(text.encode("utf-8")) + 2 > data_words:
            continue
        words = to_codewords(text, version, level)
        codewords = words + rs_remainder(words, ec_words)

        best = None
        for mask in range(8):
            matrix, reserved = blank(version)
            place_function_patterns(matrix, reserved, version)
            positions = list(data_positions(version, reserved))
            bits = [(word >> shift) & 1
                    for word in codewords for shift in range(7, -1, -1)]
            for (row, col), bit in zip(positions, bits):
                matrix[row][col] = bit
            for row, col in positions[len(bits):]:
                matrix[row][col] = 0
            for row, col in positions:
                if MASKS[mask](row, col):
                    matrix[row][col] ^= 1
            place_format(matrix, level, mask, version)
            filled = [[0 if cell is None else cell for cell in row]
                      for row in matrix]
            cost = penalty(filled)
            if best is None or cost < best[0]:
                best = (cost, filled, mask, version, reserved, codewords)
        return best[1], best[2], best[3], best[4], best[5]
    raise ValueError(f"{text!r} is too long for a single block QR code")


# --- reading it back --------------------------------------------------------


def verify(matrix, mask: int, version: int, reserved, codewords, text: str,
           level: str) -> None:
    """Undo the mask, walk the placement backwards, check what comes out.

    Placement order and masking are the two parts of this an encoder written
    from the specification gets wrong, and both fail into a tidy square that
    no reader can decode. Checking the round trip here is the difference
    between shipping a QR code and shipping a picture of one.
    """
    unmasked = [row[:] for row in matrix]
    positions = list(data_positions(version, reserved))
    for row, col in positions:
        if MASKS[mask](row, col):
            unmasked[row][col] ^= 1

    bits = [unmasked[row][col] for row, col in positions]
    recovered = [int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(codewords) * 8, 8)]
    if recovered != codewords:
        raise AssertionError("the matrix does not read back as what was put in")

    data_words, ec_words = CAPACITY[(version, level)]
    if rs_remainder(recovered[:data_words], ec_words) != recovered[data_words:]:
        raise AssertionError("the error correction codewords do not check out")

    # And the payload itself, back out of the data codewords.
    stream = "".join(f"{word:08b}" for word in recovered[:data_words])
    if int(stream[:4], 2) != 0b0100:
        raise AssertionError("the mode indicator is not byte mode")
    length = int(stream[4:12], 2)
    payload = bytes(int(stream[12 + i * 8:20 + i * 8], 2) for i in range(length))
    if payload.decode("utf-8") != text:
        raise AssertionError(f"read back {payload!r}, not {text!r}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    text = sys.argv[1]
    matrix, mask, version, reserved, codewords = encode(text)
    verify(matrix, mask, version, reserved, codewords, text, "L")

    lines = ["# Generated by installer/tools/make-qr.py. Do not edit by hand.",
             f"# {text}",
             f"# version {version}, error correction L, mask {mask}"]
    lines += ["".join(str(cell) for cell in row) for row in matrix]
    out = "\n".join(lines) + "\n"
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w") as handle:
            handle.write(out)
        print(f"{sys.argv[2]}: version {version}, "
              f"{size_of(version)} by {size_of(version)}, mask {mask}")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
