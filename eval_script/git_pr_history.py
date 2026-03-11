#!/usr/bin/env python3
"""
查看 Git 仓库的 PR 历史和分支信息

使用方法:
    python git_pr_history.py [repo_path] [limit] [--author=提交者名称]
    
示例:
    python git_pr_history.py /ai_train/bingodong/dhs/EchoCraft
    python git_pr_history.py /ai_train/bingodong/dhs/EchoCraft 50
    python git_pr_history.py /ai_train/bingodong/dhs/EchoCraft 100 --author=杨永康
    python git_pr_history.py /ai_train/bingodong/dhs/EchoCraft --author=lance
    python git_pr_history.py --list-authors  # 列出所有提交者
"""

import subprocess
import re
import sys
import os
import argparse
from typing import List, Dict, Optional


class CommitInfo:
    """提交信息"""
    def __init__(self, hash: str = '', message: str = '', pr_number: Optional[str] = None,
                 module: Optional[str] = None, author_name: Optional[str] = None,
                 author_email: Optional[str] = None, commit_date: Optional[str] = None):
        self.hash = hash
        self.message = message
        self.pr_number = pr_number
        self.module = module
        self.author_name = author_name
        self.author_email = author_email
        self.commit_date = commit_date


def run_git_command(repo_path: str, args: List[str]) -> Optional[str]:
    """执行 git 命令并返回输出"""
    try:
        result = subprocess.run(
            ['git'] + args,
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout.decode('utf-8', errors='ignore').strip()
        else:
            print(f"Git 命令错误: {result.stderr.decode('utf-8', errors='ignore')}")
            return None
    except subprocess.TimeoutExpired:
        print("Git 命令超时")
        return None
    except Exception as e:
        print(f"执行 Git 命令失败: {e}")
        return None


def get_remote_info(repo_path: str) -> Dict[str, str]:
    """获取远程仓库信息"""
    output = run_git_command(repo_path, ['remote', '-v'])
    if not output:
        return {}
    
    remotes = {}
    for line in output.split('\n'):
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            url = parts[1]
            if name not in remotes:
                remotes[name] = url
    return remotes


def get_branches(repo_path: str) -> Dict[str, List[str]]:
    """获取分支信息"""
    output = run_git_command(repo_path, ['branch', '-a'])
    if not output:
        return {'local': [], 'remote': []}
    
    local_branches = []
    remote_branches = []
    current_branch = None
    
    for line in output.split('\n'):
        line = line.strip()
        if line.startswith('* '):
            current_branch = line[2:]
            local_branches.append(current_branch)
        elif line.startswith('remotes/'):
            # 跳过 HEAD 引用
            if '-> ' not in line:
                remote_branches.append(line.replace('remotes/', ''))
        elif line:
            local_branches.append(line)
    
    return {
        'local': local_branches,
        'remote': remote_branches,
        'current': current_branch
    }


def parse_commit_message(message: str) -> CommitInfo:
    """解析提交信息，提取 PR 号和模块"""
    # 提取 PR 号 (格式: #123 或 (#123))
    pr_match = re.search(r'\(#(\d+)\)|\s#(\d+)', message)
    pr_number = None
    if pr_match:
        pr_number = pr_match.group(1) or pr_match.group(2)
    
    # 提取模块 (格式: [xxx /module/path] 或 feat(module):)
    module = None
    module_match = re.search(r'\[(?:fix|feat|refactor|docs)?\s*/([^\]]+)\]', message, re.IGNORECASE)
    if module_match:
        module = module_match.group(1).strip()
    else:
        module_match = re.search(r'(?:fix|feat|refactor|docs)\(([^)]+)\):', message, re.IGNORECASE)
        if module_match:
            module = module_match.group(1).strip()
    
    return CommitInfo(
        hash='',
        message=message,
        pr_number=pr_number,
        module=module
    )


def get_commit_history(repo_path: str, limit: int = 50) -> List[CommitInfo]:
    """获取提交历史，包含作者和时间"""
    # 使用自定义格式获取更多信息
    # 格式: hash|author_name|author_email|date|message
    output = run_git_command(repo_path, [
        'log', 
        '--pretty=format:%h|%an|%ae|%ad|%s',
        '--date=format:%Y-%m-%d %H:%M',
        f'-{limit}'
    ])
    if not output:
        return []
    
    commits = []
    for line in output.split('\n'):
        if not line.strip():
            continue
        
        # 格式: hash|author_name|author_email|date|message
        parts = line.split('|', 4)
        if len(parts) >= 5:
            commit_hash = parts[0]
            author_name = parts[1]
            author_email = parts[2]
            commit_date = parts[3]
            message = parts[4]
            
            commit_info = parse_commit_message(message)
            commit_info.hash = commit_hash
            commit_info.author_name = author_name
            commit_info.author_email = author_email
            commit_info.commit_date = commit_date
            commits.append(commit_info)
        elif len(parts) >= 2:
            # 回退到简单格式
            commit_hash = parts[0]
            message = parts[1] if len(parts) > 1 else ""
            commit_info = parse_commit_message(message)
            commit_info.hash = commit_hash
            commits.append(commit_info)
    
    return commits


def get_github_url(remote_url: str) -> Optional[str]:
    """从远程 URL 提取 GitHub 仓库地址"""
    # 处理 SSH 格式: git@github.com:user/repo.git
    ssh_match = re.match(r'git@github\.com:(.+?)(?:\.git)?$', remote_url)
    if ssh_match:
        return f"https://github.com/{ssh_match.group(1)}"
    
    # 处理 HTTPS 格式: https://github.com/user/repo.git
    https_match = re.match(r'https://github\.com/(.+?)(?:\.git)?$', remote_url)
    if https_match:
        return f"https://github.com/{https_match.group(1)}"
    
    return None


def print_report(repo_path: str, limit: int = 50, output_file: Optional[str] = None, 
                 author_filter: Optional[str] = None, list_authors: bool = False):
    """生成并打印报告
    
    Args:
        repo_path: Git 仓库路径
        limit: 获取的提交数量上限
        output_file: 输出文件路径
        author_filter: 按提交者筛选（支持部分匹配）
        list_authors: 是否只列出提交者
    """
    lines = []
    
    def log(text: str = ""):
        lines.append(text)
        print(text)
    
    # 先获取提交历史
    all_commits = get_commit_history(repo_path, limit)
    
    # 如果只需要列出提交者
    if list_authors:
        log("=" * 60)
        log(f"Git 仓库提交者列表: {repo_path}")
        log("=" * 60)
        
        author_counts = {}
        for c in all_commits:
            if c.author_name:
                if c.author_name not in author_counts:
                    author_counts[c.author_name] = {'count': 0, 'email': c.author_email}
                author_counts[c.author_name]['count'] += 1
        
        log(f"\n共 {len(author_counts)} 位提交者 (最近 {limit} 条提交):\n")
        log(f"{'序号':<6} {'提交者':<25} {'提交次数':<10} 邮箱")
        log("-" * 80)
        
        for idx, (author, info) in enumerate(sorted(author_counts.items(), key=lambda x: -x[1]['count']), 1):
            email = info['email'] or '-'
            log(f"{idx:<6} {author:<25} {info['count']:<10} {email}")
        
        log("\n" + "=" * 60)
        log("\n提示: 使用 --author=提交者名称 查看特定提交者的提交记录")
        log("      例如: python git_pr_history.py /path/to/repo --author=杨永康")
        return
    
    # 按提交者筛选
    if author_filter:
        commits = [c for c in all_commits if c.author_name and author_filter.lower() in c.author_name.lower()]
        filter_desc = f" (筛选: {author_filter})"
    else:
        commits = all_commits
        filter_desc = ""
    
    log("=" * 100)
    log(f"Git 仓库分析报告: {repo_path}{filter_desc}")
    log("=" * 100)
    
    # 远程仓库信息（仅在非筛选模式下显示）
    if not author_filter:
        log("\n## 远程仓库")
        remotes = get_remote_info(repo_path)
        if remotes:
            for name, url in remotes.items():
                log(f"  {name}: {url}")
                github_url = get_github_url(url)
                if github_url:
                    log(f"       GitHub PR 页面: {github_url}/pulls")
        else:
            log("  (未配置远程仓库)")
        
        # 分支信息
        log("\n## 分支信息")
        branches = get_branches(repo_path)
        if branches.get('current'):
            log(f"  当前分支: {branches['current']}")
        if branches.get('local'):
            log(f"  本地分支: {', '.join(branches['local'])}")
        if branches.get('remote'):
            log(f"  远程分支:")
            for branch in branches['remote']:
                log(f"    - {branch}")
    
    # 提交历史
    if author_filter:
        log(f"\n## 提交者 '{author_filter}' 的提交历史")
    else:
        log(f"\n## 最近 {limit} 条提交历史 (含 PR 信息)")
    log("-" * 70)
    
    if not commits:
        if author_filter:
            log(f"  (未找到提交者 '{author_filter}' 的提交记录)")
            log(f"  提示: 使用 --list-authors 查看所有提交者")
        else:
            log("  (无提交历史)")
    else:
        # 统计 PR
        pr_commits = [c for c in commits if c.pr_number]
        log(f"  共 {len(commits)} 条提交，其中 {len(pr_commits)} 条包含 PR 编号\n")
        
        # 打印表格
        log(f"{'Hash':<10} {'PR':<8} {'提交时间':<18} {'提交者':<20} 提交信息")
        log("-" * 100)
        
        for commit in commits:
            pr_str = f"#{commit.pr_number}" if commit.pr_number else "-"
            date_str = commit.commit_date or "-"
            author_str = commit.author_name[:18] + ".." if commit.author_name and len(commit.author_name) > 20 else (commit.author_name or "-")
            # 截断过长的消息
            msg = commit.message
            if len(msg) > 40:
                msg = msg[:37] + "..."
            log(f"{commit.hash:<10} {pr_str:<8} {date_str:<18} {author_str:<20} {msg}")
    
    # PR 统计
    if commits:
        log("\n## PR 统计")
        log("-" * 100)
        
        # 按提交者统计
        author_counts = {}
        for c in commits:
            if c.author_name:
                author_counts[c.author_name] = author_counts.get(c.author_name, 0) + 1
        
        if author_counts:
            log("\n按提交者分布:")
            for author, count in sorted(author_counts.items(), key=lambda x: -x[1]):
                log(f"  {author}: {count} 次提交")
        
        # 按模块统计
        module_counts = {}
        for c in commits:
            if c.module:
                module_counts[c.module] = module_counts.get(c.module, 0) + 1
        
        if module_counts:
            log("\n按模块分布:")
            for module, count in sorted(module_counts.items(), key=lambda x: -x[1]):
                log(f"  {module}: {count} 次提交")
    
    log("\n" + "=" * 100)
    
    # 保存到文件
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"\n报告已保存到: {output_file}")


