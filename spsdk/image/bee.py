#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2020-2023 NXP
#
# SPDX-License-Identifier: BSD-3-Clause
"""Contains support for BEE encryption for RT10xx devices."""


import logging
import os
from struct import calcsize, pack, unpack_from
from typing import Any, Dict, List, Optional, Sequence

from Crypto.Cipher import AES

from spsdk import SPSDKError
from spsdk.exceptions import SPSDKOverlapError
from spsdk.utils import UTILS_DATA_FOLDER
from spsdk.utils.crypto import Counter, crypto_backend
from spsdk.utils.database import Database
from spsdk.utils.easy_enum import Enum
from spsdk.utils.misc import (
    DebugInfo,
    align_block_fill_random,
    extend_block,
    load_binary,
    split_data,
    value_to_bytes,
    value_to_int,
)
from spsdk.utils.schema_validator import ConfigTemplate, ValidationSchemas

logger = logging.getLogger(__name__)


BEE_DATA_FOLDER: str = os.path.join(UTILS_DATA_FOLDER, "bee")
BEE_SCH_FILE: str = os.path.join(BEE_DATA_FOLDER, "sch_bee.yaml")
BEE_DATABASE_FILE: str = os.path.join(BEE_DATA_FOLDER, "database.yaml")

# maximal size of encrypted block in bytes
BEE_ENCR_BLOCK_SIZE = 0x400
# mask of the bits in the address, that must be zero
_ENCR_BLOCK_ADDR_MASK = BEE_ENCR_BLOCK_SIZE - 1  # 0x3FF


class BeeBaseClass:
    """BEE base class."""

    # format of the binary representation of the class, used as parameter for struct.pack/unpack methods
    # the format is class specific, and must be defined in child class
    _FORMAT = "@_must_be_defined_in_child_class_@"

    @classmethod
    def _struct_format(cls) -> str:
        """:return: format string for struct.pack/unpack function used for export/import from binary format."""
        return cls._FORMAT  # _FORMAT class constant must be defined in child class

    @classmethod
    def _size(cls) -> int:
        """:return: size of the exported binary data in bytes."""
        return calcsize(cls._struct_format())

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, self.__class__) and (vars(other) == vars(self))

    @property
    def size(self) -> int:
        """:return: size of the exported binary data in bytes."""
        return self._size()

    def info(self) -> str:
        """Info method.

        :return: text description of the instance.
        :raises NotImplementedError: Derived class has to implement this method
        """
        raise NotImplementedError("Derived class has to implement this method.")

    def update(self) -> None:
        """Updates internal fields of the instance."""

    def validate(self) -> None:
        """Validates the configuration of the instance.

        It is recommended to call the method before export and after parsing.
        """

    def export(self) -> bytes:
        """:return: binary representation of the region (serialization)."""
        self.update()
        self.validate()
        return b""

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> Any:
        """Deserialization.

        :param data: binary data to be parsed
        :param offset: to start parsing the data
        :return: instance created from binary data; this method returns just `0`
        :raises SPSDKError: If size of the data is not sufficient
        """
        if len(data) - offset < cls._size():
            raise SPSDKError("Insufficient size of the data")
        return 0


