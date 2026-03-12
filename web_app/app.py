#!/usr/bin/env python3
"""
第二代评估和可视化框架 - Flask后端服务

功能：
1. 提供Web API接口
2. 根据用户输入查询echocraft数据
3. 获取Git仓库的commit历史
4. 进行版本对比和相似度计算
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

# 添加父目录到路径以导入现有模块
sys.path.insert(0, str(Path(__file__).parent.parent / 'repo_verify'))
from restore import load_reposhot, load_changes, reposhot_refresh
from compare import load_actual_repo, compare_repos, compute_similarity, _detect_prefix, _strip_prefix

app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
CORS(app)

# ==================== 配置 ====================
CONFIG = {
    'reposhot_base': '/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/repos',
    'changes_base': '/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/changes',
    'github_repos_base': '/ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_data',
    'echocraft_results': '/ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_script/result/echocraft_results.txt',
}

# 用户ID到GitHub用户名的映射
USER_MAPPING = {
    '19802552-04bf-4173-acd4-bcbd25eaa9bd': {'name': '杨永康', 'github': 'yangyongkang'},
    'e6e42a7f-a0ee-4e29-8f63-f3faefc54e24': {'name': 'chenhaokun', 'github': 'haokunchen'},
    '2e1fb58b-ffa3-487f-86a6-eb613f42bc65': {'name': 'Xwell', 'github': 'xwellxia'},
    '83902969-394d-442b-9b65-2c9ac41b60f1': {'name': '刘峰', 'github': 'neolscarlet'},
    '3ad75b0f-ce21-41c1-8ed1-3c54b9c1c84b': {'name': 'aacedar', 'github': 'aacedar'},
}


# ==================== 工具函数 ====================

def get_changes_timestamp(changes_base: str, date: str, user_id: str, request_id: str) -> Optional[float]:
    """
    从 changes 目录中读取 request_id 对应的精确时间戳（秒级）。
    
    读取 changes/{date}/{user_id}/{request_id}/ 目录下最后一个 jsonl 文件的
    最后一条记录的 timestamp 字段（毫秒级），转换为秒级返回。
    这代表该 request_id 最后一次变更操作的时间。
    
    Returns:
        精确的秒级时间戳，如果无法读取则返回 None
    """
    changes_dir = os.path.join(changes_base, date, user_id, request_id)
    if not os.path.isdir(changes_dir):
        return None
    
    # 找到目录下所有 .jsonl 文件并排序（文件名格式如 20260204-152527.jsonl）
    jsonl_files = sorted([
        f for f in os.listdir(changes_dir) if f.endswith('.jsonl')
    ])
    if not jsonl_files:
        return None
    
    # 取最后一个文件的最后一行
    last_file = os.path.join(changes_dir, jsonl_files[-1])
    try:
        # 使用 tail -1 高效获取最后一行（避免手动 seek 大文件）
        # 兼容 Python 3.6: 使用 stdout/stderr=PIPE 替代 capture_output
        result = subprocess.run(
            ['tail', '-1', last_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10
        )
        last_line = result.stdout.decode('utf-8').strip() if result.returncode == 0 else None
        
        if not last_line:
            return None
        
        data = json.loads(last_line)
        ts_ms = data.get('timestamp')
        if ts_ms is not None:
            # changes 中的时间戳是毫秒级，转换为秒级
            return float(ts_ms) / 1000.0
    except (json.JSONDecodeError, IOError, ValueError, KeyError) as e:
        print(f"[WARN] Failed to read timestamp from {last_file}: {e}")
    
    return None


def parse_echocraft_results(results_file: str) -> Dict[str, List[Dict]]:
    """
    解析 echocraft_results.txt 文件，返回按用户分组的数据。
    
    对于每个 request_id，会尝试从 changes 目录读取精确的毫秒级时间戳，
    以区分同一天内多个 request_id 的先后顺序。
    如果无法读取精确时间戳，则降级为日期级别的时间戳。
    """
    user_data = {}
    
    if not os.path.exists(results_file):
        return user_data
    
    changes_base = CONFIG['changes_base']
    
    with open(results_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('搜索') or line.startswith('匹配') or line.startswith('涉及') or line.startswith('=') or line.startswith('详细'):
                continue
            
            parts = line.split('\t')
            if len(parts) >= 3:
                date, user_id, request_id = parts[0], parts[1], parts[2]
                # 跳过异常格式（带.jsonl后缀的user_id）
                if '.jsonl' in user_id:
                    continue
                    
                if user_id not in user_data:
                    user_data[user_id] = []
                
                # 尝试从 changes 目录获取精确时间戳
                precise_ts = get_changes_timestamp(changes_base, date, user_id, request_id)
                
                if precise_ts is not None:
                    timestamp = precise_ts
                    # 将精确时间戳转换为可读的日期时间字符串
                    precise_dt = datetime.fromtimestamp(precise_ts)
                    precise_time_str = precise_dt.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # 降级：使用日期级别时间戳
                    try:
                        dt = datetime.strptime(date, '%Y%m%d')
                        timestamp = dt.timestamp()
                    except ValueError:
                        timestamp = 0
                    precise_time_str = None
                    
                user_data[user_id].append({
                    'date': date,
                    'request_id': request_id,
                    'timestamp': timestamp,
                    'precise_time': precise_time_str,
                })
    
    # 按精确时间戳排序每个用户的数据
    for user_id in user_data:
        user_data[user_id].sort(key=lambda x: x['timestamp'])
    
    return user_data


def get_git_commits(repo_path: str, limit: int = 100) -> List[Dict]:
    """获取Git仓库的commit历史"""
    if not os.path.exists(repo_path):
        return []
    
    try:
        result = subprocess.run(
            ['git', 'log', '--pretty=format:%H|%h|%an|%ae|%ad|%s', 
             '--date=format:%Y-%m-%d %H:%M:%S', f'-{limit}'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return []
        
        commits = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('|', 5)
            if len(parts) >= 6:
                commits.append({
                    'hash': parts[0],
                    'short_hash': parts[1],
                    'author_name': parts[2],
                    'author_email': parts[3],
                    'date': parts[4],
                    'message': parts[5],
                    'timestamp': datetime.strptime(parts[4], '%Y-%m-%d %H:%M:%S').timestamp()
                })
        
        return commits
    except Exception as e:
        print(f"Error getting git commits: {e}")
        return []


def find_nearest_commit(commits: List[Dict], target_time: datetime) -> Optional[Dict]:
    """查找最接近目标时间且在目标时间之前的commit"""
    target_ts = target_time.timestamp()
    nearest = None
    min_diff = float('inf')
    
    for commit in commits:
        if commit['timestamp'] <= target_ts:
            diff = target_ts - commit['timestamp']
            if diff < min_diff:
                min_diff = diff
                nearest = commit
    
    return nearest


def find_nearest_snapshot(user_data: List[Dict], target_time: datetime) -> Optional[Dict]:
    """
    查找最接近目标时间且在目标时间之前的快照。
    
    利用 parse_echocraft_results() 中从 changes 目录读取的精确毫秒级时间戳，
    可以准确区分同一天内多个 request_id 的先后顺序。
    
    Args:
        user_data: 该用户的快照列表（已按 timestamp 排序）
        target_time: 目标时间
    
    Returns:
        最接近目标时间且在目标时间之前的快照，如果没有则返回 None
    """
    target_ts = target_time.timestamp()
    nearest = None
    min_diff = float('inf')
    
    for snapshot in user_data:
        if snapshot['timestamp'] <= target_ts:
            diff = target_ts - snapshot['timestamp']
            if diff < min_diff:
                min_diff = diff
                nearest = snapshot
    
    return nearest


def checkout_git_version(repo_path: str, commit_hash: str) -> bool:
    """切换Git仓库到指定版本"""
    try:
        # 先stash当前修改
        subprocess.run(['git', 'stash'], cwd=repo_path, capture_output=True, timeout=30)
        # 切换到目标commit
        result = subprocess.run(
            ['git', 'checkout', commit_hash],
            cwd=repo_path,
            capture_output=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Error checking out version: {e}")
        return False


def restore_snapshot(date: str, user_id: str, request_id: str) -> Tuple[Optional[Dict], Optional[Dict], List[Dict]]:
    """
    还原指定的快照，并返回原始快照和变更序列
    
    Returns:
        Tuple[Optional[Dict], Optional[Dict], List[Dict]]: (还原后的仓库, 原始快照, 变更序列)
    """
    try:
        reposhot = load_reposhot(CONFIG['reposhot_base'], date, user_id, request_id)
        if not reposhot or not reposhot.get('repo_infos'):
            return None, None, []
        
        diffs = load_changes(CONFIG['changes_base'], date, user_id, request_id)
        if diffs:
            restored = reposhot_refresh(reposhot, diffs)
        else:
            restored = reposhot
        
        return restored, reposhot, diffs
    except Exception as e:
        print(f"Error restoring snapshot: {e}")
        return None, None, []


def extract_request_changes(diffs: List[Dict]) -> List[Dict]:
    """
    从变更序列中提取文件级的变更摘要，用于前端展示
    
    Args:
        diffs: load_changes 返回的变更序列
        
    Returns:
        List[Dict]: 文件变更列表，每项包含 file_path, op_type, diff, timestamp
    """
    file_changes = []
    for diff_item in diffs:
        timestamp = diff_item.get('timestamp', 0)
        results = diff_item.get('results', [])
        for result in results:
            file_changes.append({
                'file_path': result.get('file_path', ''),
                'op_type': result.get('op_type', 'unknown'),
                'diff': result.get('diff', ''),
                'timestamp': timestamp,
            })
    return file_changes


def compare_versions(restored_repo: Dict, actual_repo_path: str) -> Dict:
    """
    对比两个版本的仓库，同时缓存文件内容以供前端 diff 展示。
    
    返回的 file_details 中每个条目增加：
      - restored_content: 还原版本的文件内容
      - actual_content: 真实仓库的文件内容
    """
    try:
        actual_files = load_actual_repo(actual_repo_path)
        restored_infos = restored_repo.get('repo_infos', {})
        workspace_path = restored_repo.get('workspace_path', '')
        
        results = compare_repos(restored_infos, actual_files, workspace_path)
        
        # 为每个文件补充内容，用于前端 diff 展示
        prefix = _detect_prefix(restored_infos.keys(), actual_files.keys(), workspace_path)
        restored_rel_map = {}
        for path, content in restored_infos.items():
            rel_path = _strip_prefix(path, prefix)
            restored_rel_map[rel_path] = content
        
        for detail in results.get('file_details', []):
            rel_path = detail.get('rel_path', '')
            detail['restored_content'] = restored_rel_map.get(rel_path, '')
            detail['actual_content'] = actual_files.get(rel_path, '')
        
        return results
    except Exception as e:
        print(f"Error comparing versions: {e}")
        return {'error': str(e)}


def compare_original_with_actual(original_reposhot: Dict, actual_repo_path: str) -> Dict:
    """
    对比原始快照（还原前）与真实仓库，同时缓存文件内容以供前端 diff 展示。
    
    返回的 file_details 中每个条目增加：
      - restored_content: 原始快照的文件内容（字段名保持一致以复用前端逻辑）
      - actual_content: 真实仓库的文件内容
    """
    try:
        actual_files = load_actual_repo(actual_repo_path)
        original_infos = original_reposhot.get('repo_infos', {})
        workspace_path = original_reposhot.get('workspace_path', '')
        
        results = compare_repos(original_infos, actual_files, workspace_path)
        
        # 为每个文件补充内容，用于前端 diff 展示
        prefix = _detect_prefix(original_infos.keys(), actual_files.keys(), workspace_path)
        original_rel_map = {}
        for path, content in original_infos.items():
            rel_path = _strip_prefix(path, prefix)
            original_rel_map[rel_path] = content
        
        for detail in results.get('file_details', []):
            rel_path = detail.get('rel_path', '')
            # 字段名用 restored_content 以复用前端逻辑
            detail['restored_content'] = original_rel_map.get(rel_path, '')
            detail['actual_content'] = actual_files.get(rel_path, '')
        
        return results
    except Exception as e:
        print(f"Error comparing original with actual: {e}")
        return {'error': str(e)}


# ==================== API路由 ====================

@app.route('/')
def index():
    """渲染主页"""
    return render_template('index.html')


@app.route('/api/users', methods=['GET'])
def get_users():
    """获取所有用户列表"""
    user_data = parse_echocraft_results(CONFIG['echocraft_results'])
    users = []
    
    for user_id, snapshots in user_data.items():
        user_info = USER_MAPPING.get(user_id, {'name': 'Unknown', 'github': ''})
        users.append({
            'user_id': user_id,
            'name': user_info['name'],
            'github_username': user_info['github'],
            'snapshot_count': len(snapshots),
            'date_range': {
                'start': snapshots[0]['date'] if snapshots else '',
                'end': snapshots[-1]['date'] if snapshots else ''
            }
        })
    
    return jsonify({
        'success': True,
        'users': users
    })


@app.route('/api/snapshots/<user_id>', methods=['GET'])
def get_user_snapshots(user_id: str):
    """获取指定用户的所有快照"""
    user_data = parse_echocraft_results(CONFIG['echocraft_results'])
    
    if user_id not in user_data:
        return jsonify({
            'success': False,
            'error': f'User {user_id} not found'
        }), 404
    
    return jsonify({
        'success': True,
        'user_id': user_id,
        'snapshots': user_data[user_id]
    })


@app.route('/api/commits/<github_username>', methods=['GET'])
def get_commits(github_username: str):
    """获取GitHub仓库的commit历史"""
    # 从主仓库 EchoCraft 获取 commit 历史
    repo_path = os.path.join(CONFIG['github_repos_base'], 'EchoCraft')
    
    if not os.path.exists(repo_path):
        return jsonify({
            'success': False,
            'error': f'Repository not found at {repo_path}'
        }), 404
    
    limit = request.args.get('limit', 100, type=int)
    commits = get_git_commits(repo_path, limit)
    
    return jsonify({
        'success': True,
        'github_username': github_username,
        'repo_path': repo_path,
        'commits': commits
    })


@app.route('/api/query', methods=['POST'])
def query_versions():
    """
    核心查询接口
    根据用户输入的 user_id、github_username、target_time
    返回最近的commit版本和require版本
    """
    data = request.get_json()
    
    user_id = data.get('user_id')
    github_username = data.get('github_username')
    target_time_str = data.get('target_time')  # 格式: "2026-02-04 14:30:00"
    
    if not all([user_id, github_username, target_time_str]):
        return jsonify({
            'success': False,
            'error': 'Missing required parameters: user_id, github_username, target_time'
        }), 400
    
    try:
        target_time = datetime.strptime(target_time_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return jsonify({
            'success': False,
            'error': 'Invalid target_time format. Use: YYYY-MM-DD HH:MM:SS'
        }), 400
    
    # 1. 从主仓库 EchoCraft 获取 commit 历史并查找最近的 commit
    git_repo_path = os.path.join(CONFIG['github_repos_base'], 'EchoCraft')
    commits = get_git_commits(git_repo_path, 500)
    nearest_commit = find_nearest_commit(commits, target_time)
    
    # TODO: 暂时固定 commit 时间为 2026-02-05 18:00:00，待实际数据就绪后使用真实 commit 时间
    commit_time = datetime.strptime('2026-02-05 18:00:00', '%Y-%m-%d %H:%M:%S')
    if nearest_commit:
        nearest_commit['fixed_time'] = '2026-02-05 18:00:00'
    
    # 2. 获取用户快照数据
    user_data = parse_echocraft_results(CONFIG['echocraft_results'])
    if user_id not in user_data:
        return jsonify({
            'success': False,
            'error': f'User {user_id} not found in echocraft data'
        }), 404
    
    # 3. 查找 commit 时间之前最近的快照（而非用户搜索时间）
    nearest_snapshot = find_nearest_snapshot(user_data[user_id], commit_time)
    if not nearest_snapshot:
        return jsonify({
            'success': False,
            'error': f'No snapshot found before commit time ({commit_time})'
        }), 404
    
    # 4. 还原快照
    restore_error = None
    restored_repo = None
    original_reposhot = None
    request_changes = []
    try:
        restored_repo, original_reposhot, diffs = restore_snapshot(
            nearest_snapshot['date'],
            user_id,
            nearest_snapshot['request_id']
        )
        if not restored_repo:
            restore_error = f"restore_snapshot returned None for date={nearest_snapshot['date']}, request_id={nearest_snapshot['request_id']}"
        else:
            # 提取该 request 的文件变更摘要
            request_changes = extract_request_changes(diffs)
    except Exception as e:
        restore_error = f"restore_snapshot exception: {str(e)}"
        print(f"Error in restore_snapshot: {e}", flush=True)
    
    # EchoCraft_aacedar 作为本地真实代码仓库，直接用于对比（不做 git checkout）
    # TODO: 暂时固定，待实际数据就绪后改为动态查找
    actual_repo_path = os.path.join(CONFIG['github_repos_base'], 'EchoCraft_aacedar')
    
    # 对比原始快照（还原前）与真实仓库
    original_comparison = None
    if original_reposhot:
        try:
            original_comparison = compare_original_with_actual(original_reposhot, actual_repo_path)
        except Exception as e:
            print(f"Error comparing original with actual: {e}", flush=True)
            original_comparison = {'error': str(e)}

    result = {
        'success': True,
        'query_params': {
            'user_id': user_id,
            'github_username': github_username,
            'target_time': target_time_str
        },
        'require_version': {
            'snapshot': nearest_snapshot,
            'restored': restored_repo is not None,
            'restore_error': restore_error,
            'file_count': len(restored_repo.get('repo_infos', {})) if restored_repo else 0
        },
        'commit_version': nearest_commit,
        'repo_path': actual_repo_path,
        'request_changes': request_changes,  # 该 request 的文件变更详情
        'original_comparison': original_comparison,  # 原始快照与真实仓库的对比结果
    }
    
    # 5. 如果快照还原成功，直接与本地仓库 EchoCraft_aacedar 对比
    if restored_repo:
        try:
            comparison = compare_versions(restored_repo, actual_repo_path)
            result['comparison'] = comparison
        except Exception as e:
            result['compare_error'] = f"Compare exception: {str(e)}"
            print(f"Error in comparison: {e}", flush=True)
    else:
        result['compare_error'] = f"Cannot compare: snapshot restore failed ({restore_error})"
    
    return jsonify(result)


@app.route('/api/compare', methods=['POST'])
def compare_detailed():
    """
    详细对比接口
    对比指定的快照和commit版本，返回详细的文件级diff
    """
    data = request.get_json()
    
    user_id = data.get('user_id')
    snapshot_date = data.get('snapshot_date')
    request_id = data.get('request_id')
    commit_hash = data.get('commit_hash')
    repo_path = data.get('repo_path')
    
    if not all([user_id, snapshot_date, request_id, commit_hash, repo_path]):
        return jsonify({
            'success': False,
            'error': 'Missing required parameters'
        }), 400
    
    # 1. 还原快照
    restored_repo, _, _ = restore_snapshot(snapshot_date, user_id, request_id)
    if not restored_repo:
        return jsonify({
            'success': False,
            'error': 'Failed to restore snapshot'
        }), 500
    
    # 2. 切换到目标commit
    if not checkout_git_version(repo_path, commit_hash):
        return jsonify({
            'success': False,
            'error': f'Failed to checkout commit {commit_hash}'
        }), 500
    
    # 3. 进行详细对比
    comparison = compare_versions(restored_repo, repo_path)
    
    # 4. 切换回默认分支
    subprocess.run(['git', 'checkout', '-'], cwd=repo_path, capture_output=True)
    
    return jsonify({
        'success': True,
        'comparison': comparison,
        'restored_files': len(restored_repo.get('repo_infos', {})),
        'repo_name': restored_repo.get('repo_name', '')
    })


@app.route('/api/file-content', methods=['POST'])
def get_file_content():
    """获取指定文件的还原版本和真实仓库版本内容（用于详细 diff 对比）"""
    data = request.get_json()
    
    user_id = data.get('user_id')
    snapshot_date = data.get('snapshot_date')
    request_id = data.get('request_id')
    rel_path = data.get('rel_path')
    
    if not all([user_id, snapshot_date, request_id, rel_path]):
        return jsonify({
            'success': False,
            'error': 'Missing required parameters: user_id, snapshot_date, request_id, rel_path'
        }), 400
    
    # 还原快照
    restored_repo, _ = restore_snapshot(snapshot_date, user_id, request_id)
    restored_content = ''
    if restored_repo:
        restored_infos = restored_repo.get('repo_infos', {})
        workspace_path = restored_repo.get('workspace_path', '')
        # 在还原的文件中查找匹配的文件
        for path, content in restored_infos.items():
            if path.endswith('/' + rel_path) or path == rel_path:
                restored_content = content
                break
    
    # 读取真实仓库文件
    actual_repo_path = os.path.join(CONFIG['github_repos_base'], 'EchoCraft_aacedar')
    actual_file_path = os.path.join(actual_repo_path, rel_path)
    actual_content = ''
    if os.path.exists(actual_file_path):
        try:
            with open(actual_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                actual_content = f.read()
        except Exception:
            pass
    
    return jsonify({
        'success': True,
        'rel_path': rel_path,
        'restored_content': restored_content,
        'actual_content': actual_content,
    })


@app.route('/api/github-repos', methods=['GET'])
def list_github_repos():
    """列出本地的GitHub仓库"""
    base_path = CONFIG['github_repos_base']
    repos = []
    
    if os.path.exists(base_path):
        for item in os.listdir(base_path):
            item_path = os.path.join(base_path, item)
            if os.path.isdir(item_path) and os.path.exists(os.path.join(item_path, '.git')):
                repos.append({
                    'name': item,
                    'path': item_path,
                    'is_echocraft': 'EchoCraft' in item
                })
    
    return jsonify({
        'success': True,
        'repos': repos
    })


# ==================== 主入口 ====================

if __name__ == '__main__':
    # 确保模板和静态文件目录存在
    os.makedirs(Path(__file__).parent / 'templates', exist_ok=True)
    os.makedirs(Path(__file__).parent / 'static', exist_ok=True)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
