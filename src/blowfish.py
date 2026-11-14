# -*- coding: utf-8 -*-
"""Pure-Python implementation of the Blowfish block cipher (Bruce Schneier, 1993).

Written from scratch; no third-party crypto libraries are used here (they are
used only in tests to cross-check the results).

The code is compatible with BOTH Python 3 and Python 2.7, because the
PARCS-Python nodes (docker image hummer12007/parcs-node) run Python 2.7.

Overview of Blowfish
--------------------
* Block size: 64 bits (8 bytes), key size: 32..448 bits (4..56 bytes;
  shorter keys down to 1 byte are accepted here to run the original test
  vectors).
* 16-round Feistel network. Each 64-bit block is split into two 32-bit
  halves L and R. In round i:
        L = L xor P[i]
        R = R xor F(L)
        swap(L, R)
  After 16 rounds the last swap is undone and the halves are whitened with
  P[16] and P[17].
* Round function F splits a 32-bit word x into four bytes a, b, c, d and
  uses four key-dependent S-boxes (each maps 8 bits -> 32 bits):
        F(x) = ((S0[a] + S1[b]) xor S2[c]) + S3[d]      (additions mod 2^32)
* Key schedule: P-array (18 words) and S-boxes (4 x 256 words) are first
  filled with the hexadecimal digits of pi. Then the key is XOR-ed into the
  P-array (cyclically), and the all-zero block is repeatedly encrypted; each
  output replaces the next two entries of P and then of the S-boxes
  (521 encryptions in total). That is why creating a cipher object is
  relatively expensive while encrypting a block is cheap.
* Decryption is the same network with the P-array applied in reverse order.

Modes of operation implemented here
-----------------------------------
* ECB -- every block independently (needs padding, PKCS#7).
* CBC -- C[i] = E(P[i] xor C[i-1]); encryption is inherently sequential
  because block i needs the ciphertext of block i-1 (decryption, however,
  is parallelisable).
* CTR -- keystream block i = E(nonce || counter0 + i), C = P xor keystream.
  Blocks are completely independent, so any byte range starting at a block
  boundary can be processed by a different worker if it knows its starting
  counter (= byte_offset / 8). No padding is needed; encryption and
  decryption are the same operation. This is the mode used for the parallel
  version.
"""
from __future__ import division

import struct

from blowfish_constants import PI_P_ARRAY, PI_S_BOXES  # @@INLINE-IMPORT

try:  # Python 2
    xrange
except NameError:  # Python 3
    xrange = range

BLOCK_SIZE = 8
ROUNDS = 16
MASK32 = 0xFFFFFFFF

# CTR data is processed in segments of this many blocks, so that we never
# build huge temporary lists of integers (keeps memory usage bounded).
_SEGMENT_BLOCKS = 8192  # 64 KiB


def _to_bytearray(data):
    return data if isinstance(data, bytearray) else bytearray(data)


def _xor_bytes(a, b):
    return bytes(bytearray(x ^ y for x, y in zip(bytearray(a), bytearray(b))))


