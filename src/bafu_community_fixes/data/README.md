# Supporting data for patches

| File | Used by | Source |
|---|---|---|
| `brightway-flows-corrections-bafu-2026-v1.json` | patches 0004–0008 | [Brightway Flows](https://github.com/brightway-labs/brightway-flows) |
| `brightway-flows-crosswalk-bafu-2026-v1.csv` | patch 0010 | [Brightway Flows](https://github.com/brightway-labs/brightway-flows) |

Brightway Flows is published under the ODbL 1.0. Its author, Chris Mutel, has given
permission (13 October 2026) for this data to be used in this repository, with the
pipeline's output following the BAFU licensing (the BAFU Terms of Use).

Rebuild both files with `uv run python scripts/build_brightway_flows_data.py`. It
downloads everything it needs from public, pinned sources (GitHub and Zenodo) and
checks their hashes; don't edit the files by hand.
