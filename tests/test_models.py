import pytest
from pydantic import ValidationError

from bafu_community_fixes.models import Dataset, OutputGroup, UncertaintyType


def test_assignment_is_validated(dataset):
    exchange = dataset.exchanges[0]
    with pytest.raises(ValidationError):
        exchange.mean_value = "1.0"
    with pytest.raises(ValidationError):
        exchange.mean_value = float("nan")
    with pytest.raises(ValidationError):
        exchange.name = "x" * 256
    with pytest.raises(ValidationError):
        exchange.uncertainty_type = 1  # must be UncertaintyType.LOGNORMAL
    exchange.uncertainty_type = UncertaintyType.LOGNORMAL
    exchange.mean_value = 2  # ints are fine for floats


def test_unknown_fields_rejected(dataset):
    with pytest.raises(ValueError):
        dataset.exchanges[0].meanvalue = 1.0


def test_country_code_enumeration(dataset):
    person = dataset.meta_information.administrative_information.persons[0]
    person.country_code = "DE"
    with pytest.raises(ValidationError):
        person.country_code = "XX"


def test_percent_has_one_decimal(dataset):
    representativeness = dataset.meta_information.modelling_and_validation.representativeness
    representativeness.percent = 55.5
    with pytest.raises(ValidationError):
        representativeness.percent = 55.55
    with pytest.raises(ValidationError):
        representativeness.percent = 100.1


def test_exchange_is_input_or_output(dataset):
    exchange = dataset.exchanges[0]
    assert exchange.output_group is OutputGroup.REFERENCE_PRODUCT
    data = exchange.model_dump() | {"input_group": 5}
    with pytest.raises(ValidationError, match="both"):
        type(exchange).model_validate(data, strict=False)


def test_time_period_needs_one_start(dataset):
    time_period = dataset.meta_information.process_information.time_period
    with pytest.raises(ValidationError, match="exactly one start"):
        time_period.start_year = 2020  # start_date is already set


def test_keys_checked_on_revalidation(dataset):
    dataset.exchanges[1].number = dataset.exchanges[0].number
    with pytest.raises(ValidationError, match="Duplicate exchange numbers"):
        Dataset.model_validate(dataset)


def test_keyrefs_checked_on_revalidation(dataset):
    dataset.meta_information.administrative_information.data_entry_by.person = 42
    with pytest.raises(ValidationError, match="dataEntryBy.person refers to 42"):
        Dataset.model_validate(dataset)


def test_shortcuts(dataset):
    assert dataset.name == "Electricity, at plant"
    assert dataset.location == "EURwoCH"
    assert len(dataset.exchanges) == 3
