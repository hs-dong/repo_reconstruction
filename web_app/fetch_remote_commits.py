#!/usr/bin/env python3
"""
获取 EchoCraft GitHub 仓库的远程 commit 历史

支持两种方式：
1. GitHub REST API（推荐，不需要本地克隆仓库）
2. 本地 git 仓库（需要先 clone 或 fetch）

使用方法:
    # 方式1: 通过 GitHub API 获取远程 commit 历史（默认）
    python fetch_remote_commits.py

    # 指定仓库和分支
    python fetch_remote_commits.py --owner DongHande --repo EchoCraft --branch main

    # 获取指定数量的 commit
    python fetch_remote_commits.py --per-page 50 --pages 3

    # 按作者筛选
    python fetch_remote_commits.py --author aacedar

    # 按时间范围筛选
    python fetch_remote_commits.py --since 2026-01-01 --until 2026-03-11

    # 方式2: 从本地仓库获取
    python fetch_remote_commits.py --local /ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_data/EchoCraft

    # 输出为 JSON 文件
    python fetch_remote_commits.py --output commits.json

    # 输出为 JSONL 文件（每行一条记录）
    python fetch_remote_commits.py --output commits.jsonl --format jsonl

    # 使用 GitHub Token（可获取更高频率限制）
    python fetch_remote_commits.py --token ghp_xxxxxxxxxxxx

    检查hsdong的仓库: python eval_script/web_app/fetch_remote_commits.py --local /ai_train/bingodong/dhs/repo_reconstruction_evaluation --branch master
    检查Echocraft的仓库:  python eval_script/web_app/fetch_remote_commits.py --local eval_data/EchoCraft
"""

import os
import sys
import json
import argparse
import subprocess
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
import time


# ==================== 数据类（兼容 Python 3.6+）====================

class RemoteCommitInfo:
    """远程 commit 信息"""

    def __init__(
        self,
        sha='',                    # 完整 SHA
        short_sha='',              # 短 SHA（前7位）
        message='',                # commit 消息（第一行）
        full_message='',           # 完整 commit 消息
        author_name='',            # 作者名称
        author_email='',           # 作者邮箱
        author_login='',           # GitHub 用户名
        author_avatar_url='',      # 作者头像 URL
        committer_name='',         # 提交者名称
        committer_email='',        # 提交者邮箱
        commit_date='',            # 提交日期（ISO 格式）
        commit_timestamp=0.0,      # 提交时间戳
        pr_number=None,            # 关联的 PR 编号
        module=None,               # 关联的模块名称
        html_url='',               # GitHub 上的 commit 链接
        parents=None,              # 父 commit 列表
        stats=None,                # 变更统计（additions, deletions, total）
    ):
        self.sha = sha
        self.short_sha = short_sha
        self.message = message
        self.full_message = full_message
        self.author_name = author_name
        self.author_email = author_email
        self.author_login = author_login
        self.author_avatar_url = author_avatar_url
        self.committer_name = committer_name
        self.committer_email = committer_email
        self.commit_date = commit_date
        self.commit_timestamp = commit_timestamp
        self.pr_number = pr_number
        self.module = module
        self.html_url = html_url
        self.parents = parents if parents is not None else []
        self.stats = stats

    def to_dict(self):
        """转换为字典"""
        return {
            'sha': self.sha,
            'short_sha': self.short_sha,
            'message': self.message,
            'full_message': self.full_message,
            'author_name': self.author_name,
            'author_email': self.author_email,
            'author_login': self.author_login,
            'author_avatar_url': self.author_avatar_url,
            'committer_name': self.committer_name,
            'committer_email': self.committer_email,
            'commit_date': self.commit_date,
            'commit_timestamp': self.commit_timestamp,
            'pr_number': self.pr_number,
            'module': self.module,
            'html_url': self.html_url,
            'parents': self.parents,
            'stats': self.stats,
        }

    def __repr__(self):
        return (f"RemoteCommitInfo(sha={self.short_sha!r}, "
                f"author={self.author_name!r}, "
                f"date={self.commit_date!r}, "
                f"msg={self.message[:40]!r})")


# ==================== GitHub API 方式 ====================

