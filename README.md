# PosterPulse

PosterPulse turns a screen connected to your Jellyfin server into a rotating movie-poster display. It shows what's currently playing, or rotates through posters from your library when nothing is playing.

Choose the setup that matches your screen:

| Screen | Display mode | Setup |
| --- | --- | --- |
| HDMI monitor, TV, or LCD | Regular | Tkinter window with poster transitions |
| Waveshare 4-inch E6 or 7.3-inch PhotoPainter | E-ink | Low-power, headless display |

Both modes can run on a Raspberry Pi. You can also run regular mode on a desktop computer, or preview e-ink mode without a panel.

## Get started

You’ll need a Jellyfin server that your display device can reach, and a Jellyfin API key.

1. Clone the repository and install the Python dependencies:

   ```bash
   git clone https://github.com/MFerretti27/PosterPulse.git
   cd PosterPulse
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create your local settings file:

   ```bash
   cp .env.example .env
   ```

3. In `.env`, set `JELLYFIN_URL` and `JELLYFIN_API_TOKEN`. Leave `DISPLAY_TYPE=regular` for an HDMI/LCD screen.

   To create an API key in Jellyfin, open **Dashboard → API Keys → +**, then copy the key into `.env`.

4. Start the app:

   ```bash
   python main.py
   ```

Press `Esc` to quit regular mode. Set `FULLSCREEN=true` in `.env` for kiosk use.

> **Tkinter:** Regular mode needs Tkinter in addition to the pip packages. On Raspberry Pi OS, the LCD setup script installs it. On Debian or Raspberry Pi OS manual installs, use `sudo apt install python3-tk`. On macOS with Homebrew Python 3.14, use `brew install python-tk@3.14` (match the version to your Python).

## Set up a Raspberry Pi

The setup scripts can configure the Pi locally or deploy to it from a Mac/Linux computer over SSH. Before remote setup, create `.env` and enter your Jellyfin URL and API key.

### HDMI or LCD screen

The Pi needs Raspberry Pi OS Desktop and a connected display. From your computer, replace the example address and username with your Pi’s details:

```bash
bash .github/setup-pi-lcd.sh -ip=192.168.1.50 -user=pi
```

Remote LCD setup reuses one SSH connection for all transfers and setup commands,
so SSH authentication is only needed once per run. The Pi may separately prompt
once for your sudo password. The connection is closed when setup finishes.

Or, on the Pi itself:

```bash
sudo bash .github/setup-pi-lcd.sh --local
```

The script installs display dependencies and configures PosterPulse to start when the desktop session opens.
If a desktop session is already running, it also launches PosterPulse immediately
and checks for early startup failures. That launch writes its log to
`~/.local/state/posterpulse/regular.log` under the Pi user's home directory.

### E-ink screen

The setup script configures the 7.3-inch PhotoPainter by default. From your computer, replace the example address and username with your Pi’s details:

```bash
bash .github/setup-pi-eink.sh -ip=192.168.1.50 -user=pi
```

Remote e-ink setup also reuses one SSH connection: one SSH authentication per
run, plus a separate sudo password prompt if required. The connection is closed
when setup finishes, including if deployment fails.

Or, on the Pi itself:

```bash
sudo bash .github/setup-pi-eink.sh --local
```

The script installs hardware dependencies, enables SPI, and starts PosterPulse as a headless systemd service. For a 4-inch E6, update `EINK_MODEL`, `EINK_WIDTH`, `EINK_HEIGHT`, and `EINK_PWR_PIN` in `.env` after setup (see the [panel table](#supported-e-ink-panels)), then restart the service:

```bash
sudo systemctl restart posterpulse
sudo journalctl -u posterpulse -f
```

### Supported e-ink panels

The panel model, resolution, and power pin must match the hardware:

| Panel | `EINK_MODEL` | Resolution | `EINK_PWR_PIN` |
| --- | --- | --- | --- |
| Waveshare 4-inch Spectra 6 E6 HAT | `4in0e` | 400 × 600 | 18 |
| Waveshare 7.3-inch PhotoPainter | `7in3e` | 800 × 480 | 27 |

The setup script configures the 7.3-inch PhotoPainter (`7in3e`) with an 800 × 480 resolution and power pin 27. The checked-in `.env.example` contains 4-inch E6 settings (`4in0e`, 400 × 600, power pin 18). If using the 4-inch panel, set all four values to match it after running the setup script.

For panel-specific wiring and driver details, see the [4-inch E6 manual](https://www.waveshare.com/wiki/4inch_e-Paper_HAT%2B_%28E%29), [4-inch driver](https://github.com/waveshareteam/e-Paper/blob/master/E-paper_Separate_Program/4inch_e-Paper_E/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epd4in0e.py), [7.3-inch manual](https://www.waveshare.com/wiki/7.3inch_e-Paper_HAT_%28E%29), and [Waveshare driver repository](https://github.com/waveshareteam/e-Paper/tree/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd).

### Preview e-ink mode without a panel

On a Mac or PC, set `DISPLAY_TYPE=eink` in `.env` and run:

```bash
python main.py
```

PosterPulse writes a preview image to `eink_preview.png` by default. This shows the dithered image without requiring SPI hardware.

## Choose which posters to show

All settings are in `.env`; the complete, commented list is in [`.env.example`](.env.example). Comma-separated values are supported for the filters below.

| Setting | What it does |
| --- | --- |
| `MEDIA_TYPES` | Choose `Movie`, `Series`, or both. |
| `SELECT_MOVIES` | Limit idle rotation to the listed movie titles. |
| `COLLECTIONS` | Limit idle rotation to selected Jellyfin collections. |
| `POSTER_TAGS` | Include items with any matching Jellyfin tag. |
| `GENRES` | Include items with any matching genre. |
| `EXCLUDED_GENRES` | Exclude items with any matching genre. |
| `TOP_RATED_MOVIE_COUNT` | Rotate through the top-rated movies; `0` disables this mode. Requires Jellyfin rating metadata. |
| `HOLIDAY_MODE` | Use configured holiday genres during their date ranges instead of `GENRES`. |
| `REFRESH_SECONDS` | How often to check Jellyfin for playback changes. |
| `IDLE_REFRESH_MINUTES` | How often to change posters while idle. |
| `POSTER_CACHE_SIZE` | How many recent posters to keep for when Jellyfin is unavailable. |

Text filters are case-insensitive. Regular mode supports `FADE_SPEED` and `DISPLAY_ROTATION` (`0` or `180`); e-ink mode supports `EINK_ROTATION` (`0`, `90`, `180`, or `270`). The `EINK_MODEL` setting selects the panel.

For LCD/regular displays, set `PROGRESS_BAR_ENABLED=true` to show a thin playback
progress bar along the edge opposite the Currently Playing banner (right at 0°
rotation, left at 180°). It defaults to off. Set `PROGRESS_BAR_COLOR` to a
color name or quoted hex value, such as `PROGRESS_BAR_COLOR="#00FF00"` (default:
light blue). The bar follows `DISPLAY_ROTATION` and updates every `REFRESH_SECONDS`,
including when playback is paused or seeks. It shows the progress of the displayed
session's movie or episode and hides when idle, offline, or duration is unknown.
These settings do not affect e-ink displays.

When top-rated movie mode is enabled, it takes precedence over `GENRES`, `EXCLUDED_GENRES`, holiday genres, and `SELECT_MOVIES`. If `COLLECTIONS` is set, it still limits the collection of movies considered.

## What to expect

- When configured media is playing, PosterPulse shows the active movie or TV-series poster.
- When nothing is playing, it rotates through selected movies or matching library posters.
- Playback is checked every `REFRESH_SECONDS`. Idle posters (and multiple active playback posters) change every `IDLE_REFRESH_MINUTES`.
- Regular screens crossfade between posters and advance to the next poster when clicked or tapped.
- E-ink screens use six-color dithering and sleep between updates to reduce power use and panel refreshes.
- If Jellyfin is unavailable, the app can show recently cached posters.

## Hardware examples

These are example parts, not requirements for regular screens:

- [Raspberry Pi 3 Model B+](https://www.amazon.com/Raspberry-Pi-Model-Board-Plus/dp/B0BNJPL4MW)
- [FREENOVE 5-inch touchscreen](https://www.amazon.com/dp/B0B455LDKH)
- [Printable 5-inch LCD case](https://github.com/user-attachments/files/34608595/5Inch_LCD_DisplayCase.2.3mf.zip)
- [Waveshare 4-inch e-ink display](https://www.amazon.com/dp/B0DHTNHRRY)
- [Printable 4-inch e-ink case](https://github.com/user-attachments/files/34538065/Waveshare_4-inch_EInk_DisplayCase.3mf.zip)
- [KLAYERS 7.3-inch PhotoPainter display](https://www.amazon.com/dp/B0G934X8YG)

## Troubleshooting

- **The app says Jellyfin settings are missing:** Check that `JELLYFIN_URL` and `JELLYFIN_API_TOKEN` are set in `.env`.
- **Jellyfin can’t be reached:** Confirm the Pi/computer can access the server URL over the network.
- **Regular mode won’t start:** Make sure Tkinter is installed for the Python version running the app.
- **No posters match:** Check your media types, selected titles, collections, tags, and genre filters in `.env`.
- **E-ink screen does not update:** Check the selected model and its resolution/power-pin settings, and confirm SPI is enabled.

For HTTPS with a self-signed certificate, add the certificate to the system trust store rather than disabling certificate verification.

## Screenshots

<img width="250" height="350" alt="PosterPulse display" src="https://github.com/user-attachments/assets/6ab9b078-47a8-4112-ae6d-69c4fab73c89" />
<img width="250" height="350" alt="PosterPulse display" src="https://github.com/user-attachments/assets/c0a4eed2-3518-4d3c-bc3b-345416a788c2" />
<img width="250" height="350" alt="PosterPulse display" src="https://github.com/user-attachments/assets/c6e35e94-bfdb-4a65-9339-3b5430c351e4" />
<img width="250" height="350" alt="PosterPulse display" src="https://github.com/user-attachments/assets/f1c08008-fd1c-408c-86d4-f453e1533a5c" />
<img width="250" height="350" alt="PosterPulse display" src="https://github.com/user-attachments/assets/8735a5f0-0ab2-4697-bcc7-b069c3fff7d5" />
