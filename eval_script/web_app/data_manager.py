#!/usr/bin/env python3
"""
数据仓库管理工具

功能：
1. 从 echocraft 系统获取 commit 版本数据
2. 本地管理 GitHub 仓库的克隆和版本切换
3. 构建还原轨迹对比数据
4. 支持批量处理和自动化评估

使用方式:
    python data_manager.py --help
    python data_manager.py list-users
    python data_manager.py list-snapshots --user-id <uuid>
    python data_manager.py setup-repo --github-url <url> --local-path <path>
    python data_manager.py compare --user-id <uuid> --request-id <id> --target-time <time>
"""

import os
import sys
import json
import argparse
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import difflib

# 添加父目录
sys.path.insert(0, str(Path(__file__).parent.parent / 'repo_verify'))
from restore import load_reposhot, load_changes, reposhot_refresh
from compare import load_actual_repo, compare_repos, compute_similarity


# ==================== 数据类 ====================

@dataclass
class UserInfo:
    """用户信息"""
    user_id: str
    name: str
    github_username: str
    snapshot_count: int
    date_range: Tuple[str, str]


@dataclass
class SnapshotInfo:
    """快照信息"""
    date: str
    user_id: str
    request_id: str
    timestamp: float
    file_count: int = 0


@dataclass
class CommitInfo:
    """Commit信息"""
    hash: str
    short_hash: str
    author_name: str
    author_email: str
    date: str
    message: str
    timestamp: float


@dataclass
class ComparisonResult:
    """对比结果"""
    snapshot_info: SnapshotInfo
    commit_info: Optional[CommitInfo]
    total_files: int
    matched_files: int
    identical_files: int
    different_files: int
    missing_files: int
    avg_similarity: float
    file_details: List[Dict]


# ==================== 配置 ====================

CONFIG = {
    'reposhot_base': '/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/repos',
    'changes_base': '/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/changes',
    'local_repos_base': '/ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_data',
    'echocraft_results': '/ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_script/result/echocraft_results.txt',
    'output_base': '/ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_script/web_app/output',
}

# 用户映射
USER_MAPPING = {
    '19802552-04bf-4173-acd4-bcbd25eaa9bd': ('杨永康', 'yangyongkang'),
    'e6e42a7f-a0ee-4e29-8f63-f3faefc54e24': ('chenhaokun', 'haokunchen'),
    '2e1fb58b-ffa3-487f-86a6-eb613f42bc65': ('Xwell', 'xwellxia'),
    '83902969-394d-442b-9b65-2c9ac41b60f1': ('刘峰', 'neolscarlet'),
    '3ad75b0f-ce21-41c1-8ed1-3c54b9c1c84b': ('aacedar', 'aacedar'),
}


# ==================== 核心功能 ====================

