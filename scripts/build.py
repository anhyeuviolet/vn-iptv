"""Tải danh sách IPTV của iptv-org, lọc kênh Việt Nam, xuất tệp m3u.

Chạy: python scripts/build.py [--no-check]
Ra:   vn.m3u      kênh còn xem được (cộng kênh [Geo-blocked], vì máy kiểm ở ngoài VN)
      vn-all.m3u  mọi kênh lọc được, không kiểm
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
TAG_RE = re.compile(r"\s*\[[^\]]*\]")          # [Geo-blocked], [Not 24/7]
RES_RE = re.compile(r"\s*\(\d{3,4}[pi]\)")       # (720p), (1080i)


@dataclass
class Entry:
    attrs: dict
    raw_name: str
    url: str
    options: list = field(default_factory=list)  # các dòng #EXTVLCOPT / #KODIPROP

    @property
    def tvg_id(self) -> str:
        return self.attrs.get("tvg-id", "")

    @property
    def name(self) -> str:
        return RES_RE.sub("", TAG_RE.sub("", self.raw_name)).strip()

    @property
    def geo_blocked(self) -> bool:
        return "[Geo-blocked]" in self.raw_name

    def header(self, name: str) -> dict:
        for opt in self.options:
            if opt.lower().startswith(f"#extvlcopt:http-{name}="):
                return {name: opt.split("=", 1)[1]}
        return {}


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_m3u(text: str) -> list[Entry]:
    out, cur = [], None
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        if line.startswith("#EXTINF"):
            # Tên kênh nằm sau dấu phẩy đầu tiên ngoài ngoặc kép (thuộc tính có thể chứa dấu phẩy).
            in_q, cut = False, len(line)
            for i, ch in enumerate(line):
                if ch == '"':
                    in_q = not in_q
                elif ch == "," and not in_q:
                    cut = i
                    break
            head, name = line[:cut], line[cut + 1:]
            cur = Entry(dict(ATTR_RE.findall(head)), name.strip(), "")
        elif line.startswith("#") and cur is not None:
            if line.startswith(("#EXTVLCOPT", "#KODIPROP")):
                cur.options.append(line)
        elif not line.startswith("#") and cur is not None:
            cur.url = line
            out.append(cur)
            cur = None
    return out


def pick_group(e: Entry, cfg: dict) -> str:
    for group, pattern in cfg["group_rules"]:
        if re.search(pattern, e.name):
            return group
    first = (e.attrs.get("group-title") or "Undefined").split(";")[0]
    return cfg["category_names"].get(first, first)


_host_locks: dict[str, threading.Semaphore] = {}
_host_guard = threading.Lock()


def _host_sem(url: str) -> threading.Semaphore:
    host = urllib.parse.urlsplit(url).hostname or ""
    with _host_guard:
        return _host_locks.setdefault(host, threading.Semaphore(2))


def check(e: Entry, timeout: float) -> bool:
    """Gọi curl (Python urllib bị vài máy chủ chặn), đọc tối đa 8 KB đầu."""
    ua = e.header("user-agent").get("user-agent", DEFAULT_UA)
    cmd = ["curl", "-sL", "-k", "-m", str(timeout), "-r", "0-8191", "-A", ua,
           "-o", "-", "-w", "\n__CODE__ %{http_code} %{content_type}"]
    ref = e.header("referrer").get("referrer")
    if ref:
        cmd += ["-e", ref]
    cmd.append(e.url)
    for attempt in range(3):
        if attempt:
            time.sleep(2 * attempt)
        with _host_sem(e.url):
            p = subprocess.run(cmd, capture_output=True)
        body, _, tail = p.stdout.rpartition(b"\n__CODE__ ")
        parts = tail.decode("latin-1").split(" ", 1)
        code = int(parts[0]) if parts[0].isdigit() else 0
        ctype = parts[1].lower() if len(parts) > 1 else ""
        if p.returncode not in (0, 28) or code == 0 or code >= 500 or code == 429:
            continue  # lỗi mạng / máy chủ bận: thử lại
        if code >= 400:
            return False
        if body.lstrip().startswith(b"#EXTM3U") or body[:1] == b"G":  # m3u8 hoặc gói MPEG-TS
            return True
        return any(k in ctype for k in ("mpegurl", "video", "dash+xml", "mp2t"))
    return False


def write_m3u(path: Path, entries: list[Entry], cfg: dict) -> None:
    lines = ["#EXTM3U"]
    for e in entries:
        logo = e.attrs.get("tvg-logo", "")
        lines.append(
            f'#EXTINF:-1 tvg-id="{e.tvg_id}" tvg-name="{e.name}" tvg-logo="{logo}" '
            f'group-title="{pick_group(e, cfg)}",{e.name}'
        )
        lines.extend(e.options)
        lines.append(e.url)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-check", action="store_true", help="bỏ bước kiểm luồng")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

    include = re.compile(cfg["include_tvg_id_regex"])
    exclude_ids = set(cfg.get("exclude_tvg_ids", []))
    exclude_name = re.compile(cfg["exclude_name_regex"]) if cfg.get("exclude_name_regex") else None

    entries: dict[str, Entry] = {}
    for src in cfg["sources"]:
        items = parse_m3u(fetch_text(src))
        print(f"{src}: {len(items)} luồng")
        for e in items:
            if e.url in entries or e.tvg_id in exclude_ids:
                continue
            if exclude_name and exclude_name.search(e.name):
                continue
            # Chỉ giữ kênh có mã Việt Nam (danh sách gốc lẫn kênh Lào, Hmong, Mông Cổ...).
            if not include.search(e.tvg_id):
                continue
            entries[e.url] = e

    order = {g: n for n, (g, _) in enumerate(cfg["group_rules"])}
    natural = lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]
    all_entries = sorted(
        entries.values(),
        key=lambda e: (order.get(pick_group(e, cfg), 99), pick_group(e, cfg), natural(e.name)),
    )
    write_m3u(ROOT / "vn-all.m3u", all_entries, cfg)
    print(f"vn-all.m3u: {len(all_entries)} kênh")

    chk = cfg.get("check", {})
    if args.no_check or not chk.get("enabled", True):
        write_m3u(ROOT / "vn.m3u", all_entries, cfg)
        print("vn.m3u: bỏ qua bước kiểm")
        return 0

    with cf.ThreadPoolExecutor(chk.get("workers", 16)) as pool:
        alive = list(pool.map(lambda e: check(e, chk.get("timeout_seconds", 12)), all_entries))
    keep_geo = chk.get("keep_geo_blocked", True)
    good = [e for e, ok in zip(all_entries, alive) if ok or (keep_geo and e.geo_blocked)]
    dead = [e for e, ok in zip(all_entries, alive) if not ok and not (keep_geo and e.geo_blocked)]
    if not any(alive):
        print("Không luồng nào phản hồi, có thể mạng lỗi. Giữ nguyên vn.m3u cũ.", file=sys.stderr)
        return 1
    write_m3u(ROOT / "vn.m3u", good, cfg)
    print(f"vn.m3u: {len(good)} kênh (bỏ {len(dead)} luồng không phản hồi)")
    for e in dead:
        print(f"  - {e.name}: {e.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
