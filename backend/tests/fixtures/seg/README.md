# Real NCBI segmasker output fixtures

The eight `*.interval.txt` files contain the exact original bytes emitted by the
official Windows NCBI BLAST+ 2.17.0 distribution. The application identifies itself
as `segmasker: 1.0.0`, with `Package: blast 2.17.0`, built July 1, 2025.
`version.txt` and `help.txt` preserve the original executable's output.

These bytes were copied from `.audit/module3/raw_probe/` and checked against the
SHA256 values in `cases.json` **before the production parser was implemented**.
Original CRLF endings are intentional and must be preserved for byte-level checks.

The command uses stdin FASTA with one fixed `query` record and stdout intervals:

```text
segmasker -in - -infmt fasta -out - -outfmt interval -window 12 -locut 2.2 -hicut 2.5
```

`parse_seqids` is false (the flag is omitted). The sequence content is supplied via
stdin, never as a shell command argument. `cases.json` retains input sequences,
hashes, original outputs, return codes, and measured times from the actual run.

Seven sequences are artificial software-behavior examples, including homopolymers,
mixed composition, and terminal regions. Their outputs are genuine tool outputs,
not fabricated expected predictions. The human sequence is reused from the existing
Human LRECA baseline; its historical fixture identifier does not make SEG a classifier.
No fixture establishes LLPS behavior or experimental validation.

Native intervals are zero-based and inclusive. API intervals add one to both ends.
Native segment records are preserved; only coverage uses the union of positions.
