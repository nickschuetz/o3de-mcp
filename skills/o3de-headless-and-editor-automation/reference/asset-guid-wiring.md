# Part C — Offline asset-GUID wiring (no editor at all)

You can compute an O3DE source-asset GUID offline and write component refs into
prefab/level JSON without launching the editor. This lets you author
script/spawnable/texture/material references deterministically in a batch.

## The algorithm (faithful to the engine)

O3DE's `AZ::Uuid::CreateName(name)` (AzCore/Math/Uuid.inl) is:

1. `SHA1(name_bytes)` — the raw bytes of the name string. **No namespace is
   prepended** (so this is NOT Python's `uuid.uuid5`, which prepends a namespace).
2. Take the first 16 bytes of the 20-byte digest.
3. Set the version nibble to 5 (`m_data[6] = (m_data[6] & 0x5F) | 0x50`).
4. Set the RFC-4122 variant (`m_data[8] = (m_data[8] & 0xBF) | 0x80`).

`CreateName` itself does NOT lowercase. The **asset system** lowercases and
normalizes the path (forward slashes, relative to the scan folder) before calling
it. So for an asset source GUID the input is the lowercased product/relative path,
e.g. `diorama/textures/spark.png`.

## Bundled script

`scripts/compute_asset_guid.py` is a faithful port of the above.

```
python3 ${CLAUDE_SKILL_DIR}/scripts/compute_asset_guid.py "diorama/textures/spark.png"
python3 ${CLAUDE_SKILL_DIR}/scripts/compute_asset_guid.py --raw "BlaBla"   # CreateName on an arbitrary string
python3 ${CLAUDE_SKILL_DIR}/scripts/compute_asset_guid.py --selftest        # algorithm sanity check
```

By default the path argument is lowercased (asset semantics). `--raw` hashes the
string verbatim (matches `Uuid.CreateName("...")` for a non-path string).

## VERIFY ONCE before trusting a batch

The hash port is exact, but the fragile part is the **input string normalization**
for asset paths (scan-folder-relative vs project-relative, separators, extension
case). Before relying on computed GUIDs for a new project:

- Generate one GUID with the editor (or read one the editor already wrote into a
  prefab) for a known asset, and confirm `compute_asset_guid.py` reproduces it for
  the same lowercased path. If it differs, adjust the input path form (that is the
  variable, not the hash).
- Quick independent check of the algorithm: run `Uuid.CreateName("BlaBla")` in any
  O3DE Lua/editor console and compare to `compute_asset_guid.py --raw "BlaBla"`.

## Writing the ref into JSON

A component asset reference in a prefab/level looks like an `AssetId`
(`{guid}:{subId}`) plus a hint path. Use the computed guid for the `guid` field and
the product sub-id (usually `0` for single-product assets like textures/scripts).
Always reopen or load the level after editing to confirm the ref resolves.
