"""
PowerButtonObject: Handles GPIO button input and WS2811 LED output for a power button service.
"""
import math
import os
import time
import subprocess
import urllib.request
import urllib.error
import threading
from typing import Any, cast
import logging
from threading import Event
import logManager

try:
    import RPi.GPIO as IO  # type: ignore
    from rpi_ws281x import PixelStrip, Color  # type: ignore
except (ImportError, RuntimeError):
    from services.dummy_import import DummyGPIO as IO  # Import a dummy GPIO class for testing
    from services.dummy_import import DummyPixelStrip as PixelStrip, DummyColor as Color  # type: ignore
from services.dummy_import import DummyPixelStrip


logger: logging.Logger = logManager.logger.get_logger(__name__)

GPIO_BCM: Any = cast(Any, IO.BCM)
GPIO_IN: Any = cast(Any, IO.IN)
GPIO_LOW: Any = cast(Any, IO.LOW)
GPIO_PUD_UP: Any = cast(Any, IO.PUD_UP)

# WS2811 strip constants
_LED_COUNT: int = 1
_LED_FREQ_HZ: int = 800_000
_LED_INVERT: bool = False
_LED_CHANNEL: int = 0


class PowerButtonObject:
    """
    Power button service for handling GPIO button input and WS2811 LED output.
    """
    def __init__(self, data: dict[str, Any]) -> None:
        self.button_pin: int = data.get("button_pin", 3)
        self.long_press_duration: float = data.get("long_press_duration", 3.0)
        self.debounce_time: float = data.get("debounce_time", 0.05)
        self.led_pin: int = data.get("led_pin", 18)
        self.led_brightness: int = data.get("led_brightness", 150)
        self.led_dma: int = data.get("led_dma", 5)
        # Host shutdown configuration (can be set via web UI)
        self.host_shutdown_url: str = data.get(
            "host_shutdown_url",
            os.environ.get(
                'HOST_SHUTDOWN_URL',
                'http://localhost:5000/api/system/commands/core/reboot'
            ),
        )
        self.host_api_key: str | None = data.get("host_api_key", os.environ.get('HOST_API_KEY'))

        self.shutdown_event: Event = Event()

        # GPIO button setup
        IO.setmode(GPIO_BCM)
        IO.setup(self.button_pin, GPIO_IN, pull_up_down=GPIO_PUD_UP)
        self.last_press_time: float = time.time()

        # WS2811 LED setup
        self._strip: Any = PixelStrip(
            _LED_COUNT,
            self.led_pin,
            _LED_FREQ_HZ,
            self.led_dma,
            _LED_INVERT,
            self.led_brightness,
            _LED_CHANNEL,
        )
        try:
            self._strip.begin()
        except RuntimeError as e:
            logger.warning(f"LED strip init failed ({e}), falling back to dummy LED")
            self._strip = DummyPixelStrip(
                _LED_COUNT,
                self.led_pin,
                _LED_FREQ_HZ,
                self.led_dma,
                _LED_INVERT,
                self.led_brightness,
                _LED_CHANNEL,
            )
            self._strip.begin()

        self._led_stop_event: threading.Event = threading.Event()
        self._led_thread: threading.Thread | None = None

        # Boot colour-sweep animation
        self._led_boot_effect()
        # Idle: slow green breathing
        self._led_start_breathing(0, 200, 60)

    # ------------------------------------------------------------------ #
    # Internal LED helpers                                                 #
    # ------------------------------------------------------------------ #

    def _raw_set_color(self, r: int, g: int, b: int) -> None:
        """Set pixel color directly without touching the background thread."""
        self._strip.setPixelColor(0, Color(r, g, b))
        self._strip.show()

    def _stop_led_effect(self) -> None:
        """Signal the background LED thread to stop and wait for it."""
        self._led_stop_event.set()
        if self._led_thread and self._led_thread.is_alive():
            self._led_thread.join(timeout=1.0)
        self._led_thread = None
        self._led_stop_event.clear()

    def _breathing_worker(self, r: int, g: int, b: int) -> None:
        """Smooth sinusoidal breathing effect – runs in a background thread."""
        t = 0.0
        while not self._led_stop_event.is_set():
            brightness = (math.sin(t) + 1.0) / 2.0  # 0.0 – 1.0
            self._raw_set_color(
                int(r * brightness),
                int(g * brightness),
                int(b * brightness),
            )
            t += 0.035
            self._led_stop_event.wait(0.02)  # ~50 fps, interruptible sleep

    # ------------------------------------------------------------------ #
    # Public LED effects                                                   #
    # ------------------------------------------------------------------ #

    def _led_start_breathing(self, r: int, g: int, b: int) -> None:
        """Start a smooth breathing animation in a background thread."""
        self._stop_led_effect()
        self._led_thread = threading.Thread(
            target=self._breathing_worker,
            args=(r, g, b),
            daemon=True,
        )
        self._led_thread.start()

    def _led_set_solid(self, r: int, g: int, b: int) -> None:
        """Set a solid colour (stops any running effect)."""
        self._stop_led_effect()
        self._raw_set_color(r, g, b)

    def _led_off(self) -> None:
        """Turn the LED off."""
        self._stop_led_effect()
        self._raw_set_color(0, 0, 0)

    def _led_flash(
        self,
        r: int,
        g: int,
        b: int,
        times: int = 3,
        on_time: float = 0.15,
        off_time: float = 0.10,
    ) -> None:
        """Synchronous flash: blink `times` times then leave LED off."""
        self._stop_led_effect()
        for _ in range(times):
            self._raw_set_color(r, g, b)
            time.sleep(on_time)
            self._raw_set_color(0, 0, 0)
            time.sleep(off_time)

    def _led_boot_effect(self) -> None:
        """Rainbow colour-sweep on startup."""
        rainbow = [
            (255, 0,   0),    # red
            (255, 80,  0),    # orange
            (255, 200, 0),    # yellow
            (0,   255, 0),    # green
            (0,   100, 255),  # blue
            (160, 0,   255),  # violet
        ]
        for r, g, b in rainbow:
            self._raw_set_color(r, g, b)
            time.sleep(0.12)
        # Fade out from violet
        for step in range(10, -1, -1):
            v = step / 10.0
            self._raw_set_color(int(160 * v), 0, int(255 * v))
            time.sleep(0.04)

    def _led_shutdown_effect(self) -> None:
        """Escalating red pulses to signal imminent shutdown, ending solid-red."""
        self._stop_led_effect()
        for delay in (0.25, 0.20, 0.15, 0.10, 0.07, 0.05):
            self._raw_set_color(255, 0, 0)
            time.sleep(delay)
            self._raw_set_color(0, 0, 0)
            time.sleep(delay)
        self._raw_set_color(255, 0, 0)  # stay red until cleanup

    # ------------------------------------------------------------------ #
    # GPIO / system helpers                                                #
    # ------------------------------------------------------------------ #

    def cleanup(self) -> None:
        """Clean up LED and GPIO resources."""
        self._led_off()
        IO.cleanup()
        logger.info("IO cleanup completed")

    def button_pressed(self) -> bool:
        """Return True if the button is currently pressed (LOW with pull-up)."""
        return IO.input(self.button_pin) == GPIO_LOW

    def wait_for_button_release(self) -> None:
        """Block until the button is released."""
        while self.button_pressed():
            time.sleep(0.01)

    def execute_shutdown(self) -> None:
        """Execute a clean system shutdown."""
        logger.info("Initiating system shutdown...")
        try:
            subprocess.run(['sync'], check=True)
            if os.geteuid() == 0:
                # Attempt to call configured host shutdown service (useful when running in Docker).
                if self.host_api_key:
                    logger.info(f"Shutting down host via HTTP POST to {self.host_shutdown_url}")
                    try:
                        req = urllib.request.Request(
                            self.host_shutdown_url,
                            data=b'',
                            method='POST',
                            headers={
                                'X-Api-Key': self.host_api_key,
                                'Content-Type': 'application/json',
                            },
                        )
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            status = getattr(resp, 'status', None) or resp.getcode()
                            logger.info(f"Host shutdown service responded: {status}")
                            return
                    except urllib.error.HTTPError as e:
                        logger.error(f"Host shutdown HTTP error: {e.code} {e.reason}")
                    except urllib.error.URLError as e:
                        logger.error(f"Host shutdown URL error: {e}")
                    except (TimeoutError, OSError) as e:
                        logger.error(f"Unexpected error calling host shutdown service: {e}")
                    # If the HTTP call failed, fall through to local shutdown fallback
                # Fallback to direct shutdown if no API key or HTTP call fails
                subprocess.run(['/sbin/shutdown', '-h', 'now'], check=True)
            else:
                subprocess.run(['sudo', '/sbin/shutdown', '-h', 'now'], check=True)
        except (subprocess.CalledProcessError, OSError) as e:
            logger.error(f"Shutdown command failed: {e}")

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Poll the button once; called repeatedly by the service loop."""
        try:
            if not self.button_pressed():
                return

            # Debounce
            time.sleep(self.debounce_time)
            if not self.button_pressed():
                return

            logger.info("Button pressed")
            self._stop_led_effect()
            press_start: float = time.time()

            while self.button_pressed() and not self.shutdown_event.is_set():
                press_duration: float = time.time() - press_start
                progress: float = press_duration / self.long_press_duration

                if press_duration >= self.long_press_duration:
                    logger.info(f"Long press detected ({press_duration:.1f}s) – shutting down")
                    self._led_shutdown_effect()
                    self.execute_shutdown()
                    return

                # Colour feedback based on how long the button has been held
                if progress < 0.50:
                    # Phase 1 – solid blue
                    self._raw_set_color(0, 80, 255)
                elif progress < 0.75:
                    # Phase 2 – warm orange warning
                    self._raw_set_color(255, 80, 0)
                else:
                    # Phase 3 – urgent fast red blink
                    if int(time.time() * 12) % 2 == 0:
                        self._raw_set_color(255, 0, 0)
                    else:
                        self._raw_set_color(0, 0, 0)

                time.sleep(0.05)

            # Button released before long-press threshold
            press_duration = time.time() - press_start
            if press_duration < self.long_press_duration:
                logger.info(f"Short press ({press_duration:.1f}s) – button event logged")
                self._led_flash(255, 255, 255, times=2, on_time=0.08, off_time=0.05)
                self._led_start_breathing(0, 200, 60)  # resume green idle

            self.wait_for_button_release()
            time.sleep(self.debounce_time)

        except (RuntimeError, OSError, AttributeError) as e:
            logger.error(f"Error in button handler: {e}")

    # ------------------------------------------------------------------ #
    # Config persistence                                                   #
    # ------------------------------------------------------------------ #

    def get_all_data(self) -> dict[str, Any]:
        """Get all power button service data"""
        return {
            "button_pin": self.button_pin,
            "long_press_duration": self.long_press_duration,
            "debounce_time": self.debounce_time,
            "led_pin": self.led_pin,
            "led_brightness": self.led_brightness,
            "led_dma": self.led_dma,
            "host_shutdown_url": self.host_shutdown_url,
            "host_api_key": self.host_api_key,
        }

    def save(self) -> dict[str, Any]:
        """Save the power button service configuration"""
        return self.get_all_data()
