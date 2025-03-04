#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2019-2023 NXP
#
# SPDX-License-Identifier: BSD-3-Clause
"""Module for creation commands."""

from abc import abstractmethod
from enum import Enum as BuiltinEnum
from struct import calcsize, pack, unpack_from
from typing import Any, Dict, List, Mapping, Optional, Tuple, Type, Union

from spsdk import SPSDKError
from spsdk.sbfile.sb31.constants import EnumCmdTag
from spsdk.utils.easy_enum import Enum
from spsdk.utils.misc import align_block, load_binary, value_to_int

########################################################################################################################
# Main Class
########################################################################################################################


class MainCmd:
    """Functions for creating cmd intended for inheritance."""

    def __eq__(self, obj: object) -> bool:
        """Comparison of values."""
        return isinstance(obj, self.__class__) and vars(obj) == vars(self)

    def __str__(self) -> str:
        """Get info of command."""
        return self.info()

    @abstractmethod
    def info(self) -> str:
        """Get info of command.

        :raises NotImplementedError: Derived class has to implement this method
        """
        raise NotImplementedError("Derived class has to implement this method.")

    def export(self) -> bytes:
        """Export command as bytes.

        :raises NotImplementedError: Derived class has to implement this method
        """
        raise NotImplementedError("Derived class has to implement this method.")

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> object:
        """Parse command from bytes array.

        :raises NotImplementedError: Derived class has to implement this method
        """
        raise NotImplementedError("Derived class has to implement this method.")

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "MainCmd":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        :raises NotImplementedError: Derived class has to implement this method
        """
        raise NotImplementedError("Derived class has to implement this method.")


########################################################################################################################
# Base Command Class
########################################################################################################################


class BaseCmd(MainCmd):
    """Functions for creating cmd intended for inheritance."""

    FORMAT = "<4L"
    SIZE = calcsize(FORMAT)
    TAG = 0x55AAAA55

    @property
    def address(self) -> int:
        """Get address."""
        return self._address

    @address.setter
    def address(self, value: int) -> None:
        """Set address."""
        if value < 0x00000000 or value > 0xFFFFFFFF:
            raise SPSDKError("Invalid address")
        self._address = value

    @property
    def length(self) -> int:
        """Get length."""
        return self._length

    @length.setter
    def length(self, value: int) -> None:
        """Set value."""
        if value < 0x00000000 or value > 0xFFFFFFFF:
            raise SPSDKError("Invalid length")
        self._length = value

    def __init__(self, address: int, length: int, cmd_tag: int = EnumCmdTag.NONE) -> None:
        """Constructor for Commands header.

        :param address: Input address
        :param length: Input length
        :param cmd_tag: Command tag
        """
        self._address = address
        self._length = length
        self.cmd_tag = cmd_tag

    def info(self) -> str:
        """Get info of command.

        :raises NotImplementedError: Derived class has to implement this method
        """
        raise NotImplementedError("Derived class has to implement this method.")

    def export(self) -> bytes:
        """Export command as bytes."""
        return pack(self.FORMAT, self.TAG, self.address, self.length, self.cmd_tag)

    @classmethod
    def header_parse(cls, cmd_tag: int, data: bytes, offset: int = 0) -> Tuple[int, int]:
        """Parse header command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :param cmd_tag: Information about command tag
        :raises SPSDKError: Raised if tag is not equal to required TAG
        :raises SPSDKError: Raised if cmd is not equal EnumCmdTag
        :return: Tuple
        """
        tag, address, length, cmd = unpack_from(cls.FORMAT, data, offset)
        if tag != cls.TAG:
            raise SPSDKError("TAG is not valid.")
        if cmd != cmd_tag:
            raise SPSDKError("Values are not same.")
        return address, length


########################################################################################################################
# Commands Classes version 3.1
########################################################################################################################
class CmdLoadBase(BaseCmd):
    """Base class for commands loading data."""

    HAS_MEMORY_ID_BLOCK = True

    def __init__(self, cmd_tag: int, address: int, data: bytes, memory_id: int = 0) -> None:
        """Constructor for command.

        :param cmd_tag: Command tag for the derived class
        :param address: Address for the load command
        :param data: Data to load
        :param memory_id: Memory ID
        """
        super().__init__(address=address, length=len(data), cmd_tag=cmd_tag)
        self.memory_id = memory_id
        self.data = data

    def export(self) -> bytes:
        """Export command as bytes."""
        data = super().export()
        if self.HAS_MEMORY_ID_BLOCK:
            data += pack("<4L", self.memory_id, 0, 0, 0)
        data += self.data
        data = align_block(data, alignment=16)
        return data

    def info(self) -> str:
        """Get info about the load command."""
        msg = f"{EnumCmdTag.name(self.cmd_tag)}: "
        if self.HAS_MEMORY_ID_BLOCK:
            msg += f"Address=0x{self.address:08X}, Length={self.length}, Memory ID={self.memory_id}"
        else:
            msg += f"Address=0x{self.address:08X}, Length={self.length}"
        return msg

    @classmethod
    def _extract_data(cls, data: bytes, offset: int = 0) -> Tuple[int, int, bytes, int, int]:
        tag, address, length, cmd = unpack_from(cls.FORMAT, data)
        memory_id = 0
        if tag != cls.TAG:
            raise SPSDKError(f"Invalid TAG, expected: {cls.TAG}")
        offset += BaseCmd.SIZE
        if cls.HAS_MEMORY_ID_BLOCK:
            memory_id, pad0, pad1, pad2 = unpack_from("<4L", data, offset=offset)
            if not pad0 == pad1 == pad2 == 0:
                raise SPSDKError("Invalid padding")
            offset += 16
        load_data = data[offset : offset + length]
        return address, length, load_data, cmd, memory_id

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdLoadBase":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdLoad
        :raises SPSDKError: Invalid cmd_tag was found
        """
        address, _, data, cmd_tag, memory_id = cls._extract_data(data, offset)
        if cmd_tag not in [
            EnumCmdTag.LOAD,
            EnumCmdTag.LOAD_CMAC,
            EnumCmdTag.LOAD_HASH_LOCKING,
            EnumCmdTag.LOAD_KEY_BLOB,
            EnumCmdTag.PROGRAM_FUSES,
            EnumCmdTag.PROGRAM_IFR,
        ]:
            raise SPSDKError(f"Invalid cmd_tag found: {cmd_tag}")
        if cls == CmdLoadBase:
            return cls(cmd_tag=cmd_tag, address=address, data=data, memory_id=memory_id)
        # pylint: disable=no-value-for-parameter
        return cls(address=address, data=data, memory_id=memory_id)  # type: ignore

    # pylint: disable=redundant-returns-doc
    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> MainCmd:
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        assert False


