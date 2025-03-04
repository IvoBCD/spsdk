#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2022-2023 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

from spsdk.image.images import BootImgRT
from spsdk.image.segments import XMCDHeader


def test_parse_xmcd(data_dir):
    with open(f"{data_dir}/evkmimxrt1170_xmcd.bin", "rb") as f:
        data = f.read()
    image = BootImgRT.parse(data)
    assert image.xmcd
    assert "XMCD" in image.info()


def test_parse_no_xmcd(data_dir):
    with open(f"{data_dir}/iled_blinky_cm7_dcd.bin", "rb") as f:
        data = f.read()
    image = BootImgRT.parse(data)
    assert image.xmcd is None
    assert "XMCD" not in image.info()


def test_xmcd_header():
    data = b"\x04\x12\x00\xc0"
    xmcd = XMCDHeader.parse(data)
    assert xmcd.block_size == 516
    assert xmcd.block_type == 1
    assert xmcd.instance == 0
    assert xmcd.interface == 0
    assert xmcd.tag == 12
    assert xmcd.version == 0
    exported = xmcd.export()
    assert exported == data
