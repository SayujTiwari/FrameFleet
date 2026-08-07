# FrameFleet

Distribute video encoding across a fleet of computers to produce exports faster.

## Local development

The React frontend runs on the host machine. FastAPI accepts uploads, a separate
worker uses FFmpeg to encode video segments in the background, and PostgreSQL stores
durable encoding job records.

Each segment is encoded independently. Once all segments finish, one worker
assembles them into a final MP4 that can be downloaded from the frontend.
Export resolution and quality settings are stored with the job so every worker
uses identical FFmpeg parameters.
Workers renew database leases while encoding. Expired work can be reclaimed,
and fencing tokens prevent late workers from publishing stale output.
Queued and active jobs can be cancelled; cancellation revokes worker leases so
in-progress FFmpeg processes stop at their next heartbeat.

Start the backend, worker, and database:

```bash
docker compose up --build
```

In another terminal, start the frontend:

```bash
npm install
npm run dev
```

Open the URL printed by Vite, normally <http://localhost:5173>. FastAPI's
interactive API documentation is available at <http://localhost:8000/docs>.

Uploaded videos are stored in the Docker volume named
`framefleet_uploads`, and database data is stored in `framefleet_database`.
`docker compose down` stops and removes the containers without deleting either
volume.

## Worker recovery test

The recovery test runs in an isolated Docker Compose project, pauses a worker
while it owns a segment, and waits for its database lease to expire. A second
worker must reclaim and complete the segment. The first worker is then resumed
to verify that its fenced, stale attempt cannot overwrite the accepted output.

Run the test from the repository root:

```bash
bash scripts/test-worker-recovery.sh
```

The script verifies the retry count and final download before removing its
temporary containers, PostgreSQL volume, uploaded video, and generated export.
