# dupehawk — duplicate-file hawk-eye scanner

English README (中文版见 [README.md](README.md))

> One command to find the copy-paste hoarders eating your disk. **Read-only, zero false positives, zero dependencies** — deletion is always your call.

## The problem

Disk full again. `du` shows nothing obviously wrong — the real culprits are **the same file copied N times**: archives unzipped inside archives, backup dirs stacked on backup dirs, installers downloaded twice.

dupehawk lists them all by content hash:

```
[组   1]     198.0M x5  recoverable 792.1 MB
  keep ↓   ~/Downloads/jdk8/jdk8.exe
  copy ✗   ~/Downloads/toolkit 2/env/jdk_8.0.1310.11_64.exe
  copy ✗   ~/Downloads/toolkit/env/jdk_8.0.1310.11_64.exe
...
Total: 283 duplicate groups, 399 redundant copies, 7448.6 MB recoverable
```

(Real-world run on a macOS Downloads dir: 283 groups, **7.4 GB recoverable** — the classic nested-unzip mess.)

## Quick start

```bash
python3 dupehawk.py --selftest          # 12 invariants, should all PASS
python3 dupehawk.py ~/Downloads         # scan (files >= 1MB)
python3 dupehawk.py ~/Downloads --json baseline.json
python3 dupehawk.py ~/Downloads --baseline baseline.json   # diff vs last run
python3 dupehawk.py ~/Downloads --threshold 500            # exit 2 if recoverable >= 500MB
```

## Zero false positives, by construction

Three-stage funnel:

| Stage | Technique | Error allowed |
|---|---|---|
| 1 | Group by file size | different size = never duplicates |
| 2 | Head+tail 4KB partial hash prefilter | collisions allowed, coarse only |
| 3 | Full MD5 within group | **zero false positives** |

The selftest ships a bait sample: identical first 4KB, different tails — the prefilter catches it, the full hash acquits it.

## Invariants

1. **Strictly read-only** — never touches scanned files; the dedup plan is a suggestion only
2. **Symlinks are always skipped** (no loops, no cross-volume surprises)
3. **Empty files flagged separately** — not counted as recoverable, not recommended for deletion
4. **Keep = lexicographically smallest path** — stable, reproducible across runs
5. **Zero dependencies** — Python 3.6+ stdlib only

## Exit codes

`0` clean or under threshold · `2` recoverable space over threshold (alert hook) · `1` usage/selftest error.

## Toolchain position

Part of a desktop-hygiene suite: `cronguard` (cron watchdog) → `logwhisperer` (log archaeology) → `diskhound` (disk culprit overview) → **dupehawk (duplicate copies, precise strike)** → `debugkit` (case-based fixing). diskhound tells you the directory is big; dupehawk tells you **which file was copied how many times and which copy to drop**.

## License

MIT