class DataManager:
    """数据仓库管理器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or CONFIG
        self._user_data = None
    
    # ---------- 用户和快照管理 ----------
    
    def load_echocraft_results(self) -> Dict[str, List[SnapshotInfo]]:
        """加载 echocraft_results.txt，返回用户->快照列表的映射"""
        if self._user_data is not None:
            return self._user_data
        
        self._user_data = {}
        results_file = self.config['echocraft_results']
        
        if not os.path.exists(results_file):
            print(f"[WARN] Results file not found: {results_file}")
            return self._user_data
        
        with open(results_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(('搜索', '匹配', '涉及', '=', '详细')):
                    continue
                
                parts = line.split('\t')
                if len(parts) >= 3:
                    date, user_id, request_id = parts[0], parts[1], parts[2]
                    if '.jsonl' in user_id:
                        continue
                    
                    if user_id not in self._user_data:
                        self._user_data[user_id] = []
                    
                    try:
                        dt = datetime.strptime(date, '%Y%m%d')
                        timestamp = dt.timestamp()
                    except ValueError:
                        timestamp = 0
                    
                    self._user_data[user_id].append(SnapshotInfo(
                        date=date,
                        user_id=user_id,
                        request_id=request_id,
                        timestamp=timestamp
                    ))
        
        # 按时间排序
        for user_id in self._user_data:
            self._user_data[user_id].sort(key=lambda x: x.timestamp)
        
        return self._user_data
    
    def list_users(self) -> List[UserInfo]:
        """列出所有用户"""
        user_data = self.load_echocraft_results()
        users = []
        
        for user_id, snapshots in user_data.items():
            name, github = USER_MAPPING.get(user_id, ('Unknown', ''))
            date_range = (
                snapshots[0].date if snapshots else '',
                snapshots[-1].date if snapshots else ''
            )
            users.append(UserInfo(
                user_id=user_id,
                name=name,
                github_username=github,
                snapshot_count=len(snapshots),
                date_range=date_range
            ))
        
        return users
    
    def list_snapshots(self, user_id: str) -> List[SnapshotInfo]:
        """列出指定用户的所有快照"""
        user_data = self.load_echocraft_results()
        return user_data.get(user_id, [])
    
    def find_nearest_snapshot(self, user_id: str, target_time: datetime) -> Optional[SnapshotInfo]:
        """查找最接近目标时间的快照"""
        snapshots = self.list_snapshots(user_id)
        target_ts = target_time.timestamp()
        
        nearest = None
        min_diff = float('inf')
        
        for snapshot in snapshots:
            if snapshot.timestamp <= target_ts:
                diff = target_ts - snapshot.timestamp
                if diff < min_diff:
                    min_diff = diff
                    nearest = snapshot
        
        return nearest
    
    # ---------- Git 仓库管理 ----------
    
    def get_repo_path(self, github_username: str) -> str:
        """获取本地仓库路径"""
        # 尝试用户特定的仓库
        user_repo = os.path.join(self.config['local_repos_base'], f'EchoCraft_{github_username}')
        if os.path.exists(user_repo):
            return user_repo
        
        # 回退到默认仓库
        default_repo = os.path.join(self.config['local_repos_base'], 'EchoCraft')
        return default_repo
    
    def clone_repo(self, github_url: str, local_path: str, branch: str = 'main') -> bool:
        """克隆 GitHub 仓库"""
        if os.path.exists(local_path):
            print(f"[INFO] Repository already exists at: {local_path}")
            return True
        
        print(f"[INFO] Cloning {github_url} to {local_path}...")
        try:
            result = subprocess.run(
                ['git', 'clone', '--branch', branch, github_url, local_path],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                print(f"[INFO] Clone successful")
                return True
            else:
                print(f"[ERROR] Clone failed: {result.stderr}")
                return False
        except Exception as e:
            print(f"[ERROR] Clone error: {e}")
            return False
    
    def get_commits(self, repo_path: str, limit: int = 500) -> List[CommitInfo]:
        """获取仓库的 commit 历史"""
        if not os.path.exists(repo_path):
            return []
        
        try:
            result = subprocess.run(
                ['git', 'log', '--pretty=format:%H|%h|%an|%ae|%ad|%s',
                 '--date=format:%Y-%m-%d %H:%M:%S', f'-{limit}'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                return []
            
            commits = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split('|', 5)
                if len(parts) >= 6:
                    commits.append(CommitInfo(
                        hash=parts[0],
                        short_hash=parts[1],
                        author_name=parts[2],
                        author_email=parts[3],
                        date=parts[4],
                        message=parts[5],
                        timestamp=datetime.strptime(parts[4], '%Y-%m-%d %H:%M:%S').timestamp()
                    ))
            
            return commits
        except Exception as e:
            print(f"[ERROR] Failed to get commits: {e}")
            return []
    
    def find_nearest_commit(self, commits: List[CommitInfo], target_time: datetime) -> Optional[CommitInfo]:
        """查找最接近目标时间的 commit"""
        target_ts = target_time.timestamp()
        nearest = None
        min_diff = float('inf')
        
        for commit in commits:
            if commit.timestamp <= target_ts:
                diff = target_ts - commit.timestamp
                if diff < min_diff:
                    min_diff = diff
                    nearest = commit
        
        return nearest
    
    def checkout_version(self, repo_path: str, commit_hash: str) -> bool:
        """切换到指定版本"""
        try:
            # 先 stash 当前修改
            subprocess.run(['git', 'stash'], cwd=repo_path, capture_output=True, timeout=30)
            
            # 切换版本
            result = subprocess.run(
                ['git', 'checkout', commit_hash],
                cwd=repo_path,
                capture_output=True,
                timeout=30
            )
            return result.returncode == 0
        except Exception as e:
            print(f"[ERROR] Checkout failed: {e}")
            return False
    
    def checkout_default_branch(self, repo_path: str) -> bool:
        """切换回默认分支"""
        try:
            # 尝试 main，失败则尝试 master
            result = subprocess.run(
                ['git', 'checkout', 'main'],
                cwd=repo_path,
                capture_output=True,
                timeout=30
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ['git', 'checkout', 'master'],
                    cwd=repo_path,
                    capture_output=True,
                    timeout=30
                )
            return result.returncode == 0
        except Exception as e:
            print(f"[ERROR] Checkout default branch failed: {e}")
            return False
    
    # ---------- 快照还原 ----------
    
    def restore_snapshot(self, snapshot: SnapshotInfo) -> Optional[Dict]:
        """还原指定的快照"""
        try:
            reposhot = load_reposhot(
                self.config['reposhot_base'],
                snapshot.date,
                snapshot.user_id,
                snapshot.request_id
            )
            
            if not reposhot or not reposhot.get('repo_infos'):
                return None
            
            diffs = load_changes(
                self.config['changes_base'],
                snapshot.date,
                snapshot.user_id,
                snapshot.request_id
            )
            
            if diffs:
                restored = reposhot_refresh(reposhot, diffs)
            else:
                restored = reposhot
            
            return restored
        except Exception as e:
            print(f"[ERROR] Restore failed: {e}")
            return None
    
    # ---------- 版本对比 ----------
    
    def compare_versions(
        self,
        restored_repo: Dict,
        actual_repo_path: str
    ) -> Dict:
        """对比还原的仓库和实际仓库"""
        try:
            actual_files = load_actual_repo(actual_repo_path)
            restored_infos = restored_repo.get('repo_infos', {})
            workspace_path = restored_repo.get('workspace_path', '')
            
            results = compare_repos(restored_infos, actual_files, workspace_path)
            return results
        except Exception as e:
            print(f"[ERROR] Comparison failed: {e}")
            return {'error': str(e)}
    
    def run_comparison(
        self,
        user_id: str,
        github_username: str,
        target_time: datetime
    ) -> Optional[ComparisonResult]:
        """执行完整的对比流程"""
        print(f"\n{'='*60}")
        print(f"Running comparison for user: {user_id}")
        print(f"Target time: {target_time}")
        print(f"{'='*60}")
        
        # 1. 查找最近的快照
        snapshot = self.find_nearest_snapshot(user_id, target_time)
        if not snapshot:
            print("[ERROR] No snapshot found before target time")
            return None
        print(f"[INFO] Found snapshot: {snapshot.date} / {snapshot.request_id[:12]}...")
        
        # 2. 还原快照
        restored = self.restore_snapshot(snapshot)
        if not restored:
            print("[ERROR] Failed to restore snapshot")
            return None
        snapshot.file_count = len(restored.get('repo_infos', {}))
        print(f"[INFO] Restored {snapshot.file_count} files")
        
        # 3. 获取本地仓库路径
        repo_path = self.get_repo_path(github_username)
        if not os.path.exists(repo_path):
            print(f"[ERROR] Repository not found: {repo_path}")
            return None
        print(f"[INFO] Using repository: {repo_path}")
        
        # 4. 获取 commits 并查找最近的
        commits = self.get_commits(repo_path)
        commit = self.find_nearest_commit(commits, target_time)
        if commit:
            print(f"[INFO] Found commit: {commit.short_hash} ({commit.date})")
        else:
            print("[WARN] No commit found before target time")
        
        # 5. 切换到目标版本并对比
        comparison_results = None
        if commit:
            if self.checkout_version(repo_path, commit.hash):
                comparison_results = self.compare_versions(restored, repo_path)
                self.checkout_default_branch(repo_path)
            else:
                print("[WARN] Failed to checkout target version, comparing with current HEAD")
                comparison_results = self.compare_versions(restored, repo_path)
        else:
            comparison_results = self.compare_versions(restored, repo_path)
        
        if not comparison_results or 'error' in comparison_results:
            print(f"[ERROR] Comparison failed: {comparison_results.get('error', 'Unknown error')}")
            return None
        
        # 6. 构建结果
        result = ComparisonResult(
            snapshot_info=snapshot,
            commit_info=commit,
            total_files=comparison_results.get('total_restored_files', 0),
            matched_files=comparison_results.get('matched_files', 0),
            identical_files=comparison_results.get('identical_files', 0),
            different_files=comparison_results.get('different_files', 0),
            missing_files=comparison_results.get('missing_in_actual', 0),
            avg_similarity=comparison_results.get('avg_similarity', 0),
            file_details=comparison_results.get('file_details', [])
        )
        
        print(f"\n{'='*60}")
        print("Comparison Results:")
        print(f"  Total files:     {result.total_files}")
        print(f"  Matched files:   {result.matched_files}")
        print(f"  Identical:       {result.identical_files}")
        print(f"  Different:       {result.different_files}")
        print(f"  Missing:         {result.missing_files}")
        print(f"  Avg similarity:  {result.avg_similarity:.4f}")
        print(f"{'='*60}\n")
        
        return result
    
    # ---------- 批量处理 ----------
    
    def batch_compare(
        self,
        user_id: str,
        github_username: str,
        time_points: List[datetime]
    ) -> List[ComparisonResult]:
        """批量对比多个时间点"""
        results = []
        for target_time in time_points:
            result = self.run_comparison(user_id, github_username, target_time)
            if result:
                results.append(result)
        return results
    
    def export_results(self, results: List[ComparisonResult], output_path: str):
        """导出对比结果到 JSON 文件"""
        data = []
        for r in results:
            data.append({
                'snapshot': asdict(r.snapshot_info),
                'commit': asdict(r.commit_info) if r.commit_info else None,
                'stats': {
                    'total_files': r.total_files,
                    'matched_files': r.matched_files,
                    'identical_files': r.identical_files,
                    'different_files': r.different_files,
                    'missing_files': r.missing_files,
                    'avg_similarity': r.avg_similarity,
                },
                'file_details': r.file_details
            })
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[INFO] Results exported to: {output_path}")


# ==================== 命令行接口 ====================

def cmd_list_users(args, manager: DataManager):
    """列出所有用户"""
    users = manager.list_users()
    
    print(f"\n{'='*80}")
    print(f"Found {len(users)} users")
    print(f"{'='*80}\n")
    
    print(f"{'User ID':<40} {'Name':<15} {'GitHub':<15} {'Snapshots':<10} {'Date Range'}")
    print("-" * 100)
    
    for user in users:
        print(f"{user.user_id:<40} {user.name:<15} {user.github_username:<15} {user.snapshot_count:<10} {user.date_range[0]}-{user.date_range[1]}")


def cmd_list_snapshots(args, manager: DataManager):
    """列出指定用户的快照"""
    snapshots = manager.list_snapshots(args.user_id)
    
    print(f"\n{'='*80}")
    print(f"User: {args.user_id}")
    print(f"Found {len(snapshots)} snapshots")
    print(f"{'='*80}\n")
    
    print(f"{'Date':<12} {'Request ID':<36} {'Timestamp'}")
    print("-" * 70)
    
    for s in snapshots[:50]:  # 最多显示50条
        print(f"{s.date:<12} {s.request_id:<36} {datetime.fromtimestamp(s.timestamp)}")
    
    if len(snapshots) > 50:
        print(f"... and {len(snapshots) - 50} more")


def cmd_setup_repo(args, manager: DataManager):
    """设置本地仓库"""
    success = manager.clone_repo(args.github_url, args.local_path, args.branch)
    if success:
        print(f"[SUCCESS] Repository ready at: {args.local_path}")
    else:
        print(f"[FAILED] Could not setup repository")
        sys.exit(1)


def cmd_compare(args, manager: DataManager):
    """执行单次对比"""
    try:
        target_time = datetime.strptime(args.target_time, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        print(f"[ERROR] Invalid time format. Use: YYYY-MM-DD HH:MM:SS")
        sys.exit(1)
    
    result = manager.run_comparison(args.user_id, args.github_username, target_time)
    
    if result and args.output:
        manager.export_results([result], args.output)


def cmd_batch_compare(args, manager: DataManager):
    """批量对比"""
    # 从文件读取时间点
    time_points = []
    with open(args.times_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    time_points.append(datetime.strptime(line, '%Y-%m-%d %H:%M:%S'))
                except ValueError:
                    print(f"[WARN] Invalid time format: {line}")
    
    if not time_points:
        print("[ERROR] No valid time points found")
        sys.exit(1)
    
    results = manager.batch_compare(args.user_id, args.github_username, time_points)
    
    if results and args.output:
        manager.export_results(results, args.output)


def main():
    parser = argparse.ArgumentParser(
        description='数据仓库管理工具 - 用于 Repo Reconstruction Evaluation V2',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # list-users
    sub_list_users = subparsers.add_parser('list-users', help='列出所有用户')
    
    # list-snapshots
    sub_list_snapshots = subparsers.add_parser('list-snapshots', help='列出指定用户的快照')
    sub_list_snapshots.add_argument('--user-id', required=True, help='用户 UUID')
    
    # setup-repo
    sub_setup = subparsers.add_parser('setup-repo', help='设置本地仓库')
    sub_setup.add_argument('--github-url', required=True, help='GitHub 仓库 URL')
    sub_setup.add_argument('--local-path', required=True, help='本地存储路径')
    sub_setup.add_argument('--branch', default='main', help='分支名称 (默认: main)')
    
    # compare
    sub_compare = subparsers.add_parser('compare', help='执行单次版本对比')
    sub_compare.add_argument('--user-id', required=True, help='用户 UUID')
    sub_compare.add_argument('--github-username', required=True, help='GitHub 用户名')
    sub_compare.add_argument('--target-time', required=True, help='目标时间 (YYYY-MM-DD HH:MM:SS)')
    sub_compare.add_argument('--output', help='输出文件路径 (JSON)')
    
    # batch-compare
    sub_batch = subparsers.add_parser('batch-compare', help='批量版本对比')
    sub_batch.add_argument('--user-id', required=True, help='用户 UUID')
    sub_batch.add_argument('--github-username', required=True, help='GitHub 用户名')
    sub_batch.add_argument('--times-file', required=True, help='时间点列表文件 (每行一个时间)')
    sub_batch.add_argument('--output', required=True, help='输出文件路径 (JSON)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    manager = DataManager()
    
    if args.command == 'list-users':
        cmd_list_users(args, manager)
    elif args.command == 'list-snapshots':
        cmd_list_snapshots(args, manager)
    elif args.command == 'setup-repo':
        cmd_setup_repo(args, manager)
    elif args.command == 'compare':
        cmd_compare(args, manager)
    elif args.command == 'batch-compare':
        cmd_batch_compare(args, manager)


if __name__ == '__main__':
    main()
