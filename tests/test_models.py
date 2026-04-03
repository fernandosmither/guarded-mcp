"""Tests for ApprovalRequest and configuration models."""

import time

from src.models import ApprovalRequest, ApprovalStatus


def test_hash_deterministic():
    a = ApprovalRequest(tool_name="t", integration="i", arguments={"k": "v"})
    b = ApprovalRequest(tool_name="t", integration="i", arguments={"k": "v"})
    assert a.params_hash == b.params_hash


def test_hash_differs_with_different_args():
    a = ApprovalRequest(tool_name="t", integration="i", arguments={"k": "v1"})
    b = ApprovalRequest(tool_name="t", integration="i", arguments={"k": "v2"})
    assert a.params_hash != b.params_hash


def test_hash_differs_with_different_tool():
    a = ApprovalRequest(tool_name="t1", integration="i", arguments={"k": "v"})
    b = ApprovalRequest(tool_name="t2", integration="i", arguments={"k": "v"})
    assert a.params_hash != b.params_hash


def test_verify_hash_passes():
    req = ApprovalRequest(tool_name="t", integration="i", arguments={"x": 1})
    assert req.verify_hash() is True


def test_verify_hash_fails_on_tamper():
    req = ApprovalRequest(tool_name="t", integration="i", arguments={"x": 1})
    req.arguments["x"] = 999
    assert req.verify_hash() is False


def test_is_expired():
    req = ApprovalRequest(
        tool_name="t",
        integration="i",
        arguments={},
        created_at=time.time() - 600,
    )
    assert req.is_expired(300) is True


def test_not_expired():
    req = ApprovalRequest(tool_name="t", integration="i", arguments={})
    assert req.is_expired(300) is False


def test_unique_ids():
    a = ApprovalRequest(tool_name="t", integration="i", arguments={})
    b = ApprovalRequest(tool_name="t", integration="i", arguments={})
    assert a.id != b.id
    assert a.nonce != b.nonce


def test_trust_elevated_default_false():
    req = ApprovalRequest(tool_name="t", integration="i", arguments={})
    assert req.trust_elevated is False


def test_status_enum_values():
    assert ApprovalStatus.PENDING == "pending"
    assert ApprovalStatus.APPROVED == "approved"
    assert ApprovalStatus.REJECTED == "rejected"
    assert ApprovalStatus.EXPIRED == "expired"
