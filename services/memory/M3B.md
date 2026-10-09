# M3B — Photo/video memory ingestion (foundation)

M3B is a staged, **owner-token-only** media ingestion workflow, not yet autonomous computer vision. It extends the M3A PostgreSQL service; it does not integrate with the older local-only HomeOS dashboard.

## Flow

1. Create a visual session linked to an existing confirmed location entity.
2. Upload JPEG, PNG, WebP, MP4 or QuickTime files (private storage; validated signatures and maximum bytes).
3. Attach uploaded media IDs to the session.
4. Submit an observation citing a media ID and an optional frame timestamp. Observations remain **PENDING**.
5. Record which zones were observed, partially covered, or not observed; lack of visibility is *not* absence.
6. Review observations separately. Accepting them **does not directly update verified graph relationships**.

**No AI model or video frame extraction is wired yet.** A trusted vision worker will eventually produce the proposed observations, matched entities, and frames.

## Local setup

Existing databases must apply `schema/002_visual_memory.sql` after `001_home_memory.sql`. Never use `docker compose down -v` as a migration strategy. In this standalone Compose stack, new volumes initialize both SQL scripts in filename order.

`PRIVATE_MEDIA_ROOT` defaults to `/srv/memory/private_media` inside the container and is mounted to a named volume. There is deliberately no public file-serving endpoint. The service has a default 25 MiB file limit (configurable `MAX_MEDIA_BYTES`, do not expose publicly without tighter policy, rate limits and antivirus scanning).

All M3B APIs use the existing `Authorization: Bearer ...` bootstrap token. This is not production authentication. Implement role-scoped identity, consent, retention, malware scanning and audit-based download authorization before sharing real household videos with staff or external integrations.

## Key APIs

- `POST /api/v1/visual/sessions` — create inspection session for known location
- `POST /api/v1/visual/media` — upload validated file
- `POST /api/v1/visual/sessions/{id}/media/{media_id}` — attach file
- `POST /api/v1/visual/sessions/{id}/coverage` — record observed zones
- `GET /api/v1/visual/sessions/{id}` — read coverage and linked media
- Existing `POST /api/v1/memory/observations` — evidence-linked proposal (M3B optional media ID)

Neither upload nor coverage implies a model verified cleanliness, damage, or inventory counts.
