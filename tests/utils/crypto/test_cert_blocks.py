#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2020-2023 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

import os

import pytest

from spsdk import SPSDKError
from spsdk.exceptions import SPSDKValueError
from spsdk.utils.crypto.cert_blocks import (
    CertBlockHeader,
    CertBlockV2,
    Certificate,
    CertificateBlockHeader,
    find_main_cert_index,
    find_root_certificates,
    get_main_cert_index,
)


def test_cert_block_header():
    header = CertBlockHeader()
    assert header.version == "1.0"
    assert header.flags == 0
    assert header.build_number == 0
    assert header.image_length == 0
    assert header.cert_count == 0
    assert header.cert_table_length == 0

    data = header.export()
    assert len(data) == CertBlockHeader.SIZE

    header_parsed = CertBlockHeader.parse(data)
    assert header == header_parsed


def test_cert_block_header_invalid():
    with pytest.raises(SPSDKError, match="Invalid version"):
        CertBlockHeader(version="bbb")


def test_cert_block_basic():
    cb = CertBlockV2()
    # test default values
    assert cb.image_length == 0
    assert cb.alignment == 16
    assert cb.rkh_index is None
    # test setters
    cb.image_length = 1
    cb.alignment = 1
    assert cb.alignment == 1
    assert cb.image_length == 1
    assert cb.header.image_length == 1
    # invalid root key index
    with pytest.raises(SPSDKError):
        cb.set_root_key_hash(4, bytes([0] * 32))
    # invalid root key size
    with pytest.raises(SPSDKError):
        cb.set_root_key_hash(0, bytes())


def test_cert_block(data_dir):
    with open(os.path.join(data_dir, "selfsign_2048_v3.der.crt"), "rb") as f:
        cert_data = f.read()

    cert_obj = Certificate(cert_data)

    cb = CertBlockV2()
    cb.set_root_key_hash(0, cert_obj.public_key_hash)
    cb.add_certificate(cert_data)
    assert cb.rkh_index == 0
    cb.export()

    # test RKHT
    assert cb.rkht.hex() == "db31d46c717711a8231cbc38b1de8a6e8657e1f733e04c2ee4b62fcea59149fa"
    fuses = cb.rkht_fuses
    assert len(fuses) == 8
    assert fuses[0] == 1825845723

    # test exception if child certificate in chain is not signed by parent certificate
    with open(os.path.join(data_dir, "ca0_v3.der.crt"), "rb") as f:
        ca0_cert_data = f.read()
    ca0_cert = Certificate(ca0_cert_data)
    with pytest.raises(SPSDKError):
        cb.add_certificate(ca0_cert)

    # test exception if no certificate specified
    cb = CertBlockV2()
    cb.set_root_key_hash(0, cert_obj.public_key_hash)
    with pytest.raises(SPSDKError):
        cb.export()

    # test exception last certificate is set as CA
    cb = CertBlockV2()
    cb.set_root_key_hash(0, ca0_cert.public_key_hash)
    cb.add_certificate(ca0_cert)
    with pytest.raises(SPSDKError):
        cb.export()

    # test exception if hash does not match any certificate
    cb = CertBlockV2()
    cb.set_root_key_hash(0, ca0_cert.public_key_hash)
    cb.add_certificate(cert_data)
    with pytest.raises(SPSDKError):
        cb.export()


def test_add_invalid_cert_in_cert_block(data_dir):
    cb = CertBlockV2()
    with open(os.path.join(data_dir, "selfsign_2048_v3.der.crt"), "rb") as f:
        cert_data = f.read()
    with open(os.path.join(data_dir, "ca0_v3.der.crt"), "rb") as f:
        ca0_cert_data = f.read()
    with pytest.raises(SPSDKError):
        cb.add_certificate(cert=5)
    with pytest.raises(
        SPSDKError, match="Chain certificate cannot be verified using parent public key"
    ):
        cb.add_certificate(cert=cert_data)
        cb.add_certificate(cert=ca0_cert_data)


def test_cert_block_export_invalid(data_dir):
    with open(os.path.join(data_dir, "selfsign_2048_v3.der.crt"), "rb") as f:
        cert_data = f.read()
    with open(os.path.join(data_dir, "ca0_v3.der.crt"), "rb") as f:
        ca0_cert_data = f.read()
    cert_obj = Certificate(cert_data)
    cb = CertBlockV2()
    cb.set_root_key_hash(0, cert_obj.public_key_hash)
    cb.add_certificate(cert_data)
    cb.add_certificate(cert_data)
    assert cb.rkh_index == 0
    with pytest.raises(
        SPSDKError, match="All certificates except the last chain certificate must be CA"
    ):
        cb.export()


def test_invalid_cert_block_header():
    ch = CertificateBlockHeader()
    ch.MAGIC = b"chdx"
    data = ch.export()
    with pytest.raises(SPSDKError, match="Magic is not same!"):
        CertificateBlockHeader.parse(data=data)
    with pytest.raises(SPSDKError, match="SIZE is bigger than length of the data without offset"):
        CertificateBlockHeader.parse(data=bytes(8))


def test_cert_block_invalid():
    cb = CertBlockV2()
    cb.RKH_SIZE = 77777
    with pytest.raises(SPSDKError, match="Invalid length of data"):
        cb.rkht
    with pytest.raises(SPSDKError, match="Invalid image length"):
        cb.image_length = -2
    with pytest.raises(SPSDKError, match="Invalid alignment"):
        cb.alignment = -2
    cb = CertBlockV2()
    with pytest.raises(SPSDKError, match="Invalid index of root key hash in the table"):
        cb.set_root_key_hash(5, bytes(32))
    with pytest.raises(SPSDKError, match="Invalid length of key hash"):
        cb.set_root_key_hash(3, bytes(5))