class BeeFacRegion(BeeBaseClass):
    """BEE Factory Access Control (FAC) region."""

    # format of the binary representation of the class, used as parameter for struct.pack/unpack methods
    _FORMAT = "<3I20s"

    def __init__(self, start: int = 0, length: int = 0, protected_level: int = 0):
        """Constructor.

        :param start: Start address of one FAC region, align at 1KB boundary; 32-bit number
        :param length: Length of one FAC region, align at 1KB boundary; 32-bit number
        :param protected_level: Protected level: 0/1/2/3; 32-bit number
        """
        self.start_addr = start
        self.length = length
        self.protected_level = protected_level
        # immediately validate all parameters
        self.validate()

    def __str__(self) -> str:
        return f"FAC: 0x{self.start_addr:08x}[0x{self.length:x}]"

    @property
    def end_addr(self) -> int:
        """:return: end address of the region (which is last address of the region + 1)."""
        return self.start_addr + self.length

    def info(self) -> str:
        """:return: test description of the instance."""
        return f"FAC(start={hex(self.start_addr)}, length={hex(self.length)}, protected_level={self.protected_level})"

    def validate(self) -> None:
        """Validates the configuration of the instance."""
        if (self.start_addr & _ENCR_BLOCK_ADDR_MASK != 0) and (
            self.length & _ENCR_BLOCK_ADDR_MASK != 0
        ):
            raise SPSDKError("Invalid configuration of the instance")
        if self.protected_level < 0 or self.protected_level > 3:
            raise SPSDKError("Invalid protected level")
        if self.start_addr < 0 or self.end_addr > 0xFFFFFFFF or self.start_addr >= self.end_addr:
            raise SPSDKError("Invalid start/end address")

    def export(self) -> bytes:
        """Exports the binary representation."""
        result = super().export()
        return result + pack(
            self._struct_format(),
            self.start_addr,
            self.end_addr,
            self.protected_level,
            b"\x00" * 20,
        )

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "BeeFacRegion":
        """Deserialization.

        :param data: binary data to be parsed
        :param offset: to start parsing the data
        :return: instance created from binary data
        :raises SPSDKError: If reserved area is non-zero
        """
        super().parse(data, offset)  # check size of the data
        (start, end, protected_level, _reserved) = unpack_from(
            BeeFacRegion._struct_format(), data, offset
        )
        if _reserved != b"\x00" * 20:
            raise SPSDKError("Reserved area is non-zero")
        return BeeFacRegion(start, end - start, protected_level)


class BeeProtectRegionBlockAesMode(Enum):
    """AES mode selection for BEE PRDB encryption."""

    ECB = 0
    CTR = 1


