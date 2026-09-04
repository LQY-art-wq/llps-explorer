"""Single-protein input validation shared by API and direct adapter callers."""

STANDARD_AMINO_ACIDS = frozenset("ACDEFGHIKLMNPQRSTVWY")
ASCII_UPPERCASE = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


class SequenceValidationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        residue: str | None = None,
        position: int | None = None,
    ) -> None:
        super().__init__(message)
        self.detail: dict[str, str | int] = {"code": code, "message": message}
        if residue is not None:
            self.detail["residue"] = residue
        if position is not None:
            self.detail["position"] = position


def normalize_sequence(sequence: str) -> str:
    """Normalize whitespace/case and strip one leading FASTA header only.

    Invalid-residue positions refer to the normalized sequence, not the input
    text (which may contain a FASTA header and whitespace). Only ASCII case is
    changed, so characters such as sharp-s cannot silently become valid AAs.
    """
    if not isinstance(sequence, str):
        raise SequenceValidationError("INVALID_SEQUENCE_TYPE", "Sequence must be a string.")
    lines = [line.strip() for line in sequence.splitlines() if line.strip()]
    headers = [index for index, line in enumerate(lines) if line.startswith(">")]
    if len(headers) > 1:
        raise SequenceValidationError(
            "MULTIPLE_FASTA_RECORDS", "Exactly one protein sequence is accepted per request."
        )
    if headers:
        if headers[0] != 0:
            raise SequenceValidationError(
                "INVALID_FASTA", "A FASTA header must precede the protein sequence."
            )
        if not lines[0][1:].strip():
            raise SequenceValidationError("INVALID_FASTA", "A FASTA header must have a name.")
        lines = lines[1:]
    canonical = "".join(
        character for line in lines for character in line if not character.isspace()
    )
    canonical = canonical.translate(ASCII_UPPERCASE)
    if not canonical:
        raise SequenceValidationError("EMPTY_SEQUENCE", "Sequence must contain amino acids.")
    for position, residue in enumerate(canonical, start=1):
        if residue not in STANDARD_AMINO_ACIDS:
            raise SequenceValidationError(
                "INVALID_AMINO_ACID",
                f"Invalid amino acid {residue!r} at position {position}.",
                residue=residue,
                position=position,
            )
    return canonical


def ensure_sequence_length(sequence: str, max_length: int) -> str:
    """Apply the deployment limit after scientific sequence normalization."""
    if len(sequence) > max_length:
        raise SequenceValidationError(
            "ANALYSIS_SEQUENCE_TOO_LONG",
            "The protein sequence exceeds the configured analysis length limit.",
        )
    return sequence


normalize_protein_sequence = normalize_sequence
