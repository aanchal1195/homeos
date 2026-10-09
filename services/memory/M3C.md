# M3C — Visual Intelligence (first working vertical slice)

Adds a real OpenAI-compatible image-vision request against the **official OpenAI Chat Completions endpoint** (the service never synthesizes detections without a configured API key). It uses the private media upload and inspection sessions introduced in M3B.

## Run

For a fresh standalone memory service, provide environment values in `services/memory/.env` (see README) and add:

```env
HOMEOS_VISION_API_KEY=your_api_key
HOMEOS_VISION_MODEL=gpt-4.1-mini
```

Do not commit keys. Start with `cd services/memory && docker compose --env-file .env up --build -d`. Existing PostgreSQL installations **must apply `schema/003_visual_analysis.sql`** using a migration plan and backup; automatic init SQL runs only on a fresh database volume.

## Workflow

1. Create or look up a ROOM/SPACE entity in Home Memory.
2. Start a visual session for that room: `POST /api/v1/visual/sessions`.
3. Upload supported photo/video: `POST /api/v1/visual/media`.
4. Attach it: `POST /api/v1/visual/sessions/{session_id}/media/{media_id}`.
5. Analyze: `POST /api/v1/visual/sessions/{session_id}/analyze/{media_id}`.
6. Inspect runs: `GET /api/v1/visual/sessions/{session_id}/analysis`.
7. Review pending observations through existing memory observation review endpoint.

For videos, FFmpeg samples frames at 0, 5 and 10 seconds when those frames exist. Only decoded, resized JPEG frames are sent to the vision provider; original evidence remains private. Image metadata is stripped before sending to the model. The provider returns a constrained JSON list of visibly recognized objects.

Detection labels are matched **only** against unambiguously named, confirmed assets in the inspection location (and its known sublocations). Unmatched objects become pending observations, **not new confirmed assets**. A detected object in a different room does not automatically move it; unobserved objects are not assumed missing. All generated observations are persisted with the original media reference, model version and frame timestamp.

## Boundaries

- **External disclosure**: analysis sends image content or sampled video frames to the configured OpenAI vision provider. Obtain owner/staff consent before submitting private household images; do not upload sensitive footage without approval.
- **Cost**: each media analysis may issue up to 3 paid model requests.
- **Reliability**: this first increment runs synchronously and retries require explicit new model versions after a failed attempt; no background queue or recovery scheduler yet.
- **Review**: observation acceptance never changes the confirmed knowledge graph. An authorized domain workflow must apply approved facts.
- **Accuracy**: no identity recognition, exact object tracking, calibrated confidence, depth estimation, hidden defect diagnosis, or accurate inventory quantification.
- **Authentication**: existing single-owner bootstrap token remains unsuitable for staff/public deployment.
- **UI**: this service is not yet integrated with the separate local-only HomeOS dashboard.
