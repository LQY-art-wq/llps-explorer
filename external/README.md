# External sources

`lreca/` is a local, unmodified checkout of the official LRECA repository. It is
excluded from this project's Git history; the pinned source and weight metadata
are versioned in [lreca-source.json](lreca-source.json). Do not select weights by
alphabetical order or silently fall back to another dataset.

To reproduce the audited checkout from the project root:

```powershell
git -c core.autocrlf=false clone https://github.com/ai-phasepro/LRECA.git external/lreca
git -C external/lreca checkout --detach 0b4b48ab7870529a34028c6e30dfba42eddbf215
python scripts/verify_sources.py
```

If Windows Git's Schannel backend produces `SEC_E_NO_CREDENTIALS`, the audited
clone succeeded with the per-command option `-c http.sslBackend=openssl`.
TLS certificate verification stays enabled; no global Git settings are changed.

Module 0 performed the source audit. Module 1 ran the unchanged Human demo and
verified CPU/CUDA inference and explainability; see [the baseline](../docs/lreca_baseline.md).
Human classification and the default `mydata` attribution weights must not be mixed:
the Module 1 compatibility layer uses the same loaded Human model for both paths.
There is no `external/fuzdrop/` directory: FuzDrop remains a remote integration
under the user's specification. SEG and DisMeta are not installed in this module.

## SEG — Module 3 update

The installation status above records Module 1. Module 3 now uses the official
NCBI BLAST+ **2.17.0+** `segmasker` executable for low-complexity-region annotation.
It does not produce an LLPS probability or class label. DisMeta remains pending.

The pinned package URLs, official MD5 values, observed Windows archive/executable
SHA256 values, and fixed-release source hashes are recorded in
[seg-source.json](seg-source.json). The Windows binary reports application version
1.0.0 and Package blast 2.17.0; record both, rather than calling 1.0.0 the release.

From the project root, `python scripts/setup_seg.py` selects Windows x64 or Linux
x64 and installs a limited subset under `.tools/seg`. It retains segmasker,
package dynamic libraries and notices, verifies checksums, reuses valid caches,
and refuses to replace differing installed files. It does not run the executable,
change global PATH, or invoke a GUI installer. Set `SEG_EXECUTABLE_PATH` explicitly
when the installed program is not on the service's PATH.

Windows installation and cache reuse have been verified. Only the small official
Linux MD5 file was retrieved; the Linux archive/binary SHA256 values remain null
and Linux/Docker execution is unverified. Keep the distributed LICENSE, README,
BLAST_PRIVACY and other notices. The backend sets BLAST_USAGE_REPORT=false for
its SEG subprocesses, following the official opt-out documentation.

Installation commands, exact source anchors, output coordinates and future Linux
container requirements are documented in [SEG runtime](../docs/seg_runtime.md).
The installation cache is excluded from Git; there is no `external/seg/` binary
checkout to copy into the application image.
