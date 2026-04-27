# Jellyfin Poster Display (Raspberry Pi)

This Python app connects to a Jellyfin server and displays movie posters for your home theater display.

Behavior:
- If users are actively watching movies, it rotates through each currently watched movie poster.
- If nobody is actively watching a movie, it shows posters from `SELECT_MOVIES` (if configured) or random posters from your library.
- Posters are auto-rotated so the long side of the poster aligns with the long side of the screen.
- Poster changes use a configurable crossfade transition.

## 1) Setup

```bash
cd ~/PosterPulse
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy environment template:

```bash
cp .env.example .env
```

Then edit `.env` and set:
- `JELLYFIN_URL`
- `JELLYFIN_API_TOKEN`
- `REFRESH_SECONDS`
- `BACKGROUND_COLOR`
- `FADE_SPEED` (1 = slowest, 10 = fastest)
- `SELECT_MOVIES` (comma-separated titles; blank = random fallback)
- `FULLSCREEN`

## 2) Run

```bash
source .venv/bin/activate
python main.py
```

- Press `Esc` to exit.
- `FULLSCREEN=true` is recommended for kiosk display.
- Use `FADE_SPEED` to control transition speed.
- Example: `SELECT_MOVIES=Inception,The Matrix,Interstellar`

## 3) Create Jellyfin API Token

In Jellyfin:
1. Open Dashboard.
2. Go to **API Keys**.
3. Create a key and paste it into `.env` as `JELLYFIN_API_TOKEN`.


## Notes

- Ensure client device can reach Jellyfin over the network.
- If `SELECT_MOVIES` is set but none of the listed titles are found with posters, the app will show an error status.
- For HTTPS with self-signed certs, import your cert to the trust store instead of disabling SSL verification.
- If you want TV shows or mixed content, change `IncludeItemTypes` in `main.py`.
