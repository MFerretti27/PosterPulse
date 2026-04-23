# Jellyfin Poster Display (Raspberry Pi)

This Python app connects to a Jellyfin server and displays movie posters for your home theater.

Behavior:
- If users are actively watching movies, it rotates through each currently watched movie poster.
- If nobody is actively watching a movie, it falls back to random movie posters from the library.

## 1) Setup

```bash
cd ~/Jellyfin_poster
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
- optionally `JELLYFIN_USER_ID`

## 2) Run

```bash
source .venv/bin/activate
python main.py
```

- Press `Esc` to exit.
- `FULLSCREEN=true` is recommended for kiosk display.

## 3) Create Jellyfin API Token

In Jellyfin:
1. Open Dashboard.
2. Go to **API Keys**.
3. Create a key and paste it into `.env` as `JELLYFIN_API_TOKEN`.


## Notes

- Ensure client device can reach Jellyfin over the network.
- For HTTPS with self-signed certs, import your cert to the trust store instead of disabling SSL verification.
- If you want TV shows or mixed content, change `IncludeItemTypes` in `main.py`.