class CmdErase(BaseCmd):
    """Erase given address range. The erase will be rounded up to the sector size."""

    def __init__(self, address: int, length: int, memory_id: int = 0) -> None:
        """Constructor for command.

        :param address: Input address
        :param length: Input length
        :param memory_id: Memory ID
        """
        super().__init__(cmd_tag=EnumCmdTag.ERASE, address=address, length=length)
        self.memory_id = memory_id

    def info(self) -> str:
        """Get info of command."""
        return (
            f"ERASE: Address=0x{self.address:08X}, Length={self.length}, Memory ID={self.memory_id}"
        )

    def export(self) -> bytes:
        """Export command as bytes."""
        data = super().export()
        data += pack("<4L", self.memory_id, 0, 0, 0)
        return data

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdErase":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdErase
        :raises SPSDKError: Invalid padding
        """
        address, length = cls.header_parse(data=data, offset=offset, cmd_tag=EnumCmdTag.ERASE)
        memory_id, pad0, pad1, pad2 = unpack_from("<4L", data, offset=offset + 16)
        if not pad0 == pad1 == pad2 == 0:
            raise SPSDKError("Invalid padding")
        return cls(address=address, length=length, memory_id=memory_id)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdErase":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        address = value_to_int(config["address"], 0)
        length = value_to_int(config["size"], 0)
        memory_id = value_to_int(config.get("memoryId", "0"), 0)
        return CmdErase(address=address, length=length, memory_id=memory_id)


class CmdLoad(CmdLoadBase):
    """Data to write follows the range header."""

    def __init__(self, address: int, data: bytes, memory_id: int = 0) -> None:
        """Constructor for command.

        :param address: Address for the load command
        :param data: Data to load
        :param memory_id: Memory ID
        """
        super().__init__(cmd_tag=EnumCmdTag.LOAD, address=address, data=data, memory_id=memory_id)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> Union["CmdLoad", "CmdLoadHashLocking", "CmdLoadCmac"]:
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        :raises SPSDKError: Invalid configuration field.
        """
        authentication = config.get("authentication")
        address = value_to_int(config["address"], 0)
        memory_id = value_to_int(config.get("memoryId", "0"), 0)
        if authentication == "hashlocking":
            data = load_binary(config["file"], search_paths=search_paths)
            return CmdLoadHashLocking.load_from_config(
                config, search_paths=search_paths
            )  # Backward compatibility
        if authentication == "cmac":
            data = load_binary(config["file"], search_paths=search_paths)
            return CmdLoadCmac.load_from_config(
                config, search_paths=search_paths
            )  # Backward compatibility
        # general non-authenticated load command
        if config.get("file"):
            data = load_binary(config["file"], search_paths=search_paths)
            return CmdLoad(address=address, data=data, memory_id=memory_id)
        if config.get("values"):
            values = [value_to_int(s, 0) for s in config["values"].split(",")]
            data = pack(f"<{len(values)}L", *values)
            return CmdLoad(address=address, data=data, memory_id=memory_id)

        raise SPSDKError(f"Unsupported LOAD command args: {config}")


