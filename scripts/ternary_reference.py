#!/usr/bin/env python3
"""Bit-exact reference encodings and integer GEMV for ternary weights.

Conventions
-----------
Weights are -1, 0, or +1.
All bitstreams are little-endian within each byte and preserve tensor order.

Dense 2-bit codes:
    00 -> 0
    01 -> +1
    10 -> -1
    11 -> reserved / invalid

Five-trit digits:
    0 -> 0
    1 -> +1
    2 -> -1
Five consecutive ternary weights are interpreted as base-3 digits, with the
first weight as the least-significant trit. Missing values in the final group
are zero padded.

BITCOS-like bitmap/sign layout:
    presence bit 0 -> zero
    presence bit 1 -> nonzero
    compact sign bit 0 -> +1
    compact sign bit 1 -> -1
Sign bits appear only for nonzero weights, in tensor order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


TERNARY_VALUES = (-1, 0, 1)
_DENSE_ENCODE = {0: 0b00, 1: 0b01, -1: 0b10}
_DENSE_DECODE = {0b00: 0, 0b01: 1, 0b10: -1}
_TRIT_ENCODE = {0: 0, 1: 1, -1: 2}
_TRIT_DECODE = {0: 0, 1: 1, 2: -1}


def _weights(values: Iterable[int]) -> list[int]:
    out = [int(v) for v in values]
    bad = [v for v in out if v not in TERNARY_VALUES]
    if bad:
        raise ValueError(f"weights must be -1, 0, or +1; got {bad[:4]}")
    return out


def _pack_bits(bits: Sequence[int]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for i, bit in enumerate(bits):
        if bit not in (0, 1):
            raise ValueError(f"bit must be 0 or 1, got {bit}")
        out[i // 8] |= bit << (i % 8)
    return bytes(out)


def _unpack_bits(data: bytes, nbits: int) -> list[int]:
    if nbits < 0:
        raise ValueError("nbits must be nonnegative")
    if len(data) * 8 < nbits:
        raise ValueError("not enough bytes for requested bit count")
    return [(data[i // 8] >> (i % 8)) & 1 for i in range(nbits)]


def encode_dense2(values: Iterable[int]) -> bytes:
    """Pack four 2-bit ternary codes per byte."""
    weights = _weights(values)
    out = bytearray((len(weights) + 3) // 4)
    for i, w in enumerate(weights):
        out[i // 4] |= _DENSE_ENCODE[w] << (2 * (i % 4))
    return bytes(out)


def decode_dense2(data: bytes, count: int) -> list[int]:
    if count < 0:
        raise ValueError("count must be nonnegative")
    if len(data) * 4 < count:
        raise ValueError("not enough dense-2 data")
    out: list[int] = []
    for i in range(count):
        code = (data[i // 4] >> (2 * (i % 4))) & 0b11
        if code == 0b11:
            raise ValueError(f"reserved dense-2 code at weight {i}")
        out.append(_DENSE_DECODE[code])
    return out


def encode_five_trit(values: Iterable[int]) -> bytes:
    """Pack five base-3 ternary digits into each byte."""
    weights = _weights(values)
    out = bytearray()
    for base in range(0, len(weights), 5):
        byte = 0
        for lane in range(5):
            idx = base + lane
            w = weights[idx] if idx < len(weights) else 0
            byte += _TRIT_ENCODE[w] * (3**lane)
        if byte > 242:
            raise AssertionError("five-trit byte overflow")
        out.append(byte)
    return bytes(out)


def decode_five_trit(data: bytes, count: int) -> list[int]:
    if count < 0:
        raise ValueError("count must be nonnegative")
    if len(data) * 5 < count:
        raise ValueError("not enough five-trit data")
    out: list[int] = []
    for byte in data:
        value = int(byte)
        if value > 242:
            raise ValueError(f"invalid five-trit byte {value}")
        for _ in range(5):
            out.append(_TRIT_DECODE[value % 3])
            value //= 3
            if len(out) == count:
                return out
    return out


@dataclass(frozen=True)
class BitmapSigns:
    presence: bytes
    signs: bytes
    count: int
    nonzeros: int

    @property
    def symbol_bits(self) -> int:
        """Unpadded representation size, excluding scales/metadata."""
        return self.count + self.nonzeros


def encode_bitmap_sign(values: Iterable[int]) -> BitmapSigns:
    weights = _weights(values)
    presence_bits: list[int] = []
    sign_bits: list[int] = []
    for w in weights:
        present = int(w != 0)
        presence_bits.append(present)
        if present:
            sign_bits.append(int(w < 0))
    return BitmapSigns(
        presence=_pack_bits(presence_bits),
        signs=_pack_bits(sign_bits),
        count=len(weights),
        nonzeros=len(sign_bits),
    )


def decode_bitmap_sign(encoded: BitmapSigns) -> list[int]:
    presence = _unpack_bits(encoded.presence, encoded.count)
    signs = _unpack_bits(encoded.signs, encoded.nonzeros)
    out: list[int] = []
    sign_idx = 0
    for present in presence:
        if not present:
            out.append(0)
            continue
        if sign_idx >= len(signs):
            raise ValueError("sign stream ended before presence bitmap")
        out.append(-1 if signs[sign_idx] else 1)
        sign_idx += 1
    if sign_idx != encoded.nonzeros:
        raise ValueError("unused sign bits remain")
    return out


def bitmap_sign_words(values: Iterable[int]) -> tuple[int, int, int]:
    """Return (presence_word, compact_sign_word, nonzero_count).

    Bit i of presence corresponds to input weight i. Compact sign bit j is the
    sign of the j-th nonzero weight in tensor order. This is the direct input
    convention used by the initial RTL microbenchmarks.
    """
    weights = _weights(values)
    presence = 0
    signs = 0
    nz = 0
    for i, w in enumerate(weights):
        if w == 0:
            continue
        presence |= 1 << i
        if w < 0:
            signs |= 1 << nz
        nz += 1
    return presence, signs, nz


def dense2_word(values: Iterable[int]) -> int:
    weights = _weights(values)
    word = 0
    for i, w in enumerate(weights):
        word |= _DENSE_ENCODE[w] << (2 * i)
    return word


def five_trit_word(values: Iterable[int]) -> tuple[int, int]:
    """Return (packed_word, byte_count) with first byte in least-significant bits."""
    encoded = encode_five_trit(values)
    return int.from_bytes(encoded, "little"), len(encoded)


def pack_signed_activations(values: Sequence[int], width: int = 8) -> int:
    """Pack signed two's-complement activations into an integer, lane 0 LSB."""
    if width < 2:
        raise ValueError("width must be >= 2")
    lo = -(1 << (width - 1))
    hi = (1 << (width - 1)) - 1
    mask = (1 << width) - 1
    word = 0
    for i, v in enumerate(values):
        v = int(v)
        if not lo <= v <= hi:
            raise ValueError(f"activation {v} does not fit signed {width}-bit")
        word |= (v & mask) << (i * width)
    return word


def dot_ternary(weights: Sequence[int], activations: Sequence[int]) -> int:
    w = _weights(weights)
    if len(w) != len(activations):
        raise ValueError("weights and activations must have equal length")
    return sum(wi * int(ai) for wi, ai in zip(w, activations))


def dot_bitmap_sign(
    presence_word: int,
    sign_word: int,
    activations: Sequence[int],
) -> int:
    """Execute GEMV dot product directly from compact bitmap/sign semantics."""
    total = 0
    sign_idx = 0
    for i, activation in enumerate(activations):
        if not ((presence_word >> i) & 1):
            continue
        negative = (sign_word >> sign_idx) & 1
        total += -int(activation) if negative else int(activation)
        sign_idx += 1
    return total
