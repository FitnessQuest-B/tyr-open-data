# TYR Open Data

Local development candidate for working with a supported subset of TYR SQLite records. The Open Data specification version is **0.1.0**. The export adapter supports **TYR application schema v92**. The generated records and Brain Lab files have separate SQLite application identifiers and each starts at file schema version 1.

## Create the empty databases

Use Python 3.10 or later with SQLite 3.41.0 or later and SQLite JSON support. The commands run offline using the Python standard library. Check the SQLite version linked to your Python with `python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'`.

```sh
python3 tools/create_empty.py records /tmp/tyr-records.sqlite
python3 tools/create_empty.py brain-lab /tmp/tyr-lab.sqlite
python3 -m unittest discover -s tests -v
```

The builder starts with a new file, replays the versioned SQL, and verifies every schema object, database integrity, foreign keys and empty tables before moving the result into place without replacing an existing destination. Two prebuilt empty files and their hashes are in [databases/empty](databases/empty).

For SQLite CLI use, create a file at a new path from [records.sql](schema/versions/0.1.0/records.sql) or [brain-lab.sql](schema/versions/0.1.0/brain-lab.sql). Enable foreign key enforcement in any connection that writes.

```sh
sqlite3 -bail /tmp/tyr-records-cli.sqlite < schema/versions/0.1.0/records.sql
sqlite3 -readonly /tmp/tyr-records-cli.sqlite '.tables'
```

## Generate synthetic observations

Four deterministic starter scenarios can be generated offline from this checkout. The generator writes a standalone SQLite file for the agent and keeps the simulation truth in a separate evaluator directory. See [generation and verification](databases/synthetic/README.md).

## Inspect an owner export locally

Use a closed SQLite file produced by **Settings → About → Save your records** in TYR.

```sh
python3 tools/read_export.py inspect /path/to/TYR-records.sqlite
python3 tools/read_export.py read /path/to/TYR-records.sqlite body_weight --limit 25
```

Inspection reports supported, limited and unavailable projections and a file-wide foreign key violation count when available. Reads return explicit columns from a read-only transaction. Use `--allow-partial` to deliberately inspect legacy storage rows for a routed health series. Returned records are private and can contain user-entered labels. Keep those outputs local.

- [Start here for AI agents](AGENTS.md)
- [Supported v92 table dictionary](docs/data-dictionary/README.md)
- [Measurements, provenance and time](docs/measurements/README.md)
- [Brain v92 contract](docs/brain/README.md)
- [Read-only examples](examples/README.md)
- [Compatibility and schema generation](docs/architecture/compatibility.md)
- [Machine-readable compatibility manifest](schema/versions/0.1.0/manifest.json)
- [Table and column inventory](schema/versions/0.1.0/inventory.json)
- [Foreign key inventory](schema/versions/0.1.0/foreign-keys.md)
- [Offline Brain Lab walkthrough](brain-lab/README.md)
- [Offline benchmark and mock provider adapters](benchmark/README.md)

## License

Copyright © 2026 Bhavik Patel.

TYR Open Data and TYR Brain Lab are licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE). The license covers the specifications, documentation, tooling, examples, fictional starter inputs, and empty schema databases included in this repository.

The TYR mobile application and separately obtained TYR records are outside the scope of this repository’s license. You retain your rights to your own records and may use them with the tools and agents you choose. Product names identify the project or describe compatibility. Trademark use is governed by Section 6 of the license.