class CmdExecute(BaseCmd):
    """Address will be the jump-to address."""

    def __init__(self, address: int) -> None:
        """Constructor for Command.

        :param address: Input address
        """
        super().__init__(cmd_tag=EnumCmdTag.EXECUTE, address=address, length=0)

    def info(self) -> str:
        """Get info of command."""
        return f"EXECUTE: Address=0x{self.address:08X}"

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdExecute":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdExecute
        """
        address, _ = cls.header_parse(data=data, offset=offset, cmd_tag=EnumCmdTag.EXECUTE)
        return cls(address=address)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdExecute":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        address = value_to_int(config["address"], 0)
        return CmdExecute(address=address)


class CmdCall(BaseCmd):
    """Address will be the address to jump."""

    def __init__(self, address: int) -> None:
        """Constructor for Command.

        :param address: Input address
        """
        super().__init__(cmd_tag=EnumCmdTag.CALL, address=address, length=0)

    def info(self) -> str:
        """Get info of command."""
        return f"CALL: Address=0x{self.address:08X}"

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdCall":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdCall
        """
        address, _ = cls.header_parse(data=data, offset=offset, cmd_tag=EnumCmdTag.CALL)
        return cls(address=address)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdCall":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        address = value_to_int(config["address"], 0)
        return CmdCall(address=address)


class CmdProgFuses(CmdLoadBase):
    """Address will be address of fuse register."""

    HAS_MEMORY_ID_BLOCK = False

    def __init__(self, address: int, data: bytes) -> None:
        """Constructor for Command.

        :param address: Input address
        :param data: Input data
        """
        super().__init__(cmd_tag=EnumCmdTag.PROGRAM_FUSES, address=address, data=data)
        self.length //= 4

    @classmethod
    def _extract_data(cls, data: bytes, offset: int = 0) -> Tuple[int, int, bytes, int, int]:
        tag, address, length, cmd = unpack_from(cls.FORMAT, data)
        length *= 4
        memory_id = 0
        if tag != cls.TAG:
            raise SPSDKError(f"Invalid TAG, expected: {cls.TAG}")
        offset += BaseCmd.SIZE
        if cls.HAS_MEMORY_ID_BLOCK:
            memory_id, pad0, pad1, pad2 = unpack_from("<4L", data, offset=offset)
            if pad0 != pad1 != pad2 != 0:
                raise SPSDKError("Invalid padding")
            offset += 16
        load_data = data[offset : offset + length]
        return address, length, load_data, cmd, memory_id

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdProgFuses":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdProgFuses
        """
        address, _, data, _, _ = cls._extract_data(data=data, offset=offset)
        return cls(address=address, data=data)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdProgFuses":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        address = value_to_int(config["address"], 0)
        fuses = [value_to_int(fuse, 0) for fuse in config["values"].split(",")]
        data = pack(f"<{len(fuses)}L", *fuses)
        return CmdProgFuses(address=address, data=data)


class CmdProgIfr(CmdLoadBase):
    """Address will be the address into the IFR region."""

    HAS_MEMORY_ID_BLOCK = False

    def __init__(self, address: int, data: bytes) -> None:
        """Constructor for Command.

        :param address: Input address
        :param data: Input data as bytes array
        """
        super().__init__(cmd_tag=EnumCmdTag.PROGRAM_IFR, address=address, data=data)

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdProgIfr":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdProgFuses
        """
        address, _, data, _, _ = cls._extract_data(data=data, offset=offset)
        return cls(address=address, data=data)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdProgIfr":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        address = value_to_int(config["address"], 0)
        data = load_binary(config["file"], search_paths=search_paths)
        return CmdProgIfr(address=address, data=data)