class BeeProtectRegionBlock(BeeBaseClass):
    """BEE protect region block (PRDB)."""

    # format of the binary representation of the class, used as parameter for struct.pack/unpack methods
    _FORMAT = "<8I16s32s"
    # low TAG used in the header
    TAGL = 0x5F474154  # "TAG_"
    # high TAG used in the header
    TAGH = 0x52444845  # "EHDR"
    # version of the format
    VERSION = 0x56010000
    # number of FAC regions included in the header; the real limit of FAC regions depends on the processor
    FAC_REGIONS = 4
    # total size
    SIZE = 0x100

    @classmethod
    def _size(cls) -> int:
        """:return: size of the exported binary data in bytes."""
        return cls.SIZE

    def __init__(
        self,
        encr_mode: BeeProtectRegionBlockAesMode = BeeProtectRegionBlockAesMode.CTR,
        lock_options: int = 0,
        counter: Optional[bytes] = None,
    ):
        """Constructor.

        :param encr_mode: AES encryption mode
        :param lock_options: Lock options; 32-bit number
        :param counter: Counter for AES-CTR mode; 16 bytes; by default, random value is used
        """
        # - Encrypt region info:
        self._start_addr = 0  # this is calculated automatically based on FAC regions
        self._end_addr = 0xFFFFFFFF  # this is calculated automatically based on FAC regions
        self.mode = encr_mode
        self.lock_options = lock_options
        self.counter = (
            counter if counter else crypto_backend().random_bytes(12) + b"\x00\x00\x00\x00"
        )

        # - FAC regions, 1 - 4
        self.fac_regions: List[BeeFacRegion] = []

    def update(self) -> None:
        """Updates start and end address of the encryption region."""
        super().update()
        # update FAC regions
        for fac in self.fac_regions:
            fac.update()
        # update start and end address
        min_addr = 0 if self.fac_count == 0 else 0xFFFFFFFF
        max_addr = 0
        for fac in self.fac_regions:
            min_addr = min(min_addr, fac.start_addr)
            max_addr = max(max_addr, fac.end_addr)
        self._start_addr = min_addr
        self._end_addr = max_addr

    def add_fac(self, fac: BeeFacRegion) -> None:
        """Append FAC region.

        :param fac: Factory Access Control to be added
        """
        self.fac_regions.append(fac)
        self.update()

    @property
    def fac_count(self) -> int:
        """:return: number of Factory Access Control regions."""
        return len(self.fac_regions)

    def info(self) -> str:
        """:return: test description of the instance."""
        result = f"BEE Region Header (start={hex(self._start_addr)}, end={hex(self._end_addr)})\n"
        result += f"AES Encryption mode: {BeeProtectRegionBlockAesMode.name(self.mode)}\n"
        for fac in self.fac_regions:
            result += fac.info() + "\n"
        return result

    def validate(self) -> None:
        """Validates settings of the instance."""
        if self._start_addr < 0 or self._start_addr > 0xFFFFFFFF:
            raise SPSDKError("Invalid start address")
        if self._start_addr > self._end_addr or self._end_addr > 0xFFFFFFFF:
            raise SPSDKError("Invalid start/end address")
        if self.mode != BeeProtectRegionBlockAesMode.CTR:
            raise SPSDKError("Only AES/CTR encryption mode supported now")
        if len(self.counter) != 16:
            raise SPSDKError("Invalid counter")
        if self.counter[-4:] != b"\x00\x00\x00\x00":
            raise SPSDKError("last four bytes must be zero")
        if self.fac_count <= 0 or self.fac_count > self.FAC_REGIONS:
            raise SPSDKError("Invalid FAC regions")
        for fac in self.fac_regions:
            fac.validate()

    def export(self) -> bytes:
        """:return: binary representation of the region (serialization)."""
        result = super().export()
        result += pack(
            self._struct_format(),
            self.TAGL,
            self.TAGH,
            self.VERSION,
            self.fac_count,
            self._start_addr,
            self._end_addr,
            self.mode,
            self.lock_options,
            self.counter[::-1],  # bytes swapped: reversed order
            b"\x00" * 32,
        )
        for fac in self.fac_regions:
            result += fac.export()
        result = extend_block(result, self.SIZE)
        return result

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "BeeProtectRegionBlock":
        """Deserialization.

        :param data: binary data to be parsed
        :param offset: to start parsing the data
        :return: instance created from binary data
        :raises SPSDKError: If format does not match
        """
        super().parse(data, offset)  # check size of the input data
        (
            tagl,
            tagh,
            version,
            fac_count,
            start_addr,
            end_addr,
            mode,
            lock_options,
            counter,
            _reserved_32,
        ) = unpack_from(BeeProtectRegionBlock._struct_format(), data, offset)
        #
        if (tagl != BeeProtectRegionBlock.TAGL) or (tagh != BeeProtectRegionBlock.TAGH):
            raise SPSDKError("Invalid tag or unsupported version")
        if version != BeeProtectRegionBlock.VERSION:
            raise SPSDKError("Unsupported version")
        if _reserved_32 != b"\x00" * 32:
            raise SPSDKError("Reserved area is non-zero")
        #
        result = BeeProtectRegionBlock(mode, lock_options, counter[::-1])
        result._start_addr = start_addr
        result._end_addr = end_addr
        offset += calcsize(BeeProtectRegionBlock._struct_format())
        for _ in range(fac_count):
            fac = BeeFacRegion.parse(data, offset)
            result.add_fac(fac)
            offset += fac.size
        result.validate()
        return result

    def is_inside_region(self, start_addr: int) -> bool:
        """Returns true if the start address lies within any FAC region.

        :param start_addr: start address of the data
        """
        return self._start_addr <= start_addr < self._end_addr

    def encrypt_block(self, key: bytes, start_addr: int, data: bytes) -> bytes:
        """Encrypt block located in any FAC region.

        :param key: user for encryption
        :param start_addr: start address of the data
        :param data: binary block to be encrypted; the block size must be BEE_ENCR_BLOCK_SIZE
        :return: encrypted block if it is inside any FAC region; untouched block if it is not in any FAC region
        :raises SPSDKError: When incorrect length of binary block
        :raises SPSDKError: When encryption mode different from AES/CTR provided
        :raises SPSDKError: When invalid length of key
        :raises SPSDKError: When invalid range of region
        """
        if len(data) > BEE_ENCR_BLOCK_SIZE:
            raise SPSDKError("Incorrect length of binary block to be encrypted")
        if self.is_inside_region(start_addr):
            if self.mode != BeeProtectRegionBlockAesMode.CTR:
                raise SPSDKError("only AES/CTR encryption mode supported now")
            if len(key) != 16:
                raise SPSDKError("Invalid length of key")
            for fac in self.fac_regions:
                if fac.start_addr <= start_addr < fac.end_addr:
                    if start_addr + len(data) > fac.end_addr:
                        raise SPSDKError("Invalid range of region")
                    cntr_key = Counter(
                        self.counter,
                        ctr_value=start_addr >> 4,
                        ctr_byteorder_encoding="big",
                    )
                    logger.debug(
                        f"Encrypting data, start={hex(start_addr)},"
                        f"end={hex(start_addr + len(data))} with {self.info()} using fac {fac.info()}"
                    )
                    data = align_block_fill_random(data, 16)  # align data to 16 bytes
                    return crypto_backend().aes_ctr_encrypt(key, data, cntr_key.value)
        return data


