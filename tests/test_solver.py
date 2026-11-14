"""End-to-end test of the PARCS solver without PARCS.

Builds the self-contained build/solver.py, runs Solver.solve() with in-process
fake workers and checks that every parallel configuration produces exactly the
same ciphertext (SHA-256) as the sequential algorithm.
"""
import csv
import hashlib
import importlib.util

import build_solver
from blowfish import Blowfish
from jobfile import read_job_file, write_job_file


class FakeWorker:
    """Stands in for a Pyro4 proxy: calls the exposed method directly."""

    def __init__(self, module):
        self.solver = module.Solver()

    def encrypt_chunk(self, *args):
        return self.solver.encrypt_chunk(*args)


def _load_solver(tmp_path):
    path = build_solver.build(str(tmp_path / "solver.py"))
    spec = importlib.util.spec_from_file_location("built_solver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_jobfile_roundtrip(tmp_path):
    path = tmp_path / "job.bin"
    write_job_file(str(path), b"\x00\n\xffdata", b"key!", b"\x01\x02\x03\x04", [0, 2], 3, "t")
    header, data = read_job_file(str(path))
    assert data == b"\x00\n\xffdata"
    assert header["key_bytes"] == b"key!" and header["nonce_bytes"] == b"\x01\x02\x03\x04"
    assert header["workers"] == [0, 2] and header["repeats"] == 3


def test_solver_parallel_matches_sequential(tmp_path):
    module = _load_solver(tmp_path)
    data = bytes(range(256)) * 40 + b"tail!"  # not a multiple of 8
    key, nonce = b"solver-test-key", b"\xca\xfe\xba\xbe"
    job = tmp_path / "job.bin"
    write_job_file(str(job), data, key, nonce, [0, 1, 2, 3, 5], 2, "test")
    out = tmp_path / "out.csv"

    workers = [FakeWorker(module) for _ in range(3)]
    module.Solver(workers, str(job), str(out)).solve()

    text = out.read_text()
    assert "skipped workers=5" in text
    rows = list(csv.DictReader(line for line in text.splitlines() if not line.startswith("#")))
    assert [int(r["workers"]) for r in rows] == [0, 0, 1, 1, 2, 2, 3, 3]
    expected = hashlib.sha256(Blowfish(key).ctr_xcrypt(data, nonce)).hexdigest()
    assert all(r["sha256"] == expected and r["matches_sequential"] == "1" for r in rows)
