import json

from conductor.blocks import extract_block, inject_block


def test_extract_inject_roundtrip():
    body = "标题\n\n```json loop\n{}\n```\n尾巴"
    blk = {"id": "C-1", "charter": ["G0"]}
    new_body = inject_block(body, blk)
    assert extract_block(new_body) == blk
    assert new_body.endswith("\n尾巴")


def test_inject_when_missing_block():
    blk = {"id": "C-2"}
    body = inject_block("正文", blk)
    assert "```json loop" in body
    assert extract_block(body) == blk


def test_bad_json_returns_none():
    assert extract_block("```json loop\n{bad\n```") is None
