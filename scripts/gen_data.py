#!/usr/bin/env python3
"""Generate job files with random plaintext of the given sizes.

Each output file data/job_<N>mb.bin contains the job header (key, nonce,
worker configurations to test, number of repeats) followed by N MiB of
pseudo-random bytes (reproducible with --seed).

Usage:
    python3 scripts/gen_data.py --sizes 1 4 8 16 --workers 0 1 2 3 4 --repeats 3
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from jobfile import write_job_file  # noqa: E402

DEFAULT_KEY = "4c61622d312d426c6f77666973682d4b6579"  # "Lab-1-Blowfish-Key"
DEFAULT_NONCE = "0badc0de"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=float, nargs="+", required=True, help="sizes in MiB")
    parser.add_argument("--workers", type=int, nargs="+", default=[0, 1, 2, 3, 4],
                        help="configurations to measure; 0 = sequential")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--key", default=DEFAULT_KEY, help="hex, 4..56 bytes")
    parser.add_argument("--nonce", default=DEFAULT_NONCE, help="hex, 4 bytes")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    rng = random.Random(args.seed)
    for size_mb in args.sizes:
        n_bytes = int(size_mb * 2 ** 20)
        label = ("%g" % size_mb).replace(".", "_")
        path = os.path.join(args.out_dir, "job_%smb.bin" % label)
        write_job_file(path, rng.randbytes(n_bytes), bytes.fromhex(args.key),
                       bytes.fromhex(args.nonce), args.workers, args.repeats,
                       name="%sMB" % label)
        print("Wrote %s (%d bytes of data)" % (path, n_bytes))


if __name__ == "__main__":
    main()
