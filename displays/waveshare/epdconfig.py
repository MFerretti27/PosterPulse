import logging
import time
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


class RaspberryPi:
    def __init__(
        self,
        rst_pin: int = 17,
        dc_pin: int = 25,
        cs_pin: int = 8,
        busy_pin: int = 24,
        pwr_pin: int = 27,
    ) -> None:
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.cs_pin = cs_pin
        self.busy_pin = busy_pin
        self.pwr_pin = pwr_pin

        self.spi: Any = None
        self.gpio_lib: Optional[str] = None
        self._gpio: Any = None
        self._gpiozero_devs: dict = {}

    def digital_write(self, pin: int, value: int) -> None:
        # CE0/BCM 8 is owned by the SPI controller and must not also be claimed
        # as a gpiozero/RPi.GPIO output. The SPI driver controls chip select.
        if pin == self.cs_pin:
            return
        if self.gpio_lib == "RPi.GPIO":
            self._gpio.output(pin, value)
        elif self.gpio_lib == "gpiozero":
            dev = self._gpiozero_devs.get(pin)
            if dev:
                if value:
                    dev.on()
                else:
                    dev.off()
        elif self.gpio_lib == "mock":
            pass

    def digital_read(self, pin: int) -> int:
        if self.gpio_lib == "RPi.GPIO":
            return int(self._gpio.input(pin))
        elif self.gpio_lib == "gpiozero":
            dev = self._gpiozero_devs.get(pin)
            if dev:
                return 1 if dev.is_active else 0
        elif self.gpio_lib == "mock":
            return 1
        return 1

    def delay_ms(self, delaytime: int) -> None:
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data: List[int]) -> None:
        if self.spi is not None:
            self.spi.writebytes(data)

    def spi_writebyte2(self, data: List[int]) -> None:
        if self.spi is not None:
            # Transfer in chunks to prevent SPI buffer overflow
            chunk_size = 4096
            for i in range(0, len(data), chunk_size):
                self.spi.writebytes2(data[i : i + chunk_size])

    def module_init(self) -> int:
        # EPD.init() may call this after the display backend already probed the
        # hardware. Reuse an existing setup instead of claiming GPIOs twice.
        if self.spi is not None and self.gpio_lib is not None:
            return 0

        # Try gpiozero first (standard on Bookworm), then RPi.GPIO
        try:
            import gpiozero  # type: ignore[import]

            self.gpio_lib = "gpiozero"
            self._gpiozero_devs[self.rst_pin] = gpiozero.LED(self.rst_pin)
            self._gpiozero_devs[self.dc_pin] = gpiozero.LED(self.dc_pin)
            self._gpiozero_devs[self.pwr_pin] = gpiozero.LED(self.pwr_pin)
            self._gpiozero_devs[self.busy_pin] = gpiozero.Button(
                self.busy_pin, pull_up=None, active_state=True
            )
        except Exception:  # noqa: BLE001 - try alternate GPIO backend on any init failure
            try:
                import RPi.GPIO as GPIO  # type: ignore[import]

                self.gpio_lib = "RPi.GPIO"
                self._gpio = GPIO
                self._gpio.setmode(self._gpio.BCM)
                self._gpio.setwarnings(False)
                self._gpio.setup(self.rst_pin, self._gpio.OUT)
                self._gpio.setup(self.dc_pin, self._gpio.OUT)
                self._gpio.setup(self.cs_pin, self._gpio.OUT)
                self._gpio.setup(self.pwr_pin, self._gpio.OUT)
                self._gpio.setup(self.busy_pin, self._gpio.IN)
            except Exception as exc:  # noqa: BLE001 - fall back when GPIO init fails
                logger.warning(
                    "GPIO library not available (gpiozero / RPi.GPIO): %s. Falling back to mock.",
                    exc,
                )
                self.gpio_lib = "mock"

        # Initialize SPI
        try:
            import spidev  # type: ignore[import]

            self.spi = spidev.SpiDev(0, 0)
            self.spi.max_speed_hz = 4000000
            self.spi.mode = 0b00
        except Exception as exc:  # noqa: BLE001 - SPI is optional outside the Pi
            logger.warning("spidev not available: %s. Falling back to mock SPI.", exc)
            self.spi = None

        # Turn on display power pin (BCM 27 for PhotoPainter)
        self.digital_write(self.pwr_pin, 1)
        return 0

    def module_exit(self, cleanup_power: bool = True) -> None:
        if cleanup_power:
            self.digital_write(self.pwr_pin, 0)

        if self.spi is not None:
            try:
                self.spi.close()
            except Exception:  # noqa: BLE001 - continue cleanup after close failure
                logger.warning("Could not close SPI device", exc_info=True)

        if self.gpio_lib == "RPi.GPIO" and self._gpio is not None:
            self._gpio.output(self.rst_pin, 0)
            self._gpio.output(self.dc_pin, 0)
            self._gpio.cleanup(
                [self.rst_pin, self.dc_pin, self.busy_pin, self.pwr_pin]
            )
        elif self.gpio_lib == "gpiozero":
            for dev in self._gpiozero_devs.values():
                try:
                    dev.close()
                except Exception:  # noqa: BLE001 - close remaining GPIO devices
                    logger.warning("Could not close GPIO device", exc_info=True)
            self._gpiozero_devs.clear()

        self.spi = None
        self.gpio_lib = None


# Default singleton instance (configured with PhotoPainter PWR_PIN=27)
implementation = RaspberryPi()

digital_write = implementation.digital_write
digital_read = implementation.digital_read
delay_ms = implementation.delay_ms
spi_writebyte = implementation.spi_writebyte
spi_writebyte2 = implementation.spi_writebyte2
module_init = implementation.module_init
module_exit = implementation.module_exit
