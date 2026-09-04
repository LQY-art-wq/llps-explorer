from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class ResiduePosition(BaseModel):
    """A public residue coordinate; zero and non-integers are invalid."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    position: int = Field(ge=1, strict=True)


class Region(BaseModel):
    """One-based closed interval [start, end] at every API/UI boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: int = Field(ge=1, strict=True)
    end: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def validate_order(self):
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self

    @computed_field
    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @classmethod
    def from_zero_based_half_open(cls, start: int, end: int) -> "Region":
        # Python [start, end) becomes API [start + 1, end].
        if type(start) is not int or type(end) is not int:
            raise ValueError("coordinates must be integers")
        if start < 0 or end <= start:
            raise ValueError("a zero-based interval must be nonempty and ordered")
        return cls(start=start + 1, end=end)

    def to_zero_based_half_open(self) -> tuple[int, int]:
        return self.start - 1, self.end