def main():
    # 使用 argparse 解析参数
    parser = argparse.ArgumentParser(
        description='查看 Git 仓库的 PR 历史和分支信息',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python git_pr_history.py /path/to/repo                    # 查看仓库历史
  python git_pr_history.py /path/to/repo 100                # 查看最近100条
  python git_pr_history.py /path/to/repo --author=杨永康     # 筛选特定提交者
  python git_pr_history.py /path/to/repo --list-authors     # 列出所有提交者
        '''
    )
    parser.add_argument('repo_path', nargs='?', default=os.getcwd(),
                        help='Git 仓库路径 (默认: 当前目录)')
    parser.add_argument('limit', nargs='?', type=int, default=50,
                        help='获取的提交数量 (默认: 50)')
    parser.add_argument('--author', '-a', dest='author_filter',
                        help='按提交者筛选（支持部分匹配，如 "杨永康" 或 "lance"）')
    parser.add_argument('--list-authors', '-l', action='store_true',
                        help='列出所有提交者')
    
    args = parser.parse_args()
    
    repo_path = args.repo_path
    limit = args.limit
    author_filter = args.author_filter
    list_authors = args.list_authors
    
    # 验证路径
    if not os.path.isdir(repo_path):
        print(f"错误: 路径不存在: {repo_path}")
        sys.exit(1)
    
    git_dir = os.path.join(repo_path, '.git')
    if not os.path.isdir(git_dir):
        print(f"错误: {repo_path} 不是一个 Git 仓库")
        sys.exit(1)
    
    # 输出文件
    if author_filter:
        output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                   f'git_pr_history_{author_filter}.txt')
    else:
        output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                   'git_pr_history_report.txt')
    
    print_report(repo_path, limit, output_file, author_filter, list_authors)


if __name__ == '__main__':
    main()