@pytest.mark.parametrize(
    "config,passed,expected_result",
    [
        ({}, False, SPSDKError),
        (
            {
                "mainCertPrivateKeyFile": "k0_cert0_2048.pem",
                "rootCertificate0File": "root_k0_signed_cert0_noca.der.cert",
                "rootCertificate1File": "root_k1_signed_cert0_noca.der.cert",
            },
            True,
            0,
        ),
        (
            {
                "mainCertPrivateKeyFile": "k0_cert0_2048.pem",
                "rootCertificate0File": "root_k0_signed_cert0_noca.der.cert",
                "rootCertificate1File": "root_k1_signed_cert0_noca.der.cert",
                "mainRootCertId": 1,
            },
            True,
            1,
        ),
        ({"mainRootCertId": 1}, True, 1),
        ({"mainCertChainId": 1}, True, 1),
        ({"mainRootCertId": "2"}, True, 2),
        ({"mainCertChainId": "2"}, True, 2),
        ({"mainRootCertId": "1abc"}, False, SPSDKValueError),
        ({"mainRootCertId": "1abc"}, False, SPSDKValueError),
        ({"mainRootCertId": 1, "mainCertChainId": 1}, True, 1),
        ({"mainRootCertId": 1, "mainCertChainId": 2}, False, SPSDKError),
    ],
)
def test_get_main_cert_index(data_dir, config, passed, expected_result):
    search_paths = [os.path.join(data_dir, "certs_and_keys")]
    if passed:
        result = get_main_cert_index(config, search_paths=search_paths)
        assert result == expected_result
    else:
        with pytest.raises(expected_result):
            get_main_cert_index(config, search_paths=search_paths)


@pytest.mark.parametrize(
    "config,index",
    [
        (
            {
                "mainCertPrivateKeyFile": "k0_cert0_2048.pem",
                "rootCertificate0File": "root_k1_signed_cert0_noca.der.cert",
                "rootCertificate1File": "root_k0_signed_cert0_noca.der.cert",
                "rootCertificate2File": "root_k1_signed_cert0_noca.der.cert",
                "rootCertificate3File": "root_k1_signed_cert0_noca.der.cert",
            },
            1,
        ),
        (
            {
                "mainCertPrivateKeyFile": "k0_cert0_2048.pem",
                "rootCertificate0File": "root_k1_signed_cert0_noca.der.cert",
                "rootCertificate1File": "root_k1_signed_cert0_noca.der.cert",
                "rootCertificate2File": "root_k1_signed_cert0_noca.der.cert",
                "rootCertificate3File": "root_k1_signed_cert0_noca.der.cert",
            },
            None,
        ),
        (
            {
                "rootCertificate0File": "root_k0_signed_cert0_noca.der.cert",
                "rootCertificate1File": "root_k1_signed_cert0_noca.der.cert",
                "rootCertificate2File": "root_k2_signed_cert0_noca.der.cert",
                "rootCertificate3File": "root_k3_signed_cert0_noca.der.cert",
            },
            None,
        ),
        (
            {
                "mainCertPrivateKeyFile": "k0_cert0_2048.pem",
                "rootCertificate0File": "non_existing.cert",
                "rootCertificate1File": "another_non_existing.cert",
                "rootCertificate2File": "one_more_non_existing.cert",
            },
            None,
        ),
        (
            {
                "mainCertPrivateKeyFile": "non_existing.pem",
                "rootCertificate0File": "root_k0_signed_cert0_noca.der.cert",
                "rootCertificate1File": "root_k1_signed_cert0_noca.der.cert",
                "rootCertificate2File": "root_k2_signed_cert0_noca.der.cert",
                "rootCertificate3File": "root_k3_signed_cert0_noca.der.cert",
            },
            None,
        ),
    ],
)
def test_find_main_cert_index(data_dir, config, index):
    search_paths = [os.path.join(data_dir, "certs_and_keys")]
    found_index = find_main_cert_index(config, search_paths=search_paths)
    assert found_index == index


@pytest.mark.parametrize(
    "config,error,expected_list",
    [
        (
            {
                "rootCertificate0File": "root_k0.cert",
                "rootCertificate1File": "root_k1.cert",
                "rootCertificate2File": "root_k2.cert",
                "rootCertificate3File": "root_k3.cert",
            },
            None,
            [
                "root_k0.cert",
                "root_k1.cert",
                "root_k2.cert",
                "root_k3.cert",
            ],
        ),
        (
            {
                "rootCertificate0File": "root_k0.cert",
                "rootCertificate1File": "root_k1.cert",
                "rootCertificate2File": "root_k2.cert",
                "rootCertificate3File": "",
            },
            None,
            [
                "root_k0.cert",
                "root_k1.cert",
                "root_k2.cert",
            ],
        ),
        (
            {
                "rootCertificate0File": "root_k0.cert",
                "rootCertificate1File": "root_k1.cert",
                "rootCertificate2File": "",
                "rootCertificate3File": "root_k2.cert",
            },
            SPSDKError,
            None,
        ),
        (
            {
                "rootCertificate0File": "root_k0.cert",
                "rootCertificate3File": "root_k2.cert",
            },
            SPSDKError,
            None,
        ),
        (
            {
                "rootCertificate0File": "root_k0.cert",
                "rootCertificate1File": "root_k1.cert",
            },
            None,
            [
                "root_k0.cert",
                "root_k1.cert",
            ],
        ),
    ],
)
def test_find_root_certficates(config, error, expected_list):
    if error is not None:
        with pytest.raises(error):
            find_root_certificates(config)
    else:
        certificates = find_root_certificates(config)
        assert certificates == expected_list
        assert certificates == expected_list
