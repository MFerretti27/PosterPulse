import logging
import time
from typing import List, Union
from PIL import Image # pyright: ignore[reportMissingImports]
from displays.waveshare import epdconfig

logger = logging.getLogger(__name__)


class EPD:
    # Display resolution
    width = 800
    height = 480

    BLACK = 0x0
    WHITE = 0x1
    YELLOW = 0x2
    RED = 0x3
    BLUE = 0x5
    GREEN = 0x6

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

    def send_data2(self, data: List[int]) -> None:
        self.config.digital_write(self.dc_pin, 1)
        self.config.digital_write(self.cs_pin, 0)
        self.config.spi_writebyte2(data)
        self.config.digital_write(self.cs_pin, 1)

    def read_busy_high(self, timeout_sec: float = 30.0) -> None:
        logger.debug("Waiting for e-Paper BUSY pin to go HIGH...")
        start = time.time()
        while self.config.digital_read(self.busy_pin) == 0:
            self.config.delay_ms(5)
            if time.time() - start > timeout_sec:
                logger.warning("Timeout waiting for e-Paper BUSY pin release.")
                break
        logger.debug("e-Paper is idle (BUSY pin released).")

    def turn_on_display(self) -> None:
        self.send_command(0x04)  # POWER_ON
        self.read_busy_high()

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

        # Register initialization sequence for 7.3inch e-Paper (E)
        self.send_command(0xAA)
        self.send_data(0x49)
        self.send_data(0x55)
        self.send_data(0x20)
        self.send_data(0x08)
        self.send_data(0x09)
        self.send_data(0x18)

        self.send_command(0x01)
        self.send_data(0x3F)

        self.send_command(0x00)
        self.send_data(0x5F)
        self.send_data(0x69)

        self.send_command(0x03)
        self.send_data(0x00)
        self.send_data(0x54)
        self.send_data(0x00)
        self.send_data(0x44)

        self.send_command(0x05)
        self.send_data(0x40)
        self.send_data(0x1F)
        self.send_data(0x1F)
        self.send_data(0x2C)

        self.send_command(0x06)
        self.send_data(0x6F)
        self.send_data(0x1F)
        self.send_data(0x17)
        self.send_data(0x49)

        self.send_command(0x08)
        self.send_data(0x6F)
        self.send_data(0x1F)
        self.send_data(0x1F)
        self.send_data(0x22)

        self.send_command(0x30)
        self.send_data(0x03)

        self.send_command(0x50)
        self.send_data(0x3F)

        self.send_command(0x60)
        self.send_data(0x02)
        self.send_data(0x00)

        self.send_command(0x61)
        self.send_data(0x03)
        self.send_data(0x20)
        self.send_data(0x01)
        self.send_data(0xE0)

        self.send_command(0x84)
        self.send_data(0x01)

        self.send_command(0xE3)
        self.send_data(0x2F)

        self.send_command(0x04)  # PWR ON
        self.read_busy_high()

        return 0

    @staticmethod
    def create_palette_image() -> Image.Image:
        """Create a 1x1 image with the 6-color palette for Floyd-Steinberg dithering."""
        pal_image = Image.new("P", (1, 1))
        # 6-color palette matching EPD 7in3e registers:
        # 0: Black, 1: White, 2: Yellow, 3: Red, 4: Unused, 5: Blue, 6: Green
        palette = [
            0,
            0,
            0,  # 0: Black
            255,
            255,
            255,  # 1: White
            255,
            255,
            0,  # 2: Yellow
            255,
            0,
            0,  # 3: Red
            0,
            0,
            0,  # 4: Reserved
            0,
            0,
            255,  # 5: Blue
            0,
            255,
            0,  # 6: Green
        ]
        # Pad up to 256 colors
        palette += [0, 0, 0] * (256 - 7)
        pal_image.putpalette(palette)
        return pal_image

    def getbuffer(self, image: Image.Image) -> List[int]:
        """Convert a PIL image (RGB) into the packed 4-bit buffer for epd7in3e."""
        pal_image = self.create_palette_image()

        imwidth, imheight = image.size
        if imwidth == self.width and imheight == self.height:
            image_temp = image
        elif imwidth == self.height and imheight == self.width:
            image_temp = image.rotate(90, expand=True)
        else:
            image_temp = image.resize(
                (self.width, self.height), Image.Resampling.LANCZOS
            )

        # Quantize using Floyd-Steinberg dithering against the 6-color palette
        image_quantized = image_temp.convert("RGB").quantize(
            palette=pal_image, dither=Image.Dither.FLOYDSTEINBERG
        )
        buf_raw = bytearray(image_quantized.tobytes("raw"))

        # Pack two 4-bit pixels into each byte: (pixel0 << 4) | pixel1
        buf: List[int] = [0x00] * int(self.width * self.height / 2)
        for idx, i in enumerate(range(0, len(buf_raw), 2)):
            buf[idx] = (buf_raw[i] << 4) + buf_raw[i + 1]

        return buf

    def display(self, image_or_buf: Union[Image.Image, List[int]]) -> None:
        if isinstance(image_or_buf, list):
            buf = image_or_buf
        else:
            buf = self.getbuffer(image_or_buf)

        self.send_command(0x10)
        self.send_data2(buf)
        self.turn_on_display()

    def clear(self, color: int = WHITE) -> None:
        high = (color << 4) | color
        buf = [high] * int(self.width * self.height / 2)
        self.send_command(0x10)
        self.send_data2(buf)
        self.turn_on_display()

    def sleep(self) -> None:
        self.send_command(0x07)  # DEEP_SLEEP
        self.send_data(0xA5)
        self.config.delay_ms(100)
        # Power down logic board via PWR pin
        self.config.digital_write(self.config.pwr_pin, 0)
        self.config.module_exit(cleanup_power=True)
