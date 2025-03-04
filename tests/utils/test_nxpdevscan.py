#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2021-2023 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

import platform
from unittest.mock import MagicMock, patch

import libusbsio
import pytest
from serial import Serial
from serial.tools.list_ports_common import ListPortInfo

import spsdk.utils.devicedescription as devicedescription
import spsdk.utils.nxpdevscan as nds
from spsdk import SPSDKError


def test_usb_device_search():
    """Test, that search method returns all NXP devices based on their VID.
    Default VID's so far are 0x1fc9, 0x15a2.
    """
    test_vector = [
        {
            "vendor_id": 0x0001,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
        {
            "vendor_id": 0x15,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
        {
            "vendor_id": 0x1FC9,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
        {
            "vendor_id": 0x15A2,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
    ]
    result = [
        devicedescription.USBDeviceDescription(0x1FC9, 0, "", "", "", "", ""),
        devicedescription.USBDeviceDescription(0x15A2, 0, "", "", "", "", ""),
    ]

    with patch("libusbsio.LIBUSBSIO.HIDAPI_Enumerate", MagicMock(return_value=test_vector)):
        devices = nds.search_nxp_usb_devices()

        assert len(devices) == len(result)

        for dev, res in zip(devices, result):
            assert dev.info() == res.info()


def test_usb_device_search_extended():
    """Verify search method returns all NXP devices based on their VID + all
    additional devices.
    Default VID's so far are 0x1fc9, 0x15a2
    """
    test_vector = [
        {
            "vendor_id": 0x1FC9,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
        {
            "vendor_id": 0x0001,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
        {
            "vendor_id": 0x15,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
        {
            "vendor_id": 0x1FC9,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
        {
            "vendor_id": 0x0002,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
        {
            "vendor_id": 0x15A2,
            "product_id": 0,
            "path": b"",
            "manufacturer_string": "",
            "product_string": "",
            "serial_number": "",
        },
    ]
    result = [
        devicedescription.USBDeviceDescription(0x1FC9, 0, "", "", "", "", ""),
        devicedescription.USBDeviceDescription(0x1FC9, 0, "", "", "", "", ""),
        devicedescription.USBDeviceDescription(0x0002, 0, "", "", "", "", ""),
        devicedescription.USBDeviceDescription(0x15A2, 0, "", "", "", "", ""),
    ]
    with patch("libusbsio.LIBUSBSIO.HIDAPI_Enumerate", MagicMock(return_value=test_vector)):
        devices = nds.search_nxp_usb_devices([0x2])

        assert len(devices) == len(result)

        for dev, res in zip(devices, result):
            assert dev.info() == res.info()


# following mock functions are only for `test_uart_device_search usage`
def mock_mb_scan_uart(port, *args, **kwargs):
    return True if port == "COM1" else False


def mock_sdp_read_status(self, *args, **kwargs):
    print("inside mock_sdp_read_status")
    retval = 1 if self._device.device.port == "COM5" else None
    return retval


def mock_sdp_uart_init(self, port: str = None, timeout: int = 5000, baudrate: int = 115200):
    self.device = Serial(port=None, timeout=timeout / 1000, baudrate=baudrate)
    self.device.port = port
    self.expect_status = True


list_port_info_mock = [
    ListPortInfo(device="COM1"),
    ListPortInfo(device="COM5"),
    ListPortInfo(device="COM28"),
]


@patch("spsdk.utils.nxpdevscan.mb_scan_uart", mock_mb_scan_uart)
@patch("spsdk.utils.nxpdevscan.SDP.read_status", mock_sdp_read_status)
@patch("spsdk.utils.nxpdevscan.SDP_Uart.__init__", mock_sdp_uart_init)
@patch("spsdk.utils.nxpdevscan.comports", MagicMock(return_value=list_port_info_mock))
def test_uart_device_search():
    """Test, that search method returns all NXP Uart devices."""

    result = [
        devicedescription.UartDeviceDescription(name="COM1", dev_type="mboot device"),
        devicedescription.UartDeviceDescription(name="COM5", dev_type="SDP device"),
    ]

    devices = nds.search_nxp_uart_devices()

    assert len(devices) == len(result)

    for dev, res in zip(devices, result):
        assert dev.info() == res.info()


@pytest.mark.parametrize(
    "vid, pid, expected_result",
    [
        (0x1111, 0x2222, []),
        (0x15A2, 0x0073, ["MKL27", "MXRT20", "MXRT50", "MXRT60"]),
        (0x1FC9, 0x0135, ["IMXRT", "MXRT60"]),
    ],
)
def test_get_device_name(vid, pid, expected_result):
    """Verify search works and returns appropriate name based on VID/PID"""
    assert devicedescription.get_usb_device_name(vid, pid) == expected_result


def test_path_conversion():
    """Verify, that path gets converted properly."""
    with patch("platform.system", MagicMock(return_value="Windows")):
        win_path = (
            b"\\\\?\\hid#vid_1fc9&pid_0130#6&1625c75b&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}"
        )
        assert (
            devicedescription.convert_usb_path(win_path)
            == "HID\\VID_1FC9&PID_0130\\6&1625C75B&0&0000"
        )

    with patch("platform.system", MagicMock(return_value="Linux")):
        linux_path = b"000A:000B:00"

        assert devicedescription.convert_usb_path(linux_path) == "10#11"

    with patch("platform.system", MagicMock(return_value="Darwin")):
        mac_path = b"IOService:/AppleACPIPlatformExpert/PCI0@0/AppleACPIPCI/XHC1@14/XHC1@14000000/HS02@14200000/SE Blank RT Family @14200000"

        assert (
            devicedescription.convert_usb_path(mac_path)
            == "IOService:/AppleACPIPlatformExpert/PCI0@0/AppleACPIPCI/XHC1@14/XHC1@14000000/HS02@14200000/SE Blank RT Family @14200000"
        )


PATH_BY_SYSTEM = {
    "win": (b"some_path", "SOME_PATH", "0a595daf"),
    "linux": (b"000A:000B:00", "10#11", "6359be0f"),
    "darwin": (
        b"IOService:/AppleACPIPlatformExpert/PCI0@0/AppleACPIPCI/XHC1@14/XHC1@14000000/HS02@14200000/SE Blank RT Family @14200000",
        "IOService:/AppleACPIPlatformExpert/PCI0@0/AppleACPIPCI/XHC1@14/XHC1@14000000/HS02@14200000/SE Blank RT Family @14200000",
        "cafe5e92",
    ),
}


def mock_libusbsio_GetDeviceInfo(self, dev: int):
    """MagicMock override function to return information."""
    assert dev == 0
    sio_info = libusbsio.LIBUSBSIO.HIDAPI_DEVICE_INFO_T()
    sio_info.vendor_id = 10
    sio_info.product_id = 20
    sio_info.product_string = "my product"
    sio_info.manufacturer_string = "manufacturer X"
    sio_info.serial_number = "sio device"
    sio_info.interface_number = 5
    sio_info.release_number = 125

    system = platform.system()
    if system == "Windows":
        sio_info.path = PATH_BY_SYSTEM["win"][0]
    if system == "Linux":
        sio_info.path = PATH_BY_SYSTEM["linux"][0]
    if system == "Darwin":
        sio_info.path = PATH_BY_SYSTEM["darwin"][0]

    return sio_info


@patch("libusbsio.LIBUSBSIO.GetNumPorts", MagicMock(return_value=1))
@patch("libusbsio.LIBUSBSIO.GetDeviceInfo", mock_libusbsio_GetDeviceInfo)
def test_sio_device_search():
    """Test, that search method returns all NXP SIO devices."""

    def get_return(path):
        return (
            "LIBUSBSIO - manufacturer X, my product\n"
            "Vendor ID: 0x000a\n"
            "Product ID: 0x0014\n"
            f"Path: {path[1]}\n"
            f"Path Hash: {path[2]}\n"
            "Serial number: sio device\n"
            "Interface number: 5\n"
            "Release number: 125"
        )

    if platform.system() != "Darwin":
        # Windows and Linux libraries cannot be loaded on Mac with Apple Sillicon
        with patch("platform.system", MagicMock(return_value="Windows")):
            devices = nds.search_libusbsio_devices()
            assert len(devices) == 1
            assert devices[0].info() == get_return(PATH_BY_SYSTEM["win"])

        with patch("platform.system", MagicMock(return_value="Linux")):
            devices = nds.search_libusbsio_devices()
            assert len(devices) == 1
            assert devices[0].info() == get_return(PATH_BY_SYSTEM["linux"])

    with patch("platform.system", MagicMock(return_value="Darwin")):
        devices = nds.search_libusbsio_devices()
        assert len(devices) == 1
        assert devices[0].info() == get_return(PATH_BY_SYSTEM["darwin"])


def mock_libusbsio_GetNumPorts(self, vidpids=None):
    """Try to get number of ports from LIBUSBSIO, but it fails."""
    raise libusbsio.LIBUSBSIO_Exception("Test Fail")


@patch("libusbsio.LIBUSBSIO.GetNumPorts", mock_libusbsio_GetNumPorts)
def test_sio_device_search_fail():
    """Test, that search method returns all NXP SIO devices and its fails."""
    with pytest.raises(SPSDKError):
        nds.search_libusbsio_devices()
