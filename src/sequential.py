# -*- coding: utf-8 -*-
"""Sequential Blowfish-CTR encryption of a file on a single node.

Works with Python 2.7 and 3. Accepts either a job file (see jobfile.py) or a
raw file together with --key/--nonce.

Examples:
    python3 src/sequential.py data/job_4mb.bin --repeats 3
    python3 src/sequential.py photo.jpg --key 00112233445566778899aabbccddeeff \
        --nonce 01020304 --out photo.enc
    # CTR is symmetric: running the same command on photo.enc decrypts it.
"""
from __future__ import division, print_function

import argparse
import binascii
import hashlib
import json
import platform
import time

from blowfish import Blowfish
from jobfile import MAGIC, read_job_file


def encrypt_sequential(key, nonce, data):
    """Return (ciphertext, seconds). Key schedule time is included."""
    start = time.time()
    ciphertext = Blowfish(key).ctr_xcrypt(data, nonce, 0)
    return ciphertext, time.time() - start


def load_input(args):
    with open(args.input, "rb") as f:
        is_job = f.readline().rstrip(b"\r\n") == MAGIC
    if is_job:
        header, data = read_job_file(args.input)
        return header["key_bytes"], header["nonce_bytes"], data
    if not (args.key and args.nonce):
        raise SystemExit("raw input files need --key and --nonce")
    with open(args.input, "rb") as f:
        data = f.read()
    return binascii.unhexlify(args.key), binascii.unhexlify(args.nonce), data


def main():
    parser = argparse.ArgumentParser(description="Sequential Blowfish-CTR")
    parser.add_argument("input", help="job file or raw file")
    parser.add_argument("--key", help="hex key (raw input only)")
    parser.add_argument("--nonce", help="4-byte hex nonce (raw input only)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", help="write ciphertext here")
    args = parser.parse_args()

    key, nonce, data = load_input(args)
    for repeat in range(1, args.repeats + 1):
        ciphertext, seconds = encrypt_sequential(key, nonce, data)
        print(json.dumps({
            "python": platform.python_version(),
            "bytes": len(data),
            "repeat": repeat,
            "seconds": round(seconds, 4),
            "mb_per_s": round(len(data) / 2.0 ** 20 / seconds, 4) if seconds else None,
            "sha256": hashlib.sha256(ciphertext).hexdigest(),
        }))
    if args.out:
        with open(args.out, "wb") as f:
            f.write(ciphertext)


if __name__ == "__main__":
    main()
