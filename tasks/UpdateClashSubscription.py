#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UpdateClashSubscription.py

抓取昨天(北京时间)的 0-4 共 5 个 Clash 订阅 YAML：
  https://node.freessr.net/uploads/{YYYY}/{MM}/{i}-{YYYYMMDD}.yaml  (i in 0..4)

步骤：下载 → 尝试 Base64 解码(若失败则按文本处理) → 合并去重为多文档 YAML (--- 分隔) → 将合并后的文本整体 Base64 编码 → 输出为仓库根目录 Clash.txt。
与 V2Ray 一样供 GitHub Actions 每天北京时间 0 点运行。
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Iterable, List, Optional

try:
	from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
	ZoneInfo = None  # type: ignore


PRIMARY_HOST = "https://node.freessr.net"
FALLBACK_HOSTS = [os.environ.get("CLASH_FALLBACK_HOST", "https://node.freeclashnode.com")]
OUTPUT_FILE = "Clash.txt"
USER_AGENT = (
	"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_SECONDS = 20


def compute_yesterday_date_in_shanghai() -> dt.date:
	if ZoneInfo is not None:
		shanghai_now = dt.datetime.now(ZoneInfo("Asia/Shanghai"))
		return (shanghai_now - dt.timedelta(days=1)).date()
	utc_now = dt.datetime.utcnow()
	return (utc_now - dt.timedelta(days=1)).date()


def build_yaml_urls(target_date: dt.date) -> List[str]:
	year = target_date.year
	month = target_date.month
	yyyymmdd = f"{target_date:%Y%m%d}"
	return [
		f"{PRIMARY_HOST}/uploads/{year}/{month:02d}/{i}-{yyyymmdd}.yaml" for i in range(5)
	]

def build_url_for_host(host: str, target_date: dt.date, index: int) -> str:
	year = target_date.year
	month = target_date.month
	return f"{host}/uploads/{year}/{month:02d}/{index}-{target_date:%Y%m%d}.yaml"


def http_get_bytes(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Optional[bytes]:
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
	b = re.sub(rb"\s+", b"", b)
	padding = (-len(b)) % 4
	if padding:
		b += b"=" * padding
	return b


def try_base64_decode_to_text(b: bytes) -> Optional[str]:
	raw = _normalize_b64_bytes(b)
	decoded: Optional[bytes] = None
	try:
		decoded = base64.b64decode(raw, validate=False)
	except Exception:
		try:
			decoded = base64.urlsafe_b64decode(raw)
		except Exception:
			decoded = None
	if not decoded:
		return None
	text = decoded.decode("utf-8", errors="ignore")
	# Heuristic: require some YAML-ish tokens to consider success
	hint_tokens = ("proxies:", "proxy-groups:", "mixed-port:", "port:", "rules:")
	normalized = text.replace("\r\n", "\n").replace("\r", "\n")
	if any(tok in normalized for tok in hint_tokens) or len(normalized) > 200:
		return normalized
	return normalized  # still return; consumer will just treat as text


def merge_unique_docs(docs: Iterable[str]) -> List[str]:
	seen = set()
	result: List[str] = []
	for doc in docs:
		key = doc.strip()
		if not key:
			continue
		if key in seen:
			continue
		seen.add(key)
		result.append(key)
	return result


def encode_text_to_base64(text: str) -> str:
	return base64.b64encode(text.encode("utf-8")).decode("ascii")


def fetch_yaml_text_for_index(target_date: dt.date, index: int) -> Optional[str]:
	for host in [PRIMARY_HOST] + [h for h in FALLBACK_HOSTS if h]:
		url = build_url_for_host(host, target_date, index)
		print(f"[INFO] Trying: {url}")
		data = http_get_bytes(url)
		if not data:
			continue
		text = try_base64_decode_to_text(data)
		if text is None:
			text = data.decode("utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
		print(f"[INFO] Collected YAML doc from {url}, size={len(text)} chars")
		return text
	return None


def main(argv: List[str] | None = None) -> int:
	argv = argv or sys.argv[1:]
	override = os.environ.get("CLASH_TARGET_DATE") or os.environ.get("V2RAY_TARGET_DATE")
	if override:
		try:
			target_date = dt.datetime.strptime(override, "%Y%m%d").date()
		except ValueError:
			print(f"[ERROR] Invalid *_TARGET_DATE: {override}")
			return 2
	else:
		target_date = compute_yesterday_date_in_shanghai()

	print(f"[INFO] Target date: {target_date:%Y-%m-%d}")

	docs: List[str] = []
	success_count = 0
	for i in range(5):
		text = fetch_yaml_text_for_index(target_date, i)
		if text is None:
			continue
		docs.append(text)
		success_count += 1

	if not docs:
		print("[WARN] No YAML docs collected. Skip writing Clash.txt.")
		return 0

	unique_docs = merge_unique_docs(docs)
	print(f"[INFO] Unique YAML docs: {len(unique_docs)}")

	combined = "\n---\n".join(unique_docs) + "\n"
	encoded = encode_text_to_base64(combined)

	with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
		f.write(encoded)

	print(f"[INFO] Wrote {OUTPUT_FILE} with {len(encoded)} Base64 chars from {len(unique_docs)} docs (sources: {success_count}/5)")
	return 0


if __name__ == "__main__":
	sys.exit(main()) 