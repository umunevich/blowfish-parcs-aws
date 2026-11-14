#!/usr/bin/env python3
"""Run a series of experiments on a PARCS-Python master and collect a CSV.

For every job file it submits a PARCS job (solver + input) through the
master's HTTP API, waits for it to finish, downloads the output CSV and
appends the rows to results/raw_results.csv. Then it prints and saves
mean values per (data size, number of workers) to results/summary.csv.

Only the Python 3 standard library is used, so it runs on the master VM
(Ubuntu) as well as on your PC.

Usage (on the master VM, where the web UI is http://localhost:8080):
    python3 scripts/run_experiments.py --master http://localhost:8080 \
        --solver build/solver.py data/job_*.bin
"""
import argparse
import csv
import io
import os
import re
import statistics
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict


def http(method, url, body=None, headers=None, timeout=600):
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def multipart(fields, files):
    """Encode form fields and files as multipart/form-data."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, name, value)).encode())
    for name, path in files.items():
        with open(path, "rb") as f:
            content = f.read()
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                      "Content-Type: application/octet-stream\r\n\r\n"
                      % (boundary, name, os.path.basename(path))).encode())
        parts.append(content + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    return b"".join(parts), "multipart/form-data; boundary=%s" % boundary


def job_ids(master):
    html = http("GET", master + "/jobs").decode("utf-8", "replace")
    return {int(x) for x in re.findall(r'data-job-id="(\d+)"', html)}


def submit_and_wait(master, solver, job_file, poll, timeout):
    before = job_ids(master)
    body, content_type = multipart(
        {"job_name": "blowfish-" + os.path.basename(job_file)},
        {"solution_file": solver, "input_file": job_file})
    http("POST", master + "/api/job", body, {"Content-Type": content_type})
    new = job_ids(master) - before
    if len(new) != 1:
        raise RuntimeError("could not identify the new job id (found %s)" % sorted(new))
    job_id = new.pop()
    print("  job #%d submitted, waiting..." % job_id, flush=True)

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return job_id, http("GET", "%s/api/job/%d/output" % (master, job_id)).decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:  # job ended but produced no output -> failed
                raise RuntimeError("job #%d failed; see the Jobs page / master logs" % job_id)
            time.sleep(poll)  # 400 = still running
    raise RuntimeError("job #%d did not finish in %d s" % (job_id, timeout))


def parse_output(text):
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    comments = [line for line in text.splitlines() if line.startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(lines)))), comments


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(int(row["size_bytes"]), int(row["workers"]))].append(row)
    metrics = ["total_s", "compute_max_s", "overhead_s", "prepare_s", "wait_s", "merge_s"]
    summary = []
    for (size, workers), items in sorted(groups.items()):
        entry = {"size_bytes": size, "workers": workers, "runs": len(items),
                 "all_match_sequential": int(all(r["matches_sequential"] == "1" for r in items))}
        for m in metrics:
            values = [float(r[m]) for r in items]
            entry[m + "_mean"] = statistics.mean(values)
            entry[m + "_std"] = statistics.stdev(values) if len(values) > 1 else 0.0
        summary.append(entry)
    return summary


def write_csv(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_files", nargs="+")
    parser.add_argument("--master", default="http://localhost:8080")
    parser.add_argument("--solver", default=os.path.join("build", "solver.py"))
    parser.add_argument("--raw-out", default=os.path.join("results", "raw_results.csv"))
    parser.add_argument("--summary-out", default=os.path.join("results", "summary.csv"))
    parser.add_argument("--poll", type=float, default=3.0)
    parser.add_argument("--timeout", type=int, default=3 * 3600, help="per job, seconds")
    args = parser.parse_args()
    master = args.master.rstrip("/")

    workers = http("GET", master + "/api/worker").decode()
    print("Workers registered on master: %s" % workers.count('"ip"'))

    all_rows = []
    for job_file in args.job_files:
        print("Running %s" % job_file, flush=True)
        job_id, output = submit_and_wait(master, args.solver, job_file, args.poll, args.timeout)
        rows, comments = parse_output(output)
        for comment in comments:
            print("  " + comment)
        for row in rows:
            row["job_id"] = job_id
            row["job_file"] = os.path.basename(job_file)
        all_rows.extend(rows)
        write_csv(args.raw_out, all_rows)  # save after every job
        print("  %d rows saved to %s" % (len(rows), args.raw_out))

    summary = summarize(all_rows)
    write_csv(args.summary_out, summary)
    print("\nsize_MB  workers  total_mean_s  overhead_mean_s  match")
    for s in summary:
        print("%7.1f  %7d  %12.3f  %15.3f  %5d" % (s["size_bytes"] / 2 ** 20, s["workers"],
                                                    s["total_s_mean"], s["overhead_s_mean"],
                                                    s["all_match_sequential"]))
    print("Summary saved to %s" % args.summary_out)


if __name__ == "__main__":
    main()
