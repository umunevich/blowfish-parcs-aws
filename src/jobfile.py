# -*- coding: utf-8 -*-
"""Input file format shared by the sequential program and the PARCS solver.

PARCS-Python accepts exactly one input file per job, so the file carries both
the experiment parameters and the data to encrypt:

    line 1:  BLOWFISH-JOB 1
    line 2:  {"key": "<hex>", "nonce": "<8 hex chars>", "workers": [0, 1, 2],
              "repeats": 3, "name": "..."}          (one line of JSON)
    rest:    raw bytes of the plaintext

"workers" lists the configurations to measure; 0 means the sequential
algorithm (run on the master node), k > 0 means the parallel algorithm with k
workers. Compatible with Python 2.7 and 3.
"""
import binascii
import json

MAGIC = b"BLOWFISH-JOB 1"


def write_job_file(path, data, key, nonce, workers, repeats, name=""):
    header = {
        "key": binascii.hexlify(key).decode("ascii"),
        "nonce": binascii.hexlify(nonce).decode("ascii"),
        "workers": list(workers),
        "repeats": int(repeats),
        "name": name,
    }
    with open(path, "wb") as f:
        f.write(MAGIC + b"\n")
        f.write(json.dumps(header, sort_keys=True).encode("ascii") + b"\n")
        f.write(data)


def read_job_file(path):
    """Return (header, data) where header also has binary "key_bytes"/"nonce_bytes"."""
    with open(path, "rb") as f:
        magic = f.readline().rstrip(b"\r\n")
        if magic != MAGIC:
            raise ValueError("%s is not a Blowfish job file (bad first line)" % path)
        header = json.loads(f.readline().decode("ascii"))
        data = f.read()
    header["key_bytes"] = binascii.unhexlify(str(header["key"]))
    header["nonce_bytes"] = binascii.unhexlify(str(header["nonce"]))
    return header, data
