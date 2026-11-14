# -*- coding: utf-8 -*-
"""PARCS-Python solver: parallel Blowfish-CTR encryption.

This is a TEMPLATE. PARCS uploads a single solution file to the master and to
every worker, so `scripts/build_solver.py` inlines blowfish_constants.py,
blowfish.py and jobfile.py at the @@INLINE-MODULES@@ marker and writes the
self-contained build/solver.py, which is what you upload to PARCS.

How PARCS-Python (github.com/Hummer12007/parcs-python) runs it:
  * master: Solver(workers, input_file_name, output_file_name).solve(),
    where `workers` is a list of Pyro4 proxies, one per enabled worker node;
  * worker: Solver() is registered in a Pyro4 daemon, and methods marked
    with @expose (encrypt_chunk) can be called remotely by the master.

Parallel algorithm (master side, k workers):
  1. split the plaintext into k contiguous ranges aligned to 8-byte blocks
     (split_blocks); range i starts at byte offset s_i;
  2. send range i to worker i together with the key, the nonce and the
     initial CTR counter s_i / 8 (data is base64-encoded: Pyro4 serialises
     text more reliably than binary strings under Python 2);
  3. every worker encrypts its range independently (CTR blocks do not depend
     on each other) and returns ciphertext + its pure compute time;
  4. the master concatenates the pieces in the order of the ranges.
The result is byte-for-byte equal to the sequential encryption, which is
checked by comparing SHA-256 digests.

Python 2.7 / 3 compatible.
"""
from __future__ import division, print_function

import base64
import binascii
import hashlib
import platform
import socket
import threading
import time

try:
    from Pyro4 import expose
except ImportError:  # running locally without Pyro4 (scripts/run_local.py)
    def expose(func):
        return func

from blowfish import Blowfish, split_blocks  # @@INLINE-IMPORT
from jobfile import read_job_file  # @@INLINE-IMPORT

# @@INLINE-MODULES@@

CSV_COLUMNS = [
    "size_bytes", "workers", "repeat",
    "total_s",             # full wall time of one encryption run on the master
    "prepare_s",           # splitting + base64 encoding on the master
    "wait_s",              # from sending the first chunk to receiving the last result
    "merge_s",             # base64 decoding + concatenation on the master
    "compute_max_s",       # slowest worker's pure encryption time
    "compute_sum_s",       # sum of pure encryption times of all workers
    "worker_codec_max_s",  # max base64 decode/encode time on a worker
    "overhead_s",          # total_s - compute_max_s: everything that is not encryption
    "throughput_mb_s",
    "sha256",
    "matches_sequential",
]


def _b64encode(data):
    return base64.b64encode(data).decode("ascii")


def _resolve(result):
    """Pyro4 async proxies return FutureResult objects; plain calls return values."""
    return result.value if hasattr(result, "value") else result


