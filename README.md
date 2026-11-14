# vn-iptv

Danh sách kênh truyền hình Việt Nam dạng m3u, tự cập nhật 6 giờ một lần từ [iptv-org/iptv](https://github.com/iptv-org/iptv#playlists).

## Dùng trong app IPTV (TV Mate, Tivimate, OTT Navigator, VLC...)

Thêm danh sách bằng đường dẫn:

| Tệp | Nội dung | Đường dẫn |
|---|---|---|
| `vn.m3u` | Kênh còn phản hồi lúc kiểm (khuyên dùng) | `https://raw.githubusercontent.com/anhyeuviolet/vn-iptv/main/vn.m3u` |
| `vn-all.m3u` | Mọi kênh lọc được, không kiểm | `https://raw.githubusercontent.com/anhyeuviolet/vn-iptv/main/vn-all.m3u` |

## Cách hoạt động

1. GitHub Actions (`.github/workflows/update.yml`) chạy `scripts/build.py` theo lịch.
2. Script tải `countries/vn.m3u` và `languages/vie.m3u` của iptv-org, gộp lại, bỏ link trùng.
3. Chỉ giữ kênh có `tvg-id` của Việt Nam (`.vn@...` hoặc `@Vietnam`). Danh sách gốc lẫn vài kênh Lào, Hmong, Mông Cổ.
4. Xếp nhóm: VTV, HTV, SCTV, VTVcab ON, Quốc gia, Địa phương, rồi theo thể loại.
5. Kiểm từng luồng bằng curl. Luồng chết bị bỏ khỏi `vn.m3u`. Kênh ghi `[Geo-blocked]` vẫn được giữ, vì máy chạy Actions ở ngoài Việt Nam.
6. Có thay đổi thì tự commit.

## Tuỳ chỉnh

Sửa `config.json`:

- `exclude_tvg_ids`: danh sách mã kênh muốn bỏ, vd `["TeaTV.vn@SD"]`.
- `exclude_name_regex`: bỏ kênh theo tên, vd `"Shop|Mua sam"`.
- `group_rules`: luật xếp nhóm theo tên kênh (biểu thức chính quy, khớp luật đầu tiên).
- `check.enabled`: `false` để bỏ bước kiểm luồng.

Chạy thử trên máy: `python scripts/build.py` (cần Python 3.10+ và curl).

## Lưu ý

- Luồng do iptv-org thu thập từ nguồn công khai. Repo này không lưu trữ video.
- Nhiều link sống ngắn, có thể chết giữa hai lần cập nhật.
- Tab Actions có nút "Run workflow" để cập nhật ngay.
