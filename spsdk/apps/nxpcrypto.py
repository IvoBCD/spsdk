#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2022-2023 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

"""CLI application for various cryptographic operations."""

import copy
import hashlib
import logging
import os
import sys
from typing import Dict, Union

import click
from Crypto.PublicKey import ECC, RSA

from spsdk import SPSDKError
from spsdk.apps.nxpcertgen import main as cert_gen_main
from spsdk.apps.nxpkeygen import main as key_gen_main
from spsdk.apps.utils.common_cli_options import (
    CommandsTreeGroup,
    GroupAliasedGetCfgTemplate,
    spsdk_apps_common_options,
)
from spsdk.apps.utils.utils import SPSDKAppError, catch_spsdk_error
from spsdk.utils.misc import load_binary, write_file


@click.group(name="nxpcrypto", no_args_is_help=True, cls=CommandsTreeGroup)
@spsdk_apps_common_options
def main(log_level: int) -> None:
    """Collection of utilities for cryptographic operations."""
    logging.basicConfig(level=log_level or logging.WARNING)


@main.command(name="digest", no_args_is_help=True)
@click.option(
    "-h",
    "--hash",
    "hash_name",
    required=True,
    type=click.Choice(list(hashlib.algorithms_available), case_sensitive=False),
    help="Name of a hash to use.",
)
@click.option(
    "-i",
    "--infile",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    help="Path to a file to digest.",
)
@click.option(
    "-c",
    "--compare",
    metavar="PATH | DIGEST",
    help="Reference digest to compare. It may be directly on the command line or fetched from a file.",
)
def digest(hash_name: str, infile: str, compare: str) -> None:
    """Computes digest/hash of the given file."""
    data = load_binary(infile)
    hasher = hashlib.new(hash_name.lower())
    hasher.update(data)
    hexdigest = hasher.hexdigest()
    click.echo(f"{hash_name.upper()}({infile})= {hexdigest}")
    if compare:
        # assume comparing to a file
        if os.path.isfile(compare):
            with open(compare) as f:
                compare_data = f.readline().strip()
                # assume format generated by openssl
                if "=" in compare_data:
                    ref = compare_data.split("=")[-1].strip()
                # assume hash is on the fist line
                else:
                    ref = compare_data
        else:
            ref = compare
        if ref.lower() == hexdigest.lower():
            click.echo("Digests are the same.")
        else:
            raise SPSDKAppError("Digests differ!")


@main.group(name="cert", no_args_is_help=True, cls=GroupAliasedGetCfgTemplate)
def cert() -> None:
    """Group of command for working with x509 certificates."""


cert.add_command(cert_gen_main.commands["generate"], name="generate")
cert.add_command(cert_gen_main.commands["get-template"], name="get-template")
cert.add_command(cert_gen_main.commands["verify"], name="verify")


@main.group(name="key", no_args_is_help=True)
def key_group() -> None:
    """Group of commands for working with asymmetric keys."""


key_gen_copy = copy.deepcopy(key_gen_main)
key_gen_copy.name = "generate"
key_group.add_command(key_gen_copy)


