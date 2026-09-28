"""decode_q2_0 must invert the CAT-Q Q2_0 packer (BitTern projects/cat-q/quantize/q2_0.py)."""

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("safetensors")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_ternary_checkpoint import decode_q2_0  # noqa: E402

QK = 128


def pack_q2_0(codes, scales):
    """Same arithmetic as BitTern's pack_q2_0: fp16 scale, then code+1 at bits 2*(j%4) of byte j//4."""
    rows, k = codes.shape
    n_blocks = codes.size // QK
    levels = (codes.astype(np.int8).reshape(n_blocks, QK) + np.int8(1)).astype(np.uint8)
    levels = levels.reshape(n_blocks, QK // 4, 4)
    shifted = levels << np.array([0, 2, 4, 6], dtype=np.uint8).reshape(1, 1, 4)
    qs = shifted[..., 0] | shifted[..., 1] | shifted[..., 2] | shifted[..., 3]
    d = scales.astype(np.float16).reshape(n_blocks, 1).view(np.uint8)
    return np.concatenate([d, qs], axis=-1).reshape(rows, k // QK, 34)


@pytest.mark.parametrize("rows,k", [(3, 128), (17, 512), (64, 2048)])
def test_round_trip_and_scale_counts(rows, k):
    rng = np.random.default_rng(rows * k)
    codes = rng.integers(-1, 2, size=(rows, k)).astype(np.int8)
    scales = rng.uniform(-0.1, 0.2, size=rows * k // QK).astype(np.float32)
    scales[0] = 0.0
    got, stats = decode_q2_0(pack_q2_0(codes, scales))
    assert np.array_equal(got, codes)
    half = scales.astype(np.float16)
    assert stats["q2_0_groups"] == half.size
    assert stats["q2_0_zero_scale_groups"] == int((half == 0).sum())
    assert stats["q2_0_negative_scale_groups"] == int((half < 0).sum())


def test_code_three_rejected():
    blocks = pack_q2_0(np.zeros((1, QK), np.int8), np.ones(1, np.float32))
    blocks[0, 0, 2] |= 0x03
    with pytest.raises(ValueError):
        decode_q2_0(blocks)
