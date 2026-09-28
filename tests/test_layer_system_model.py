"""Check system accounting against explicit row schedules and packed words."""

import pytest

from scripts.layer_system_model import tensor_layout
from scripts.ternary_reference import encode_bitmap_sign, decode_bitmap_sign


def test_matched_row_schedule_counts_start_and_prefill():
    # The model deliberately matches the power-trace schedule for every design:
    # start, one prefill cycle, then two compute groups per six-weight row.
    schedule = ["start", "prefill", "group0", "group1"] * 2
    layout = tensor_layout(rows=2, k=6, nonzeros=8)
    assert {v["cycles"] for v in layout.values()} == {len(schedule)}
    assert layout["five_trit"]["weight_bits"] == 32  # four packed bytes
    assert layout["bitmap_A"]["weight_bits"] == 20  # 12 presence + 8 signs
    assert layout["bitmap_B_streamed"]["weight_bits"] == 28  # 20 presence + 8 signs


@pytest.mark.parametrize("k", [1, 4, 5, 6, 128, 2560])
def test_bank_rows_pack_into_whole_five_bit_words(k):
    rows = [[(i + r) % 3 - 1 for i in range(k)] for r in range(3)]
    padded_rows = []
    for row in rows:
        padded = list(row)
        while len(padded) % 5:
            padded.append(0)
        padded_rows.append(padded)
    stream = encode_bitmap_sign([w for row in padded_rows for w in row])
    decoded = decode_bitmap_sign(stream)
    # A whole number of five-bit bank words separates each row start.
    cursor = 0
    for original, padded in zip(rows, padded_rows):
        assert cursor % 5 == 0
        assert decoded[cursor:cursor + k] == original
        assert all(w == 0 for w in decoded[cursor + k:cursor + len(padded)])
        cursor += len(padded)
    nonzeros = sum(w != 0 for row in rows for w in row)
    layout = tensor_layout(len(rows), k, nonzeros)
    for design in ("bitmap_B_resident", "bitmap_B_streamed"):
        assert layout[design]["weight_bits"] == stream.symbol_bits
        assert layout[design]["presence_padding_bits"] == cursor - len(rows) * k
    assert stream.nonzeros == nonzeros  # zero padding needs no sign storage


def test_block128_packing_preserves_separate_row_overhead():
    # Two 128-weight blocks: 26 packed bytes each, then one leftover byte.
    layout = tensor_layout(rows=1, k=257, nonzeros=100, five_trit_block=128)
    assert layout["five_trit"]["weight_bits"] == 53 * 8
    assert layout["five_trit"]["cycles"] == 55
    assert layout["bitmap_A"]["cycles"] == 54
    assert layout["bitmap_B_streamed"]["weight_bits"] == 260 + 100
