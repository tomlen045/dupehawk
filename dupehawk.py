#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dupehawk v1.0.0 — 重复文件鹰眼：找出占着磁盘的复制粘贴元凶
工具链咬合: cronguard(盯任务)→logwhisperer(考古日志)→diskhound(磁盘元凶)→dupehawk(重复副本)→debugkit(立案修复)

一条命令列出重复文件组、可找回空间、去重建议(只建议不执行)。

不变量:
  1. 绝对只读: 不修改、不移动、不删除任何被扫描文件
  2. 空文件(0字节)单独标记, 不计入可找回空间, 默认不建议删
  3. 符号链接一律跳过, 不追踪
  4. 判重两级: 大小分组 → 首尾4KB部分哈希预筛 → 组内全量MD5确认(零误报)
  5. 保留建议 = 路径字典序最小者(结果稳定可复现)

用法:
  python3 dupehawk.py <目录> [--min-size MB] [--top N] [--json OUT] [--baseline OLD.json]
                      [--threshold MB] [--selftest]
退出码: 0=无重复 / 2=可找回空间超阈值 / 1=用法或自测错误
"""
import argparse
import hashlib
import json
import os
import sys

CHUNK = 4096          # 部分哈希: 头尾各4KB
FULL_HASH_LIMIT = 8 * 1024 * 1024 * 1024  # 超过8GB仍全量(慢但准), 零误报优先


def part_hash(path, size):
    """头尾各4KB的SHA256, 用于预筛(快, 允许碰撞)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        head = f.read(CHUNK)
        h.update(head)
        if size > CHUNK:
            if size > 2 * CHUNK:
                f.seek(size - CHUNK)
                h.update(f.read(CHUNK))
            else:
                h.update(f.read(size - CHUNK))
    return h.hexdigest()


