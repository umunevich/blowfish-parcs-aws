"""Tests for the pure-Python Blowfish implementation.

* Official test vectors by Eric Young published on Bruce Schneier's site
  (tests/schneier_vectors.txt, https://www.schneier.com/wp-content/uploads/2015/12/vectors-2.txt).
* Cross-check against pycryptodome (ECB / CBC / CTR).
* Round-trip checks (encrypt -> decrypt == original), padding, splitting.

Run:  pytest -v
"""
import os
import random
import re

import pytest
from Crypto.Cipher import Blowfish as RefBlowfish

from blowfish import (
    BLOCK_SIZE,
    Blowfish,
    pkcs7_pad,
    pkcs7_unpad,
    split_blocks,
)

VECTORS_FILE = os.path.join(os.path.dirname(__file__), "schneier_vectors.txt")


def _load_vectors():
    with open(VECTORS_FILE) as f:
        text = f.read()
    ecb = re.findall(r"^([0-9A-F]{16})\s+([0-9A-F]{16})\s+([0-9A-F]{16})\s*$", text, re.M)
    set_key = re.findall(r"^c=([0-9A-F]{16}) k\[\s*\d+\]=([0-9A-F]+)\s*$", text, re.M)
    set_key_plain = re.search(r"^data\[8\]= ([0-9A-F]{16})", text, re.M).group(1)
    return ecb, set_key, set_key_plain


ECB_VECTORS, SET_KEY_VECTORS, SET_KEY_PLAIN = _load_vectors()


def test_vector_file_parsed():
    assert len(ECB_VECTORS) == 34
    assert len(SET_KEY_VECTORS) == 24


# ---------------------------------------------------------------------------
# Official test vectors
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key,plain,cipher", ECB_VECTORS)
def test_schneier_ecb_vectors(key, plain, cipher):
    bf = Blowfish(bytes.fromhex(key))
    assert bf.encrypt_block(bytes.fromhex(plain)).hex().upper() == cipher
    assert bf.decrypt_block(bytes.fromhex(cipher)).hex().upper() == plain


@pytest.mark.parametrize("cipher,key", SET_KEY_VECTORS)
def test_schneier_variable_key_length(cipher, key):
    """Keys of 1..24 bytes, all encrypting the same block."""
    bf = Blowfish(bytes.fromhex(key))
    assert bf.encrypt_block(bytes.fromhex(SET_KEY_PLAIN)).hex().upper() == cipher


def test_schneier_cbc_vector():
    key = bytes.fromhex("0123456789ABCDEFF0E1D2C3B4A59687")
    iv = bytes.fromhex("FEDCBA9876543210")
    data = bytes.fromhex("37363534333231204E6F77206973207468652074696D6520666F722000")
    data += b"\x00" * (-len(data) % 8)  # the reference pads with zero bytes
    expected = "6B77B4D63006DEE605B156E27403979358DEB9E7154616D959F1652BD5FF92CC"
    bf = Blowfish(key)
    assert bf.cbc_encrypt(data, iv).hex().upper() == expected
    assert bf.cbc_decrypt(bytes.fromhex(expected), iv) == data


# ---------------------------------------------------------------------------
# Cross-check with pycryptodome
# ---------------------------------------------------------------------------
KEY_SIZES = [4, 8, 16, 32, 56]
DATA_SIZES = [0, 1, 7, 8, 9, 15, 16, 100, 1000, 4096 + 3]


def _rand(n, seed):
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(n))


@pytest.mark.parametrize("key_size", KEY_SIZES)
def test_ecb_matches_pycryptodome(key_size):
    key = _rand(key_size, key_size)
    data = pkcs7_pad(_rand(1000, 1))
    ours = Blowfish(key).ecb_encrypt(data)
    ref = RefBlowfish.new(key, RefBlowfish.MODE_ECB).encrypt(data)
    assert ours == ref


@pytest.mark.parametrize("key_size", KEY_SIZES)
def test_cbc_matches_pycryptodome(key_size):
    key = _rand(key_size, key_size + 100)
    iv = _rand(8, 7)
    data = pkcs7_pad(_rand(1003, 2))
    ours = Blowfish(key).cbc_encrypt(data, iv)
    ref = RefBlowfish.new(key, RefBlowfish.MODE_CBC, iv=iv).encrypt(data)
    assert ours == ref


