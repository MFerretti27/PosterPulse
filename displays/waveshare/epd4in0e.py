"""Waveshare 4-inch E-Paper E (E6) driver, adapted for PosterPulse's GPIO/SPI backend.

The controller sequence and packed 4-bit pixel format follow the Waveshare
reference driver (MIT license):
https://github.com/waveshareteam/e-Paper/tree/master/E-paper_Separate_Program/4inch_e-Paper_E/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epd4in0e.py

Copyright (c) Waveshare team
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import logging
import time

from PIL import Image

from displays.waveshare import epdconfig

logger = logging.getLogger(__name__)


class EPD:
    """400x600 six-color E6 panel using the shared Raspberry Pi SPI/GPIO layer."""

    width = 400
    height = 600

    def __init__(self, config=None) -> None:
        self.config = config or epdconfig.implementation
        self.reset_pin = self.config.rst_pin
        self.dc_pin = self.config.dc_pin
        self.busy_pin = self.config.busy_pin
        self.cs_pin = self.config.cs_pin

    def reset(self) -> None:
        self.config.digital_write(self.reset_pin, 1)
        self.config.delay_ms(20)
        self.config.digital_write(self.reset_pin, 0)
        self.config.delay_ms(2)
        self.config.digital_write(self.reset_pin, 1)
        self.config.delay_ms(20)

    def send_command(self, command: int) -> None:
        self.config.digital_write(self.dc_pin, 0)
        self.config.digital_write(self.cs_pin, 0)
        self.config.spi_writebyte([command])
        self.config.digital_write(self.cs_pin, 1)

    def send_data(self, data: int) -> None:
        self.config.digital_write(self.dc_pin, 1)
        self.config.digital_write(self.cs_pin, 0)
        self.config.spi_writebyte([data])
        self.config.digital_write(self.cs_pin, 1)

    def send_data2(self, data: list[int]) -> None:
        self.config.digital_write(self.dc_pin, 1)
        self.config.digital_write(self.cs_pin, 0)
        self.config.spi_writebyte2(data)
        self.config.digital_write(self.cs_pin, 1)

    def read_busy_high(self, timeout_seconds: float = 60.0) -> None:
        started = time.monotonic()
        while self.config.digital_read(self.busy_pin) == 0:
            if time.monotonic() - started >= timeout_seconds:
                raise TimeoutError("Timed out waiting for E6 e-Paper BUSY pin")
            self.config.delay_ms(5)
        self.config.delay_ms(200)

    def turn_on_display(self) -> None:
        self.send_command(0x04)  # POWER_ON
        self.read_busy_high()
        self.send_command(0x06)  # Booster soft start
        for value in (0x6F, 0x1F, 0x17, 0x27):
            self.send_data(value)
        self.config.delay_ms(200)
        self.send_command(0x12)  # DISPLAY_REFRESH
        self.send_data(0x00)
        self.read_busy_high()
        self.send_command(0x02)  # POWER_OFF
        self.send_data(0x00)
        self.read_busy_high()

    def init(self) -> int:
        if self.config.module_init() != 0:
            return -1

        self.reset()
        self.read_busy_high()
        self.config.delay_ms(30)

        # Waveshare E6 controller register sequence.
        for command, values in (
            (0xAA, (0x49, 0x55, 0x20, 0x08, 0x09, 0x18)),
            (0x01, (0x3F,)),
            (0x00, (0x5F, 0x69)),
            (0x05, (0x40, 0x1F, 0x1F, 0x2C)),
            (0x08, (0x6F, 0x1F, 0x1F, 0x22)),
            (0x06, (0x6F, 0x1F, 0x17, 0x17)),
            (0x03, (0x00, 0x54, 0x00, 0x44)),
            (0x60, (0x02, 0x00)),
            (0x30, (0x08,)),
            (0x50, (0x3F,)),
            (0x61, (0x01, 0x90, 0x02, 0x58)),
            (0xE3, (0x2F,)),
            (0x84, (0x01,)),
        ):
            self.send_command(command)
            for value in values:
                self.send_data(value)

        self.read_busy_high()
        return 0

    @staticmethod
    def create_palette_image() -> Image.Image:
        """Return the panel's palette: black, white, yellow, red, blue, green."""
        palette_image = Image.new("P", (1, 1))
        palette = [
            0,
            0,
            0,  # Black, index 0
            255,
            255,
            255,  # White, index 1
            255,
            255,
            0,  # Yellow, index 2
            255,
            0,
            0,  # Red, index 3
            0,
            0,
            0,  # Reserved, index 4
            0,
            0,
            255,  # Blue, index 5
            0,
            255,
            0,  # Green, index 6
        ]
        palette.extend([0, 0, 0] * (256 - 7))
        palette_image.putpalette(palette)
        return palette_image

    def getbuffer(self, image: Image.Image) -> list[int]:
        """Convert RGB image into the E6 controller's packed 4-bit pixel data."""
        if image.size == (self.width, self.height):
            source = image
        elif image.size == (self.height, self.width):
            source = image.rotate(90, expand=True)
        else:
            source = image.resize((self.width, self.height), Image.Resampling.LANCZOS)

        indexed = source.convert("RGB").quantize(
            palette=self.create_palette_image(), dither=Image.Dither.FLOYDSTEINBERG
        )
        pixels = indexed.tobytes()
        packed = [0] * (self.width * self.height // 2)
        for output_index, pixel_index in enumerate(range(0, len(pixels), 2)):
            packed[output_index] = (pixels[pixel_index] << 4) | pixels[pixel_index + 1]
        return packed

    def display(self, buffer: list[int]) -> None:
        self.send_command(0x10)
        self.send_data2(buffer)
        self.turn_on_display()

    def clear(self, color: int = 0x11) -> None:
        self.send_command(0x10)
        self.send_data2([color] * (self.width * self.height // 2))
        self.turn_on_display()

    def sleep(self) -> None:
        self.send_command(0x07)
        self.send_data(0xA5)
        self.config.delay_ms(2000)
        self.config.module_exit(cleanup_power=True)