@key_group.command(name="convert", no_args_is_help=True)
@click.option(
    "-f",
    "--output-format",
    type=click.Choice(["PEM", "DER", "RAW"], case_sensitive=False),
    help="Desired output format.",
)
@click.option(
    "-i",
    "--infile",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    help="Path to key file to convert.",
)
@click.option(
    "-o",
    "--outfile",
    type=click.Path(dir_okay=False),
    help="Path to output file.",
)
@click.option(
    "-p",
    "--puk",
    is_flag=True,
    default=False,
    help="Extract public key instead of converting private key.",
)
@click.option(
    "--use-pkcs8/--no-pkcs8",
    is_flag=True,
    default=True,
    help="Use/don't use PKCS8 encoding for private keys, default: --use-pkcs8",
)
def convert(output_format: str, infile: str, outfile: str, puk: bool, use_pkcs8: bool) -> None:
    """Convert Asymmetric key into various formats."""
    key_data = load_binary(infile)
    key = reconstruct_key(key_data=key_data)
    if puk:
        key = key.public_key()

    if output_format.upper() in ["PEM", "DER"]:
        params: Dict[str, Union[str, int, bool]] = {
            "format": output_format.upper(),
        }
        if key.has_private():
            if isinstance(key, ECC.EccKey):
                params["use_pkcs8"] = use_pkcs8
            if isinstance(key, RSA.RsaKey):
                params["pkcs"] = 8 if use_pkcs8 else 1
        tmp_data = key.export_key(**params)  # type: ignore  # yeah, MyPy doesn't like dict unpacking
        out_data = tmp_data.encode("utf-8") if isinstance(tmp_data, str) else tmp_data
    if output_format.upper() == "RAW":
        if not isinstance(key, ECC.EccKey):
            raise SPSDKError("Converting to RAW is supported only for ECC keys")
        key_size = key.pointQ.size_in_bytes()
        if key.has_private():
            out_data = key.d.to_bytes(key_size)  # type: ignore  # this `to_bytes` doesn't have byteorder
        else:
            x = key.pointQ.x.to_bytes(key_size)  # type: ignore  # this `to_bytes` doesn't have byteorder
            y = key.pointQ.y.to_bytes(key_size)  # type: ignore  # this `to_bytes` doesn't have byteorder
            out_data = x + y

    write_file(out_data, outfile, mode="wb")


@key_group.command(name="verify", no_args_is_help=True)
@click.argument("key1", type=click.Path(exists=True, dir_okay=False))
@click.argument("key2", type=click.Path(exists=True, dir_okay=False))
def check_keys(key1: str, key2: str) -> None:
    """Check whether provided keys form a key pair or represent the same key."""
    key1_data = load_binary(key1)
    key2_data = load_binary(key2)
    first = reconstruct_key(key1_data)
    second = reconstruct_key(key2_data)

    if not (isinstance(first, ECC.EccKey) and isinstance(second, ECC.EccKey)):
        raise SPSDKError("Currently on ECC keys are supported.")

    if first.pointQ == second.pointQ:
        click.echo("Keys match.")
    else:
        raise SPSDKAppError("Keys are NOT a valid pair!")


def get_curve_name(key_length: int) -> str:
    """Get curve name for Crypto library."""
    if key_length <= 32:
        return "p256"
    if key_length <= 48:
        return "p384"
    if key_length in [64, 96]:
        return f"p{key_length * 4}"
    raise SPSDKError(f"Not sure what curve corresponds to {key_length} data")


# we use Crypto instead of cryptography because of binary private key reconstruction
def reconstruct_key(key_data: bytes) -> Union[ECC.EccKey, RSA.RsaKey]:
    """Reconstruct Crypto key from PEM,DER or RAW data."""
    try:
        return RSA.import_key(key_data)
    except (ValueError, TypeError):
        pass
    try:
        return ECC.import_key(key_data)
    except ValueError:
        pass
    # attempt to reconstruct key from raw data
    key_length = len(key_data)
    curve = get_curve_name(key_length)
    # everything under 49 bytes is a private key
    if key_length <= 48:
        # pylint: disable=invalid-name   # 'd' is regular name for private key number
        d = int.from_bytes(key_data, byteorder="big")
        return ECC.construct(curve=curve, d=d)
    # public keys in binary form have exact sizes
    if key_length in [64, 96]:
        coord_length = key_length // 2
        x = int.from_bytes(key_data[:coord_length], byteorder="big")
        y = int.from_bytes(key_data[coord_length:], byteorder="big")
        return ECC.construct(curve=curve, point_x=x, point_y=y)
    raise SPSDKError(f"Can't recognize key with length {key_length}")


@catch_spsdk_error
def safe_main() -> None:
    """Call the main function."""
    sys.exit(main())  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    safe_main()
