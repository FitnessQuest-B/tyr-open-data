# Native TYR v93 compatibility candidate

The native export profile `v93.1` extends the direct export reader with eight
nullable prospective temporal fields. The open data specification, standalone
empty artifacts, and original v92 reader keep their existing formats.
The v93 profile requires explicit selection. The v92 profile continues to
require a closed native v92 database.

```sh
python3 tools/read_native.py --profile v93 path/to/closed-export.sqlite
python3 tools/read_native.py --profile v93 path/to/closed-export.sqlite --projection log_entries
python3 tools/read_native.py --profile v93 path/to/closed-export.sqlite --evaluation-uuid UUID
```

The profile uses the same owner-scoped projections and route disclosure as the
v92 reader. Timestamps and nutrition day keys retain their existing meanings.
Legacy temporal fields are null. A UTC timestamp alone does not identify the
historical local clock. A stored offset applies to that event and an assigned
civil label is a calendar assignment. Use only the provenance actually recorded
with the observation.

Native v93 allows the canonical `caffeine_mg` Brain metric in `mg` per
assigned nutrition day. A recorded zero and an unknown amount are distinct.
The metric does not supply dose-band or timing assumptions.

The separate Brain receipt mode copies one named evaluation and its evidence
into a versioned JSON packet. It checks the native frozen specification digest,
identities, method versions and canonical evidence units. Exercise–nutrition
receipts preserve the explicit calendar, lag, threshold, matching and exclusion
metadata. The packet authenticates no individual or recording of a health event.
Fingerprinted evidence depends on original inputs for replay. The packet can
contain personal hypotheses and local evidence references, so keep it private
unless the owner approves sharing. The portable Lab's own database and source
admission rules are unchanged by this native reader.

This is a local compatibility release candidate. Use synthetic examples for
tests, demos and distribution.
