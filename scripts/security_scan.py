#!/usr/bin/env python3
"""
安全扫描器 — Private Dashboard

功能：
    扫描 JSON / JS / HTML 文件，检测以下违规内容：
    1. 绝对文件路径（/home/、/Users/）
    2. 原始 session_key 明文
    3. API Key / Token（ghp_, sk-, eyJ, ha_token 等）
    4. PII（手机号、邮箱）
    5. message.content 字段泄漏

用法：
    # 扫描整个 docs/ 和 data/ 目录
    python3 scripts/security_scan.py

    # 仅扫描暂存文件
    python3 scripts/security_scan.py --staged

    # 扫描指定文件列表
    python3 scripts/security_scan.py --files "docs/lcm/data/latest.json" "docs/lcm/assets/js/dashboard.js"

    # 严格模式（发现违规即 exit 1）
    python3 scripts/security_scan.py --strict

安全约束：
    - 不修改任何文件
    - 不发送任何数据
    - 仅读取和分析
"""
from __future__ import annotations

import json
import os
import re
import sys
import argparse
from pathlib import Path
from typing import NamedTuple


# ── 检测模式定义 ─────────────────────────────────────────────────────────────

class Pattern(NamedTuple):
    name: str
    pattern: re.Pattern
    severity: str  # "CRITICAL" | "HIGH" | "MEDIUM"
    example: str


PATTERNS: list[Pattern] = [
    # 绝对路径
    Pattern(
        name="absolute_path",
        pattern=re.compile(r"/home/[a-zA-Z0-9_.-]+/|/Users/[a-zA-Z0-9_.-]+/"),
        severity="HIGH",
        example="/home/yrwd999/.openclaw/lcm.db",
    ),
    # session_key 明文（UUID 格式）
    Pattern(
        name="session_key_raw",
        pattern=re.compile(r'"session_key"\s*:\s*"agent:[a-z0-9]+:[a-z0-9\-]+:[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}"'),
        severity="CRITICAL",
        example='agent:main:dashboard:e3604e28-35c5-4e6e-a3eb-b1d314950402',
    ),
    # session_key 明文（数字 ID 格式）
    Pattern(
        name="session_key_numeric",
        pattern=re.compile(r'"session_key"\s*:\s*"agent:[a-z0-9]+:[a-z0-9\-]+:\d{10,}"'),
        severity="HIGH",
        example="agent:main:web:1780896220022",
    ),
    # GitHub Token
    Pattern(
        name="github_token",
        pattern=re.compile(r'gh[psto]_[a-zA-Z0-9]{36,}'),
        severity="CRITICAL",
        example="ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    ),
    # OpenAI / DashScope Key
    Pattern(
        name="openai_key",
        pattern=re.compile(r'sk-[a-zA-Z0-9]{20,}'),
        severity="CRITICAL",
        example="sk-abcdefghijklmnopqrst",
    ),
    # JWT Token
    Pattern(
        name="jwt_token",
        pattern=re.compile(r'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*'),
        severity="HIGH",
        example="eyJhbGciOiJIUzI1NiJ9...",
    ),
    # Home Assistant Token
    Pattern(
        name="ha_token",
        pattern=re.compile(r'ha_[a-zA-Z0-9]{20,}', re.IGNORECASE),
        severity="HIGH",
        example="ha_abcd1234efgh5678ijkl",
    ),
    # 手机号（中国大陆）
    Pattern(
        name="phone_number",
        pattern=re.compile(r'\b1[3-9]\d{9}\b'),
        severity="MEDIUM",
        example="13812345678",
    ),
    # 邮箱
    Pattern(
        name="email",
        pattern=re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
        severity="MEDIUM",
        example="user@example.com",
    ),
    # message.content / large_content
    Pattern(
        name="message_content",
        pattern=re.compile(r'"(?:content|large_content|summary_content)"\s*:\s*"[^"]{20,}"'),
        severity="CRITICAL",
        example='"content": "完整对话内容..."',
    ),
    # 内网 IP（仅在 JSON 数据上下文中）
    Pattern(
        name="internal_ip",
        pattern=re.compile(r'"[^"]*(?:url|endpoint|host|source|path)"[^"]*\s*:\s*"https?://10\.\d+'),
        severity="MEDIUM",
        example='"source": "https://10.0.1.11:8123"',
    ),
]

# 文件扩展名白名单
SCANNABLE_EXTS = {".json", ".js", ".mjs", ".html", ".css", ".md", ".yaml", ".yml", ".txt"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv"}


# ── 扫描逻辑 ─────────────────────────────────────────────────────────────────

class Violation(NamedTuple):
    file: str
    line: str
    pattern_name: str
    severity: str
    matched: str
    example: str


def scan_file(path: Path) -> list[Violation]:
    """扫描单个文件，返回所有违规项。"""
    violations = []

    if path.suffix.lower() not in SCANNABLE_EXTS:
        return violations

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"  ⚠️  无法读取 {path}: {e}", file=sys.stderr)
        return violations

    content = "".join(lines)

    for pat in PATTERNS:
        for match in pat.pattern.finditer(content):
            matched_text = match.group()

            # 计算行号
            line_num = content[:match.start()].count("\n") + 1

            # 获取该行内容（用于上下文）
            try:
                line_content = lines[line_num - 1].strip()
            except IndexError:
                line_content = matched_text[:80]

            violations.append(Violation(
                file=str(path),
                line=str(line_num),
                pattern_name=pat.name,
                severity=pat.severity,
                matched=matched_text[:100],
                example=pat.example,
            ))

    return violations


def should_scan(path: Path) -> bool:
    """判断文件是否应该扫描。"""
    # 跳过隐藏目录和特定目录
    parts = path.parts
    for skip in SKIP_DIRS:
        if skip in parts:
            return False

    # 必须是扫描范围内的扩展名
    if path.suffix.lower() not in SCANNABLE_EXTS:
        return False

    return True


def scan_paths(paths: list[Path]) -> list[Violation]:
    """扫描指定路径列表（文件或目录）。"""
    all_violations = []

    for p in paths:
        p = Path(p).resolve()

        if p.is_dir():
            for fpath in p.rglob("*"):
                if should_scan(fpath):
                    all_violations.extend(scan_file(fpath))
        elif p.is_file():
            if should_scan(p):
                all_violations.extend(scan_file(p))

    return all_violations


def get_staged_files() -> list[Path]:
    """获取暂存文件列表。"""
    try:
        result = os.popen("git diff --cached --name-only --diff-filter=ACM").read()
        files = [Path(f.strip()) for f in result.splitlines() if f.strip()]
        return files
    except Exception as e:
        print(f"  ⚠️  无法获取暂存文件（git diff --cached 失败）: {e}", file=sys.stderr)
        return []


# ── 输出格式化 ────────────────────────────────────────────────────────────────

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}


