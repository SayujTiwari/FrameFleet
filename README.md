# FrameFleet

Distribute video encoding across a fleet of computers to produce exports faster.

## Local development

The React frontend runs on the host machine. FastAPI and FFmpeg run together in
the backend container, while PostgreSQL stores durable encoding job records.

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
`framefleet_uploads`, and database data is stored in `framefleet_database`.
`docker compose down` stops and removes the containers without deleting either
volume.
