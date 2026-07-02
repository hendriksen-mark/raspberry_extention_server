"""Driver for TM1637 four-digit seven-segment LED display."""
import math
import time
from typing import Any, cast
try:
    import RPi.GPIO as IO  # type: ignore
except (ImportError, RuntimeError):
    from services.dummy_import import DummyGPIO as IO

from time import sleep
GPIO_BCM: Any = cast(Any, IO.BCM)
GPIO_OUT: Any = cast(Any, IO.OUT)
GPIO_IN: Any = cast(Any, IO.IN)
GPIO_HIGH: Any = cast(Any, IO.HIGH)
GPIO_LOW: Any = cast(Any, IO.LOW)

IO.setwarnings(False)
IO.setmode(GPIO_BCM)

HEX_DIGITS: list[int] = [0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d,
             0x07, 0x7f, 0x6f, 0x77, 0x7c, 0x39, 0x5e, 0x79, 0x71]

ADDR_AUTO: int = 0x40
ADDR_FIXED: int = 0x44
STARTADDR: int = 0xC0

class TM1637:
    """Driver for TM1637 four-digit seven-segment LED display."""
    __double_point: bool = False
    __clk_pin: int = 0
    __data_pin: int = 0
    __brightness: int = 0
    #1.0  # default to max brightness
    __current_data: list[int] = [0, 0, 0, 0]

    def __init__(self, clk: int, dio: int) -> None:
        self.__clk_pin = clk
        self.__data_pin = dio
        # Clean up any previous setup on these specific pins
        try:
            IO.cleanup([self.__clk_pin, self.__data_pin])
        except (RuntimeError, ValueError):
            pass  # Ignore if pins weren't previously setup
        IO.setup(self.__clk_pin, GPIO_OUT)
        IO.setup(self.__data_pin, GPIO_OUT)

    def cleanup(self) -> None:
        """Stop updating clock, turn off display, and cleanup GPIO"""
        self.clear()
        IO.cleanup()

    def clear(self) -> None:
        """Clear the display by sending 0x7F to all digits"""
        b: int = self.__brightness
        point: bool = self.__double_point
        self.__brightness = 0
        self.__double_point = False
        data: list[int] = [0x7F, 0x7F, 0x7F, 0x7F]
        self.show(data)
        # Restore previous settings:
        self.__brightness = b
        self.__double_point = point

    def show(self, data: list[int]) -> None:
        """
        Show the data on the display.
        Data should be a list of 4 integers (0-15) or 0x7F for blank.
        """
        for i in range(0, 4):
            self.__current_data[i] = data[i]

        self.start()
        self.write_byte(ADDR_AUTO)
        self.br()
        self.write_byte(STARTADDR)
        for i in range(0, 4):
            self.write_byte(self.coding(data[i]))
        self.br()
        self.write_byte(0x88 + int(self.__brightness))
        self.stop()

    def set_brightness(self, percent: float) -> None:
        """Accepts percent brightness from 0 - 1"""
        max_brightness: float = 7.0
        brightness: int = math.ceil(max_brightness * percent)
        brightness = max(brightness, 0)
        if self.__brightness != brightness:
            self.__brightness = brightness
            self.show(self.__current_data)

    def show_double_point(self, on: bool) -> None:
        """Show or hide double point divider"""
        if self.__double_point != on:
            self.__double_point = on
            self.show(self.__current_data)

    def write_byte(self, data: int) -> None:
        """Write a byte to the display."""
        for _ in range(0, 8):
            IO.output(self.__clk_pin, GPIO_LOW)
            if data & 0x01:
                IO.output(self.__data_pin, GPIO_HIGH)
            else:
                IO.output(self.__data_pin, GPIO_LOW)
            data = data >> 1
            IO.output(self.__clk_pin, GPIO_HIGH)

        # wait for ACK
        IO.output(self.__clk_pin, GPIO_LOW)
        IO.output(self.__data_pin, GPIO_HIGH)
        IO.output(self.__clk_pin, GPIO_HIGH)
        IO.setup(self.__data_pin, GPIO_IN)

        # Add timeout to prevent infinite blocking
        timeout = time.time() + 0.1  # 100ms timeout
        while IO.input(self.__data_pin) and time.time() < timeout:
            sleep(0.001)
            if IO.input(self.__data_pin):
                IO.setup(self.__data_pin, GPIO_OUT)
                IO.output(self.__data_pin, GPIO_LOW)
                IO.setup(self.__data_pin, GPIO_IN)
        IO.setup(self.__data_pin, GPIO_OUT)

    def start(self) -> None:
        """send start signal to TM1637"""
        IO.output(self.__clk_pin, GPIO_HIGH)
        IO.output(self.__data_pin, GPIO_HIGH)
        IO.output(self.__data_pin, GPIO_LOW)
        IO.output(self.__clk_pin, GPIO_LOW)

    def stop(self) -> None:
        """send stop signal to TM1637"""
        IO.output(self.__clk_pin, GPIO_LOW)
        IO.output(self.__data_pin, GPIO_LOW)
        IO.output(self.__clk_pin, GPIO_HIGH)
        IO.output(self.__data_pin, GPIO_HIGH)

    def br(self) -> None:
        """terse break"""
        self.stop()
        self.start()

    def coding(self, data: int) -> int:
        """Convert data to TM1637 encoding"""
        if self.__double_point:
            point_data: int = 0x80
        else:
            point_data: int = 0

        if data == 0x7F:
            encoded: int = 0
        else:
            encoded: int = HEX_DIGITS[data] + point_data
        return encoded