class CmdLoadCmac(CmdLoadBase):
    """Load cmac. ROM is calculating cmac from loaded data."""

    def __init__(self, address: int, data: bytes, memory_id: int = 0) -> None:
        """Constructor for command.

        :param address: Address for the load command
        :param data: Data to load
        :param memory_id: Memory ID
        """
        super().__init__(
            cmd_tag=EnumCmdTag.LOAD_CMAC,
            address=address,
            data=data,
            memory_id=memory_id,
        )

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdLoadCmac":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        :raises SPSDKError: Invalid configuration field.
        """
        address = value_to_int(config["address"], 0)
        memory_id = value_to_int(config.get("memoryId", "0"), 0)

        data = load_binary(config["file"], search_paths=search_paths)
        return CmdLoadCmac(address=address, data=data, memory_id=memory_id)


class CmdCopy(BaseCmd):
    """Copy data from one place to another."""

    def __init__(
        self,
        address: int,
        length: int,
        destination_address: int = 0,
        memory_id_from: int = 0,
        memory_id_to: int = 0,
    ) -> None:
        """Constructor for command.

        :param address: Input address
        :param length: Input length
        :param destination_address: Destination address
        :param memory_id_from: Memory ID
        :param memory_id_to: Memory ID
        """
        super().__init__(cmd_tag=EnumCmdTag.COPY, address=address, length=length)
        self.destination_address = destination_address
        self.memory_id_from = memory_id_from
        self.memory_id_to = memory_id_to

    def info(self) -> str:
        """Get info of command."""
        return (
            f"COPY: Address=0x{self.address:08X}, Length={self.length}, "
            f"Destination address={self.destination_address}"
            f"Memory ID from={self.memory_id_from}, Memory ID to={self.memory_id_to}"
        )

    def export(self) -> bytes:
        """Export command as bytes."""
        data = super().export()
        data += pack("<4L", self.destination_address, self.memory_id_from, self.memory_id_to, 0)
        return data

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdCopy":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdCopy
        :raises SPSDKError: Invalid padding
        """
        address, length = cls.header_parse(data=data, offset=offset, cmd_tag=EnumCmdTag.COPY)
        destination_address, memory_id_from, memory_id_to, pad0 = unpack_from(
            "<4L", data, offset=offset + 16
        )
        if pad0 != 0:
            raise SPSDKError("Invalid padding")
        return cls(
            address=address,
            length=length,
            destination_address=destination_address,
            memory_id_from=memory_id_from,
            memory_id_to=memory_id_to,
        )

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdCopy":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        address = value_to_int(config["addressFrom"], 0)
        length = value_to_int(config["size"], 0)
        destination_address = value_to_int(config["addressTo"], 0)
        memory_id_from = value_to_int(config["memoryIdFrom"], 0)
        memory_id_to = value_to_int(config["memoryIdTo"], 0)
        return CmdCopy(
            address=address,
            length=length,
            destination_address=destination_address,
            memory_id_from=memory_id_from,
            memory_id_to=memory_id_to,
        )


