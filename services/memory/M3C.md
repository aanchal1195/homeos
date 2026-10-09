# M3C — Visual analysis pipeline

M3C adds the execution boundary between private inspection media and future multimodal inference.

## What it does

1. Owner queues analysis for media already attached to a visual session.
2. A separately authenticated worker prepares bounded JPEG frames.
   - Images produce one normalized frame.
   - Videos produce at most 12 sampled frames.
3. A trusted analyzer publishes structured findings against those frames.
4. Every finding is stored as a `PENDING` memory observation with media, frame timestamp, analyzer name/version and confidence.
5. Nothing in M3C directly changes confirmed graph assertions.

## Security boundary

- Owner endpoints use `HOMEOS_API_TOKEN`.
- Worker endpoints use a separate `HOMEOS_WORKER_TOKEN`.
- Frame files remain under `PRIVATE_MEDIA_ROOT`; there is no public frame-serving endpoint.
- Worker findings must target the inspected location or a confirmed descendant in the memory graph.
- Analyzer confidence is metadata for triage, not a calibrated probability and not authorization to create repairs or spend money.

## API

- `POST /api/v1/visual/sessions/{session_id}/analysis` — queue one attached media item.
- `GET /api/v1/visual/analysis/jobs/{job_id}` — owner reads job, frames and findings.
- `POST /api/v1/visual/analysis/jobs/{job_id}/prepare` — worker creates bounded frames.
- `POST /api/v1/visual/analysis/jobs/{job_id}/findings` — worker stages structured findings.

## Not included yet

- No external multimodal model provider is called by this service.
- No object detection, embeddings, automatic task creation or confirmed graph mutation.
- No public download endpoint for frames/media.
- No production OIDC/RBAC yet.

The next increment should add a provider adapter/worker process that consumes `FRAMES_READY` jobs and submits schema-validated findings while retaining this trust boundary.
