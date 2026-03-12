#!/usr/bin/env python3
"""
查询最近快照工具
用法: python test_find_nearest_snapshot.py <user_id> <时间>
示例: python test_find_nearest_snapshot.py 19802552-04bf-4173-acd4-bcbd25eaa9bd "2026-02-04 15:00:00"
"""

import os
import sys
import json
import subprocess
from datetime import datetime

CONFIG = {
    'changes_base': '/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/changes',
    'echocraft_results': '/ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_script/result/echocraft_results.txt',
}


def get_changes_timestamp(changes_base, date, user_id, request_id):
    changes_dir = os.path.join(changes_base, date, user_id, request_id)
    if not os.path.isdir(changes_dir):
        return None
    jsonl_files = sorted([f for f in os.listdir(changes_dir) if f.endswith('.jsonl')])
    if not jsonl_files:
        return None
    last_file = os.path.join(changes_dir, jsonl_files[-1])
    try:
        result = subprocess.run(['tail', '-1', last_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        last_line = result.stdout.decode('utf-8').strip() if result.returncode == 0 else None
        if not last_line:
            return None
        data = json.loads(last_line)
        ts_ms = data.get('timestamp')
        if ts_ms is not None:
            return float(ts_ms) / 1000.0
    except Exception:
        pass
    return None


def parse_echocraft_results(results_file):
    user_data = {}
    if not os.path.exists(results_file):
        return user_data
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
                if user_id not in user_data:
                    user_data[user_id] = []
                precise_ts = get_changes_timestamp(CONFIG['changes_base'], date, user_id, request_id)
                if precise_ts is not None:
                    timestamp = precise_ts
                else:
                    try:
                        timestamp = datetime.strptime(date, '%Y%m%d').timestamp()
                    except ValueError:
                        timestamp = 0
                user_data[user_id].append({
                    'date': date,
                    'request_id': request_id,
                    'timestamp': timestamp,
                })
    for uid in user_data:
        user_data[uid].sort(key=lambda x: x['timestamp'])
    return user_data


def find_nearest_snapshot(user_data, target_time):
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


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('用法: python %s <user_id> "<时间>"' % sys.argv[0])
        print('示例: python %s 19802552-04bf-4173-acd4-bcbd25eaa9bd "2026-02-04 15:00:00"' % sys.argv[0])
        sys.exit(1)

    user_id = sys.argv[1]
    target_time_str = sys.argv[2]

    try:
        target_time = datetime.strptime(target_time_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        print('时间格式错误，请使用: YYYY-MM-DD HH:MM:SS')
        sys.exit(1)

    user_data = parse_echocraft_results(CONFIG['echocraft_results'])

    if user_id not in user_data:
        print('用户 %s 不存在' % user_id)
        sys.exit(1)

    result = find_nearest_snapshot(user_data[user_id], target_time)

    if result:
        ts_str = datetime.fromtimestamp(result['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        print('%s  (date=%s, snapshot_time=%s)' % (result['request_id'], result['date'], ts_str))
    else:
        print('未找到目标时间之前的快照')
