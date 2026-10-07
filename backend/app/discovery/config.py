from pydantic import BaseModel, ConfigDict, Field


class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = Field(default="discovery-config:v1", min_length=1, max_length=100)
    following_source: str = Field(
        default="candidate:following-read:v1", min_length=1, max_length=100
    )
    related_source: str = Field(
        default="candidate:related-public-boards:v1", min_length=1, max_length=100
    )
    crop_embedder: str = Field(default="embedder:clip-image-crop:v1", min_length=1, max_length=100)
    lens_service: str = Field(default="surface:lens:v1", min_length=1, max_length=100)
