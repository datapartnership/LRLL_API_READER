"""Pydantic models that mirror the Croissant JSON-LD response."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, Field


class OrgNode(BaseModel):
    type: str | None = Field(None, validation_alias=AliasChoices("@type", "type"))
    sc_name: str | None = Field(None, validation_alias=AliasChoices("sc:name", "scName"))

    model_config = {"populate_by_name": True}


class FileObjectNode(BaseModel):
    type: str | None = Field(None, validation_alias=AliasChoices("@type", "type"))
    id: str | None = Field(None, validation_alias=AliasChoices("@id", "id"))
    sc_name: str | None = Field(None, validation_alias=AliasChoices("sc:name", "scName"))
    sc_content_url: str | None = Field(None, validation_alias=AliasChoices("sc:contentUrl", "scContentUrl"))
    sc_encoding_format: str | None = Field(None, validation_alias=AliasChoices("sc:encodingFormat", "scEncodingFormat"))
    sc_content_size: int | None = Field(None, validation_alias=AliasChoices("sc:contentSize", "scContentSize"))
    cr_sha256: str | None = Field(None, validation_alias=AliasChoices("cr:sha256", "crSha256"))
    sc_author: str | None = Field(None, validation_alias=AliasChoices("sc:author", "scAuthor"))
    sc_date_published: str | None = Field(None, validation_alias=AliasChoices("sc:datePublished", "scDatePublished"))
    sc_date_modified: str | None = Field(None, validation_alias=AliasChoices("sc:dateModified", "scDateModified"))
    sc_in_language: str | None = Field(None, validation_alias=AliasChoices("sc:inLanguage", "scInLanguage"))
    sc_number_of_pages: int | None = Field(None, validation_alias=AliasChoices("sc:numberOfPages", "scNumberOfPages"))
    sc_word_count: int | None = Field(None, validation_alias=AliasChoices("sc:wordCount", "scWordCount"))
    ddpv_token_count: int | None = Field(None, validation_alias=AliasChoices("ddpv:tokenCount", "ddpvTokenCount"))
    ddpv_char_count: int | None = Field(None, validation_alias=AliasChoices("ddpv:charCount", "ddpvCharCount"))
    dct_subject: str | None = Field(None, validation_alias=AliasChoices("dct:subject", "dctSubject"))
    olac_discourse_type: str | None = Field(None, validation_alias=AliasChoices("olac:discourseType", "olacDiscourseType"))
    sc_keywords: list[str] | None = Field(None, validation_alias=AliasChoices("sc:keywords", "scKeywords"))
    dcat_theme: list[str] | None = Field(None, validation_alias=AliasChoices("dcat:theme", "dcatTheme"))
    dcat_theme_taxonomy: str | None = Field(None, validation_alias=AliasChoices("dcat:themeTaxonomy", "dcatThemeTaxonomy"))

    model_config = {"populate_by_name": True}


class DatasetNode(BaseModel):
    type: str | None = Field(None, validation_alias=AliasChoices("@type", "type"))
    id: str | None = Field(None, validation_alias=AliasChoices("@id", "id"))
    sc_name: str | None = Field(None, validation_alias=AliasChoices("sc:name", "scName"))
    sc_temporal_coverage: str | None = Field(None, validation_alias=AliasChoices("sc:temporalCoverage", "scTemporalCoverage"))
    sc_spatial_coverage: str | None = Field(None, validation_alias=AliasChoices("sc:spatialCoverage", "scSpatialCoverage"))
    sc_in_language: str | None = Field(None, validation_alias=AliasChoices("sc:inLanguage", "scInLanguage"))
    sc_creator: OrgNode | None = Field(None, validation_alias=AliasChoices("sc:creator", "scCreator"))
    sc_publisher: OrgNode | None = Field(None, validation_alias=AliasChoices("sc:publisher", "scPublisher"))
    sc_license: str | None = Field(None, validation_alias=AliasChoices("sc:license", "scLicense"))
    sc_version: str | None = Field(None, validation_alias=AliasChoices("sc:version", "scVersion"))
    cr_is_live_dataset: bool | None = Field(None, validation_alias=AliasChoices("cr:isLiveDataset", "crIsLiveDataset"))
    distribution: list[FileObjectNode] | None = None

    model_config = {"populate_by_name": True}


class SamplingInfo(BaseModel):
    total_matched: int = Field(alias="totalMatched")
    limit: int
    returned: int
    random_sample: bool = Field(alias="randomSample")

    model_config = {"populate_by_name": True}


class CroissantResponse(BaseModel):
    context: list | None = Field(None, validation_alias=AliasChoices("@context", "context"))
    generated_at: str | None = Field(None, alias="generatedAt")
    sampling_info: SamplingInfo | None = Field(None, alias="samplingInfo")
    graph: list[DatasetNode] | None = Field(None, validation_alias=AliasChoices("@graph", "graph"))

    model_config = {"populate_by_name": True}
