# Jellyfin Poster Display (Raspberry Pi)

This Python app connects to a Jellyfin server and displays movie posters for your home theater display.

It supports two distinct display modes:
1. **Regular Screen (HDMI / Monitor / TV)**: A fullscreen GUI (Tkinter) with smooth crossfade transitions and an active playback status banner.
2. **E-Ink Display (Waveshare RPi Zero PhotoPainter 7.3")**: A lightweight, headless e-Paper driver with 6-color Floyd-Steinberg dithering, sleep-mode power management, and smart refresh logic tailored to e-Paper refresh limits.

Behavior:
- If users are actively watching configured media types, it displays their movie or TV-series poster.
- If nobody is actively watching, it shows posters from `SELECT_MOVIES` (if configured) or random posters from the configured library media types.
- `MEDIA_TYPES` selects movies, TV series, or both; `GENRES` optionally limits poster selection to items matching any listed genre.
- When `HOLIDAY_MODE=true`, the matching holiday's genre replaces `GENRES` for its configured date range. Holiday date ranges repeat yearly and may cross New Year.
- While idle, both display modes rotate posters every `IDLE_REFRESH_MINUTES` (default: 30 minutes), while checking for playback every `REFRESH_SECONDS`.
- Recent posters are cached locally; if Jellyfin is unreachable, the display uses the last `POSTER_CACHE_SIZE` cached posters (default: 10).
- Posters are auto-rotated so the long side of the poster aligns with the long side of the screen.
- On regular screens, poster changes use a configurable crossfade transition.
- On regular screens, clicking or tapping advances to the next poster immediately.
- On e-ink screens, posters are dithered to 6 colors (Black, White, Yellow, Red, Blue, Green) and the display is placed in deep sleep between updates to conserve energy and preserve panel life.

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

### Choose your display type in `.env`:

#### Option A: Regular Screen (HDMI)
Set in `.env`:
```env
DISPLAY_TYPE=regular
FULLSCREEN=true
FADE_SPEED=8
REFRESH_SECONDS=30
IDLE_REFRESH_MINUTES=30
POSTER_CACHE_SIZE=10
MEDIA_TYPES=Movie,Series
GENRES=Action,Comedy
HOLIDAY_MODE=true
HOLIDAYS=Christmas,Independence Day,Halloween,Thanksgiving
CHRISTMAS_GENRE=Christmas
CHRISTMAS_DAYS=12/18-12/31
INDEPENDENCE_DAY_GENRE=Action
INDEPENDENCE_DAY_DAYS=07/01-07/07
HALLOWEEN_GENRE=Horror
HALLOWEEN_DAYS=10/20-10/31
THANKSGIVING_GENRE=Family
THANKSGIVING_DAYS=11/20-11/30
```
For each entry in `HOLIDAYS`, define `<HOLIDAY_NAME>_GENRE` and `<HOLIDAY_NAME>_DAYS`, replacing spaces and punctuation with underscores. For example, `Valentine's Day` uses `VALENTINE_S_DAY_GENRE` and `VALENTINE_S_DAY_DAYS`. Multiple active holiday genre rules are combined.

#### Automated LCD setup
From a Mac or Linux computer, deploy and configure a Raspberry Pi with Raspberry Pi OS Desktop over SSH:
```bash
bash .github/setup-pi-lcd.sh -ip=10.0.0.119 -user=matt
```
The script installs Tkinter/Pillow display dependencies, configures regular mode, and adds PosterPulse to the desktop's autostart. The Pi must have a graphical desktop session and an LCD/HDMI display.

For setup directly on the Pi, run:
```bash
sudo bash .github/setup-pi-lcd.sh --local
```

### Option B: E-Ink Screen (Waveshare RPi Zero PhotoPainter)

#### Quick Automated Setup from your Computer (Recommended)
You can deploy and set up the Raspberry Pi Zero 2 W directly from your Mac or PC over SSH:
```bash
.github/setup-pi-eink.sh -ip=10.0.0.27
```
*(If your Raspberry Pi username is not `pi`, pass `-user=<username>`)*.

This remote command will:
1. Connect to the Raspberry Pi over SSH.
2. Synchronize project files to `~/PosterPulse` on the Pi.
3. Automatically run the full hardware provisioning:
   - Install required system libraries (`python3-spidev`, `python3-gpiozero`, `python3-pil`, etc.).
   - Enable SPI and I2C interfaces via `raspi-config`.
   - Create `.venv` and install Python dependencies.
   - Configure [.env](.env.example) for Waveshare PhotoPainter (`DISPLAY_TYPE=eink`, `EINK_PWR_PIN=27`).
   - Create and enable the `posterpulse.service` systemd service for headless auto-start on boot.

#### Alternatively, Local Setup on the Pi
If you are logged into the Pi directly or via SSH console:
```bash
cd ~/PosterPulse
sudo .github/setup-pi-eink.sh --local
```

#### Manual Setup
Set in `.env`:
```env
DISPLAY_TYPE=eink
REFRESH_SECONDS=15              # How often to check if someone started playing a movie
IDLE_REFRESH_MINUTES=30         # How often to rotate random posters when idle
EINK_ROTATION=0                 # Set to 180 if the display is mounted upside-down
EINK_PWR_PIN=27                 # PhotoPainter custom power pin (BCM 27)
```

## 2) Waveshare PhotoPainter / Raspberry Pi Zero 2 W Notes

1. **Enable SPI**:
   ```bash
   sudo raspi-config
   ```
   Navigate to **Interface Options** -> **SPI** -> **Yes**, then reboot. Verify with:
   ```bash
   ls /dev/spi*
   # Should list /dev/spidev0.0
   ```

2. **Pin Mapping**:
   The Waveshare PhotoPainter uses standard SPI pins plus a dedicated power pin on **BCM 27**:
   - `PWR`: GPIO 27 (Pin 13)
   - `RST`: GPIO 17 (Pin 11)
   - `DC`: GPIO 25 (Pin 22)
   - `CS`: CE0 / GPIO 8 (Pin 24)
   - `BUSY`: GPIO 24 (Pin 18)

3. **Smart Refresh for E-Ink**:
   E-Paper displays require ~12-15 seconds for a full refresh and should not be refreshed continuously. PosterPulse polls Jellyfin every `REFRESH_SECONDS` (e.g. 15s) in the background, but only refreshes the e-Paper panel when:
   - Playback starts, changes, or stops.
   - Or when the idle rotation timer (`IDLE_REFRESH_MINUTES`) elapses.
   Between refreshes, the panel is put into deep sleep with power cut to BCM 27.

4. **Headless Systemd Service (Recommended for Pi Zero 2 W)**:
   Because e-ink mode runs completely headless without X11 or a desktop environment, it uses minimal RAM (~30MB), leaving plenty of memory on the Pi Zero 2 W (512MB RAM).

   Create `/etc/systemd/system/posterpulse.service`:
   ```ini
   [Unit]
   Description=PosterPulse Jellyfin Display
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/PosterPulse
   ExecStart=/home/pi/PosterPulse/.venv/bin/python main.py
   Restart=on-failure
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```
   Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now posterpulse
   ```

5. **Desktop / PC Preview**:
   If you run `DISPLAY_TYPE=eink` on a Mac or PC without SPI hardware, PosterPulse automatically runs in preview mode and generates `eink_preview.png`, showing the exact 6-color dithered poster.

## 3) Run

```bash
source .venv/bin/activate
python main.py
```

- In regular mode, press `Esc` to exit.
- `FULLSCREEN=true` is recommended for kiosk display on HDMI.
- Example: `SELECT_MOVIES=Inception,The Matrix,Interstellar`

## 4) Create Jellyfin API Token

In Jellyfin:
1. Open Dashboard.
2. Go to **API Keys**.
3. Create a key and paste it into `.env` as `JELLYFIN_API_TOKEN`.

## Notes

- Ensure client device can reach Jellyfin over the network.
- If `SELECT_MOVIES` is set but none of the listed titles are found with posters, the app will show an error status.
- For HTTPS with self-signed certs, import your cert to the trust store instead of disabling SSL verification.
- If you want TV shows or mixed content, change `IncludeItemTypes` in `main.py`.