class GitHubAPIClient:
    """GitHub REST API 客户端"""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        """
        初始化 GitHub API 客户端

        Args:
            token: GitHub Personal Access Token（可选，有更高频率限制）
        """
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "EchoCraft-Commit-Fetcher/1.0",
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"

    def _request(self, url: str, params: Optional[Dict] = None) -> Tuple[Dict, Dict]:
        """
        发送 GET 请求到 GitHub API

        Returns:
            (response_data, response_headers)
        """
        if params:
            url = f"{url}?{urlencode(params)}"

        req = Request(url, headers=self.headers)

        try:
            with urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
                headers = dict(response.headers)
                return data, headers
        except HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 403 and "rate limit" in error_body.lower():
                # 速率限制，返回重置时间
                reset_time = e.headers.get("X-RateLimit-Reset", "0")
                wait_seconds = max(int(reset_time) - int(time.time()), 0)
                print(f"\n[WARN] GitHub API 速率限制已达到，需要等待 {wait_seconds} 秒")
                print(f"       建议使用 --token 参数提供 GitHub Personal Access Token")
                raise
            elif e.code == 404:
                print(f"\n[ERROR] 仓库未找到或无权限访问: {url}")
                raise
            else:
                print(f"\n[ERROR] GitHub API 请求失败 (HTTP {e.code}): {error_body}")
                raise
        except URLError as e:
            print(f"\n[ERROR] 网络连接错误: {e}")
            raise

    def get_rate_limit(self) -> Dict:
        """获取当前 API 速率限制信息"""
        data, _ = self._request(f"{self.BASE_URL}/rate_limit")
        return data.get("rate", {})

    def get_repo_info(self, owner: str, repo: str) -> Dict:
        """获取仓库基本信息"""
        data, _ = self._request(f"{self.BASE_URL}/repos/{owner}/{repo}")
        return data

    def get_branches(self, owner: str, repo: str) -> List[Dict]:
        """获取仓库分支列表"""
        data, _ = self._request(f"{self.BASE_URL}/repos/{owner}/{repo}/branches")
        return data

    def get_commits(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        per_page: int = 100,
        pages: int = 1,
        since: Optional[str] = None,
        until: Optional[str] = None,
        author: Optional[str] = None,
    ) -> List[RemoteCommitInfo]:
        """
        获取仓库的 commit 历史

        Args:
            owner: 仓库所有者（如 "DongHande"）
            repo: 仓库名称（如 "EchoCraft"）
            branch: 分支名称
            per_page: 每页数量（最大100）
            pages: 获取页数
            since: 起始时间（ISO 格式，如 "2026-01-01T00:00:00Z"）
            until: 结束时间（ISO 格式）
            author: 筛选作者（GitHub 用户名或邮箱）

        Returns:
            List[RemoteCommitInfo]: commit 信息列表
        """
        all_commits = []
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/commits"

        for page in range(1, pages + 1):
            params = {
                "sha": branch,
                "per_page": min(per_page, 100),
                "page": page,
            }
            if since:
                params["since"] = _to_iso_time(since)
            if until:
                params["until"] = _to_iso_time(until)
            if author:
                params["author"] = author

            print(f"  [INFO] 正在获取第 {page}/{pages} 页 (每页 {per_page} 条)...")

            try:
                data, headers = self._request(url, params)
            except Exception as e:
                print(f"  [ERROR] 获取第 {page} 页失败: {e}")
                break

            if not data:
                print(f"  [INFO] 第 {page} 页无更多数据")
                break

            for item in data:
                commit_info = _parse_api_commit(item)
                all_commits.append(commit_info)

            # 检查是否还有更多数据
            link_header = headers.get("Link", "")
            if 'rel="next"' not in link_header and len(data) < per_page:
                break

            # 遵守速率限制，短暂等待
            remaining = headers.get("X-RateLimit-Remaining", "999")
            if int(remaining) < 10:
                print(f"  [WARN] API 剩余调用次数: {remaining}，暂停 1 秒...")
                time.sleep(1)

        return all_commits

    def get_commit_detail(self, owner: str, repo: str, sha: str) -> Dict:
        """获取单个 commit 的详细信息（包含文件变更）"""
        data, _ = self._request(f"{self.BASE_URL}/repos/{owner}/{repo}/commits/{sha}")
        return data


