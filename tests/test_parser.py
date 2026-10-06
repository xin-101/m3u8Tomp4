"""Phase 2: M3U8 解析器测试."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.m3u8_parser import (  # noqa: E402
    DRMProtectedError,
    ParseError,
    parse_m3u8,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def test_media_playlist():
    info = parse_m3u8(os.path.join(FIXTURES, "sample_media.m3u8"))
    assert info.segment_count == 3
    assert abs(info.duration - 28.5) < 0.01
    assert info.segment_type == "ts"
    assert not info.is_master
    assert not info.encrypted
    assert info.segments[0].uri.endswith("001.ts")
    print(f"  media: {info.segment_count} segs, {info.duration}s, {info.type_label}")


def test_master_playlist():
    info = parse_m3u8(os.path.join(FIXTURES, "sample_master.m3u8"))
    assert info.segment_count == 2
    assert info.resolution == "1920x1080"
    assert info.bandwidth == 5000000
    assert len(info.variants) == 3
    print(f"  master: picked {info.resolution} @ {info.bandwidth_label}")


def test_aes_encrypted():
    info = parse_m3u8(os.path.join(FIXTURES, "sample_aes.m3u8"))
    assert info.encrypted
    assert not info.drm
    assert info.key_method == "AES-128"
    assert info.key_url.endswith("key.bin")
    assert info.segments[0].key_uri.endswith("key.bin")
    print(f"  aes: method={info.key_method}, key={info.key_url}")


def test_fmp4():
    info = parse_m3u8(os.path.join(FIXTURES, "sample_fmp4.m3u8"))
    assert info.segment_type == "fmp4"
    print("  fmp4: detected")


def test_drm_blocked():
    try:
        parse_m3u8(os.path.join(FIXTURES, "sample_drm.m3u8"))
    except DRMProtectedError as exc:
        assert "DRM" in str(exc)
        print(f"  drm blocked: {str(exc)[:40]}...")
    else:
        raise AssertionError("DRM 未被拦截")


def test_missing_file():
    try:
        parse_m3u8(os.path.join(FIXTURES, "not_exist.m3u8"))
    except ParseError as exc:
        print(f"  missing file: {exc}")
    else:
        raise AssertionError("不存在文件未报错")


def test_empty_source():
    try:
        parse_m3u8("")
    except ParseError:
        print("  empty source: OK")
    else:
        raise AssertionError("空地址未报错")


def test_title_sanitization():
    from app.ui.task_widget import sanitize_filename

    assert "/" not in sanitize_filename("a/b:c*d?e<f>g|h")
    assert sanitize_filename("") == "未命名视频"
    print("  sanitize: OK")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"\nPhase2 parser tests: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