class BeeKIB(BeeBaseClass):
    """BEE Key block.

    Contains keys used to encrypt PRDB content.
    """

    # key length in bytes
    _KEY_LEN = 16
    # format of the binary representation of the class, used as parameter for struct.pack/unpack methods
    _FORMAT = "16s16s"

    def __init__(self, kib_key: Optional[bytes] = None, kib_iv: Optional[bytes] = None):
        """Constructor.

        :param kib_key: AES key
        :param kib_iv: AES initialization vector
        """
        # Key Info Block (KIB)
        self.kib_key = kib_key if kib_key else crypto_backend().random_bytes(16)
        self.kib_iv = kib_iv if kib_iv else crypto_backend().random_bytes(16)

    def info(self) -> str:
        """:return: test description of the instance."""
        return f"BEE-KIB: {self.kib_key.hex()}, {self.kib_iv.hex()}"

    def validate(self) -> None:
        """Validates settings of the instance.

        :raises SPSDKError: If invalid length of kib key
        :raises SPSDKError: If invalid length of kib iv
        """
        if len(self.kib_key) != self._KEY_LEN:
            raise SPSDKError("Invalid length of kib key")
        if len(self.kib_iv) != self._KEY_LEN:
            raise SPSDKError("Invalid length of kib iv")

    def export(self) -> bytes:
        """Exports binary representation of the region (serialization)."""
        result = super().export()
        return result + pack(self._struct_format(), self.kib_key, self.kib_iv)

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "BeeKIB":
        """Deserialization.

        :param data: binary data to be parsed
        :param offset: to start parsing the data
        :return: instance created from binary data
        """
        super().parse(data, offset)  # check size of the input data
        (key, iv) = unpack_from(BeeKIB._struct_format(), data, offset)
        result = cls(key, iv)
        result.validate()
        return result