class CmdLoadHashLocking(CmdLoadBase):
    """Load hash. ROM is calculating hash."""

    def __init__(self, address: int, data: bytes, memory_id: int = 0) -> None:
        """Constructor for command.

        :param address: Address for the load command
        :param data: Data to load
        :param memory_id: Memory ID
        """
        super().__init__(
            cmd_tag=EnumCmdTag.LOAD_HASH_LOCKING,
            address=address,
            data=data,
            memory_id=memory_id,
        )

    def export(self) -> bytes:
        """Export command as bytes."""
        data = super().export()
        data += bytes(64)
        return data

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdLoadHashLocking":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        :raises SPSDKError: Invalid configuration field.
        """
        address = value_to_int(config["address"], 0)
        memory_id = value_to_int(config.get("memoryId", "0"), 0)

        data = load_binary(config["file"], search_paths=search_paths)
        return CmdLoadHashLocking(address=address, data=data, memory_id=memory_id)


class CmdLoadKeyBlob(BaseCmd):
    """Load key blob."""

    FORMAT = "<L2H2L"

    class _KeyWraps(BuiltinEnum):
        """KeyWrap IDs used by the CmdLoadKeyBlob command."""

        NXP_CUST_KEK_INT_SK = 16
        NXP_CUST_KEK_EXT_SK = 17

    class KeyTypes(BuiltinEnum):
        """KeyTypes for NXP_CUST_KEK_INT_SK, NXP_CUST_KEK_EXT_SK."""

        NXP_CUST_KEK_INT_SK = 1
        NXP_CUST_KEK_EXT_SK = 2

    @classmethod
    def get_key_id(cls, family: str, key_name: KeyTypes) -> int:
        """Get key ID based on family and key name.

        :param family: chip family
        :param key_name: NXP_CUST_KEK_INT_SK or NXP_CUST_KEK_EXT_SK
        :return: integer value representing key
        """
        key_wraps = cls._KeyWraps
        return key_wraps[key_name.name].value

    def __init__(self, offset: int, data: bytes, key_wrap_id: int) -> None:
        """Constructor for command.

        :param offset: Input offset
        :param key_wrap_id: Key wrap ID (NXP_CUST_KEK_INT_SK = 16, NXP_CUST_KEK_EXT_SK = 17)
        :param data: Wrapped key blob
        """
        super().__init__(cmd_tag=EnumCmdTag.LOAD_KEY_BLOB, address=offset, length=len(data))
        self.key_wrap_id = key_wrap_id
        self.data = data

    def info(self) -> str:
        """Get info of command."""
        return f"LOAD_KEY_BLOB: Offset=0x{self.address:08X}, Length={self.length}, Key wrap ID={self.key_wrap_id}"

    def export(self) -> bytes:
        """Export command as bytes."""
        result_data = pack(
            self.FORMAT,
            self.TAG,
            self.address,
            self.key_wrap_id,
            self.length,
            self.cmd_tag,
        )
        result_data += self.data

        result_data = align_block(data=result_data, alignment=16, padding=0)
        return result_data

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdLoadKeyBlob":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdLoadKeyBlob
        """
        tag, cmpa_offset, key_wrap_id, length, cmd = unpack_from(  # pylint: disable=unused-variable
            cls.FORMAT, data, offset
        )
        key_blob_data = unpack_from(f"<{length}s", data, offset + cls.SIZE)[0]
        return cls(offset=cmpa_offset, key_wrap_id=key_wrap_id, data=key_blob_data)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdLoadKeyBlob":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        data = load_binary(config["file"], search_paths=search_paths)
        offset = value_to_int(config["offset"], 0)
        key_wrap_name = config["wrappingKeyId"]
        family = config["family"]

        key_wrap_id = cls.get_key_id(family, cls.KeyTypes[key_wrap_name])
        return CmdLoadKeyBlob(offset=offset, data=data, key_wrap_id=key_wrap_id)


