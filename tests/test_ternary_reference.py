from __future__ import annotations

import itertools
import random

import pytest

from scripts.ternary_reference import (
    BitmapSigns,
    bitmap_sign_words,
    decode_bitmap_sign,
    decode_dense2,
    decode_five_trit,
    dense2_word,
    dot_bitmap_sign,
    dot_ternary,
    encode_bitmap_sign,
    encode_dense2,
    encode_five_trit,
)


def test_dense2_exhaustive_five_weights() -> None:
    for weights in itertools.product((-1, 0, 1), repeat=5):
        assert decode_dense2(encode_dense2(weights), len(weights)) == list(weights)


def test_five_trit_exhaustive_single_byte() -> None:
    seen = set()
    for weights in itertools.product((-1, 0, 1), repeat=5):
        encoded = encode_five_trit(weights)
        assert len(encoded) == 1
        seen.add(encoded[0])
        assert decode_five_trit(encoded, 5) == list(weights)
    assert seen == set(range(243))


def test_bitmap_sign_exhaustive_five_weights() -> None:
    for weights in itertools.product((-1, 0, 1), repeat=5):
        encoded = encode_bitmap_sign(weights)
        assert decode_bitmap_sign(encoded) == list(weights)
        assert encoded.symbol_bits == len(weights) + sum(w != 0 for w in weights)


def test_all_encodings_random_roundtrip() -> None:
    rng = random.Random(17)
    for n in [1, 5, 16, 31, 128]:
        for _ in range(50):
            weights = [rng.choice((-1, 0, 1)) for _ in range(n)]
            assert decode_dense2(encode_dense2(weights), n) == weights
            assert decode_five_trit(encode_five_trit(weights), n) == weights
            assert decode_bitmap_sign(encode_bitmap_sign(weights)) == weights


def test_direct_bitmap_execution_matches_dense_dot() -> None:
    rng = random.Random(23)
    for lanes in [1, 8, 16, 32]:
        for _ in range(100):
            weights = [rng.choice((-1, 0, 1)) for _ in range(lanes)]
            activations = [rng.randint(-128, 127) for _ in range(lanes)]
            presence, signs, _ = bitmap_sign_words(weights)
            assert dot_bitmap_sign(presence, signs, activations) == dot_ternary(weights, activations)


def test_known_bit_ordering() -> None:
    weights = [0, 1, -1, 0, -1]
    presence, signs, nonzeros = bitmap_sign_words(weights)
    assert presence == 0b10110
    assert signs == 0b110
    assert nonzeros == 3
    assert dense2_word(weights) == (
        0b00 | (0b01 << 2) | (0b10 << 4) | (0b00 << 6) | (0b10 << 8)
    )


def test_reserved_dense_code_rejected() -> None:
    with pytest.raises(ValueError):
        decode_dense2(bytes([0b11]), 1)


def test_invalid_five_trit_byte_rejected() -> None:
    with pytest.raises(ValueError):
        decode_five_trit(bytes([243]), 5)


def test_bitmap_sign_truncated_sign_stream_rejected() -> None:
    bad = BitmapSigns(presence=bytes([0b11]), signs=b"", count=2, nonzeros=2)
    with pytest.raises(ValueError):
        decode_bitmap_sign(bad)