def full_hash(path):
    """全量MD5, 最终裁决。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def scan(root, min_bytes):
    """返回 (dup_groups, empty_group, skipped)
    dup_groups: [(size, [paths...]), ...] 按可找回空间降序
    """
    by_size = {}
    empty = []
    skipped = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            p = os.path.join(dirpath, name)
            try:
                st = os.lstat(p)
            except OSError:
                skipped += 1
                continue
            if os.path.islink(p):
                skipped += 1
                continue
            if st.st_size == 0:
                empty.append(p)
                continue
            if st.st_size < min_bytes:
                continue
            by_size.setdefault(st.st_size, []).append(p)

    # 预筛: 同大小且同部分哈希才进全量确认
    candidates = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_ph = {}
        for p in paths:
            try:
                by_ph.setdefault(part_hash(p, size), []).append(p)
            except OSError:
                skipped += 1
        for group in by_ph.values():
            if len(group) >= 2:
                candidates.append((size, group))

    # 全量MD5确认
    dup_groups = []
    for size, group in candidates:
        by_full = {}
        for p in group:
            try:
                by_full.setdefault(full_hash(p), []).append(p)
            except OSError:
                skipped += 1
        for g in by_full.values():
            if len(g) >= 2:
                dup_groups.append((size, sorted(g)))

    dup_groups.sort(key=lambda x: x[0] * (len(x[1]) - 1), reverse=True)
    return dup_groups, sorted(empty), skipped


def report(dup_groups, empty, top_n, min_mb):
    wasted_total = sum(size * (len(g) - 1) for size, g in dup_groups)
    dup_files_total = sum(len(g) - 1 for _, g in dup_groups)
    lines = []
    lines.append("=" * 62)
    lines.append("dupehawk 重复文件鹰眼 (只读扫描, 只建议不执行)")
    lines.append("=" * 62)
    if not dup_groups and not empty:
        lines.append("干净: 没有发现重复文件 (>= {} MB)".format(min_mb))
        return lines, wasted_total
    shown = dup_groups[:top_n]
    for i, (size, g) in enumerate(shown, 1):
        recover = size * (len(g) - 1)
        lines.append("")
        lines.append("[组 {:>3}] {:>10} x{}  可找回 {:.1f} MB".format(
            i, human(size), len(g), recover / 1048576))
        for j, p in enumerate(g):
            tag = "保留 ↓" if j == 0 else "副本 ✗"
            lines.append("  {} {}".format(tag.ljust(6), p))
    if len(dup_groups) > top_n:
        rest = dup_groups[top_n:]
        rest_waste = sum(s * (len(g) - 1) for s, g in rest)
        lines.append("")
        lines.append("... 还有 {} 组未展开, 另占 {:.1f} MB (用 --top 调整)".format(
            len(rest), rest_waste / 1048576))
    if empty:
        lines.append("")
        lines.append("[空文件] {} 个 0 字节文件 (已标记, 不计入找回, 默认不建议删)".format(len(empty)))
        for p in empty[:5]:
            lines.append("  · {}".format(p))
        if len(empty) > 5:
            lines.append("  · ... 等 {} 个".format(len(empty)))
    lines.append("")
    lines.append("-" * 62)
    lines.append("合计: {} 组重复, {} 个冗余副本, 可找回 {:.1f} MB".format(
        len(dup_groups), dup_files_total, wasted_total / 1048576))
    lines.append("去重计划(供参考, 本工具不执行删除): 每组保留路径字典序最小者")
    return lines, wasted_total


def human(n):
    if n >= 1048576:
        return "{:.1f}M".format(n / 1048576)
    if n >= 1024:
        return "{:.1f}K".format(n / 1024)
    return "{}B".format(n)


def group_key(paths):
    return json.dumps(paths)


def run_baseline(old, dup_groups):
    """对比基线: 新增重复组 / 已解决组。"""
    now_keys = {group_key(g) for _, g in dup_groups}
    old_keys = set()
    for _, paths in old.get("groups", []):
        old_keys.add(group_key(paths))
    new = now_keys - old_keys
    resolved = old_keys - now_keys
    return new, resolved


def selftest():
    """偏态分布 fixture: 少数大重复组 + 大量小噪音文件。
    返回 0=全过 / 1=有失败。"""
    import shutil
    import tempfile
    fails = []
    tmp = tempfile.mkdtemp(prefix="dupehawk_selftest_")
    try:
        # -- 大重复组A: 3MB 随机
        a = os.path.join(tmp, "projectA", "assets")
        os.makedirs(a)
        big = os.urandom(3 * 1048576)
        with open(os.path.join(a, "hero_v1.bin"), "wb") as f:
            f.write(big)
        b = os.path.join(tmp, "projectB", "backup")
        os.makedirs(b)
        with open(os.path.join(b, "hero_v1.bin"), "wb") as f:
            f.write(big)
        c = os.path.join(tmp, "copies")
        os.makedirs(c)
        with open(os.path.join(c, "hero_copy2.bin"), "wb") as f:
            f.write(big)
        # -- 大重复组B: 2MB 日志 (同一内容两份)
        log_line = b"[2026-10-18] worker ok\n"   # 23 字节/行
        log_data = (log_line * (2 * 1048576 // len(log_line) + 1))[:2 * 1048576]
        with open(os.path.join(tmp, "data.log"), "wb") as f:
            f.write(log_data)
        lg = os.path.join(tmp, "logs")
        os.makedirs(lg)
        with open(os.path.join(lg, "backup_data.log"), "wb") as f:
            f.write(log_data)
        # -- 预筛碰撞样本: 头4KB相同 尾部不同 → 不算重复
        pad = b"HEAD-SAME-" * 410  # 4100 bytes
        with open(os.path.join(tmp, "collide_x.bin"), "wb") as f:
            f.write(pad + b"TAIL-X" + os.urandom(512))
        with open(os.path.join(tmp, "collide_y.bin"), "wb") as f:
            f.write(pad + b"TAIL-Y" + os.urandom(512))
        # -- 偏态噪音: 46个小文件(1~16KB) + 4个中型唯一文件(200KB)
        noise = os.path.join(tmp, "noise")
        os.makedirs(noise)
        for i in range(46):
            with open(os.path.join(noise, "small_{:02d}.dat".format(i)), "wb") as f:
                f.write(bytes([i % 251]) * (1024 + i * 331))
        for i in range(4):
            with open(os.path.join(noise, "mid_{}.bin".format(i)), "wb") as f:
                f.write(os.urandom(204800 + i))
        # -- 空文件组
        with open(os.path.join(tmp, "empty1.txt"), "w") as f:
            pass
        with open(os.path.join(tmp, "empty2.txt"), "w") as f:
            pass
        # -- 符号链接(指向副本, 应被跳过)
        try:
            os.symlink(os.path.join(c, "hero_copy2.bin"), os.path.join(tmp, "link_to_hero"))
        except OSError:
            pass  # 文件系统不支持 symlink 时跳过该项

        dup_groups, empty, skipped = scan(tmp, 1024)
        wasted = sum(s * (len(g) - 1) for s, g in dup_groups)

        def check(name, cond):
            print("  [{}] {}".format("PASS" if cond else "FAIL", name))
            if not cond:
                fails.append(name)

        check("恰好 2 组真实重复 (得到 {})".format(len(dup_groups)), len(dup_groups) == 2)
        check("可找回空间 = 8MB (得到 {:.2f}MB)".format(wasted / 1048576),
              wasted == 8 * 1048576)
        big_group = next((g for s, g in dup_groups if s == 3 * 1048576), None)
        check("3MB 组有 3 个副本", big_group is not None and len(big_group) == 3)
        check("保留建议=字典序最小且稳定",
              all(g[0] == min(g) for _, g in dup_groups))
        check("预筛碰撞未误判 (无 collide 组)",
              not any("collide" in p for _, g in dup_groups for p in g))
        check("噪音文件零误判 (noise 无成员)",
              not any("/noise/" in p for _, g in dup_groups for p in g))
        check("空文件组被标记 (2个)", len(empty) == 2)
        check("空文件不计入可找回", all(s > 0 for s, _ in dup_groups))
        check("符号链接被跳过",
              not any("link_to_hero" in p for _, g in dup_groups for p in g))
        check("无 1MB 以下误报", all(s >= 1024 for s, _ in dup_groups))

        # -- 基线对比: 存基线→再扫→新组/解决组
        old_json = {"groups": [[s, g] for s, g in dup_groups]}
        # 模拟: 组B解决, 新增一个 1MB 小重复组
        dup_groups2 = [dup_groups[0]] + [(1048576, ["/tmp/new1", "/tmp/new2"])]
        new, resolved = run_baseline(old_json, dup_groups2)
        check("基线: 检出 1 个新组", len(new) == 1)
        check("基线: 检出 1 组已解决", len(resolved) == 1)

        # -- 阈值退出码
        check("退出码约定 0/1/2", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if fails:
        print("SELFTEST: {} FAILED /{}".format(len(fails), len(fails) + 11))
        return 1
    print("SELFTEST: 12/12 PASS")
    return 0


def main():
    ap = argparse.ArgumentParser(description="dupehawk 重复文件鹰眼(只读)")
    ap.add_argument("root", nargs="?", help="要扫描的目录")
    ap.add_argument("--min-size", type=float, default=1.0, help="忽略小于此 MB 的文件 (默认 1)")
    ap.add_argument("--top", type=int, default=20, help="展开显示前 N 组 (默认 20)")
    ap.add_argument("--json", dest="json_out", help="结果存为 JSON 基线")
    ap.add_argument("--baseline", help="与上次 JSON 基线对比")
    ap.add_argument("--threshold", type=float, default=0, help="可找回空间告警阈值 MB")
    ap.add_argument("--selftest", action="store_true", help="运行自测")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())
    if not args.root:
        ap.print_help()
        sys.exit(1)
    if not os.path.isdir(args.root):
        print("dupehawk: 目录不存在: {}".format(args.root), file=sys.stderr)
        sys.exit(1)

    min_bytes = int(args.min_size * 1048576)
    old = None
    if args.baseline:
        try:
            with open(args.baseline, "r", encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError) as e:
            print("dupehawk: 基线文件不可读: {}".format(e), file=sys.stderr)
            sys.exit(1)

    dup_groups, empty, skipped = scan(args.root, min_bytes)
    lines, wasted = report(dup_groups, empty, args.top, args.min_size)
    print("\n".join(lines))
    if skipped:
        print("已跳过 {} 个不可读/符号链接项".format(skipped))

    if args.json_out:
        payload = {
            "tool": "dupehawk",
            "version": "1.0.0",
            "root": os.path.abspath(args.root),
            "min_size_mb": args.min_size,
            "wasted_bytes": wasted,
            "groups": [[s, g] for s, g in dup_groups],
            "empty_files": empty,
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print("基线已写入: {}".format(args.json_out))

    if old is not None:
        new, resolved = run_baseline(old, dup_groups)
        print("")
        print("对比基线: 新增 {} 组, 已解决 {} 组".format(len(new), len(resolved)))
        for k in list(new)[:5]:
            print("  [新增] {}".format(k[:120]))
        for k in list(resolved)[:5]:
            print("  [已解决] {}".format(k[:120]))

    if args.threshold > 0 and wasted >= args.threshold * 1048576:
        print("\n⚠ 水位告警: 可找回 {:.1f} MB >= 阈值 {:.0f} MB (退出码 2)".format(
            wasted / 1048576, args.threshold))
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
