from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=80)
    bio: str = Field(default="", max_length=500)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A name is required")
        return value.strip()


class SectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A section name is required")
        return value.strip()


class SectionAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_id: str | None = Field(default=None, min_length=36, max_length=36)
