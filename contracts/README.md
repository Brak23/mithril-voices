# Runtime preference delta

The adopted `docs/design-v2/contracts/defaults.json` and its schema remain the
exact shipped initial configuration. `runtime-preferences.schema.json` is a
separate, closed schema for the first two user-editable settings: whether to
follow the system output default, and whether future history is enabled.

This is a preference delta, not a full replacement configuration. Unknown keys,
operational limits, capture scope, premium/corpus switches, and unverified
device or voice identifiers are rejected. The host must still apply changes in
the right thread, fence affected work, handle history cleanup choices and
validate device/asset identity. Schema validity alone authorizes no action.

Additional settings require reviewed behavior, tests and a schema version
change before they are accepted. The normative archived package is unchanged.
