#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2022-2023 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

"""This module contains generic implementation of image segment."""

import abc
from typing import Any, Dict

from spsdk.exceptions import SPSDKValueError
from spsdk.utils.database import Database
from spsdk.utils.registers import Registers


class SegmentBase:
    """Base class for image segment."""

    def __init__(self, family: str, revision: str) -> None:
        """Segment base Constructor.

        :param family: Chip family.
        :param revision: Optional Chip family revision.
        :raises SPSDKValueError: Unsupported family.
        """
        if family not in self.get_supported_families():
            raise SPSDKValueError(
                f"Unsupported chip family:{family}. {family} not in {self.get_supported_families()}"
            )
        self.family = family
        self.revision = revision

    @property
    @abc.abstractmethod
    def registers(self) -> Registers:
        """Registers of segment."""

    def export(self) -> bytes:
        """Export block binary.

        :return: Binary representation of segment.
        """
        return self.registers.image_info().export()

    def parse(self, binary: bytes) -> None:
        """Parse binary block into segment object.

        :param binary: binary image.
        :raises SPSDKValueError: Invalid input binary length.
        """
        if len(binary) != len(self.registers.image_info()):
            raise SPSDKValueError(
                f"Invalid length of input binary: {len(binary)} != {len(self.registers.image_info())}"
            )
        for reg in self.registers.get_registers():
            reg.set_value(
                int.from_bytes(binary[reg.offset // 8 : reg.offset // 8 + reg.width // 8], "little")
            )

    @staticmethod
    @abc.abstractmethod
    def load_from_config(config: Dict) -> Any:
        """Load configuration file.

        :param config: XMCD configuration file.
        :return: Segment object.
        """

    @abc.abstractmethod
    def create_config(self) -> str:
        """Create current configuration YAML.

        :return: Configuration of segment.
        """

    @classmethod
    def get_supported_families(cls) -> list:
        """Return list of supported families.

        :return: List of supported families.
        """
        return cls.get_database().devices.device_names

    @classmethod
    def get_memory_types(cls, family: str, revision: str = "latest") -> dict:
        """Get memory types data from database.

        :param family: Chip family.
        :param revision: Optional Chip family revision.
        """
        return cls.get_database().get_device_value("mem_types", family, revision, default={})

    @classmethod
    def get_supported_memory_types(cls, family: str, revision: str = "latest") -> list:
        """Get list of supported memory types data from database.

        :param family: Chip family.
        :param revision: Optional Chip family revision.
        """
        return list(cls.get_memory_types(family, revision).keys())

    @staticmethod
    @abc.abstractmethod
    def get_database() -> Database:
        """Get the devices database."""
