# Security

A TYR records export is a private SQLite file. Keep exports and read results on storage controlled by the owner. Share a reproducible synthetic case when reporting a problem with the reader or schema.

The export reader needs a closed Settings export. It opens a read-only connection, limits query columns, blocks unsupported profiles and keeps a single read transaction. The reader's database flags constrain its connection. Enforce filesystem access independently before giving an agent access to any private data.
