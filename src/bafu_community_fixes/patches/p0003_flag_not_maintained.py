"""Flag datasets that BAFU no longer maintains."""

import re

from bafu_community_fixes.models import DatasetExtension
from bafu_community_fixes.registry import patch
from bafu_community_fixes.xml import Database

ID = "0003-flag-not-maintained"
NOT_MAINTAINED = "not maintained"


@patch(
    ID,
    authored_by="Claude Code",
    authorised_by="Chris Mutel",
    reported_by="Manuel Klarmann, Eaternity",
    confirmed_by="Marine Manche, BAFU (email, 12 October 2026)",
    references=(
        "https://github.com/sentier-dev/sentier-bafu/issues/4",
        "https://gitlab.com/eos-lci/lci-bafu-catalog/-/issues/15",
    ),
)
def flag_not_maintained(db: Database) -> None:
    """Flag datasets whose name starts with `xx` or `xxx` as not maintained.

    BAFU explained by email (12 October 2026) that these datasets are old and of low
    quality, that users should avoid them, and that they will be moved to a "not
    maintained" category in the next release. This patch only adds the extension
    attribute `maintenance="not maintained"`; names and categories are unchanged.
    """
    for dataset in db:
        if re.match(r"xx", dataset.name):
            if dataset.ext is None:
                dataset.ext = DatasetExtension()
            dataset.ext.maintenance = NOT_MAINTAINED