# ==================== 本地 Git 方式 ====================

class LocalGitClient:
    """本地 Git 仓库客户端"""

    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            raise ValueError(f"路径不是一个 Git 仓库: {repo_path}")

    def _run_git(self, args, timeout=60):
        """执行 git 命令"""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            if result.returncode == 0:
                return result.stdout.decode('utf-8', errors='ignore').strip()
            else:
                print("  [ERROR] Git 命令错误: {}".format(
                    result.stderr.decode('utf-8', errors='ignore').strip()))
                return None
        except subprocess.TimeoutExpired:
            print("  [ERROR] Git 命令超时")
            return None
        except Exception as e:
            print(f"  [ERROR] 执行 Git 命令失败: {e}")
            return None

    def fetch_remote(self) -> bool:
        """从远程获取最新数据（不合并）"""
        print("  [INFO] 正在从远程仓库获取最新数据...")
        output = self._run_git(["fetch", "--all"], timeout=120)
        return output is not None

    def get_remote_url(self) -> Optional[str]:
        """获取远程仓库 URL"""
        return self._run_git(["remote", "get-url", "origin"])

    def get_branches(self) -> Dict[str, List[str]]:
        """获取分支信息"""
        output = self._run_git(["branch", "-a"])
        if not output:
            return {"local": [], "remote": []}

        local_branches = []
        remote_branches = []
        current_branch = None

        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("* "):
                current_branch = line[2:]
                local_branches.append(current_branch)
            elif line.startswith("remotes/"):
                if "-> " not in line:
                    remote_branches.append(line.replace("remotes/", ""))
            elif line:
                local_branches.append(line)

        return {
            "local": local_branches,
            "remote": remote_branches,
            "current": current_branch,
        }

    def get_commits(
        self,
        branch: str = "origin/main",
        limit: int = 300,
        since: Optional[str] = None,
        until: Optional[str] = None,
        author: Optional[str] = None,
    ) -> List[RemoteCommitInfo]:
        """
        获取 commit 历史

        Args:
            branch: 分支名称（使用 origin/ 前缀获取远程分支的 commit）
            limit: 最大数量
            since: 起始时间
            until: 结束时间
            author: 筛选作者
        """
        # 构建 git log 命令参数
        # 使用 %x00 (NULL) 作为字段分隔符，避免与 commit message 中的特殊字符冲突
        log_format = "%H%x00%h%x00%an%x00%ae%x00%aI%x00%s%x00%b%x00%P"
        args = [
            "log",
            branch,
            f"--pretty=format:{log_format}",
            f"-{limit}",
        ]

        if since:
            args.append(f"--since={since}")
        if until:
            args.append(f"--until={until}")
        if author:
            args.append(f"--author={author}")

        output = self._run_git(args)
        if not output:
            return []

        commits = []
        for line in output.split("\n"):
            if not line.strip():
                continue

            parts = line.split("\x00")
            if len(parts) < 6:
                continue

            sha = parts[0]
            short_sha = parts[1]
            author_name = parts[2]
            author_email = parts[3]
            date_str = parts[4]
            subject = parts[5]
            body = parts[6] if len(parts) > 6 else ""
            parent_str = parts[7] if len(parts) > 7 else ""

            # 解析时间
            try:
                dt = _parse_iso_datetime(date_str)
                timestamp = dt.timestamp() if dt else 0
            except (ValueError, TypeError):
                timestamp = 0

            # 解析 PR 编号和模块
            pr_number, module = _parse_commit_metadata(subject)

            # 解析父 commit
            parents = parent_str.split() if parent_str else []

            commits.append(RemoteCommitInfo(
                sha=sha,
                short_sha=short_sha,
                message=subject,
                full_message=f"{subject}\n\n{body}".strip() if body else subject,
                author_name=author_name,
                author_email=author_email,
                author_login="",  # 本地方式无法获取 GitHub login
                author_avatar_url="",
                committer_name=author_name,
                committer_email=author_email,
                commit_date=date_str,
                commit_timestamp=timestamp,
                pr_number=pr_number,
                module=module,
                html_url="",
                parents=parents,
            ))

        return commits


# ==================== 工具函数 ====================

