# Contract files

`defaults.json` is the fixed initial configuration. `defaults.schema.json` verifies that exact shipped snapshot, not every runtime preference the UI may permit. Implement a separately typed runtime-settings schema in WP-01 without widening the allowed behavior.

`ipc.schema.json` fixes the 1.0 JSON syntax. Validation is necessary but insufficient. IMPLEMENTATION_SPEC.md governs direction, current request identity, role, nonce, generation/intent/geometry admission, sender sequence, timeouts, byte limits, actual file containment/hash/audio validity and authorization. Never deserialize an object and assume that means it is current or approved.

Host-to-child types: init, inspect_windows, observe, synthesize, cancel, shutdown. Child-to-host types: hello, ready, accepted, completed, failed, canceled, cancel_ack, heartbeat. Vision accepts inspect_windows/observe; TTS accepts synthesize. Cross-role commands are PROTOCOL_INVALID. A role must not advertise capabilities absent from its tested implementation.

`completed.context` must equal submitted context for observe/synthesize; only inspect_windows uses null. A windows result is legal only for inspect_windows, observation only for observe, and audio only for synthesize. Canceled/failed results are correlated by request ID and the immutable host request record. Startup failures may have null request ID. The child may not choose a new generation.

All paths are restricted to the exact host-assigned directories and reviewed manifests. UUIDs, hashes and runtime names in ipc.examples.json are synthetic schema examples, not installed artifacts or approvals. The example messages illustrate shapes and are not one combined legal chronological trace.

`behavior-matrix.json` enumerates policy events; WP-02 must implement the complete transition table and test irrelevant-state/no-op cases. GUI labels are derived from domain states, not independent sources of truth.

Inventory requests do not authorize narration. Their cancellation is matched by request ID; any supplied generation is the host generation captured at dispatch, not a game/reading context. A host session is initialized even without a game; session renewal retires and replaces the worker instances. Sender sequence is scoped to each worker channel/instance, not shared across restarts.
