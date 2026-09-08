#!/usr/bin/env python3
# Copyright (c) Contributors to the Open 3D Engine Project.
# SPDX-License-Identifier: Apache-2.0 OR MIT
"""Compute an O3DE source-asset GUID offline (a faithful port of AZ::Uuid::CreateName).

AZ::Uuid::CreateName(name) (AzCore/Math/Uuid.inl) is:
  1. SHA1 over the RAW bytes of `name`. NO namespace is prepended -- this is NOT
     Python's uuid.uuid5 (which prepends a namespace UUID).
  2. Take the first 16 bytes of the 20-byte digest.
  3. Version nibble = 5 : data[6] = (data[6] & 0x5F) | 0x50
  4. RFC-4122 variant  : data[8] = (data[8] & 0xBF) | 0x80

CreateName does not lowercase. The asset system lowercases + normalizes the path
(forward slashes, scan-folder-relative) before calling it, so for an asset source
GUID the input is the lowercased product/relative path, e.g.
"diorama/textures/spark.png".

Usage:
  compute_asset_guid.py "diorama/textures/spark.png"   # path (lowercased) -> guid
  compute_asset_guid.py --raw "BlaBla"                  # CreateName on a verbatim string
  compute_asset_guid.py --selftest                      # algorithm sanity check

VERIFY ONCE per project before trusting a batch: the hash is exact, but the
input-path normalization (scan-folder-relative vs project-relative, separators,
extension case) is the fragile part. Compare one computed GUID against an
editor-generated one for the same asset; if it differs, adjust the input path
form, not the hash. Independent check: Uuid.CreateName("BlaBla") in any O3DE
Lua/editor console should equal `--raw "BlaBla"` below.
"""
import argparse
import hashlib
import sys


def create_name(name: str) -> str:
    """Return the O3DE Uuid::CreateName of `name` as {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX} (uppercase)."""
    digest = hashlib.sha1(name.encode("utf-8")).digest()  # 20 bytes
    data = bytearray(digest[:16])
    data[6] = (data[6] & 0x5F) | 0x50  # version 5 (name-based, SHA1)
    data[8] = (data[8] & 0xBF) | 0x80  # RFC-4122 variant
    h = data.hex().upper()
    return "{%s-%s-%s-%s-%s}" % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute an O3DE source-asset GUID (Uuid::CreateName).")
    ap.add_argument("name", nargs="?", help="asset path (lowercased) or, with --raw, a verbatim string")
    ap.add_argument("--raw", action="store_true", help="hash the string verbatim (no lowercasing)")
    ap.add_argument("--selftest", action="store_true", help="run an internal algorithm check")
    args = ap.parse_args()

    if args.selftest:
        # Determinism + correct version/variant nibbles. (Cross-check the printed
        # BlaBla value against Uuid.CreateName("BlaBla") in an O3DE console.)
        a = create_name("BlaBla")
        b = create_name("BlaBla")
        assert a == b, "not deterministic"
        ver = a[15]          # first hex digit of the 3rd group => version nibble
        variant = a[20]      # first hex digit of the 4th group => variant nibble
        assert ver == "5", f"version nibble is {ver}, expected 5"
        assert variant in "89AB", f"variant nibble is {variant}, expected 8/9/A/B"
        print("selftest OK")
        print(f'  CreateName("BlaBla") = {a}')
        print("  verify in O3DE: Uuid.CreateName(\"BlaBla\") should equal the above")
        return 0

    if not args.name:
        ap.error("provide a name/path, or use --selftest")

    name = args.name if args.raw else args.name.lower()
    print(create_name(name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
