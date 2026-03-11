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
from compare import load_actual_repo, compare_repos, compute_similarity

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

def parse_echocraft_results(results_file: str) -> Dict[str, List[Dict]]:
    """解析 echocraft_results.txt 文件，返回按用户分组的数据"""
    user_data = {}
    
    if not os.path.exists(results_file):
        return user_data
    
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
                
                # 将日期转换为时间戳格式以便排序
                try:
                    dt = datetime.strptime(date, '%Y%m%d')
                    timestamp = dt.timestamp()
                except ValueError:
                    timestamp = 0
                    
                user_data[user_id].append({
                    'date': date,
                    'request_id': request_id,
                    'timestamp': timestamp,
                })
    
    # 按时间排序每个用户的数据
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
    """查找最接近目标时间且在目标时间之前的快照"""
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


def restore_snapshot(date: str, user_id: str, request_id: str) -> Optional[Dict]:
    """还原指定的快照"""
    try:
        reposhot = load_reposhot(CONFIG['reposhot_base'], date, user_id, request_id)
        if not reposhot or not reposhot.get('repo_infos'):
            return None
        
        diffs = load_changes(CONFIG['changes_base'], date, user_id, request_id)
        if diffs:
            restored = reposhot_refresh(reposhot, diffs)
        else:
            restored = reposhot
        
        return restored
    except Exception as e:
        print(f"Error restoring snapshot: {e}")
        return None


def compare_versions(restored_repo: Dict, actual_repo_path: str) -> Dict:
    """对比两个版本的仓库"""
    try:
        actual_files = load_actual_repo(actual_repo_path)
        restored_infos = restored_repo.get('repo_infos', {})
        workspace_path = restored_repo.get('workspace_path', '')
        
        results = compare_repos(restored_infos, actual_files, workspace_path)
        return results
    except Exception as e:
        print(f"Error comparing versions: {e}")
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
    # 查找对应的本地仓库路径
    repo_path = os.path.join(CONFIG['github_repos_base'], f'EchoCraft_{github_username}')
    if not os.path.exists(repo_path):
        # 尝试默认的EchoCraft路径
        repo_path = os.path.join(CONFIG['github_repos_base'], 'EchoCraft')
    
    if not os.path.exists(repo_path):
        return jsonify({
            'success': False,
            'error': f'Repository for {github_username} not found'
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
    
    # 1. 获取用户快照数据
    user_data = parse_echocraft_results(CONFIG['echocraft_results'])
    if user_id not in user_data:
        return jsonify({
            'success': False,
            'error': f'User {user_id} not found in echocraft data'
        }), 404
    
    # 2. 查找最近的快照（require版本）
    nearest_snapshot = find_nearest_snapshot(user_data[user_id], target_time)
    if not nearest_snapshot:
        return jsonify({
            'success': False,
            'error': 'No snapshot found before target time'
        }), 404
    
    # 3. 获取Git commits并查找最近的commit版本
    repo_path = os.path.join(CONFIG['github_repos_base'], f'EchoCraft_{github_username}')
    if not os.path.exists(repo_path):
        repo_path = os.path.join(CONFIG['github_repos_base'], 'EchoCraft')
    
    commits = get_git_commits(repo_path, 500)
    nearest_commit = find_nearest_commit(commits, target_time)
    
    # 4. 还原快照
    restored_repo = restore_snapshot(
        nearest_snapshot['date'],
        user_id,
        nearest_snapshot['request_id']
    )
    
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
            'file_count': len(restored_repo.get('repo_infos', {})) if restored_repo else 0
        },
        'commit_version': nearest_commit,
        'repo_path': repo_path
    }
    
    # 5. 如果两者都存在，进行对比
    if restored_repo and nearest_commit:
        # 切换到对应的commit版本后对比
        if checkout_git_version(repo_path, nearest_commit['hash']):
            comparison = compare_versions(restored_repo, repo_path)
            result['comparison'] = comparison
            # 切换回main/master分支
            subprocess.run(['git', 'checkout', '-'], cwd=repo_path, capture_output=True)
    
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
    restored_repo = restore_snapshot(snapshot_date, user_id, request_id)
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
    """获取指定文件的内容（用于详细对比）"""
    data = request.get_json()
    
    file_path = data.get('file_path')
    source = data.get('source')  # 'restored' 或 'actual'
    
    # 根据来源获取文件内容的逻辑
    # ...
    
    return jsonify({
        'success': True,
        'content': ''  # TODO: 实现具体逻辑
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