def _parse_iso_datetime(date_str):
    """
    解析 ISO 8601 格式的日期字符串（兼容 Python 3.6+）

    支持格式：
      - 2026-03-04T10:38:00Z
      - 2026-03-04T10:38:00+08:00
      - 2026-03-04T10:38:00+0800
      - 2026-03-04 10:38:00
      - 2026-03-04T10:38:00
    """
    if not date_str:
        return None

    # 移除末尾的 Z
    clean = date_str.replace("Z", "").replace("+00:00", "")
    # 移除时区偏移（简化处理）
    import re as _re
    clean = _re.sub(r'[+-]\d{2}:\d{2}$', '', clean)
    clean = _re.sub(r'[+-]\d{4}$', '', clean)
    # 替换 T 为空格
    clean = clean.replace("T", " ").strip()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


def _to_iso_time(time_str):
    """将各种时间格式转换为 ISO 8601 格式"""
    if "T" in time_str and ("Z" in time_str or "+" in time_str):
        return time_str

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y%m%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue

    return time_str


def _parse_commit_metadata(message: str) -> Tuple[Optional[str], Optional[str]]:
    """
    从 commit 消息中解析 PR 编号和模块名称

    Returns:
        (pr_number, module)
    """
    # 提取 PR 号 (格式: (#123) 或 #123)
    pr_match = re.search(r"\(#(\d+)\)|\s#(\d+)", message)
    pr_number = None
    if pr_match:
        pr_number = pr_match.group(1) or pr_match.group(2)

    # 提取模块 (格式: [xxx /module/path] 或 feat(module):)
    module = None
    module_match = re.search(
        r"\[(?:fix|feat|refactor|docs|test|perf|add|impl|update|modify)?\s*/([^\]]+)\]",
        message,
        re.IGNORECASE,
    )
    if module_match:
        module = module_match.group(1).strip()
    else:
        module_match = re.search(
            r"(?:fix|feat|refactor|docs)\(([^)]+)\):", message, re.IGNORECASE
        )
        if module_match:
            module = module_match.group(1).strip()

    return pr_number, module


def _parse_api_commit(item: Dict) -> RemoteCommitInfo:
    """将 GitHub API 返回的 commit 数据解析为 RemoteCommitInfo"""
    commit_data = item.get("commit", {})
    author_data = item.get("author") or {}
    committer_data = commit_data.get("committer", {})
    author_info = commit_data.get("author", {})

    # 获取完整消息
    full_message = commit_data.get("message", "")
    # 第一行作为简短消息
    message = full_message.split("\n")[0]

    # 解析时间
    date_str = author_info.get("date", "")
    try:
        if date_str:
            dt = _parse_iso_datetime(date_str)
            timestamp = dt.timestamp() if dt else 0
        else:
            timestamp = 0
    except (ValueError, TypeError):
        timestamp = 0

    # 解析 PR 和模块
    pr_number, module = _parse_commit_metadata(message)

    # 父 commit
    parents = [p.get("sha", "") for p in item.get("parents", [])]

    # 统计信息（列表接口不包含，需要单独获取）
    stats = item.get("stats")

    return RemoteCommitInfo(
        sha=item.get("sha", ""),
        short_sha=item.get("sha", "")[:7],
        message=message,
        full_message=full_message,
        author_name=author_info.get("name", ""),
        author_email=author_info.get("email", ""),
        author_login=author_data.get("login", ""),
        author_avatar_url=author_data.get("avatar_url", ""),
        committer_name=committer_data.get("name", ""),
        committer_email=committer_data.get("email", ""),
        commit_date=date_str,
        commit_timestamp=timestamp,
        pr_number=pr_number,
        module=module,
        html_url=item.get("html_url", ""),
        parents=parents,
        stats=stats,
    )


# ==================== 输出格式化 ====================

