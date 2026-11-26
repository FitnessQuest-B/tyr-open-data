# Nutrition and supplements

TYR Open Data 0.1.0 records projection from TYR v92. The [data dictionary index](README.md) defines the shared conventions. See the [measurement guide](../measurements/README.md) for temporal and analytical semantics.

## `food_sources`

Lookup of source categories used by the food catalogue. A code names a provenance class. It gives no permission to redistribute catalogue data.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `code` | `TEXT` | No | Stored source code, such as a user-owned or imported catalogue class. |

## `foods`

One food reference entry at the current library state. The name may be user-entered. Use captured ledger values for historical intake.

Primary key is `id`.

Declared foreign keys include `(parent_food_id)` → `foods(id)`, `(source_id)` → `food_sources(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `name` | `TEXT` | No | Current food display name. |
| `source_id` | `INTEGER` | No | Reference to the food source category in `food_sources`. |
| `is_custom` | `INTEGER` | No | Stored custom-entry flag, encoded as 0 or 1. This is a catalogue classification. |
| `parent_food_id` | `INTEGER` | Yes | Optional linkage to a parent food library row. |
| `default_gram_weight` | `REAL` | No | Grams in the base amount for this food, when known. Use with `food_nutrients.amount_per_base_unit`. |
| `is_deleted` | `INTEGER` | No | Stored deletion flag, encoded as 0 or 1. Use it when selecting active records. |

## `food_nutrients`

One known catalogue amount for a food and nutrient. The amount is an input estimate or declaration. Absence of a row means unknown.

Primary key is `food_id`, `nutrient_id`.

Declared foreign keys include `(food_id)` → `foods(id)`, `(nutrient_id)` → `nutrients(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `food_id` | `INTEGER` | No | Food catalogue identifier. |
| `nutrient_id` | `INTEGER` | No | Nutrient catalogue identifier. Read the unit from this identity. |
| `amount_per_base_unit` | `REAL` | No | Amount of the nutrient per food base weight, in the unit of `nutrients`. Barcode foods can use a 100 g base. |
| `coverage_status` | `TEXT` | No | Stored coverage classification `COMPLETE`, `PARTIAL` or `UNCLASSIFIED`. |

## `food_portions`

One named portion option for a food. Current serving definitions can change. Historical conversions should use the ledger snapshot where available.

Primary key is `id`.

Declared foreign keys include `(food_id)` → `foods(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `food_id` | `INTEGER` | No | Food catalogue identifier. |
| `description` | `TEXT` | No | Human-readable portion label. |
| `gram_weight` | `REAL` | No | Grams represented by one of the named portions. |
| `is_base` | `INTEGER` | No | Flag for the portion marked as the food's base. |
| `sort_order` | `INTEGER` | No | Display ordering value within the food's portions. |
| `is_available` | `INTEGER` | No | Flag for whether the portion is currently offered. |

## `nutrients`

Reference row defining a nutrient identity and its canonical amount unit. Join by local ID and use the code when comparing known identities across supported files.

Primary key is `id`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `code` | `TEXT` | No | Stored nutrient identifier, for example `PROTEIN` or `CAFFEINE`. |
| `name` | `TEXT` | No | Nutrient display label. |
| `unit` | `TEXT` | No | Stored canonical unit for this identity, such as kcal, g, mg, µg or IU. |
| `category` | `TEXT` | No | Stored nutrient classification. |
| `is_trackable` | `INTEGER` | No | Flag for whether the nutrient is offered for tracking. |
| `is_custom` | `INTEGER` | No | Stored custom-entry flag, encoded as 0 or 1. This is a catalogue classification. |

## `supplements`

One supplement catalogue entry. Its declared dose describes the logged item. The entry does not establish measured contents, bioavailability or efficacy.

Primary key is `id`.

Declared foreign keys include `(parent_supplement_id)` → `supplements(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `name` | `TEXT` | No | Current supplement display name. |
| `form` | `TEXT` | Yes | Stored supplement form, when present. |
| `category_key` | `TEXT` | No | Stored category key. |
| `is_custom` | `INTEGER` | No | Stored custom-entry flag, encoded as 0 or 1. This is a catalogue classification. |
| `parent_supplement_id` | `INTEGER` | Yes | Optional linkage to a parent supplement library row. |
| `dose_amount` | `REAL` | Yes | Declared amount of one dose on the associated scale. |
| `dose_unit` | `TEXT` | Yes | Unit for the dose amount. Nutrient amounts have their own units. |
| `is_deleted` | `INTEGER` | No | Stored deletion flag, encoded as 0 or 1. Use it when selecting active records. |

## `supplement_nutrients`

One library association of supplement and nutrient. Label-derived amounts and user-entered values should be treated as declarations.

Primary key is `supplement_id`, `nutrient_id`.

Declared foreign keys include `(nutrient_id)` → `nutrients(id)`, `(supplement_id)` → `supplements(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `supplement_id` | `INTEGER` | No | Supplement catalogue identifier. |
| `nutrient_id` | `INTEGER` | No | Nutrient catalogue identifier. Read the unit from this identity. |
| `amount_per_dose` | `REAL` | Yes | Nutrient amount per catalogue dose, expressed in the nutrient unit. NULL leaves the amount unspecified. |

## `log_entries`

One historical intake ledger row. It can represent a top-level entry, a child, a grouping action, or a modifier. Parent-child rows and headline caches cannot be blindly summed. Historical logs can refer to recipe, stack or meal structures outside this projection.

Primary key is `id`.

Declared foreign keys include `(parent_log_entry_id)` → `log_entries(id)`, `(portion_id)` → `food_portions(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `id` | `INTEGER` | No | Local row identifier. Use within this file and table. |
| `user_id` | `INTEGER` | No | Local owner identifier. Join to the projected `user.id` with the source file in scope. |
| `day_key` | `INTEGER` | No | Stored integer nutrition day in YYYYMMDD form. The local nutrition day starts at 03:00. |
| `logged_at` | `INTEGER` | No | Log event instant in Unix seconds. Use the stored day key for nutrition-day grouping. |
| `entity_type` | `TEXT` | No | Type discriminator for the row, including `FOOD`, `SUPPLEMENT`, `MEAL`, `INTERVENTION`, `STACK_APPLY`, `QUICK_LOG` and `MEAL_APPLY`. |
| `entity_id` | `INTEGER` | Yes | Polymorphic local ID within the entity type. A `QUICK_LOG` row has no entity ID under the app check. |
| `quantity_kind` | `TEXT` | No | Stored quantity basis. Food resolver cases include `GRAM`, `PORTION`, `COMPOSITE_SERVING` and `BATCH_FRACTION`. Use the entity type and history to interpret it. |
| `quantity` | `REAL` | No | Stored quantity on its declared basis. It may be a user estimate. |
| `portion_id` | `INTEGER` | Yes | Local food portion reference when used. |
| `meal_type` | `TEXT` | No | Stored meal category for grouping. Multiple entries in the same category can make up one reported group. |
| `deleted_at` | `INTEGER` | Yes | Soft deletion instant in Unix seconds. NULL carries no tombstone timestamp. |
| `source_type` | `TEXT` | No | Stored entry origin or workflow label, such as `MANUAL`, `STACK`, `MEAL`, `IMPORT` or `QUICK_LOG`. |
| `parent_log_entry_id` | `INTEGER` | Yes | Optional parent log entry ID for grouping and modifiers. |
| `consumed_grams_snapshot` | `REAL` | Yes | Mass in grams captured when the row was logged, when available. |
| `consumed_grams_basis` | `TEXT` | Yes | Mass basis classification `EXACT`, `DERIVED_EXACT` or `ESTIMATED`. Exact describes conversion or entry semantics, and physical measurement uncertainty can still exist. |
| `nutrient_coverage_snapshot` | `TEXT` | Yes | Overall captured nutrient coverage where recorded. Nutrient-level coverage can differ. |
| `calories_kcal` | `REAL` | Yes | Ledger headline calorie amount in kcal, when available. See snapshot and fallback rules. |
| `protein_g` | `REAL` | Yes | Ledger headline protein amount in grams, when available. |
| `fat_g` | `REAL` | Yes | Ledger headline fat amount in grams, when available. |
| `carbs_g` | `REAL` | Yes | Ledger headline carbohydrate amount in grams, when available. |
| `fiber_g` | `REAL` | Yes | Ledger headline fibre amount in grams, when available. |
| `sugar_g` | `REAL` | Yes | Ledger headline sugar amount in grams, when available. |
| `caffeine_mg` | `REAL` | Yes | Ledger headline caffeine amount in mg, when available. Unknown caffeine stays NULL. |
| `meal_modifier_operation` | `TEXT` | No | Stored operation `NORMAL`, `ADD` or `SUBTRACT`. Subtraction is an operation applied by the app and can have a positive stored operand. |

## `log_entry_nutrients`

One stored historical nutrient snapshot per log entry and nutrient. Prefer this representation to current library amounts for the same historical nutrient when a snapshot is present. Preserve coverage and grouping context.

Primary key is `log_entry_id`, `nutrient_id`.

Declared foreign keys include `(log_entry_id)` → `log_entries(id)`, `(nutrient_id)` → `nutrients(id)`.

| Column | SQLite type | NULL allowed | Meaning |
|---|---|---|---|
| `log_entry_id` | `INTEGER` | No | Reference to the associated ledger row. |
| `nutrient_id` | `INTEGER` | No | Nutrient catalogue identifier. Read the unit from this identity. |
| `amount` | `REAL` | No | Recorded snapshot amount in the nutrient’s unit. The app table checks for a nonnegative amount. Group modifiers can change the resolved total. |
| `coverage_status` | `TEXT` | No | Per-nutrient classification `COMPLETE`, `PARTIAL` or `UNCLASSIFIED`. A missing snapshot leaves the available evidence to the historical fallback rules. |
