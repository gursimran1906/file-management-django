# Matter time and SharePoint / Word

## Folder convention

Store working documents for each matter under:

```
Matters/{file_number}/
```

Example: `Matters/ABC1234567/witness-statement.docx`

This mirrors the email subject-line file reference (`ABC1234567`) used by the email sync job.

Configure the root segment with `MATTER_SHAREPOINT_ROOT` (default: `Matters`).

## Phase 3 capture (implemented hooks)

1. **App-opened documents** — When a user downloads or opens a matter file from the app, start the matter timer from the time bar if appropriate.
2. **Graph activity subscription** (future) — Subscribe to Microsoft Graph change notifications on `Matters/{file_number}/` and aggregate edit sessions into draft `MatterTimeEvent` rows for human confirmation.
3. **Word add-in** (optional) — “Log time to ANP file” button posting to `POST /{file_number}/time-events/agent/`.

## Agent API

```
POST /{file_number}/time-events/agent/
Header: X-Matter-Time-Agent-Token: <MATTER_TIME_AGENT_TOKEN>

{
  "agent_id": "bundle-indexer",
  "activity": "Indexed bundle section 2",
  "duration_seconds": 420,
  "is_charged": false,
  "status": "draft",
  "evidence": { "bundle_uuid": "..." }
}
```

Draft events appear on **Time review** for the matter until confirmed.