class CmdConfigureMemory(BaseCmd):
    """Configure memory."""

    def __init__(self, address: int, memory_id: int = 0) -> None:
        """Constructor for command.

        :param address: Input address
        :param memory_id: Memory ID
        """
        super().__init__(address=address, length=0, cmd_tag=EnumCmdTag.CONFIGURE_MEMORY)
        self.memory_id = memory_id

    def info(self) -> str:
        """Get info of command."""
        return f"CONFIGURE_MEMORY: Address=0x{self.address:08X}, Memory ID={self.memory_id}"

    def export(self) -> bytes:
        """Export command as bytes."""
        return pack(self.FORMAT, self.TAG, self.memory_id, self.address, self.cmd_tag)

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdConfigureMemory":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdConfigureMemory
        """
        memory_id, address = cls.header_parse(
            cmd_tag=EnumCmdTag.CONFIGURE_MEMORY, data=data, offset=offset
        )
        return cls(address=address, memory_id=memory_id)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdConfigureMemory":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        memory_id = value_to_int(config["memoryId"], 0)
        return CmdConfigureMemory(
            address=value_to_int(config["configAddress"], 0), memory_id=memory_id
        )


class CmdFillMemory(BaseCmd):
    """Fill memory range by pattern."""

    def __init__(self, address: int, length: int, pattern: int) -> None:
        """Constructor for command.

        :param address: Input address
        :param length: Input length
        :param pattern: Pattern for fill memory with
        """
        super().__init__(cmd_tag=EnumCmdTag.FILL_MEMORY, address=address, length=length)
        self.pattern = pattern

    def info(self) -> str:
        """Get info of command."""
        return f"FILL_MEMORY: Address=0x{self.address:08X}, Length={self.length}, PATTERN={hex(self.pattern)}"

    def export(self) -> bytes:
        """Export command as bytes."""
        data = super().export()
        data += pack("<4L", self.pattern, 0, 0, 0)
        return data

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdFillMemory":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdErase
        :raises SPSDKError: Invalid padding
        """
        address, length = cls.header_parse(data=data, offset=offset, cmd_tag=EnumCmdTag.FILL_MEMORY)
        pattern, pad0, pad1, pad2 = unpack_from("<4L", data, offset=offset + 16)
        if pad0 != pad1 != pad2 != 0:
            raise SPSDKError("Invalid padding")
        return cls(address=address, length=length, pattern=pattern)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdFillMemory":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        address = value_to_int(config["address"], 0)
        length = value_to_int(config["size"], 0)
        pattern = value_to_int(config["pattern"], 0)
        return CmdFillMemory(address=address, length=length, pattern=pattern)


class CmdFwVersionCheck(BaseCmd):
    """Check counter value with stored value, if values are not same, SB file is rejected."""

    class CounterID(Enum):
        """Counter IDs used by the CmdFwVersionCheck command."""

        NONE = (0, "none")
        NONSECURE = (1, "nonsecure")
        SECURE = (2, "secure")
        RADIO = (3, "radio")
        SNT = (4, "snt")
        BOOTLOADER = (5, "bootloader")

    def __init__(self, value: int, counter_id: int) -> None:
        """Constructor for command.

        :param value: Input value
        :param counter_id: Counter ID (NONSECURE = 1, SECURE = 2)
        """
        super().__init__(address=0, length=0, cmd_tag=EnumCmdTag.FW_VERSION_CHECK)
        self.value = value
        self.counter_id = counter_id

    def info(self) -> str:
        """Get info of command."""
        return f"FW_VERSION_CHECK: Value={self.value}, Counter ID={self.counter_id}"

    def export(self) -> bytes:
        """Export command as bytes."""
        return pack(self.FORMAT, self.TAG, self.value, self.counter_id, self.cmd_tag)

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdFwVersionCheck":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :return: CmdFwVersionCheck
        """
        value, counter_id = cls.header_parse(
            data=data, offset=offset, cmd_tag=EnumCmdTag.FW_VERSION_CHECK
        )
        return cls(value=value, counter_id=counter_id)

    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdFwVersionCheck":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        """
        value = value_to_int(config["value"], 0)
        counter_id_str = config["counterId"]
        counter_id = CmdFwVersionCheck.CounterID[counter_id_str]
        return CmdFwVersionCheck(value=value, counter_id=counter_id)


