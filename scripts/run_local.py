#!/usr/bin/env python3
"""Run build/solver.py locally without PARCS, to test the parallel logic.

Each fake "worker" is a separate OS process (like a separate PARCS node), and
the master calls Solver.encrypt_chunk in it -- the same call PARCS makes over
Pyro4. Useful for checking correctness before deploying to the cloud.

Usage:
    python3 scripts/build_solver.py
    python3 scripts/run_local.py data/job_1mb.bin --workers 4 --output results/local.csv
"""
import argparse
import importlib.util
import os
from concurrent.futures import ProcessPoolExecutor

_solver_module = None


def _load(path):
    spec = importlib.util.spec_from_file_location("parcs_solution", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_worker(path):
    global _solver_module
    _solver_module = _load(path)


def _encrypt_chunk(*args):
    return _solver_module.Solver.encrypt_chunk(*args)


class LocalWorker:
    """Mimics a Pyro4 proxy: method call -> executed in another process."""

    def __init__(self, solver_path):
        self.pool = ProcessPoolExecutor(max_workers=1, initializer=_init_worker, initargs=(solver_path,))

    def encrypt_chunk(self, *args):
        return self.pool.submit(_encrypt_chunk, *args).result()

    def close(self):
        self.pool.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="job file from gen_data.py")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--solver", default=os.path.join("build", "solver.py"))
    parser.add_argument("--output", default=os.path.join("results", "local.csv"))
    args = parser.parse_args()

    solver_path = os.path.abspath(args.solver)
    module = _load(solver_path)
    workers = [LocalWorker(solver_path) for _ in range(args.workers)]
    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        module.Solver(workers, args.input, args.output).solve()
    finally:
        for w in workers:
            w.close()
    with open(args.output) as f:
        print(f.read())


if __name__ == "__main__":
    main()
