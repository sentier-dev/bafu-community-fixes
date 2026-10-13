"""Pydantic models for EcoSpold 1, following `schemas/ecospold1/*.xsd`.

All models are strict:

* Field values must already have the right Python type (no `"1.5"` for a float).
* Unknown fields are rejected.
* Assignment is validated (`exchange.mean_value = "x"` raises immediately).
* XSD facets are enforced: string lengths, patterns, ranges, enumerations, and
  the key/keyref constraints between persons, sources and exchanges.

Constraints that span objects are checked by `Dataset`'s validator. That validator
doesn't run when you change a nested object directly, so the pipeline revalidates
each dataset after every patch.

Two deliberate restrictions go beyond the XSD: exactly one `flowData` per dataset
(the XSD allows several, BAFU uses one), and dates without timezones.

Each field declares how it maps to XML with `Attr`, `Text` or `Child` metadata.
`xml.py` uses that to read and write documents, so this file is the single
source of truth for the format.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import IntEnum
from typing import Annotated, ClassVar, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from bafu_community_fixes.xsd import (
    BOOLEAN,
    DATE,
    DATETIME,
    DOUBLE,
    GYEAR,
    INTEGER,
    PERCENT,
    STRING,
    enumeration,
    int_enum,
)

ECOSPOLD_NS = "http://www.EcoInvent.org/EcoSpold01"
EXT_NS = "urn:bafu-community-fixes:extensions:1"


# --- XML mapping markers ---------------------------------------------------------


@dataclass(frozen=True)
class Attr:
    """Field is the XML attribute `name`."""

    name: str


@dataclass(frozen=True)
class Text:
    """Field is the text of child element(s) `tag`."""

    tag: str


@dataclass(frozen=True)
class Child:
    """Field is complex child element(s) `tag`."""

    tag: str


# --- Simple types ------------------------------------------------------------------


def _member_of(simple_type: str):
    def check(value: str) -> str:
        if value not in enumeration(simple_type):
            raise ValueError(f"{value!r} is not in the XSD enumeration {simple_type}")
        return value

    return AfterValidator(check)


def _one_decimal(value: float) -> float:
    if round(value, 1) != value:
        raise ValueError(f"{value} has more than one decimal place")
    return value


String20 = Annotated[str, Field(max_length=20), STRING]
String30 = Annotated[str, Field(max_length=30), STRING]
String40 = Annotated[str, Field(max_length=40), STRING]
String80 = Annotated[str, Field(max_length=80), STRING]
String255 = Annotated[str, Field(max_length=255), STRING]
String32000 = Annotated[str, Field(max_length=32000), STRING]
PageNumbers = Annotated[str, Field(max_length=15), STRING]
Unit = Annotated[str, Field(max_length=20), STRING]
CompanyCode = Annotated[str, Field(max_length=7), STRING]
RegionalCode = Annotated[str, Field(max_length=7), STRING]
CategoryName = Annotated[str, Field(max_length=255), STRING]
CASNumber = Annotated[str, Field(max_length=12, pattern=r"^\d{2,7}-\d{2}-\d$"), STRING]
Version = Annotated[str, Field(pattern=r"^(\d{1,4}|\d{1,2}\.\d{0,2})$"), STRING]
InternalVersion = Annotated[str, Field(pattern=r"^\d{1,3}\.\d{1,2}$"), STRING]
AnyString = Annotated[str, STRING]
IndexNumber = Annotated[int, Field(ge=1, le=2**31 - 1), INTEGER]
Integer = Annotated[int, INTEGER]
DatasetType = Annotated[int, Field(ge=0, le=5), INTEGER]
EnergyValues = Annotated[int, Field(ge=0, le=2), INTEGER]
DataPublishedIn = Annotated[int, Field(ge=0, le=2), INTEGER]
AccessRestrictedTo = Annotated[int, Field(ge=0, le=3), INTEGER]
SourceType = Annotated[int, Field(ge=0, le=7), INTEGER]
AllocationMethod = Annotated[int, Field(ge=-1, le=2), INTEGER]
VolumeNo = Annotated[int, Field(ge=0, le=999), INTEGER]
StatisticalClassification = Annotated[int, Field(ge=0, le=99_999_999), INTEGER]
Double = Annotated[float, Field(allow_inf_nan=False), DOUBLE]
Boolean = Annotated[bool, BOOLEAN]
CountryCode = Annotated[str, _member_of("TISOCountryCode"), STRING]
LanguageCode = Annotated[str, _member_of("TISOLanguageCode"), STRING]
Percent = Annotated[float, Field(ge=0, le=100), AfterValidator(_one_decimal), PERCENT]
Year = Annotated[int, Field(ge=0, le=9999), GYEAR]
YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), STRING]
Date = Annotated[date, DATE]
DateTime = Annotated[datetime, DATETIME]


class UncertaintyType(IntEnum):
    UNDEFINED = 0
    LOGNORMAL = 1
    NORMAL = 2
    TRIANGULAR = 3
    UNIFORM = 4


class InputGroup(IntEnum):
    MATERIALS_FUELS = 1
    ELECTRICITY_HEAT = 2
    SERVICES = 3
    FROM_NATURE = 4
    FROM_TECHNOSPHERE = 5


class OutputGroup(IntEnum):
    REFERENCE_PRODUCT = 0
    AVOIDED_PRODUCT = 1
    ALLOCATED_BYPRODUCT = 2
    WASTE_TO_TREATMENT = 3
    TO_NATURE = 4


# --- Models ------------------------------------------------------------------------


class Model(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        validate_assignment=True,
        revalidate_instances="always",
    )
    xml_namespace: ClassVar[str] = ECOSPOLD_NS


# Extensions: our own data, written to `<bcf:extensions>` at the end of each dataset
# (the XSD allows elements from other namespaces there). Dropped by `--no-extensions`.


class Extension(Model):
    xml_namespace: ClassVar[str] = EXT_NS


class ExchangeExtension(Extension):
    original_number: Annotated[AnyString | None, Attr("originalNumber")] = None
    # The corresponding brightway-flows elementary flow, and how close the match is
    # (SKOS: exactMatch, closeMatch or broadMatch)
    brightway_flow: Annotated[AnyString | None, Attr("brightwayFlow")] = None
    brightway_match: Annotated[AnyString | None, Attr("brightwayMatch")] = None


class DatasetExtension(Extension):
    maintenance: Annotated[AnyString | None, Attr("maintenance")] = None
    import_fixes: Annotated[list[AnyString], Text("importFix")] = []
    patches: Annotated[list[AnyString], Text("patch")] = []


class Person(Model):
    number: Annotated[IndexNumber, Attr("number")]
    name: Annotated[String40, Attr("name")]
    address: Annotated[String255, Attr("address")]
    telephone: Annotated[String40 | None, Attr("telephone")] = None
    telefax: Annotated[String40 | None, Attr("telefax")] = None
    email: Annotated[String80 | None, Attr("email")] = None
    company_code: Annotated[CompanyCode, Attr("companyCode")]
    country_code: Annotated[CountryCode, Attr("countryCode")]


class ReferenceFunction(Model):
    synonyms: Annotated[list[String255], Text("synonym")] = []
    dataset_relates_to_product: Annotated[Boolean, Attr("datasetRelatesToProduct")]
    name: Annotated[String255, Attr("name")]
    local_name: Annotated[String255, Attr("localName")]
    infrastructure_process: Annotated[Boolean, Attr("infrastructureProcess")]
    amount: Annotated[Double, Attr("amount")]
    unit: Annotated[Unit, Attr("unit")]
    category: Annotated[CategoryName, Attr("category")]
    sub_category: Annotated[CategoryName, Attr("subCategory")]
    local_category: Annotated[CategoryName, Attr("localCategory")]
    local_sub_category: Annotated[CategoryName, Attr("localSubCategory")]
    included_processes: Annotated[String32000 | None, Attr("includedProcesses")] = None
    general_comment: Annotated[String32000 | None, Attr("generalComment")] = None
    infrastructure_included: Annotated[Boolean | None, Attr("infrastructureIncluded")] = None
    cas_number: Annotated[CASNumber | None, Attr("CASNumber")] = None
    statistical_classification: Annotated[
        StatisticalClassification | None, Attr("statisticalClassification")
    ] = None
    formula: Annotated[String40 | None, Attr("formula")] = None


class Geography(Model):
    location: Annotated[RegionalCode, Attr("location")]
    text: Annotated[String32000 | None, Attr("text")] = None


class Technology(Model):
    text: Annotated[String32000 | None, Attr("text")] = None


class TimePeriod(Model):
    start_year: Annotated[Year | None, Text("startYear")] = None
    start_year_month: Annotated[YearMonth | None, Text("startYearMonth")] = None
    start_date: Annotated[Date | None, Text("startDate")] = None
    end_year: Annotated[Year | None, Text("endYear")] = None
    end_year_month: Annotated[YearMonth | None, Text("endYearMonth")] = None
    end_date: Annotated[Date | None, Text("endDate")] = None
    data_valid_for_entire_period: Annotated[Boolean, Attr("dataValidForEntirePeriod")]
    text: Annotated[String32000 | None, Attr("text")] = None

    @model_validator(mode="after")
    def _one_start_and_one_end(self) -> Self:
        for side in ("start", "end"):
            given = [
                f"{side}_{kind}"
                for kind in ("year", "year_month", "date")
                if getattr(self, f"{side}_{kind}") is not None
            ]
            if len(given) != 1:
                raise ValueError(f"Need exactly one {side} value, got {given or 'none'}")
        return self


class DataSetInformation(Model):
    type: Annotated[DatasetType, Attr("type")]
    impact_assessment_result: Annotated[Boolean, Attr("impactAssessmentResult")]
    timestamp: Annotated[DateTime, Attr("timestamp")]
    version: Annotated[Version, Attr("version")]
    internal_version: Annotated[InternalVersion, Attr("internalVersion")]
    energy_values: Annotated[EnergyValues, Attr("energyValues")]
    language_code: Annotated[LanguageCode | None, Attr("languageCode")] = None
    local_language_code: Annotated[LanguageCode | None, Attr("localLanguageCode")] = None


class ProcessInformation(Model):
    reference_function: Annotated[ReferenceFunction, Child("referenceFunction")]
    geography: Annotated[Geography, Child("geography")]
    technology: Annotated[Technology, Child("technology")]
    time_period: Annotated[TimePeriod, Child("timePeriod")]
    data_set_information: Annotated[DataSetInformation, Child("dataSetInformation")]


class Representativeness(Model):
    percent: Annotated[Percent | None, Attr("percent")] = None
    production_volume: Annotated[String32000 | None, Attr("productionVolume")] = None
    sampling_procedure: Annotated[String32000 | None, Attr("samplingProcedure")] = None
    extrapolations: Annotated[String32000 | None, Attr("extrapolations")] = None
    uncertainty_adjustments: Annotated[String32000 | None, Attr("uncertaintyAdjustments")] = None


class Source(Model):
    number: Annotated[IndexNumber, Attr("number")]
    source_type: Annotated[SourceType | None, Attr("sourceType")] = None
    first_author: Annotated[String40, Attr("firstAuthor")]
    additional_authors: Annotated[String255 | None, Attr("additionalAuthors")] = None
    year: Annotated[Year, Attr("year")]
    title: Annotated[String32000, Attr("title")]
    page_numbers: Annotated[PageNumbers | None, Attr("pageNumbers")] = None
    name_of_editors: Annotated[String40 | None, Attr("nameOfEditors")] = None
    title_of_anthology: Annotated[String255 | None, Attr("titleOfAnthology")] = None
    place_of_publications: Annotated[String40, Attr("placeOfPublications")]
    publisher: Annotated[String40 | None, Attr("publisher")] = None
    journal: Annotated[String40 | None, Attr("journal")] = None
    volume_no: Annotated[VolumeNo | None, Attr("volumeNo")] = None
    issue_no: Annotated[String40 | None, Attr("issueNo")] = None
    text: Annotated[String32000 | None, Attr("text")] = None


class Validation(Model):
    proof_reading_details: Annotated[String32000, Attr("proofReadingDetails")]
    proof_reading_validator: Annotated[IndexNumber, Attr("proofReadingValidator")]
    other_details: Annotated[String32000 | None, Attr("otherDetails")] = None


class ModellingAndValidation(Model):
    representativeness: Annotated[Representativeness | None, Child("representativeness")] = None
    sources: Annotated[list[Source], Field(min_length=1), Child("source")]
    validation: Annotated[Validation | None, Child("validation")] = None


class DataEntryBy(Model):
    person: Annotated[IndexNumber, Attr("person")]
    quality_network: Annotated[Integer | None, Attr("qualityNetwork")] = None


class DataGeneratorAndPublication(Model):
    person: Annotated[IndexNumber, Attr("person")]
    data_published_in: Annotated[DataPublishedIn | None, Attr("dataPublishedIn")] = None
    reference_to_published_source: Annotated[
        IndexNumber | None, Attr("referenceToPublishedSource")
    ] = None
    copyright: Annotated[Boolean, Attr("copyright")]
    access_restricted_to: Annotated[AccessRestrictedTo | None, Attr("accessRestrictedTo")] = None
    company_code: Annotated[CompanyCode | None, Attr("companyCode")] = None
    country_code: Annotated[CountryCode | None, Attr("countryCode")] = None
    page_numbers: Annotated[String30 | None, Attr("pageNumbers")] = None


class AdministrativeInformation(Model):
    data_entry_by: Annotated[DataEntryBy, Child("dataEntryBy")]
    data_generator_and_publication: Annotated[
        DataGeneratorAndPublication, Child("dataGeneratorAndPublication")
    ]
    persons: Annotated[list[Person], Field(min_length=1), Child("person")]


class MetaInformation(Model):
    process_information: Annotated[ProcessInformation, Child("processInformation")]
    modelling_and_validation: Annotated[ModellingAndValidation, Child("modellingAndValidation")]
    administrative_information: Annotated[
        AdministrativeInformation, Child("administrativeInformation")
    ]


class Exchange(Model):
    input_group: Annotated[InputGroup | None, int_enum(InputGroup), Text("inputGroup")] = None
    output_group: Annotated[OutputGroup | None, int_enum(OutputGroup), Text("outputGroup")] = None
    number: Annotated[IndexNumber, Attr("number")]
    category: Annotated[CategoryName | None, Attr("category")] = None
    sub_category: Annotated[CategoryName | None, Attr("subCategory")] = None
    local_category: Annotated[CategoryName | None, Attr("localCategory")] = None
    local_sub_category: Annotated[CategoryName | None, Attr("localSubCategory")] = None
    cas_number: Annotated[CASNumber | None, Attr("CASNumber")] = None
    name: Annotated[String255, Attr("name")]
    location: Annotated[RegionalCode | None, Attr("location")] = None
    unit: Annotated[Unit, Attr("unit")]
    mean_value: Annotated[Double, Attr("meanValue")]
    uncertainty_type: Annotated[
        UncertaintyType | None, int_enum(UncertaintyType), Attr("uncertaintyType")
    ] = None
    standard_deviation95: Annotated[Double | None, Attr("standardDeviation95")] = None
    formula: Annotated[String40 | None, Attr("formula")] = None
    reference_to_source: Annotated[IndexNumber | None, Attr("referenceToSource")] = None
    page_numbers: Annotated[String30 | None, Attr("pageNumbers")] = None
    general_comment: Annotated[String32000 | None, Attr("generalComment")] = None
    local_name: Annotated[String80 | None, Attr("localName")] = None
    infrastructure_process: Annotated[Boolean | None, Attr("infrastructureProcess")] = None
    min_value: Annotated[Double | None, Attr("minValue")] = None
    max_value: Annotated[Double | None, Attr("maxValue")] = None
    most_likely_value: Annotated[Double | None, Attr("mostLikelyValue")] = None

    ext: ExchangeExtension | None = None

    @property
    def is_elementary(self) -> bool:
        """From or to nature, rather than from or to another process."""
        return (
            self.input_group == InputGroup.FROM_NATURE or self.output_group == OutputGroup.TO_NATURE
        )

    @model_validator(mode="after")
    def _input_or_output(self) -> Self:
        if self.input_group is not None and self.output_group is not None:
            raise ValueError("An exchange can't have both an inputGroup and an outputGroup")
        return self


class Allocation(Model):
    reference_to_input_output: Annotated[list[IndexNumber], Text("referenceToInputOutput")] = []
    reference_to_co_product: Annotated[IndexNumber, Attr("referenceToCoProduct")]
    allocation_method: Annotated[AllocationMethod | None, Attr("allocationMethod")] = None
    fraction: Annotated[Double, Attr("fraction")]
    explanations: Annotated[String32000 | None, Attr("explanations")] = None


class FlowData(Model):
    exchanges: Annotated[list[Exchange], Field(min_length=1), Child("exchange")]
    allocations: Annotated[list[Allocation], Child("allocation")] = []


def _unique(numbers: list[int], what: str) -> set[int]:
    if len(set(numbers)) != len(numbers):
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
        raise ValueError(f"Duplicate {what} numbers: {duplicates}")
    return set(numbers)


def _refers(value: int | None, targets: set[int], what: str) -> None:
    if value is not None and value not in targets:
        raise ValueError(f"{what} refers to {value}, which doesn't exist")


class Dataset(Model):
    meta_information: Annotated[MetaInformation, Child("metaInformation")]
    flow_data: Annotated[FlowData, Child("flowData")]
    number: Annotated[IndexNumber, Attr("number")]
    internal_schema_version: Annotated[AnyString | None, Attr("internalSchemaVersion")] = None
    generator: Annotated[String255, Attr("generator")]
    timestamp: Annotated[DateTime, Attr("timestamp")]
    valid_company_codes: Annotated[AnyString | None, Attr("validCompanyCodes")] = None
    valid_regional_codes: Annotated[AnyString | None, Attr("validRegionalCodes")] = None
    valid_categories: Annotated[AnyString | None, Attr("validCategories")] = None
    valid_units: Annotated[AnyString | None, Attr("validUnits")] = None

    ext: DatasetExtension | None = None

    # Shortcuts for the paths patches use most.
    @property
    def reference_function(self) -> ReferenceFunction:
        return self.meta_information.process_information.reference_function

    @property
    def exchanges(self) -> list[Exchange]:
        return self.flow_data.exchanges

    @property
    def name(self) -> str:
        return self.reference_function.name

    @property
    def location(self) -> str:
        return self.meta_information.process_information.geography.location

    @model_validator(mode="after")
    def _keys(self) -> Self:
        """The key and keyref constraints from the XSD's `dataset` element."""
        meta, flow = self.meta_information, self.flow_data
        admin = meta.administrative_information
        persons = _unique([p.number for p in admin.persons], "person")
        sources = _unique([s.number for s in meta.modelling_and_validation.sources], "source")
        exchanges = _unique([e.number for e in flow.exchanges], "exchange")
        _refers(admin.data_entry_by.person, persons, "dataEntryBy.person")
        dgp = admin.data_generator_and_publication
        _refers(dgp.person, persons, "dataGeneratorAndPublication.person")
        _refers(
            dgp.reference_to_published_source,
            sources,
            "dataGeneratorAndPublication.referenceToPublishedSource",
        )
        if (validation := meta.modelling_and_validation.validation) is not None:
            _refers(validation.proof_reading_validator, persons, "validation.proofReadingValidator")
        for exchange in flow.exchanges:
            _refers(exchange.reference_to_source, sources, f"exchange {exchange.number} source")
        for allocation in flow.allocations:
            _refers(allocation.reference_to_co_product, exchanges, "allocation co-product")
            for number in allocation.reference_to_input_output:
                _refers(number, exchanges, "allocation referenceToInputOutput")
        return self


class EcoSpold(Model):
    """One EcoSpold 1 document (file), with one or more datasets."""

    datasets: Annotated[list[Dataset], Field(min_length=1), Child("dataset")]
    validation_id: Annotated[Integer | None, Attr("validationId")] = None
    validation_status: Annotated[AnyString | None, Attr("validationStatus")] = None

    @model_validator(mode="after")
    def _unique_numbers(self) -> Self:
        _unique([d.number for d in self.datasets], "dataset")
        return self