class BeeRegionHeader(BeeBaseClass):
    """BEE keys and regions header."""

    # offset of the Protected Region Block in the header
    PRDB_OFFSET = 0x80
    # total size including padding
    SIZE = 0x200

    @classmethod
    def _struct_format(cls) -> str:
        """:raises SPSDKError: It is not expected to called for the class."""
        raise SPSDKError(
            "This method is not expected to be used for this class, format depends on its fields"
        )

    @classmethod
    def _size(cls) -> int:
        """:return: size of the exported binary data in bytes."""
        return cls.SIZE

    def __init__(
        self,
        prdb: Optional[BeeProtectRegionBlock] = None,
        sw_key: Optional[bytes] = None,
        kib: Optional[BeeKIB] = None,
    ):
        """Constructor.

        :param prdb: protect region block; None to use default
        :param sw_key: key used to encrypt KIB content
        :param kib: keys block; None to use default
        """
        self._prdb = prdb if (prdb is not None) else BeeProtectRegionBlock()
        self._sw_key = sw_key if (sw_key is not None) else crypto_backend().random_bytes(16)
        self._kib = kib if (kib is not None) else BeeKIB()

    def add_fac(self, fac: BeeFacRegion) -> None:
        """Append FAC region.

        :param fac: to be added
        """
        self._prdb.add_fac(fac)

    @property
    def fac_regions(self) -> Sequence[BeeFacRegion]:
        """:return: lift of Factory Access Control regions."""
        return self._prdb.fac_regions

    def info(self) -> str:
        """:return: test description of the instance."""
        result = "BEE Region Header\n"
        result += f"- KIB: {self._kib.info()}"
        result += f"- PRDB: {self._prdb.info()}"
        return result

    def sw_key_fuses(self) -> Sequence[int]:
        """:return: sequence of fuse values for SW key to be burned into processor.

        The result is ordered, first value should be burned to the lowest address.
        """
        result = []
        for pos in range(16, 0, -4):
            result.append(unpack_from(">I", self._sw_key[pos - 4 : pos])[0])
        return result

    def update(self) -> None:
        """Updates internal fields of the instance."""
        super().update()
        self._kib.update()
        self._prdb.update()

    def validate(self) -> None:
        """Validates settings of the instance.

        :raises SPSDKError: If settings invalid
        """
        self._kib.validate()
        self._prdb.validate()
        if len(self._sw_key) != 16:
            raise SPSDKError("Invalid settings")

    def export(self, dbg_info: DebugInfo = DebugInfo.disabled()) -> bytes:
        """Serialization to binary representation.

        :param dbg_info: instance allowing to provide debug info about exported data
        :return: binary representation of the region (serialization).
        """
        result = super().export()
        # KIB
        kib_data = self._kib.export()
        dbg_info.append_binary_section("BEE-KIB (non-crypted)", kib_data)
        aes_ecb = AES.new(self._sw_key, AES.MODE_ECB)
        result += aes_ecb.encrypt(kib_data)
        # padding
        result = extend_block(result, self.PRDB_OFFSET)
        # PRDB
        prdb_data = self._prdb.export()
        dbg_info.append_binary_section("BEE-PRDB (non-crypted)", prdb_data)
        aes_cbc = AES.new(self._kib.kib_key, AES.MODE_CBC, self._kib.kib_iv)
        result += aes_cbc.encrypt(prdb_data)
        # padding
        return extend_block(result, self.SIZE)

    @classmethod
    def parse(cls, data: bytes, offset: int = 0, sw_key: bytes = b"") -> "BeeRegionHeader":
        """Deserialization.

        :param data: binary data to be parsed
        :param offset: to start parsing the data
        :param sw_key: SW key used to decrypt the EKIB data (the key is marked as SW_GP2 on RT10xx)
        :return: instance created from binary data
        :raises SPSDKError: If invalid sw key
        """
        super().parse(data, offset)  # check size of the input data
        if len(sw_key) != 16:
            raise SPSDKError("Invalid sw key")
        aes_ecb = AES.new(sw_key, AES.MODE_ECB)
        decr_data = aes_ecb.decrypt(data[offset : offset + BeeKIB._size()])
        kib = BeeKIB.parse(decr_data)
        aes_cbc = AES.new(kib.kib_key, AES.MODE_CBC, kib.kib_iv)
        decr_data = aes_cbc.decrypt(
            data[offset + cls.PRDB_OFFSET : offset + cls.PRDB_OFFSET + BeeProtectRegionBlock.SIZE]
        )
        prdb = BeeProtectRegionBlock.parse(decr_data)
        result = cls(prdb, sw_key, kib)
        result.validate()
        return result

    def is_inside_region(self, start_addr: int) -> bool:
        """Returns true if the start address lies within any FAC region.

        :param start_addr: start address of the data
        """
        return self._prdb.is_inside_region(start_addr)

    def encrypt_block(self, start_addr: int, data: bytes) -> bytes:
        """Encrypt block located in any FAC region.

        :param start_addr: start address of the data
        :param data: binary block to be encrypted; the block size must be BEE_ENCR_BLOCK_SIZE
        :return: encrypted block if it is inside any FAC region; untouched block if it is not in any FAC region
        """
        return self._prdb.encrypt_block(self._sw_key, start_addr, data)


