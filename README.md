# Jellyfin Poster Display (Raspberry Pi)

This Python app connects to a Jellyfin server and displays movie posters for your home theater display.

It supports two distinct display modes:
1. **Regular Screen (HDMI / Monitor / TV)**: A fullscreen GUI (Tkinter) with smooth crossfade transitions and an active playback status banner.
2. **E-Ink Display (Waveshare 4-inch E6 or 7.3-inch PhotoPainter)**: A lightweight, headless e-Paper driver with 6-color Floyd-Steinberg dithering, sleep-mode power management, and smart refresh logic tailored to e-Paper refresh limits.

## Screenshots
<img width="250" height="400" alt="IMG_3225" src="https://github.com/user-attachments/assets/f09f5665-7f0e-45fc-9487-8a7631e0cbc4" />
<img width="250" height="400" alt="IMG_3220" src="https://github.com/user-attachments/assets/c0a4eed2-3518-4d3c-bc3b-345416a788c2" />
<img width="250" height="400" alt="IMG_3224" src="https://github.com/user-attachments/assets/c6e35e94-bfdb-4a65-9339-3b5430c351e4" />


## Hardware
Should work on all LCD screens no matter the size, this is the size I like with a case you can 3D print <br>
[FREENOVE Touchscreen Display 5 Inch](https://www.amazon.com/dp/B0B455LDKH?ref_=ppx_hzsearch_conn_dt_b_fed_asin_title_6&th=1)<br>
[5Inch_LCD_DisplayCase.3mf.zip](https://github.com/user-attachments/files/34538067/5Inch_LCD_DisplayCase.3mf.zip)<br>
[Raspberry Pi 3 Model B+](https://www.amazon.com/Raspberry-Pi-Model-Board-Plus/dp/B0BNJPL4MW/ref=sr_1_1?crid=2XGOX73JO2ZAF&dib=eyJ2IjoiMSJ9.gIGv_xElPh1m_T7EI7Yvln4029GwVLqzeMvlo0uICl_D86G3fPZEVOutKQiRDG71iZWJlPkTCFXji5kRW03ixYuAdj0UFrMref7FaPEwURJkWUD9Uu93gRDclTrCS3Gbe-bk-7HI0bfHEsFqPApcxgITmnvAMNuV_HcBEyuX5W4Q-5Vweq82cX6jXwyMMaRnb6z2wOrzbOV54vG_XXt79rH__u-Sb6j0SNj6XL8zqj7qe_n-xRAzmVOzljht6Gg3e5TT854cW4q2C2E6mhFZUpmqZHXHLEHgA2os0HWX6Sk.z0LTlOV45S0y35XPJVmQSbrA488yN-kRB-1DzMYEAkg&dib_tag=se&keywords=raspberry+pi+3b&qid=1794116536&s=electronics&sprefix=raspberry+pi+3b%2Celectronics%2C186&sr=1-1)<br>

These are currently the 2 Eink displays that are supported, more can be supported with additional changes to code<br>

[Waveshare 4-inch EInk Display](https://www.amazon.com/dp/B0DHTNHRRY?ref=ppx_yo2ov_dt_b_fed_asin_title)<br>
[Waveshare_4-inch_EInk_DisplayCase.3mf.zip](https://github.com/user-attachments/files/34538065/Waveshare_4-inch_EInk_DisplayCase.3mf.zip)<br>
[Raspberry Pi Zero 2W](https://www.amazon.com/dp/B0FWRPF4FV/ref=sspa_dk_detail_0?psc=1&pd_rd_i=B0FWRPF4FV&pd_rd_w=Yq3Jb&content-id=amzn1.sym.17345c9b-ef8c-4a79-bcd9-8894b1e1e0ea&pf_rd_p=17345c9b-ef8c-4a79-bcd9-8894b1e1e0ea&pf_rd_r=P00MTT26XZ6QACJEB91G&pd_rd_wg=dKmtY&pd_rd_r=c7287873-ccfc-41e8-929a-c60a2765149e&s=electronics&sp_csd=d2lkZ2V0TmFtZT1zcF9kZXRhaWw)<br>

[KLAYERS PhotoPainter 7-inch EInk Display](https://www.amazon.com/dp/B0G934X8YG?ref_=ppx_hzsearch_conn_dt_b_fed_asin_title_2)

## Behavior:
- If users are actively watching configured media types, it displays their movie or TV-series poster.
- If nobody is actively watching, it shows posters from `SELECT_MOVIES` (if configured) or random posters from the configured library media types.
- `MEDIA_TYPES` selects movies, TV series, or both; `POSTER_TAGS` limits poster selection to items matching any listed Jellyfin tag; `GENRES` optionally limits poster selection to items matching any listed genre; `EXCLUDED_GENRES` always filters out matching genres. Text-based filters—including media types, tags, genres, collection names, selected titles, and holiday genres—are matched case-insensitively.
- Optionally set `COLLECTIONS` to comma-separated Jellyfin collection names (BoxSets) to limit idle poster selection to those collections. Leave it empty to use the library. It also scopes top-rated movie mode when enabled.
- Set `TOP_RATED_MOVIE_COUNT` above zero to rotate among that many top-rated movies, bypassing genre, holiday, and selected-title filters. Ranking uses Jellyfin's `CommunityRating` metadata; ensure your Jellyfin metadata provider populates it.
- When `HOLIDAY_MODE=true`, the matching holiday's genres replace `GENRES` for its configured date range. A media item must have every configured holiday genre; regular `GENRES` still matches any listed genre. Holiday date ranges repeat yearly and may cross New Year.
- Both display modes rotate idle posters and cycle between multiple active playback posters every `IDLE_REFRESH_MINUTES` (default: 30 minutes). They still check for playback changes every `REFRESH_SECONDS`.
- Recent posters are cached locally; if Jellyfin is unreachable, the display uses the last `POSTER_CACHE_SIZE` cached posters (default: 10).
- Posters are auto-rotated so the long side of the poster aligns with the long side of the screen.
- On regular screens, poster changes use a configurable crossfade transition.
- On regular screens, clicking or tapping advances to the next poster immediately.
- Set `DISPLAY_ROTATION=180` to rotate the entire regular/LCD output for an upside-down-mounted screen; use `0` for normal orientation.
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
DISPLAY_ROTATION=0
REFRESH_SECONDS=30
IDLE_REFRESH_MINUTES=30
POSTER_CACHE_SIZE=10
COLLECTIONS=Pixar,Studio Ghibli
MEDIA_TYPES=Movie,Series
POSTER_TAGS=PosterPulse,Poster Pulse
GENRES=Action,Comedy
EXCLUDED_GENRES=Documentary,News
TOP_RATED_MOVIE_COUNT=25
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
For each entry in `HOLIDAYS`, define `<HOLIDAY_NAME>_GENRE` and `<HOLIDAY_NAME>_DAYS`, replacing spaces and punctuation with underscores. For example, `Valentine's Day` uses `VALENTINE_S_DAY_GENRE` and `VALENTINE_S_DAY_DAYS`. If a holiday has multiple comma-separated genres, a media item must have all of them. Multiple active holiday genre rules are combined, and all genres from those rules must match.

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

### Option B: E-Ink Screen (Waveshare 4-inch E6 or 7.3-inch PhotoPainter)

Choose the panel model before setup. In `.env`, set `DISPLAY_TYPE=eink` and use **one** matching configuration:

| Panel | `EINK_MODEL` | Width × height | `EINK_PWR_PIN` |
| --- | --- | --- | --- |
| Waveshare 4-inch Spectra 6 E6 HAT | `4in0e` | `400 × 600` | `18` |
| Waveshare 7.3-inch PhotoPainter | `7in3e` | `800 × 480` | `27` |

The model, resolution, and power pin must all match the attached panel. The `.env.example` is set up for the 4-inch E6; change all four values in the table if using the 7.3-inch PhotoPainter.

#### Waveshare documentation and reference drivers
- [4-inch e-Paper HAT+ (E) manual](https://www.waveshare.com/wiki/4inch_e-Paper_HAT%2B_%28E%29) and [official Raspberry Pi E6 driver](https://github.com/waveshareteam/e-Paper/blob/master/E-paper_Separate_Program/4inch_e-Paper_E/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epd4in0e.py).
- [7.3-inch e-Paper HAT (E) manual](https://www.waveshare.com/wiki/7.3inch_e-Paper_HAT_%28E%29) and [official Waveshare e-Paper driver repository](https://github.com/waveshareteam/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd).

#### Quick Automated Setup from your Computer (Recommended)
You can deploy and set up the Raspberry Pi Zero 2 W directly from your Mac or PC over SSH:
```bash
bash .github/setup-pi-eink.sh -ip=10.0.0.27 -user=pi
```
Replace the IP and username with your Pi's address and account. The script deploys the current project and `.env`, provisions SPI/software dependencies, and enables the headless service. Set the desired e-ink model in your local `.env` before remote setup so the matching configuration is copied to the Pi.

It connects over SSH, copies the project and `.env`, installs the hardware/software dependencies, enables SPI, and configures the `posterpulse.service` systemd service for headless startup.

#### Alternatively, Local Setup on the Pi
If you are logged into the Pi directly or via SSH console:
```bash
cd ~/PosterPulse
sudo .github/setup-pi-eink.sh --local
```

#### Manual Setup
Set the common e-ink options in `.env`:
```env
DISPLAY_TYPE=eink
REFRESH_SECONDS=15              # How often to check if someone started playing a movie
IDLE_REFRESH_MINUTES=30         # How often to rotate random posters when idle
EINK_ROTATION=0                 # Set to 180 if the display is mounted upside-down
```
Set `EINK_MODEL` to the panel in the table. `EINK_WIDTH`, `EINK_HEIGHT`, and `EINK_PWR_PIN` are optional; if omitted, PosterPulse uses the selected model's defaults. If you set any of them explicitly, keep them matched to the panel.

## 2) Waveshare e-Paper / Raspberry Pi Notes

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
   Both panels use the HAT's standard SPI/control pins. Their power pins differ:
   - 4-inch E6 HAT: `PWR` uses BCM 18.
   - 7.3-inch PhotoPainter: `PWR` uses BCM 27.
   Shared control connections are:
   - `RST`: GPIO 17 (Pin 11)
   - `DC`: GPIO 25 (Pin 22)
   - `CS`: CE0 / GPIO 8 (Pin 24)
   - `BUSY`: GPIO 24 (Pin 18)

3. **Smart Refresh for E-Ink**:
   E-Paper displays require ~12-15 seconds for a full refresh and should not be refreshed continuously. PosterPulse polls Jellyfin every `REFRESH_SECONDS` (e.g. 15s) in the background, but only refreshes the e-Paper panel when:
   - Playback starts, changes, or stops.
   - Or when the idle rotation timer (`IDLE_REFRESH_MINUTES`) elapses.
   Between refreshes, the panel is put into deep sleep and its model-specific power pin is disabled.

4. **Headless systemd service**:
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