class Solver:
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.workers = workers or []
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name

    # ------------------------------------------------------------------
    # Master side
    # ------------------------------------------------------------------
    def solve(self):
        print("Blowfish job started; %d workers available" % len(self.workers))
        header, data = read_job_file(self.input_file_name)
        key, nonce = header["key_bytes"], header["nonce_bytes"]
        counts = header.get("workers") or [0] + list(range(1, len(self.workers) + 1))
        repeats = int(header.get("repeats", 3))

        # Untimed warm-up: opens Pyro4 connections and loads code on every
        # worker, so that the first measured repeat is not penalised.
        if self.workers:
            self.run_parallel(len(self.workers), key, nonce, data[:8 * len(self.workers)])

        rows = []
        notes = []
        reference = None
        for k in counts:
            if k > len(self.workers):
                notes.append("skipped workers=%d: only %d workers available" % (k, len(self.workers)))
                continue
            for repeat in range(1, repeats + 1):
                if k == 0:
                    ciphertext, row = self.run_sequential(key, nonce, data)
                else:
                    ciphertext, row = self.run_parallel(k, key, nonce, data)
                digest = hashlib.sha256(ciphertext).hexdigest()
                if k == 0 and reference is None:
                    reference = digest
                row.update(size_bytes=len(data), workers=k, repeat=repeat, sha256=digest)
                row["throughput_mb_s"] = len(data) / 2.0 ** 20 / row["total_s"] if row["total_s"] else 0
                rows.append(row)
                print("workers=%d repeat=%d total=%.3fs" % (k, repeat, row["total_s"]))
                del ciphertext

        if reference is None:  # no sequential run requested: compute it once, untimed
            reference = hashlib.sha256(Blowfish(key).ctr_xcrypt(data, nonce, 0)).hexdigest()
        for row in rows:
            row["matches_sequential"] = int(row["sha256"] == reference)

        self.write_output(header, rows, notes)
        print("Blowfish job finished")

    def run_sequential(self, key, nonce, data):
        start = time.time()
        ciphertext = Blowfish(key).ctr_xcrypt(data, nonce, 0)
        total = time.time() - start
        return ciphertext, {
            "total_s": total, "prepare_s": 0.0, "wait_s": 0.0, "merge_s": 0.0,
            "compute_max_s": total, "compute_sum_s": total,
            "worker_codec_max_s": 0.0, "overhead_s": 0.0,
        }

    def run_parallel(self, k, key, nonce, data):
        key_hex = binascii.hexlify(key).decode("ascii")
        nonce_hex = binascii.hexlify(nonce).decode("ascii")

        t_start = time.time()
        ranges = split_blocks(len(data), k)
        payloads = [_b64encode(data[s:e]) for s, e in ranges]
        t_sent = time.time()

        # One thread per worker: works no matter whether PARCS hands us
        # synchronous or asynchronous Pyro4 proxies.
        results = [None] * len(ranges)
        errors = []

        def call(i):
            try:
                start, _ = ranges[i]
                results[i] = _resolve(self.workers[i].encrypt_chunk(
                    key_hex, nonce_hex, start // 8, payloads[i]))
            except Exception as e:  # report in the master thread
                errors.append("worker %d: %r" % (i, e))

        threads = [threading.Thread(target=call, args=(i,)) for i in range(len(ranges))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if errors:
            raise RuntimeError("; ".join(errors))
        t_received = time.time()

        ciphertext = b"".join(base64.b64decode(r[0]) for r in results)
        t_end = time.time()

        compute = [float(r[1]) for r in results]
        codec = [float(r[2]) for r in results]
        total = t_end - t_start
        return ciphertext, {
            "total_s": total,
            "prepare_s": t_sent - t_start,
            "wait_s": t_received - t_sent,
            "merge_s": t_end - t_received,
            "compute_max_s": max(compute),
            "compute_sum_s": sum(compute),
            "worker_codec_max_s": max(codec),
            "overhead_s": total - max(compute),
        }

    def write_output(self, header, rows, notes):
        with open(self.output_file_name, "w") as f:
            f.write("# job=%s python=%s host=%s workers_available=%d\n" % (
                header.get("name", ""), platform.python_version(),
                socket.gethostname(), len(self.workers)))
            for note in notes:
                f.write("# %s\n" % note)
            f.write(",".join(CSV_COLUMNS) + "\n")
            for row in rows:
                values = []
                for col in CSV_COLUMNS:
                    value = row[col]
                    values.append("%.6f" % value if isinstance(value, float) else str(value))
                f.write(",".join(values) + "\n")

    # ------------------------------------------------------------------
    # Worker side (called remotely through Pyro4)
    # ------------------------------------------------------------------
    @staticmethod
    @expose
    def encrypt_chunk(key_hex, nonce_hex, initial_counter, data_b64):
        """Encrypt one range; returns [ciphertext_b64, compute_s, codec_s]."""
        t0 = time.time()
        chunk = base64.b64decode(data_b64)
        t1 = time.time()
        cipher = Blowfish(binascii.unhexlify(str(key_hex)))
        encrypted = cipher.ctr_xcrypt(chunk, binascii.unhexlify(str(nonce_hex)), int(initial_counter))
        t2 = time.time()
        encoded = _b64encode(encrypted)
        t3 = time.time()
        return [encoded, t2 - t1, (t1 - t0) + (t3 - t2)]
