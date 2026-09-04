# Synthetic format fixtures only

All files named `synthetic_format_fixture_*` contain deliberately invented test data.
They are **not real FuzDrop predictions, service responses, or downloaded official results**.
The 45-residue canonical pattern is synthetic, and all numbers and regions are arbitrary.

Only the TSV column names and region type labels are grounded in the official frontend
exporter audited in `docs/audit/fuzdrop/export_format_evidence.json`.
No actual official export was obtained during the audit.

The scores fixture repeats arbitrary pDP values 0, 0.6, and 1 with Sbind 2.5.
The regions fixture deliberately includes a duplicate and one-residue regions to verify
that the local importer preserves supplied native records without scientific reconstruction.
These tests demonstrate parsing and validation only, never scientific accuracy.