def print_commits_table(commits: List[RemoteCommitInfo], show_url: bool = False):
    """以表格形式打印 commit 列表"""
    if not commits:
        print("  (无 commit 记录)")
        return

    print(f"\n  共 {len(commits)} 条 commit\n")

    # 统计含 PR 的 commit
    pr_count = sum(1 for c in commits if c.pr_number)
    print(f"  其中 {pr_count} 条包含 PR 编号\n")

    # 表头
    header = f"{'SHA':<10} {'PR':<8} {'提交时间':<22} {'作者':<20} {'模块':<25} 消息"
    print(f"  {header}")
    print(f"  {'-' * 120}")

    for c in commits:
        pr_str = f"#{c.pr_number}" if c.pr_number else "-"
        # 格式化时间
        if c.commit_date:
            try:
                dt = _parse_iso_datetime(c.commit_date)
                date_str = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else c.commit_date[:19]
            except (ValueError, TypeError):
                date_str = c.commit_date[:19]
        else:
            date_str = "-"

        author_str = c.author_name[:18] if c.author_name else "-"
        module_str = (c.module[:23] if c.module else "-")
        msg = c.message
        if len(msg) > 50:
            msg = msg[:47] + "..."

        line = f"  {c.short_sha:<10} {pr_str:<8} {date_str:<22} {author_str:<20} {module_str:<25} {msg}"
        print(line)

        if show_url and c.html_url:
            print(f"  {'':>10} 🔗 {c.html_url}")


def print_stats(commits: List[RemoteCommitInfo]):
    """打印统计信息"""
    if not commits:
        return

    print(f"\n{'=' * 80}")
    print("📊 统计信息")
    print(f"{'=' * 80}")

    # 按作者统计
    author_counts = {}
    for c in commits:
        name = c.author_name or c.author_login or "Unknown"
        author_counts[name] = author_counts.get(name, 0) + 1

    print("\n  按作者分布:")
    for author, count in sorted(author_counts.items(), key=lambda x: -x[1]):
        bar = "█" * min(count, 40)
        print(f"    {author:<25} {count:>4} 次提交  {bar}")

    # 按模块统计
    module_counts = {}
    for c in commits:
        if c.module:
            module_counts[c.module] = module_counts.get(c.module, 0) + 1

    if module_counts:
        print("\n  按模块分布:")
        for module, count in sorted(module_counts.items(), key=lambda x: -x[1]):
            bar = "█" * min(count, 40)
            print(f"    {module:<25} {count:>4} 次提交  {bar}")

    # 时间范围
    if commits:
        dates = [c.commit_timestamp for c in commits if c.commit_timestamp > 0]
        if dates:
            earliest = datetime.fromtimestamp(min(dates))
            latest = datetime.fromtimestamp(max(dates))
            print(f"\n  时间范围: {earliest.strftime('%Y-%m-%d')} ~ {latest.strftime('%Y-%m-%d')}")
            print(f"  总天数: {(latest - earliest).days} 天")