class CmdSectionHeader(MainCmd):
    """Create section header."""

    FORMAT = "<4L"
    SIZE = calcsize(FORMAT)

    def __init__(self, length: int, section_uid: int = 1, section_type: int = 1) -> None:
        """Constructor for Commands section.

        :param section_uid: Input uid
        :param section_type: Input type
        :param length: Input length
        """
        self.section_uid = section_uid
        self.section_type = section_type
        self.length = length
        self._pad = 0

    def info(self) -> str:
        """Get info of Section header."""
        return f"Section header: UID=0x{self.section_uid:08X}, Type={self.section_type}, Length={self.length}"

    def export(self) -> bytes:
        """Export command as bytes."""
        return pack(self.FORMAT, self.section_uid, self.section_type, self.length, self._pad)

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "CmdSectionHeader":
        """Parse command from bytes array.

        :param data: Input data as bytes array
        :param offset: The offset of input data
        :raises SPSDKError: Raised when FORMAT is bigger than length of the data without offset
        :return: CmdSectionHeader
        """
        if calcsize(cls.FORMAT) > len(data) - offset:
            raise SPSDKError("FORMAT is bigger than length of the data without offset!")
        section_uid, section_type, length, _ = unpack_from(cls.FORMAT, data, offset)
        return cls(section_uid=section_uid, section_type=section_type, length=length)

    # pylint: disable=redundant-returns-doc
    @classmethod
    def load_from_config(
        cls, config: Dict[str, Any], search_paths: Optional[List[str]] = None
    ) -> "CmdSectionHeader":
        """Load configuration from dictionary.

        :param config: Dictionary with configuration fields.
        :param search_paths: List of paths where to search for the file, defaults to None
        :return: Command object loaded from configuration.
        :raises SPSDKError: This situation cannot raise (the function here is just MYPY/PYLINT checks).
        """
        raise SPSDKError("Section header cannot be loaded from configuration.")


TAG_TO_CLASS: Mapping[int, Type[BaseCmd]] = {
    EnumCmdTag.ERASE: CmdErase,
    EnumCmdTag.LOAD: CmdLoad,
    EnumCmdTag.EXECUTE: CmdExecute,
    EnumCmdTag.CALL: CmdCall,
    EnumCmdTag.PROGRAM_FUSES: CmdProgFuses,
    EnumCmdTag.PROGRAM_IFR: CmdProgIfr,
    EnumCmdTag.LOAD_CMAC: CmdLoadCmac,
    EnumCmdTag.COPY: CmdCopy,
    EnumCmdTag.LOAD_HASH_LOCKING: CmdLoadHashLocking,
    EnumCmdTag.LOAD_KEY_BLOB: CmdLoadKeyBlob,
    EnumCmdTag.CONFIGURE_MEMORY: CmdConfigureMemory,
    EnumCmdTag.FILL_MEMORY: CmdFillMemory,
    EnumCmdTag.FW_VERSION_CHECK: CmdFwVersionCheck,
}

CFG_NAME_TO_CLASS: Mapping[str, Type[BaseCmd]] = {
    "erase": CmdErase,
    "load": CmdLoad,
    "execute": CmdExecute,
    "call": CmdCall,
    "programFuses": CmdProgFuses,
    "programIFR": CmdProgIfr,
    "loadCMAC": CmdLoadCmac,
    "copy": CmdCopy,
    "loadHashLocking": CmdLoadHashLocking,
    "loadKeyBlob": CmdLoadKeyBlob,
    "configureMemory": CmdConfigureMemory,
    "fillMemory": CmdFillMemory,
    "checkFwVersion": CmdFwVersionCheck,
}


########################################################################################################################
# Command parser from raw data
########################################################################################################################
def parse_command(data: bytes, offset: int = 0) -> object:
    """Parse command from bytes array.

    :param data: Input data as bytes array
    :param offset: The offset of input data
    :raises SPSDKError: Raised when tag is not in cmd_class
    :raises SPSDKError: Raised when tag is invalid
    :return: object
    """
    #  verify that first 4 bytes of frame are 55aaaa55
    tag = unpack_from("<L", data, offset=offset)[0]
    if tag != BaseCmd.TAG:
        raise SPSDKError("Invalid tag.")
    cmd_tag = unpack_from("<L", data, offset=offset + 12)[0]
    if cmd_tag not in TAG_TO_CLASS:
        raise SPSDKError(f"Invalid command tag: {cmd_tag}")
    return TAG_TO_CLASS[cmd_tag].parse(data, offset)
