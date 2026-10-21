# Runbook: Ledger Vault Backup and Restore

## Backups

The Ledger Vault database is backed up nightly at 01:00 PKT. Backups are kept for 35 days. File storage uses object versioning with 90-day retention.

## Restore Procedure

1. Declare an incident and inform the Head of IT.
2. Raise a ticket with Tessera Cloud support quoting agreement TC-7720.
3. Restore the most recent backup to a new database instance.
4. Point Ledger Vault at the restored instance and run the integrity check script.
5. Confirm with two audit teams that recent files are visible.

## Restore Tests

A restore test is run on the first Monday of every month and the result is recorded in the IT log.