class Blowfish(object):
    """Blowfish cipher with a fixed key.

    Low-level methods work on pairs of 32-bit integers (L, R); byte-level
    helpers and modes of operation are built on top of them.
    """

    def __init__(self, key):
        key = _to_bytearray(key)
        if not 1 <= len(key) <= 56:
            raise ValueError("Blowfish key must be 1..56 bytes long, got %d" % len(key))

        # 1. Initialise P-array and S-boxes with the digits of pi.
        self.P = list(PI_P_ARRAY)
        self.S = [list(box) for box in PI_S_BOXES]

        # 2. XOR the key into the P-array, reusing key bytes cyclically:
        #    P[0] ^= key[0..3], P[1] ^= key[4..7], ...
        j = 0
        for i in xrange(ROUNDS + 2):
            word = 0
            for _ in xrange(4):
                word = (word << 8) | key[j]
                j = (j + 1) % len(key)
            self.P[i] ^= word

        # 3. Encrypt the all-zero block; replace P[0], P[1] with the output,
        #    encrypt the output again, replace P[2], P[3], ... and then all
        #    entries of the four S-boxes in the same way. Every step uses the
        #    already modified tables (self.P / self.S are updated in place).
        left = right = 0
        for i in xrange(0, ROUNDS + 2, 2):
            left, right = self.encrypt_words(left, right)
            self.P[i], self.P[i + 1] = left, right
        for box in self.S:
            for i in xrange(0, 256, 2):
                left, right = self.encrypt_words(left, right)
                box[i], box[i + 1] = left, right

    # ------------------------------------------------------------------
    # Core: one 64-bit block as two 32-bit halves
    # ------------------------------------------------------------------
    def encrypt_words(self, left, right):
        """Encrypt one block given as two 32-bit integers; returns (L, R).

        Two Feistel rounds are done per loop iteration, which removes the
        explicit swap of the halves:
            round 2k:   L ^= P[2k];   R ^= F(L)
            round 2k+1: R ^= P[2k+1]; L ^= F(R)
        F is inlined for speed (function calls are expensive in Python).
        """
        P = self.P
        S0, S1, S2, S3 = self.S
        for i in xrange(0, ROUNDS, 2):
            left ^= P[i]
            right ^= ((((S0[left >> 24] + S1[(left >> 16) & 0xFF]) & MASK32)
                       ^ S2[(left >> 8) & 0xFF]) + S3[left & 0xFF]) & MASK32
            right ^= P[i + 1]
            left ^= ((((S0[right >> 24] + S1[(right >> 16) & 0xFF]) & MASK32)
                      ^ S2[(right >> 8) & 0xFF]) + S3[right & 0xFF]) & MASK32
        # Undo the last swap and apply output whitening with P[16], P[17].
        return right ^ P[ROUNDS + 1], left ^ P[ROUNDS]

    def decrypt_words(self, left, right):
        """Inverse of encrypt_words: the same network with P used backwards."""
        P = self.P
        S0, S1, S2, S3 = self.S
        for i in xrange(ROUNDS + 1, 1, -2):
            left ^= P[i]
            right ^= ((((S0[left >> 24] + S1[(left >> 16) & 0xFF]) & MASK32)
                       ^ S2[(left >> 8) & 0xFF]) + S3[left & 0xFF]) & MASK32
            right ^= P[i - 1]
            left ^= ((((S0[right >> 24] + S1[(right >> 16) & 0xFF]) & MASK32)
                      ^ S2[(right >> 8) & 0xFF]) + S3[right & 0xFF]) & MASK32
        return right ^ P[0], left ^ P[1]

    def encrypt_block(self, block):
        """Encrypt exactly 8 bytes (big-endian halves, as in the reference)."""
        left, right = struct.unpack(">II", bytes(block))
        return struct.pack(">II", *self.encrypt_words(left, right))

    def decrypt_block(self, block):
        left, right = struct.unpack(">II", bytes(block))
        return struct.pack(">II", *self.decrypt_words(left, right))

    # ------------------------------------------------------------------
    # ECB: Electronic Codebook
    # ------------------------------------------------------------------
    def _ecb(self, data, func):
        data = bytes(data)
        if len(data) % BLOCK_SIZE:
            raise ValueError("ECB data length must be a multiple of 8 (use PKCS#7 padding)")
        n_words = len(data) // 4
        words = struct.unpack(">%dI" % n_words, data)
        out = [0] * n_words
        for i in xrange(0, n_words, 2):
            out[i], out[i + 1] = func(words[i], words[i + 1])
        return struct.pack(">%dI" % n_words, *out)

    def ecb_encrypt(self, data):
        return self._ecb(data, self.encrypt_words)

    def ecb_decrypt(self, data):
        return self._ecb(data, self.decrypt_words)

    # ------------------------------------------------------------------
    # CBC: Cipher Block Chaining
    # ------------------------------------------------------------------
    def cbc_encrypt(self, data, iv):
        """C[i] = E(P[i] xor C[i-1]), C[-1] = IV.

        Not parallelisable: block i cannot be started before C[i-1] is known.
        """
        data = bytes(data)
        if len(data) % BLOCK_SIZE:
            raise ValueError("CBC data length must be a multiple of 8 (use PKCS#7 padding)")
        prev_l, prev_r = struct.unpack(">II", bytes(iv))
        n_words = len(data) // 4
        words = struct.unpack(">%dI" % n_words, data)
        out = [0] * n_words
        for i in xrange(0, n_words, 2):
            prev_l, prev_r = self.encrypt_words(words[i] ^ prev_l, words[i + 1] ^ prev_r)
            out[i], out[i + 1] = prev_l, prev_r
        return struct.pack(">%dI" % n_words, *out)

    def cbc_decrypt(self, data, iv):
        """P[i] = D(C[i]) xor C[i-1] -- every block depends only on ciphertext."""
        data = bytes(data)
        if len(data) % BLOCK_SIZE:
            raise ValueError("CBC data length must be a multiple of 8")
        n_words = len(data) // 4
        words = (tuple(struct.unpack(">II", bytes(iv)))
                 + struct.unpack(">%dI" % n_words, data))
        out = [0] * n_words
        for i in xrange(0, n_words, 2):
            left, right = self.decrypt_words(words[i + 2], words[i + 3])
            out[i], out[i + 1] = left ^ words[i], right ^ words[i + 1]
        return struct.pack(">%dI" % n_words, *out)

    # ------------------------------------------------------------------
    # CTR: Counter mode
    # ------------------------------------------------------------------
    def ctr_xcrypt(self, data, nonce, initial_counter=0):
        """Encrypt or decrypt (identical operation) `data` in CTR mode.

        Counter block i = nonce (4 bytes) || (initial_counter + i) as a
        32-bit big-endian integer -- the same layout as
        pycryptodome's Blowfish.new(key, MODE_CTR, nonce=nonce,
        initial_value=initial_counter).

        To process a slice that starts at byte offset `off` (a multiple of 8)
        independently, pass initial_counter = off // 8.
        """
        nonce = bytes(nonce)
        if len(nonce) != 4:
            raise ValueError("CTR nonce must be exactly 4 bytes")
        data = bytes(data)
        (nonce_word,) = struct.unpack(">I", nonce)
        encrypt_words = self.encrypt_words
        counter = initial_counter

        full_blocks = len(data) // BLOCK_SIZE
        chunks = []
        for seg_start in xrange(0, full_blocks, _SEGMENT_BLOCKS):
            seg_blocks = min(_SEGMENT_BLOCKS, full_blocks - seg_start)
            n_words = 2 * seg_blocks
            offset = seg_start * BLOCK_SIZE
            words = struct.unpack(">%dI" % n_words, data[offset:offset + 4 * n_words])
            out = [0] * n_words
            for i in xrange(0, n_words, 2):
                key_l, key_r = encrypt_words(nonce_word, counter & MASK32)
                out[i] = words[i] ^ key_l
                out[i + 1] = words[i + 1] ^ key_r
                counter += 1
            chunks.append(struct.pack(">%dI" % n_words, *out))

        tail = data[full_blocks * BLOCK_SIZE:]
        if tail:  # last partial block: use only as many keystream bytes as needed
            keystream = struct.pack(">II", *encrypt_words(nonce_word, counter & MASK32))
            chunks.append(_xor_bytes(tail, keystream[:len(tail)]))
        return b"".join(chunks)