class BeeNxp:
    """BeeNxp class."""

    def __init__(
        self,
        headers: List[BeeRegionHeader],
        input_image: bytes,
        base_address: int,
    ):
        """Constructor.

        :param headers: list of BEE Region Headers
        :param input_image: Input image to be encrypted
        :param base_address: Base address of the image
        """
        self.headers = headers
        self.input_image = input_image
        self.base_address = base_address

    def export_image(self) -> bytes:
        """Export encrypted binary image.

        :return: encrypted image
        """
        encrypted_data = bytearray()
        image_data = bytearray(self.input_image)
        base_address = self.base_address

        for block in split_data(image_data, BEE_ENCR_BLOCK_SIZE):
            logger.debug(f"Reading {hex(base_address)}, size={hex(len(block))}")
            for header in self.headers:
                block = header.encrypt_block(base_address, block)
            encrypted_data.extend(block)
            base_address += len(block)

        return bytes(encrypted_data)

    def export_headers(self) -> List[bytes]:
        """Export BEE headers.

        :return: BEE region headers
        """
        headers = []
        for header in self.headers:
            headers.append(header.export())

        return headers

    @staticmethod
    def get_supported_families() -> List[str]:
        """Get all supported families for BEE.

        :return: List of supported families.
        """
        database = Database(BEE_DATABASE_FILE)
        return database.devices.device_names

    @staticmethod
    def get_validation_schemas() -> List[Dict[str, Any]]:
        """Get list of validation schemas.

        :return: Validation list of schemas.
        """
        schemas = ValidationSchemas.get_schema_file(BEE_SCH_FILE)
        return [schemas["bee_output"], schemas["bee"]]

    @staticmethod
    def generate_config_template() -> str:
        """Generate BEE configuration template.

        :return: Dictionary of individual templates (key is name of template, value is template itself).
        """
        val_schemas = BeeNxp.get_validation_schemas()

        yaml_data = ConfigTemplate(
            "BEE configuration template",
            val_schemas,
        ).export_to_yaml()

        return yaml_data

    @staticmethod
    def check_overlaps(bee_headers: List[BeeRegionHeader], start_addr: int) -> None:
        """Check for overlaps in regions.

        :param bee_headers: List of BeeRegionHeader
        :param start_addr: start address of a region to be checked
        :raises SPSDKOverlapError: if the address is inside any region
        """
        for header in bee_headers:
            for region in header.fac_regions:
                if region.start_addr <= start_addr < region.end_addr:
                    raise SPSDKOverlapError(
                        f"Region start address {hex(start_addr)} is overlapping with {region.info()}"
                    )

    @staticmethod
    def load_from_config(
        config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "BeeNxp":
        """Converts the configuration into an BEE image object.

        "config" contains dictionary of configurations.

        :raises SPSDKError: if the count of BEE engines is invalid.
        :param config: Configuration dictionary.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: initialized BeeNxp object.
        """
        input_binary = load_binary(config["input_binary"], search_paths)

        engine_selection = config["engine_selection"]
        bee_engines: List[Dict[str, Any]] = config["bee_engine"]
        base_address = value_to_int(config["base_address"])

        prdb = BeeProtectRegionBlock()
        kib = BeeKIB()

        bee_headers: List[BeeRegionHeader] = []

        engine_selections = {"engine0": [0], "engine1": [1], "both": [0, 1]}

        try:
            for engine_idx in engine_selections[engine_selection]:
                key = value_to_bytes(bee_engines[engine_idx]["user_key"], byte_cnt=16)
                if bee_engines[engine_idx].get("header_path"):
                    bin_ehdr = load_binary(bee_engines[engine_idx]["header_path"], search_paths)
                    ehdr = BeeRegionHeader.parse(bin_ehdr, sw_key=key)
                else:
                    ehdr = BeeRegionHeader(prdb, key, kib)
                bee_headers.append(ehdr)
        except IndexError as exc:
            raise SPSDKError("The count of BEE engines is invalid") from exc

        for engine_idx, bee_engine in enumerate(bee_engines):
            for protected_region in bee_engine.get("protected_region", []):
                fac = BeeFacRegion(
                    value_to_int(protected_region["start_address"]),
                    value_to_int(protected_region["length"]),
                    value_to_int(protected_region["protected_level"]),
                )
                BeeNxp.check_overlaps(bee_headers, fac.start_addr)
                bee_headers[engine_idx].add_fac(fac)

        bee = BeeNxp(bee_headers, input_binary, base_address)

        return bee
