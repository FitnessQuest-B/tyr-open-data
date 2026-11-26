# Agent instructions for TYR Open Data

## Find the contract

1. Start with [compatibility](docs/architecture/compatibility.md) and the [versioned manifest](schema/versions/0.1.0/manifest.json). The current candidate supports 32 records projections from closed, standalone TYR v92 exports.
2. Use the [data dictionary](docs/data-dictionary/README.md), [measurement guide](docs/measurements/README.md) and [Brain contract](docs/brain/README.md) before interpreting rows.
3. Use the [read-only examples](examples/README.md). The included records and Brain Lab databases are empty and can be inspected offline.

## Protect the source and the owner

- The owner controls the data and remains free to choose other agents, models and analysis tools.
- Use only files the owner intentionally supplied. Open owner exports through `tools/read_export.py` or its read-only Python API. Keep the original export and historical source records preserved. Use an OS read-only mount or equivalent protection when other processes have filesystem access.
- Keep private exports, row excerpts, labels, notes, identifiers, findings and derived datasets out of source control, public artifacts and shared logs. Cloud transmission requires explicit authorization for the specific data and provider.
- For blind synthetic analysis, mount only the observation bundle and approved instructions. Keep the scenario configuration, seed and evaluator truth outside the agent environment. See [synthetic packages](databases/synthetic/README.md).
- Use the [typed offline Lab](brain-lab/README.md) for authorized experimental writes. Keep its database separate from the source and out of the candidate checkout. Keep the source binding intact and treat changed exports as separate inputs. Preserve source and evidence history subject to the owner’s retention and deletion choices.

## Interpret evidence conservatively

- Treat missing observations as unknown. Distinguish missing, excluded, deleted, observed zero and incomplete coverage. Report the observed count, expected denominator, applicable date window and relevant provenance.
- Keep units and time bases explicit. Use recorded calendar labels where supplied. Compare like measurement methods and disclose timezone assumptions or changes in logging, device or method.
- Treat estimated load, label nutrients, portion sizes and derived summaries as uncertain. Separate observed records, analytical interpretations and recommendations.
- Correlation does not establish causation. Examine confounding, competing explanations, selection effects, serial dependence and multiple comparisons. Separate exploration from evaluation on independent or later observations wherever feasible.
- Record the source and projection versions, query, parameters, inclusion rules, method, effect estimate, uncertainty and evidence references where possible. Preserve evidence that supports or contradicts each hypothesis. Retain failed and inconclusive evaluations as useful results subject to the owner’s data policy.
- Reassess findings when measurement methods, the person’s baseline or the relationship changes. Distinguish historical applicability from current applicability and describe when evidence remains insufficient.
- Be conservative with recommendations. The proposed roughly 90-day baseline is a future Lab policy, with metric-specific coverage and stability checks. It is not an implemented recommendation gate or a universal adequacy threshold. Early exploration can describe observations and uncertainty.

## Make changes within scope

The compatibility adapter and schema constraints describe implemented behavior. The current generator provides synthetic observations and separate truth metadata. The Lab supports source-bound local write workflows and offline replay. Use the [offline benchmark](benchmark/README.md) with detached observations and generic tasks. The bundled provider transports use mocked responses. Keep evaluator inputs, keys and paid provider use outside benchmark workers. Run `python3 -m unittest discover -s tests -v` after changes. Keep examples reproducible without TYR or paid services.
