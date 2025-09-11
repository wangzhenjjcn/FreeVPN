#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UpdateV2raySubscription.py

抓取昨天(北京时间)的 0-4 共 5 个订阅地址文本，原文本为 Base64 编码的链接列表。
脚本将下载 → Base64 解码 → 合并去重 → 再次 Base64 编码 → 输出为仓库根目录的 V2ray.txt。

URL 模板:
  https://node.freessr.net/uploads/{YYYY}/{MM}/{i}-{YYYYMMDD}.txt  (i in 0..4)

在 GitHub Actions 中按每天北京时间 0 点运行。
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Iterable, List

try:
	from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
	ZoneInfo = None  # type: ignore


PRIMARY_HOST = "https://node.freessr.net"
FALLBACK_HOSTS = [os.environ.get("V2RAY_FALLBACK_HOST", "https://node.freeclashnode.com")]
OUTPUT_FILE = "V2ray.txt"
USER_AGENT = (
	"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_SECONDS = 20


def compute_yesterday_date_in_shanghai() -> dt.date:
	"""Return yesterday's date in Asia/Shanghai timezone.

	If zoneinfo is unavailable, fallback to UTC yesterday.
	"""
	if ZoneInfo is not None:
		shanghai_now = dt.datetime.now(ZoneInfo("Asia/Shanghai"))
		return (shanghai_now - dt.timedelta(days=1)).date()
	# Fallback (should not happen on GitHub runners)
	utc_now = dt.datetime.utcnow()
	return (utc_now - dt.timedelta(days=1)).date()


def build_urls(target_date: dt.date) -> List[str]:
	"""Build the five daily URLs for indices 0..4.

	Example: https://node.freessr.net/uploads/2025/09/2-20250911.txt
	"""
	year = target_date.year
	month = target_date.month
	yyyymmdd = f"{target_date:%Y%m%d}"
	return [
		f"{PRIMARY_HOST}/uploads/{year}/{month:02d}/{i}-{yyyymmdd}.txt" for i in range(5)
	]


def build_url_for_host(host: str, target_date: dt.date, index: int) -> str:
	year = target_date.year
	month = target_date.month
	return f"{host}/uploads/{year}/{month:02d}/{index}-{target_date:%Y%m%d}.txt"


def http_get_bytes(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> bytes | None:
	"""Download the content of a URL as bytes, returning None on error/non-200."""
	req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
	try:
		with urllib.request.urlopen(req, timeout=timeout) as resp:
			status = getattr(resp, "status", 200)
			if status != 200:
				print(f"[WARN] HTTP {status} for {url}")
				return None
			data = resp.read()
			if not data:
				print(f"[WARN] Empty body for {url}")
				return None
			return data
	except urllib.error.HTTPError as e:
		print(f"[WARN] HTTPError for {url}: {e}")
		return None
	except urllib.error.URLError as e:
		print(f"[WARN] URLError for {url}: {e}")
		return None
	except Exception as e:  # pragma: no cover
		print(f"[WARN] Error fetching {url}: {e}")
		return None


def _normalize_b64_bytes(b: bytes) -> bytes:
	"""Strip whitespace and pad to a multiple of 4 for Base64 decoding."""
	b = re.sub(rb"\s+", b"", b)
	padding = (-len(b)) % 4
	if padding:
		b += b"=" * padding
	return b


def try_base64_decode_to_text_lines(b: bytes) -> List[str]:
	"""Try to Base64 decode bytes, return text lines (non-empty, stripped).

	Falls back to urlsafe decoding if standard decoding fails.
	"""
	raw = _normalize_b64_bytes(b)
	decoded: bytes | None = None
	try:
		decoded = base64.b64decode(raw, validate=False)
	except Exception:
		try:
			decoded = base64.urlsafe_b64decode(raw)
		except Exception:
			decoded = None
	if not decoded:
		return []
	text = decoded.decode("utf-8", errors="ignore")
	text = text.replace("\r\n", "\n").replace("\r", "\n")
	lines = [ln.strip() for ln in text.split("\n")]
	return [ln for ln in lines if ln]


def fetch_v2ray_lines_for_index(target_date: dt.date, index: int) -> List[str]:
	"""Try primary then fallback hosts to fetch and decode lines for an index."""
	for host in [PRIMARY_HOST] + [h for h in FALLBACK_HOSTS if h]:
		url = build_url_for_host(host, target_date, index)
		print(f"[INFO] Trying: {url}")
		data = http_get_bytes(url)
		if not data:
			continue
		lines = try_base64_decode_to_text_lines(data)
		if lines:
			print(f"[INFO] Decoded {len(lines)} lines from {url}")
			return lines
		else:
			print(f"[WARN] Base64 decode produced no lines for {url}")
	return []


def merge_unique_preserve_order(seqs: Iterable[Iterable[str]]) -> List[str]:
	"""Merge sequences into a unique list preserving first-seen order."""
	seen = set()
	result: List[str] = []
	for seq in seqs:
		for item in seq:
			if item in seen:
				continue
			seen.add(item)
			result.append(item)
	return result


def encode_text_to_base64(text: str) -> str:
	"""Encode text to standard Base64 without embedded newlines."""
	return base64.b64encode(text.encode("utf-8")).decode("ascii")


def main(argv: List[str] | None = None) -> int:
	argv = argv or sys.argv[1:]
	# Allow optional override via environment for debugging, format YYYYMMDD
	override = os.environ.get("V2RAY_TARGET_DATE")
	if override:
		try:
			target_date = dt.datetime.strptime(override, "%Y%m%d").date()
		except ValueError:
			print(f"[ERROR] Invalid V2RAY_TARGET_DATE: {override}")
			return 2
	else:
		target_date = compute_yesterday_date_in_shanghai()

	print(f"[INFO] Target date: {target_date:%Y-%m-%d}")
	decoded_lists: List[List[str]] = []
	success_count = 0
	for i in range(5):
		lines = fetch_v2ray_lines_for_index(target_date, i)
		if not lines:
			continue
		decoded_lists.append(lines)
		success_count += 1

	if not decoded_lists:
		print("[WARN] No content decoded from any URL. Skip writing V2ray.txt.")
		return 0

	merged = merge_unique_preserve_order(decoded_lists)
	print(f"[INFO] Merged unique lines: {len(merged)}")

	output_text = "\n".join(merged)
	encoded = encode_text_to_base64(output_text)

	with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
		f.write(encoded)

	print(f"[INFO] Wrote {OUTPUT_FILE} with {len(encoded)} Base64 chars from {len(merged)} lines (sources: {success_count}/5)")
	return 0


if __name__ == "__main__":
	sys.exit(main()) 