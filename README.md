# bafu-community-fixes

Community-maintained patches for the [BAFU](https://www.bafu.admin.ch/) life cycle
assessment database (UVEK LCI data), distributed as EcoSpold 1 XML.

The pipeline reads the raw release, makes it schema-compliant, applies community patches,
and writes EcoSpold 1 XML again, optionally with additional fields.

## Usage

```sh
uv sync
uv run bafu-fixes list
uv run bafu-fixes run latest output/ --strict --report output/report.html
```

`latest` downloads the latest BAFU release
(<https://files.brightway.dev/bafu-2026-v1-ecospold.zip>, about 37 MB). It's downloaded only
once: it's checked against a known SHA-256 checksum and kept in your user cache folder (on
macOS, `~/Library/Caches/bafu-community-fixes`). You can also pass a local folder or file. A
full `--strict` run with a report takes about a minute.

Or use the terminal app, which needs no command-line knowledge. It uses the latest release
by default, or a folder you pick in its file browser. Choose the output format and options,
tick the patches to apply, and press Run. It shows each step with a progress bar, and opens
the report in your web browser at the end. That last part can be switched off.

```sh
uv run bafu-fixes-tui
```

Options for `run`:

- `--strict`: also check every document against the official EcoSpold 1 XSD after
  import, and every changed dataset after each patch
- `--only ID [ID ...]` / `--skip ID [ID ...]`: choose which patches to apply
- `--no-extensions`: leave out our additional fields, giving plain EcoSpold 1
- `--report FILE.html`: write a run report (see below)
- `--placeholder-year`, `--placeholder-number`, `--placeholder-country`,
  `--placeholder-text`: values filled in where required data is missing (defaults `1111`,
  `1111`, `AQ`, `UNKNOWN`). Blank values are kept, since the schema allows them. Placeholders
  are validated before the run: the text is also used for company codes, so it can be at
  most 7 characters. The terminal app has the same settings.
- `-v`: log progress

## How it works

1. **Parse** the XML and strip the EcoSpold namespace (the raw release has none anyway).
2. **Import fixes** (`import_fixes.py`) make the raw release readable. They work on the
   raw lxml tree, always run, and run in the order they are defined. Run
   `bafu-fixes list` to see them.
3. **Build models** (`models.py`): strict pydantic models that mirror the XSD. Anything
   that doesn't fit stops the run with a list of every problem: unknown attributes or
   elements, invalid values, broken references. With `--strict`, the official XSD is
   checked as well, as an independent second check.
4. **Patches** (`patches/`) run one at a time, in order of their id. After each patch, every
   dataset is revalidated, and any error is reported against that patch. The pipeline
   records the patch id on every dataset it changed.
5. **Write** EcoSpold 1 XML, in schema element order, with canonical number and date
   formatting.

The models are strict. Values must already have the right Python type, unknown fields are
rejected, and assignments are validated as they happen:

```python
exchange.mean_value = "1.5"  # ValidationError: not a float
exchange.name = "x" * 300  # ValidationError: longer than 255 characters
exchange.uncertainty_type = 1  # ValidationError: use UncertaintyType.LOGNORMAL
person.country_code = "XX"  # ValidationError: not an ISO code in the XSD
```

## Run reports

`--report` writes a single, self-contained HTML file, with the Sentier branding and nothing
external to load. It's meant to be shared with data users. It shows:

- which import fixes and patches ran, in order, and who wrote and authorised each one
- a prominent warning for every step that changed data without recorded authorisation
- per step: datasets and values changed, an example from the data showing the XML before and
  after the step, the most common before → after changes for each field, and every
  individual change for the first 10 datasets
- the schema check results, an input fingerprint (SHA-256), options, and software versions

If a run fails, the report is still written, with the error.

## Additional fields

Our own data lives in `<bcf:extensions>` (namespace `urn:bafu-community-fixes:extensions:1`)
at the end of each dataset. The EcoSpold 1 schema allows foreign elements there, so the
output stays valid. Extensions record:

- which import fixes and patches changed each dataset
- the original BAFU number of each renumbered exchange (`originalNumber`). About 30% of
  these match a dataset number, so they may be useful for linking.

In Python they are `dataset.ext` and `exchange.ext`. `--no-extensions` leaves them out.

## Writing a patch

Add a module to `src/bafu_community_fixes/patches/`; it is discovered automatically.

```python
from bafu_community_fixes import Database, data_file, patch
from bafu_community_fixes.models import UncertaintyType


@patch(
    "0011-fix-something",
    authored_by="Jane Doe",  # who wrote this patch
    authorised_by="Chris Mutel",  # who approved it for the release; leave out until then
    reported_by="John Roe, Example AG",  # optional: who found the problem
    confirmed_by="BAFU (email, 1 November 2026)",  # optional: the data owner's confirmation
    references=("https://github.com/sentier-dev/sentier-bafu/issues/1",),
)
def fix_something(db: Database) -> None:
    """One-line description, shown by `bafu-fixes list` and in the report.

    The rest of the docstring explains why the change is needed. It appears in the
    run report, so write it for data users.
    """
    for dataset in db:
        for exchange in dataset.exchanges:
            if exchange.name == "Sulfur dioxide" and exchange.uncertainty_type is None:
                exchange.uncertainty_type = UncertaintyType.LOGNORMAL
```

- Field names are the EcoSpold names in snake_case (`meanValue` becomes `mean_value`).
  `Dataset` also has shortcuts: `name`, `location`, `reference_function`, `exchanges`.
  `db.exchanges()` yields `(dataset, exchange)` pairs.
- Put supporting data in `src/bafu_community_fixes/data/`, prefixed with the patch id, and
  read it with `data_file(name)`.
- Don't record your changes yourself. The pipeline compares every dataset before and after
  your patch and reports each changed value.
- Add a test. `tests/conftest.py` provides an imported fixture database.

## Patches

| Patch | What it does |
|---|---|
| 0001 | Corrects polyethylene disposal for three strawberry datasets (confirmed by BAFU) |
| 0002 | Uses the supplier's location for 25 exchanges (`ENTSO` → `ENTSO-E`, two `CH`; confirmed by BAFU) |
| 0003 | Flags the 1,289 `xx`/`xxx` datasets as not maintained (extension attribute) |
| 0004 | Adds missing CAS numbers to 28 elementary flows (Brightway Flows) |
| 0005 | Replaces CAS numbers naming a different substance, on 17 elementary flows (Brightway Flows) |
| 0006 | Removes CAS numbers naming a different substance, from 3 elementary flows (Brightway Flows) |
| 0007 | Removes units from 3 elementary flow names (Brightway Flows) |
| 0008 | Moves `Carbon dioxide, in air` to the `in air` resource compartment (Brightway Flows) |
| 0009 | Writes elementary flows' CAS numbers zero-padded, and on every exchange of a flow |
| 0010 | Links every elementary exchange to its Brightway Flows flow (extension attributes) |

Patches 0004–0008 change BAFU's own flow attributes and don't depend on 0010, which
only adds links. The Brightway Flows data in `src/bafu_community_fixes/data/` is used
with its author's permission (see the README there); rebuild it from public sources
with `uv run python scripts/build_brightway_flows_data.py`.

## Development

```sh
uv run pytest
BAFU_ECOSPOLD_DIR=path/to/bafu-2026-v1 uv run pytest   # also checks the full release
uv run ruff check && uv run ruff format
```

## License

MIT. The EcoSpold 1 XSD files in `schemas/ecospold1/` are under the EcoSpold Public License.
