# dupehawk 重复文件鹰眼 🦅

> 一条命令找出占着磁盘的复制粘贴元凶。**只读扫描、零误报、零依赖**，删除永远由你决定。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.6%2B-blue.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS-lightgrey.svg)]()

## 这解决什么问题

磁盘又满了，`du` 排查半天只看到一堆"看起来都该在"的目录——真正的元凶是**同一份文件被复制粘贴了 N 次**：解压包套解压包、备份目录叠备份目录、安装包下载了两遍。

dupehawk 用内容哈希把这些问题一次列清：

```
[组   1]     198.0M x5  可找回 792.1 MB
  保留 ↓   ~/Downloads/jdk8/jdk8.exe
  副本 ✗   ~/Downloads/工具包 2/环境/jdk_8.0.1310.11_64.exe
  副本 ✗   ~/Downloads/工具包/环境/jdk_8.0.1310.11_64.exe
  副本 ✗   ~/Downloads/环境/渗透测试环境/jdk_8.0.1310.11_64.exe
  副本 ✗   ~/Downloads/环境/环境/jdk_8.0.1310.11_64.exe
...
合计: 283 组重复, 399 个冗余副本, 可找回 7448.6 MB
```

（以上为真机实测输出：macOS Downloads 目录，283 组重复、**7.4 GB 可找回**——同名文件夹层层嵌套解压的典型现场。）

## 三十秒上手

```bash
# 自测（12 项不变量，应全 PASS）
python3 dupehawk.py --selftest

# 扫描目录（>=1MB 的文件才参与，避免噪音）
python3 dupehawk.py ~/Downloads

# 只看前 20 组 + 结果存为基线
python3 dupehawk.py ~/Downloads --json baseline.json

# 一周后再扫，对比：哪些新组冒出来了、哪些清掉了
python3 dupehawk.py ~/Downloads --baseline baseline.json

# 可找回空间超 500MB 时以退出码 2 告警（可接 cron）
python3 dupehawk.py ~/Downloads --threshold 500
```

## 它怎么保证零误报

三级漏斗，逐级收敛：

| 级别 | 手段 | 允许误差 |
|---|---|---|
| 1 | 按文件大小分组 | 不同大小必不重复 |
| 2 | 头尾各 4KB 部分哈希预筛 | 允许碰撞，只做粗筛 |
| 3 | 组内全量 MD5 裁决 | **零误报**（慢一点，值得） |

自测 fixture 里专门放了"头 4KB 相同、尾部不同"的诱饵样本——预筛会拦下它们，但全量裁决会还它们清白。

## 设计不变量

1. **绝对只读**：不修改、不移动、不删除任何被扫描的文件；删除建议只是建议
2. **符号链接一律跳过**，不追踪（防环、防跨卷误判）
3. **空文件单独标记**：0 字节文件不计入可找回空间，默认不建议删
4. **保留建议 = 路径字典序最小者**：结果稳定可复现，两次扫描建议完全一致
5. **零依赖**：Python 3.6+ 标准库，拷进任何机器直接跑

## 参数

```
用法: python3 dupehawk.py <目录> [选项]

  --min-size MB    忽略小于此 MB 的文件（默认 1.0）
  --top N          展开显示前 N 组（默认 20，其余折叠汇总）
  --json OUT       结果写入 JSON（作下次对比的基线）
  --baseline OLD   与旧基线对比：新增组 / 已解决组
  --threshold MB   可找回空间超过此值则退出码 2（告警钩子）
  --selftest       运行 12 项自测
```

退出码：`0` 干净或低于阈值 / `2` 可找回空间超阈值 / `1` 用法或自测错误。

## 接进你的自动化

```cron
# 每天凌晨扫一次下载目录，超 1GB 拉响退出码 2（配合你的监控/cronguard）
0 4 * * *  python3 /opt/dupehawk/dupehawk.py ~/Downloads --threshold 1024 --json /var/tmp/dupehawk.json
```

## 工具链位置

本工具是「桌面卫生套件」的重复副本环节：

```
cronguard (盯定时任务) → logwhisperer (考古日志) → diskhound (磁盘元凶总览)
    → dupehawk (重复副本精确打击) → debugkit (立案修复)
```

diskhound 告诉你"目录大了"，dupehawk 告诉你"**哪份文件复制了几遍、删哪份**"。

## License

MIT
