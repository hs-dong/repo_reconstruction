# Repo Reconstruction Evaluation V2

第二代评估和可视化框架，用于对比分析 EchoCraft 的快照还原结果与 Git 仓库的真实提交版本。

## 📁 目录结构

```
web_app/
├── README.md              # 本文档
├── requirements.txt       # Python 依赖
├── app.py                 # Flask 后端服务
├── data_manager.py        # 数据仓库管理工具
├── standalone.html        # 独立 HTML 演示页面（无需后端）
├── templates/
│   └── index.html         # Flask 模板页面
├── static/                # 静态资源（CSS/JS/图片）
└── output/                # 输出目录
```

## 🚀 快速开始

### 方式一：纯前端演示（推荐试用）

直接在浏览器中打开 `standalone.html` 文件即可体验：

```bash
# 使用浏览器打开
firefox /ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_script/web_app/standalone.html
# 或
google-chrome standalone.html
```

点击"加载演示数据"按钮查看演示效果。

### 方式二：启动 Flask 后端服务

```bash
# 1. 进入目录
cd /ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_script/web_app

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动服务
python app.py

# 4. 访问 http://localhost:5000
```

### 方式三：使用命令行工具

```bash
# 列出所有用户
python data_manager.py list-users

# 列出指定用户的快照
python data_manager.py list-snapshots --user-id 2e1fb58b-ffa3-487f-86a6-eb613f42bc65

# 执行单次对比
python data_manager.py compare \
    --user-id 2e1fb58b-ffa3-487f-86a6-eb613f42bc65 \
    --github-username xwellxia \
    --target-time "2026-02-04 14:30:00" \
    --output output/result.json
```

## 🎯 核心功能

### 1. 交互式查询界面

用户输入三个参数：
- **User ID**: EchoCraft 用户标识（UUID）
- **GitHub 用户名**: 对应的 GitHub 账号
- **查询时间点**: 需要分析的时间

系统返回：
- 该时刻之前最近的 **Commit 版本**（Git 真实提交）
- 该时刻之前最近的 **Require 版本**（快照还原）
- 两个版本的可视化对比和相似度计算

### 2. 版本对比分析

- **文件级对比**: 逐个文件比较还原结果与真实仓库
- **相似度计算**: 基于 Ratcliff/Obershelp 算法的文本相似度
- **差异可视化**: 左右分栏的 diff 视图，支持字符级高亮
- **统计概览**: 总文件数、一致/差异/缺失文件数、平均相似度

### 3. 数据仓库管理

- **快照数据管理**: 从 EchoCraft 系统读取快照数据
- **Git 仓库管理**: 克隆、版本切换、历史查询
- **批量处理**: 支持多时间点批量对比分析
- **结果导出**: JSON 格式的详细对比报告

## 📊 API 接口

### 获取用户列表
```
GET /api/users
```

### 获取用户快照
```
GET /api/snapshots/<user_id>
```

### 获取 Git 提交历史
```
GET /api/commits/<github_username>?limit=100
```

### 执行版本查询（核心接口）
```
POST /api/query
Content-Type: application/json

{
    "user_id": "2e1fb58b-ffa3-487f-86a6-eb613f42bc65",
    "github_username": "xwellxia",
    "target_time": "2026-02-04 14:30:00"
}
```

### 详细对比
```
POST /api/compare
Content-Type: application/json

{
    "user_id": "...",
    "snapshot_date": "20260204",
    "request_id": "...",
    "commit_hash": "...",
    "repo_path": "..."
}
```

## 🏗️ 数据仓库建设

### 1. 从 EchoCraft 获取数据

数据存储位置：
- **快照文件**: `/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/repos/{日期}/{user_id}/{request_id}.jsonl`
- **变更序列**: `/data_fast_v2/dataset/agent/rl_edit/reposhot_event_output/changes/{日期}/{user_id}/{request_id}/*.jsonl`

### 2. 本地 GitHub 仓库管理

为实现精确的版本对比，需要在本地维护 GitHub 仓库的副本：

```bash
# 克隆仓库
git clone https://github.com/xxx/EchoCraft.git \
    /ai_train/bingodong/dhs/repo_reconstruction_evaluation/eval_data/EchoCraft_username

# 或使用工具
python data_manager.py setup-repo \
    --github-url https://github.com/xxx/EchoCraft.git \
    --local-path ./eval_data/EchoCraft_username
```

### 3. 还原验证原则

**目标**: 还原出的代码应该与对应时间点的 Git 提交版本具有 100% 相似度。

**验证流程**:
1. 获取目标时间点的快照数据
2. 应用 diff 变更序列还原仓库
3. 找到对应时间点的 Git commit
4. 切换 Git 仓库到该 commit 版本
5. 逐文件对比计算相似度
6. 生成对比报告

## 🎨 界面预览

### 主界面
- 左侧边栏: 查询表单和用户列表
- 右侧内容区: 版本信息卡片、统计面板、文件列表

### 版本信息卡片
- **Commit 版本**: 显示 hash、时间、作者、提交信息
- **Require 版本**: 显示日期、请求ID、文件数量、还原状态

### 统计面板
- 总文件数
- 完全一致文件数 (绿色)
- 存在差异文件数 (黄色)
- 缺失文件数 (红色)
- 平均相似度 (带进度条)

### 文件列表
- 支持按状态筛选 (全部/有差异/缺失/一致)
- 点击文件查看详细 diff
- 显示每个文件的相似度百分比

## 🔧 配置说明

配置项位于各脚本的 `CONFIG` 字典中：

```python
CONFIG = {
    'reposhot_base': '...',      # 快照文件根目录
    'changes_base': '...',       # 变更文件根目录
    'local_repos_base': '...',   # 本地仓库存储目录
    'echocraft_results': '...',  # echocraft_results.txt 路径
    'output_base': '...',        # 输出目录
}
```

## 📝 已知用户映射

| User ID | 用户名 | GitHub |
|---------|--------|--------|
| 19802552-04bf-4173-acd4-bcbd25eaa9bd | 杨永康 | yangyongkang |
| e6e42a7f-a0ee-4e29-8f63-f3faefc54e24 | chenhaokun | haokunchen |
| 2e1fb58b-ffa3-487f-86a6-eb613f42bc65 | Xwell | xwellxia |
| 83902969-394d-442b-9b65-2c9ac41b60f1 | 刘峰 | neolscarlet |
| 3ad75b0f-ce21-41c1-8ed1-3c54b9c1c84b | aacedar | aacedar |

## 🔮 后续开发计划

1. **实时数据同步**: 与 EchoCraft 系统的实时数据同步
2. **历史趋势分析**: 相似度随时间变化的趋势图
3. **批量评估报告**: 支持导出 PDF/Excel 格式的评估报告
4. **自动化测试**: CI/CD 集成，自动验证还原质量
5. **多仓库支持**: 支持同时分析多个仓库的还原效果
