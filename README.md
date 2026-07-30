# FrameFleet

Distribute video encoding across a fleet of computers to produce exports faster.

## Local development

The React frontend runs on the host machine. FastAPI and FFmpeg run together in
the backend container.

Start the backend:

```bash
docker compose up --build backend
```

In another terminal, start the frontend:

```bash
npm install
npm run dev
```

Open the URL printed by Vite, normally <http://localhost:5173>. FastAPI's
interactive API documentation is available at <http://localhost:8000/docs>.

Uploaded videos are stored in the Docker volume named
`framefleet_uploads`. `docker compose down` stops and removes the container
without deleting that volume.
