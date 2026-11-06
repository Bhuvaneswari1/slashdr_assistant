# Render CSV hosting options without upgrading the web service

No paid resources have been created and no production records have been uploaded. The local import contains 19,025,648 rows in a 2.69 GiB SQLite database.

Render Free cannot attach a persistent disk. Files written to its runtime filesystem can be lost on restart or idle spin-down. GitHub is for application code, not the production CSV dump or database.

## Practical choices

1. **Client review with a smaller de-identified CSV dataset.** Preserve a linked patient/visit cohort across relevant tables and remove identifying content, including free text. It can use the same CSV importer and UI. De-identification is not achieved merely by removing names or substituting patient IDs. This option does not include all production records. It has not been prepared automatically.
2. **Full records through an existing client database or API.** Keep Render Free for the web interface/backend and add a read-only, clinic-authorized adapter to the client's already hosted data. This avoids a new paid data-storage service, provided the client already has suitable infrastructure. It requires connectivity, authorization and a new adapter; the current SQLite adapter does not automatically query a remote MySQL/Postgres service.
3. **Private external object storage.** R2 Standard includes 10 GB-month of storage per month within its free allowance, which can accommodate this database if other usage remains inside limits. It is object storage, not a remotely queryable SQL database. The current SQLite design would require downloading the database to ephemeral Render storage and repeating that after loss of the cache. Cold-start time, Render runtime disk capacity and usage limits must be tested. The code does not yet implement R2 download/bootstrap. Storage allowances are not a guarantee that the whole deployment costs zero. Do not make the bucket or database public.

Supabase Free currently includes 500 MB of database storage, so the full existing 2.69 GiB SQLite dataset cannot simply be moved there under that database allowance. Its Postgres schema/storage footprint would also need measurement after migration.

## Authentication preparation already implemented

The app no longer rejects remote clients solely because their address is not localhost. Cloud CSV access instead requires:

- `DATA_MODE=csv`
- `CLOUD_CSV_ENABLED=true`
- `REVIEW_ACCOUNTS_JSON` with named reviewers, scrypt password hashes and explicit permitted clinic IDs
- `CSV_DATABASE` pointing to an available SQLite file inside `CSV_STORAGE_DIR`

This only enables access to an already provisioned file; it does not persist, upload or download data. Do not set the cloud-enable flag expecting the database to appear automatically. An unavailable database produces a configuration error and never falls back to synthetic JSON.

Generate named reviewer settings locally with:

```bash
python3 create_review_account.py --username reviewer1 --clinics ACTUAL_CLINIC_ID
```

The command asks for a password without printing it, then writes a private account JSON file under ignored `private_data/`. Enter that JSON in the Render `REVIEW_ACCOUNTS_JSON` environment secret. Never commit that file. Add further reviewers by rerunning with different usernames and their clinic IDs. Wildcard cloud permissions are rejected. The legacy shared credentials remain available for local/demo use, but they are not accepted in place of named accounts for cloud CSV mode.

External model generation remains controlled separately by `ALLOW_EXTERNAL_PATIENT_DATA=false`; no real patient data has been sent to OpenAI in this work. Enabling cloud record display does not implicitly enable external model transmission.

## References checked

- https://render.com/docs/free
- https://render.com/docs/disks
- https://supabase.com/pricing
- https://developers.cloudflare.com/r2/pricing/