# ----------------------------------------------------------------------
# Padding
# ----------------------------------------------------------------------
def pkcs7_pad(data, block_size=BLOCK_SIZE):
    """Append N bytes of value N (1 <= N <= block_size)."""
    pad = block_size - len(data) % block_size
    return bytes(data) + bytes(bytearray([pad] * pad))


def pkcs7_unpad(data, block_size=BLOCK_SIZE):
    data = bytearray(data)
    if not data or len(data) % block_size:
        raise ValueError("Invalid padded data length")
    pad = data[-1]
    if not 1 <= pad <= block_size or data[-pad:] != bytearray([pad] * pad):
        raise ValueError("Invalid PKCS#7 padding")
    return bytes(data[:-pad])


# ----------------------------------------------------------------------
# Splitting data for parallel CTR processing
# ----------------------------------------------------------------------
def split_blocks(length, parts):
    """Split `length` bytes into `parts` contiguous ranges [(start, end), ...].

    Every range starts on an 8-byte block boundary and the numbers of blocks
    differ by at most one, so workers get balanced work. The final partial
    block (if any) belongs to the last non-empty range. Empty ranges are
    omitted when there are fewer blocks than parts.
    """
    if parts < 1:
        raise ValueError("parts must be >= 1")
    n_blocks = (length + BLOCK_SIZE - 1) // BLOCK_SIZE
    base, extra = divmod(n_blocks, parts)
    ranges = []
    block = 0
    for i in xrange(parts):
        count = base + (1 if i < extra else 0)
        if count == 0:
            continue
        start = block * BLOCK_SIZE
        end = min((block + count) * BLOCK_SIZE, length)
        ranges.append((start, end))
        block += count
    return ranges