def save_commits(commits: List[RemoteCommitInfo], output_path: str, fmt: str = "json"):
    """保存 commit 数据到文件"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    data = [c.to_dict() for c in commits]

    if fmt == "jsonl":
        with open(output_path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n  ✅ 已保存 {len(commits)} 条 commit 到: {output_path}")


# ==================== 主程序 ====================

def main():
    parser = argparse.ArgumentParser(
        description="获取 EchoCraft GitHub 仓库的远程 commit 历史",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 通过 GitHub API 获取（默认）
  python fetch_remote_commits.py

  # 指定仓库
  python fetch_remote_commits.py --owner DongHande --repo EchoCraft

  # 获取更多历史
  python fetch_remote_commits.py --per-page 100 --pages 5

  # 按作者筛选
  python fetch_remote_commits.py --author aacedar

  # 按时间范围
  python fetch_remote_commits.py --since 2026-01-01 --until 2026-03-11

  # 从本地仓库获取（先 fetch 远程数据）
  python fetch_remote_commits.py --local /path/to/EchoCraft

  # 输出为 JSON
  python fetch_remote_commits.py --output result/remote_commits.json

  # 输出为 JSONL
  python fetch_remote_commits.py --output result/remote_commits.jsonl --format jsonl
        """,
    )

    # 仓库参数
    parser.add_argument("--owner", default="DongHande", help="GitHub 仓库所有者 (默认: DongHande)")
    parser.add_argument("--repo", default="EchoCraft", help="GitHub 仓库名称 (默认: EchoCraft)")
    parser.add_argument("--branch", default="main", help="分支名称 (默认: main)")

    # 筛选参数
    parser.add_argument("--since", help="起始时间 (如: 2026-01-01)")
    parser.add_argument("--until", help="结束时间 (如: 2026-03-11)")
    parser.add_argument("--author", help="按作者筛选 (GitHub 用户名或邮箱)")

    # 分页参数
    parser.add_argument("--per-page", type=int, default=100, help="每页数量 (默认: 100, 最大: 100)")
    parser.add_argument("--pages", type=int, default=3, help="获取页数 (默认: 3)")

    # 数据源
    parser.add_argument(
        "--local",
        help="使用本地 Git 仓库路径（而非 GitHub API）",
    )
    parser.add_argument("--limit", type=int, default=300, help="本地模式下获取的 commit 数量 (默认: 300)")

    # 认证
    parser.add_argument("--token", help="GitHub Personal Access Token (也可通过 GITHUB_TOKEN 环境变量设置)")

    # 输出
    parser.add_argument("--output", "-o", help="输出文件路径 (支持 .json 和 .jsonl)")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json", help="输出格式 (默认: json)")
    parser.add_argument("--show-url", action="store_true", help="在表格中显示 commit URL")
    parser.add_argument("--no-stats", action="store_true", help="不显示统计信息")
    parser.add_argument("--quiet", "-q", action="store_true", help="安静模式，只输出数据")

    args = parser.parse_args()

    # 自动推断输出格式
    if args.output and args.output.endswith(".jsonl"):
        args.format = "jsonl"

    commits = []

    if args.local:
        # ===== 本地 Git 方式 =====
        if not args.quiet:
            print(f"\n{'=' * 80}")
            print(f"📂 从本地仓库获取 commit 历史")
            print(f"   路径: {args.local}")
            print(f"{'=' * 80}")

        client = LocalGitClient(args.local)

        # 获取远程 URL
        remote_url = client.get_remote_url()
        if not args.quiet and remote_url:
            print(f"\n  远程仓库: {remote_url}")

        # 先 fetch 远程数据
        client.fetch_remote()

        # 获取分支信息
        if not args.quiet:
            branches = client.get_branches()
            print(f"  当前分支: {branches.get('current', 'N/A')}")
            if branches.get("remote"):
                print(f"  远程分支: {', '.join(branches['remote'][:10])}")

        # 获取 commits（使用 origin/ 前缀获取远程分支的 commit）
        remote_branch = f"origin/{args.branch}"
        print(f"\n  [INFO] 正在获取 {remote_branch} 的 commit 历史 (最多 {args.limit} 条)...")
        commits = client.get_commits(
            branch=remote_branch,
            limit=args.limit,
            since=args.since,
            until=args.until,
            author=args.author,
        )

    else:
        # ===== GitHub API 方式 =====
        if not args.quiet:
            print(f"\n{'=' * 80}")
            print(f"🌐 通过 GitHub API 获取 commit 历史")
            print(f"   仓库: {args.owner}/{args.repo}")
            print(f"   分支: {args.branch}")
            if args.since:
                print(f"   起始时间: {args.since}")
            if args.until:
                print(f"   结束时间: {args.until}")
            if args.author:
                print(f"   作者筛选: {args.author}")
            print(f"{'=' * 80}")

        client = GitHubAPIClient(token=args.token)

        # 检查速率限制
        if not args.quiet:
            try:
                rate = client.get_rate_limit()
                print(f"\n  API 速率限制: {rate.get('remaining', '?')}/{rate.get('limit', '?')}")
            except Exception:
                pass

        # 获取 commits
        print()
        commits = client.get_commits(
            owner=args.owner,
            repo=args.repo,
            branch=args.branch,
            per_page=args.per_page,
            pages=args.pages,
            since=args.since,
            until=args.until,
            author=args.author,
        )

    # ===== 输出结果 =====
    if not args.quiet:
        print(f"\n{'=' * 80}")
        print(f"📋 Commit 历史 ({len(commits)} 条)")
        print(f"{'=' * 80}")

        print_commits_table(commits, show_url=args.show_url)

        if not args.no_stats:
            print_stats(commits)

    # 保存到文件
    if args.output:
        save_commits(commits, args.output, args.format)

    if not args.quiet:
        print(f"\n{'=' * 80}")
        print(f"✅ 完成！共获取 {len(commits)} 条 commit")
        print(f"{'=' * 80}\n")

    return commits


if __name__ == "__main__":
    main()
