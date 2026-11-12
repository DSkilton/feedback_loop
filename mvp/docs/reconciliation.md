# Reporting reconciliation (issue #23)

## Purpose

Quality reports use precomputed `mvp_report_counters` rather than scanning feedback records. A controlled reconciliation compares these counters against the underlying `mvp_feedback` table and can repair discrepancies.

Reconciliation is **on demand**, not part of `GET /api/reports`. The normal dashboard remains fast and read-only.

## Endpoints

| Operation | Request | Permission | Effect |
| --- | --- | --- | --- |
| Dashboard | `GET /api/reports` | Quality administrator | Reads reporting counters only |
| Check | `POST /api/reports/reconcile` | Quality administrator | Compares source aggregates to counters and logs the check; does not modify counters |
| Repair | `POST /api/reports/reconcile/repair` | Quality administrator **also explicitly allowlisted as repair operator** | Rebuilds counters in one database transaction and logs the operation |

Both maintenance commands require a short operational reason. Repair additionally requires the exact confirmation string `REBUILD_REPORT_COUNTERS`.

To grant repair permission, the application operator sets `FEEDBACK_LOOP_REPORT_REPAIR_USERS` to a comma-separated list of **internal user IDs** whose authenticated role is `admin`. The variable defaults to empty; without it, **nobody can repair**. Ordinary quality administrators can run checks but cannot repair. This is a permission decision on the server, not in the frontend.

The Entra configuration, when enabled, continues to require its own approved user and role mapping; the maintenance permission is an additional check. Development identity switching is not a substitute for deployment authentication.

### Example payloads

Check:

```json
{"reason":"Quarterly reporting validation"}
```

Repair:

```json
{"reason":"Repair counters after validation","confirmation":"REBUILD_REPORT_COUNTERS"}
```

Return values include `consistent`, `mismatch_count`, `checked_at`, `discrepancies`, and for repair `repaired` and `consistent_after`.

A discrepancy reports only the metric key and aggregate expected/actual values. `null` means that the counter is missing, rather than zero. Unexpected counter keys are also detected.

### Suggested workflow

1. Save the current aggregate report and run the check.
2. If `consistent=true`, no repair is necessary.
3. Inspect aggregate discrepancies (missing statuses, incorrect counts or stale focus tags).
4. With a separately allowlisted operator account, submit the repair command and confirmation.
5. Confirm `consistent_after=true` and re-run a check. The report should now agree with the source.

A second repair against already consistent counters records an audited **no-op** without rebuilding.

## Audit record

Each check and repair appends a row to `mvp_report_maintenance_audit` containing:
- Acting account ID, action, reason and timestamp.
- Whether the source and projection matched before the operation.
- The number of discrepancies.
- SHA-256 digests of sorted aggregate counters before/after.

No student feedback text or evidence files are loaded, returned or copied to this log. The maintenance audit is stored in the same database transaction as a repair: if audit persistence fails, the repair rolls back.

## Architecture and limitations

- The reconciliation service calls `AggregateReportReadModel.expected_counters()`, the **same aggregate calculator** used for a rebuild, rather than maintaining a duplicate set of SQL expressions.
- Neither check nor repair is exposed to learners or tutors.
- The normal report endpoint never invokes the reconciler.
- The startup code still performs the existing one-off report projection bootstrap if the `total` counter is absent. Treat startup bootstrap separately from operator-initiated reconciliation.
- Concurrency with live feedback writes during a repair is not yet fully coordinated. Run the operator repair during a quiet/maintenance period. Issue #21 covers optimistic concurrency on feedback commands; a production implementation will also need an appropriate reconciliation/write lock strategy.
- Schema changes still need versioned migrations and regular backups; this feature does not replace them.

## Tests

```bash
python -m pytest -q mvp/tests/test_reconciliation.py
python -m pytest -q mvp/tests
```

Tests cover missing and incorrect counters, unexpected keys, independent authorisation, required confirmation, repair and no-op idempotency, audit records, audit failure rollback, and ordinary dashboard reads not invoking reconciliation.