@pytest.mark.parametrize("size", DATA_SIZES)
@pytest.mark.parametrize("initial_counter", [0, 1, 12345])
def test_ctr_matches_pycryptodome(size, initial_counter):
    key = _rand(16, 3)
    nonce = _rand(4, 4)
    data = _rand(size, size)
    ours = Blowfish(key).ctr_xcrypt(data, nonce, initial_counter)
    ref = RefBlowfish.new(key, RefBlowfish.MODE_CTR, nonce=nonce,
                          initial_value=initial_counter).encrypt(data)
    assert ours == ref


def test_ctr_large_crosses_segments():
    """More than one internal 64 KiB segment plus a partial tail."""
    key, nonce = b"segment-test-key", b"\x00\x01\x02\x03"
    data = os.urandom(3 * 65536 + 5)
    ours = Blowfish(key).ctr_xcrypt(data, nonce)
    ref = RefBlowfish.new(key, RefBlowfish.MODE_CTR, nonce=nonce, initial_value=0).encrypt(data)
    assert ours == ref


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("size", DATA_SIZES)
def test_roundtrip_all_modes(size):
    bf = Blowfish(b"roundtrip key!")
    data = _rand(size, 1000 + size)
    iv = b"initvect"
    padded = pkcs7_pad(data)
    assert pkcs7_unpad(bf.ecb_decrypt(bf.ecb_encrypt(padded))) == data
    assert pkcs7_unpad(bf.cbc_decrypt(bf.cbc_encrypt(padded, iv), iv)) == data
    ct = bf.ctr_xcrypt(data, b"NONC")
    assert len(ct) == len(data)  # CTR needs no padding
    assert bf.ctr_xcrypt(ct, b"NONC") == data


def test_words_roundtrip():
    bf = Blowfish(b"words")
    rng = random.Random(5)
    for _ in range(200):
        left, right = rng.getrandbits(32), rng.getrandbits(32)
        assert bf.decrypt_words(*bf.encrypt_words(left, right)) == (left, right)


# ---------------------------------------------------------------------------
# Padding and errors
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("size", range(0, 17))
def test_pkcs7(size):
    data = b"x" * size
    padded = pkcs7_pad(data)
    assert len(padded) % BLOCK_SIZE == 0 and len(padded) > len(data)
    assert pkcs7_unpad(padded) == data


@pytest.mark.parametrize("bad", [b"", b"1234567", b"12345670", b"1234567\x09", b"123456\x01\x02"])
def test_pkcs7_rejects_bad_padding(bad):
    with pytest.raises(ValueError):
        pkcs7_unpad(bad)


def test_invalid_arguments():
    with pytest.raises(ValueError):
        Blowfish(b"")
    with pytest.raises(ValueError):
        Blowfish(b"k" * 57)
    with pytest.raises(ValueError):
        Blowfish(b"key4").ecb_encrypt(b"123")
    with pytest.raises(ValueError):
        Blowfish(b"key4").ctr_xcrypt(b"data", b"123")


# ---------------------------------------------------------------------------
# Splitting for the parallel version
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("length", [0, 1, 7, 8, 9, 63, 64, 65, 1000, 10**6 + 3])
@pytest.mark.parametrize("parts", [1, 2, 3, 4, 7])
def test_split_blocks(length, parts):
    ranges = split_blocks(length, parts)
    assert len(ranges) <= parts
    pos = 0
    for start, end in ranges:
        assert start == pos and start % BLOCK_SIZE == 0 and end > start
        pos = end
    assert pos == length
    sizes = [(e - s + 7) // 8 for s, e in ranges]
    assert not sizes or max(sizes) - min(sizes) <= 1


@pytest.mark.parametrize("parts", [1, 2, 3, 4, 5])
def test_parallel_ctr_equals_sequential(parts):
    """Encrypting chunks independently with counter = offset/8 gives the same bytes."""
    bf = Blowfish(b"parallel key")
    nonce = b"\xde\xad\xbe\xef"
    data = _rand(10007, parts)
    sequential = bf.ctr_xcrypt(data, nonce)
    pieces = [bf.ctr_xcrypt(data[s:e], nonce, s // BLOCK_SIZE) for s, e in split_blocks(len(data), parts)]
    assert b"".join(pieces) == sequential
