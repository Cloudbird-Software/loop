#!/usr/bin/env python3
"""5-field unix cron 表达式校验器。

字段顺序：minute hour day-of-month month day-of-week
  minute        0-59
  hour          0-23
  day-of-month  1-31   (0 非法)
  month         1-12
  day-of-week   0-7    (0 与 7 均为周日)

每字段支持：* / */N / N / N-M / N-M/S ，以及逗号列表（可任意组合）。
拒绝：字段数不为 5、取值越界、day-of-month 为 0、表达式畸形。

退出码：合法=0，非法=1。

仅用标准库（argparse / re / sys）。提供 main() 与 validate_cron() 供导入复用。
"""
import argparse
import re
import sys

# (min, max, label) for each of the 5 cron fields, in order.
FIELDS = (
    (0, 59, "minute"),
    (0, 23, "hour"),
    (1, 31, "day-of-month"),
    (1, 12, "month"),
    (0, 7, "day-of-week"),
)

_INT_RE = re.compile(r"^\d+$")
_RANGE_RE = re.compile(r"^\d+-\d+$")
_STAR_STEP_RE = re.compile(r"^\*/\d+$")
_RANGE_STEP_RE = re.compile(r"^\d+-\d+/\d+$")


def _check_item(item, lo, hi):
    """Return an error string for a single non-comma token, or None if OK."""
    if item == "*":
        return None
    if _STAR_STEP_RE.match(item):
        step = int(item[2:])
        if step < 1:
            return f"step must be >= 1 in {item!r}"
        return None
    if "/" in item:
        if not _RANGE_STEP_RE.match(item):
            return f"malformed stepped range {item!r}"
        rng, step_s = item.split("/")
        step = int(step_s)
        a_s, b_s = rng.split("-")
        a, b = int(a_s), int(b_s)
        if step < 1:
            return f"step must be >= 1 in {item!r}"
        if a < lo or a > hi:
            return f"value {a} out of range [{lo},{hi}] in {item!r}"
        if b < lo or b > hi:
            return f"value {b} out of range [{lo},{hi}] in {item!r}"
        if a > b:
            return f"range start > end in {item!r}"
        return None
    if _RANGE_RE.match(item):
        a_s, b_s = item.split("-")
        a, b = int(a_s), int(b_s)
        if a < lo or a > hi:
            return f"value {a} out of range [{lo},{hi}] in {item!r}"
        if b < lo or b > hi:
            return f"value {b} out of range [{lo},{hi}] in {item!r}"
        if a > b:
            return f"range start > end in {item!r}"
        return None
    if _INT_RE.match(item):
        v = int(item)
        if v < lo or v > hi:
            return f"value {v} out of range [{lo},{hi}] in {item!r}"
        return None
    return f"malformed token {item!r}"


def validate_cron(expr):
    """Return (ok: bool, message: str) for a cron expression string."""
    parts = expr.split()
    if len(parts) != 5:
        return False, f"expected 5 fields, got {len(parts)}"
    for field, (lo, hi, label) in zip(parts, FIELDS):
        items = field.split(",")
        if any(it == "" for it in items):
            return False, f"{label}: empty element in {field!r}"
        for it in items:
            err = _check_item(it, lo, hi)
            if err:
                return False, f"{label}: {err}"
    return True, "valid 5-field cron expression"


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Validate a 5-field unix cron expression.")
    p.add_argument("--cron", required=True, metavar="EXPR",
                   help="cron expression, e.g. '*/15 * * * *'")
    args = p.parse_args(argv)
    ok, msg = validate_cron(args.cron)
    if ok:
        print(f"OK: {msg}: {args.cron!r}")
        return 0
    print(f"INVALID: {msg}: {args.cron!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