def print_report(violations: list[Violation], verbose: bool = False):
    """格式化输出扫描报告。"""
    if not violations:
        print("✅ 未发现安全违规（0 violations）")
        return

    # 按严重程度 + 文件名 + 行号排序
    violations.sort(key=lambda v: (
        SEVERITY_ORDER.get(v.severity, 99),
        v.file,
        int(v.line) if v.line.isdigit() else 0,
    ))

    # 分组输出
    current_file = None
    for v in violations:
        if v.file != current_file:
            print(f"\n📄 {v.file}")
            current_file = v.file

        severity_icon = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
        }.get(v.severity, "⚪")

        print(f"  {severity_icon} [{v.severity}] L{v.line}: {v.pattern_name}")
        print(f"     匹配: {v.matched}")
        if verbose:
            print(f"     示例: {v.example}")

    # 摘要
    critical = sum(1 for v in violations if v.severity == "CRITICAL")
    high = sum(1 for v in violations if v.severity == "HIGH")
    medium = sum(1 for v in violations if v.severity == "MEDIUM")

    print(f"\n{'='*60}")
    print(f"总计: {len(violations)} violations "
          f"(🔴 {critical}  🟠 {high}  🟡 {medium})")


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Private Dashboard 安全扫描器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python3 scripts/security_scan.py                          # 扫描 docs/ data/
  python3 scripts/security_scan.py --staged                  # 仅扫描暂存文件
  python3 scripts/security_scan.py --files a.json b.js      # 扫描指定文件
  python3 scripts/security_scan.py --strict                 # 严格模式（exit 1）
  python3 scripts/security_scan.py --verbose                 # 详细输出
        """,
    )
    p.add_argument(
        "--files",
        nargs="+",
        metavar="FILE",
        help="指定要扫描的文件或目录（默认扫描 docs/ data/）",
    )
    p.add_argument(
        "--staged",
        action="store_true",
        help="仅扫描 git 暂存文件",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="发现违规返回 exit 1（CI 模式）",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示每个违规的示例",
    )
    return p.parse_args()


def main():
    args = parse_args()

    # 确定扫描路径
    repo_root = Path(__file__).parent.parent.resolve()

    if args.staged:
        paths = get_staged_files()
        if not paths:
            print("✅ 无暂存文件，跳过扫描")
            sys.exit(0)
        print(f"[security] 扫描 {len(paths)} 个暂存文件...")
    elif args.files:
        paths = [repo_root / f for f in args.files]
        print(f"[security] 扫描 {len(paths)} 个指定文件...")
    else:
        # 默认：扫描 docs/ 和 data/
        docs_dir = repo_root / "docs"
        data_dir = repo_root / "data"
        paths = [d for d in [docs_dir, data_dir] if d.exists()]
        print(f"[security] 扫描 {docs_dir.name}/ 和 {data_dir.name}/ ...")
        if not paths:
            print("⚠️  未找到 docs/ 或 data/ 目录，跳过")
            sys.exit(0)

    # 执行扫描
    violations = scan_paths(paths)

    # 输出报告
    print_report(violations, verbose=args.verbose)

    # 严格模式
    if violations and args.strict:
        print("\n🚫 发现违规内容，禁止提交。")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
