# GamesFor1024

GamesFor1024 是一个基于 Django 的多小游戏整合后端，涵盖以下模块：

- **Spot the DeepFake**：深伪识图问答接口
- **Risk Hunter**：AI 内容合规性挑战
- **MBTI Spy**：多人实时推理小游戏（依赖 Redis）
- **Prize**：抽奖库存管理
- **MBTI Test**：全新 Django Web App（`/mbtitest/`）提供在线 MBTI 测试体验

---

## 1. 环境准备

### 1.1 依赖安装

```bash
pip install -r requirements.txt
```

`requirements.txt` 仅包含项目基础依赖（Django、Redis、requests 等）。如需连接 MySQL，请额外选择以下驱动之一：

```bash
# 方案 A：纯 Python 驱动（推荐）
pip install PyMySQL

# 方案 B：MySQL 原生驱动（需系统库）
pip install mysqlclient
```

项目在 `games_backend/__init__.py` 中内置了 PyMySQL 兼容层：若检测到 `mysqlclient` 缺失但已安装 `PyMySQL`，会自动以 `MySQLdb` 方式加载。

### 1.2 配置文件

服务启动、导入脚本与管理命令都会读取根目录 `.env` 文件（不支持直接读取系统环境变量）。示例配置如下：

```
# --- 数据库（必填） ---
# PostgreSQL 示例
DATABASE_URL=postgres://user:password@host:5432/dbname

# MySQL/MariaDB 示例
# DATABASE_URL=mysql://user:password@host:3306/dbname

# SQLite 示例
# DATABASE_URL=sqlite:///absolute/path/to/db.sqlite3
# DATABASE_URL=sqlite://:memory:

# --- Redis（MBTI Spy 及部分缓存必需） ---
REDIS_URL=redis://127.0.0.1:6379/0
MBTISPY_SESSION_TTL=7200
MBTISPY_SESSION_PREFIX=mbtispy:session:
MBTISPY_SESSION_LOCK_PREFIX=mbtispy:lock:
MBTISPY_LOCK_TIMEOUT=5
MBTISPY_LOCK_WAIT=5

# --- LLM 服务（MBTI Spy 题目生成 & MBTI Test 结果分析，可选） ---
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-your-api-key
LLM_MODEL=deepseek-chat
```

### 1.3 数据库初始化

```bash
python manage.py migrate
python manage.py check  # 可选：验证配置是否完整
python manage.py runserver
```

默认服务监听 `http://127.0.0.1:8000/`。前端可直接访问 `/mbtitest/` 体验 MBTI 测试流程。

---

## 2. 模块概览

| 模块 | 功能 | 主要路由前缀 | 依赖 |
| --- | --- | --- | --- |
| DeepFake | 深伪识图题库接口 | `/deepfake/` | 数据库 |
| Risk Hunter | AI 内容审查题库接口 | `/riskhunter/` | 数据库 |
| MBTI Spy | Redis 状态驱动的推理游戏 | `/mbtispy/` | 数据库 + Redis + 可选 LLM |
| Prize | 库存抽奖接口 | `/prize/` | 数据库 |
| MBTI Test | 8 题自测 + LLM 结果分析 | `/mbtitest/` | Redis（会话）+ 可选 LLM |

各模块的导入脚本与管理命令示例见下文。

---

## 3. DeepFake（Spot the DeepFake）

### 3.1 数据导入

`import_deepfake_csv.py` 支持将配对题（真假对比）或三选一题型 CSV 导入数据库，不依赖 Django。

```bash
# 默认读取 .env 中的 DATABASE_URL
python import_deepfake_csv.py

# 导入配对题
python import_deepfake_csv.py \
  --dataset pairs \
  --database-url mysql://user:pass@127.0.0.1:3306/1024 \
  --csv-path Resources/deepfake/deepfake_data.csv \
  --table deepfake_deepfakepair \
  --truncate

# 导入三选一题
python import_deepfake_csv.py \
  --dataset selection \
  --csv-path Resources/deepfake/deepfake_data_select.csv \
  --table deepfake_deepfakeselection
```

常用参数：

- `--dataset`：`pairs`（默认）或 `selection`
- `--table`：目标表名（默认根据题型推断）
- `--truncate`：导入前清空表
- `--dry-run`：仅校验 CSV，不写入数据库

### 3.2 API

- `GET /deepfake/questions/?count=<int>`：返回指定数量的真假配对题，默认 3 组
- `GET /deepfake/selection/?count=<int>`：返回三选一题组，默认 1 组，需满足 AI 与真实图片数量条件

当题库不足或参数非法时，会返回对应的错误信息。

---

## 4. Risk Hunter

### 4.1 数据导入

- **独立脚本**（适配多种 CSV 表头）：

  ```bash
  python import_riskhunter_csv.py "RISKHUNTER.csv" \
    --encoding utf-8-sig \
    --delimiter , \
    --truncate
  ```

- **Django 管理命令**：

  ```bash
  python manage.py import_riskhunter_csv "RISKHUNTER.csv" \
    --encoding utf-8-sig \
    --delimiter , \
    --truncate
  ```

字段映射示例：

- 标题：`title`、`标题`、`场景`、`题目`
- 内容：`content`、`文本`、`题干`、`生成内容`
- 解析：`analysis`、`解析`、`答案解析`
- 标签：`risk_label`、`是否合规`、`正确答案`、`判定`

标签值会自动映射为布尔：`不合规/风险/false/no/否` 等均会被解析。

### 4.2 API

- `GET /riskhunter/scenarios/?count=<int>`：随机返回指定数量题目（默认 5）

---

## 5. MBTI Spy

Redis 用于存储房间会话、并发锁与投票状态。核心流程：

1. `POST /mbtispy/session/` 创建房间（固定 3 名玩家）
2. `POST /mbtispy/session/<code>/register/` 玩家报名（填写昵称与 MBTI）
3. `GET /mbtispy/session/<code>/register/status/` 主持人确认
4. `GET /mbtispy/session/<code>/players/` & `/role/<player_id>/` 查看身份
5. `POST /mbtispy/question/` 生成游戏问题（需配置 LLM 服务才会返回 AI 生成题）
6. `POST /mbtispy/session/<code>/vote/start/` 开启投票
7. `POST /mbtispy/session/<code>/vote/<player_id>/` 投票
8. `GET /mbtispy/session/<code>/results/` 查看胜负

若三名玩家 MBTI 相同，则全员为 Spy，可通过 `vote_for="all_spies"` 结算。详情请参考 `mbtispy/views.py` 注释或使用 `simulate_mbtispy_game.py` 模拟器。

### 5.1 问题生成

配置 `LLM_API_KEY` 后，`POST /mbtispy/question/` 会调用外部 LLM 生成包含四个维度问题的 JSON。未配置时返回占位提示信息。

### 5.2 本地模拟

```bash
python simulate_mbtispy_game.py               # 默认 http://localhost:8000
python simulate_mbtispy_game.py --base-url http://127.0.0.1:9000
```

---

## 6. Prize 抽奖

- **导入数据**
  - 管理命令：`python manage.py import_prizes [--csv Resources/stock_data.csv]`
  - 独立脚本：`python import_prize_csv.py --csv-path Resources/stock_data.csv [--dry-run]`
- **接口**
  - `GET /prize/draw/`：获取一件库存大于 0 的奖品（串行加锁保证库存一致）
  - `GET /prize/list/`：返回所有奖品及库存

---

## 7. MBTI Test（JSON API）

- 基础路径：`http://localhost:8000/mbtitest/`
- 功能：提供 8 道固定题目，通过 Session 记录答题进度，并在完成后调用 LLM（若已配置）生成类型分析。未配置或调用失败时返回保底结果。
- 提示：接口依赖 Django Session，建议使用 `curl -c cookies.txt -b cookies.txt` 或其它方式携带 Cookie。

### 接口概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET /mbtitest/` | 返回 API 状态与关键端点 |
| `POST /mbtitest/start/` | 初始化测试并返回首题 |
| `GET /mbtitest/question/<qid>/` | 查看指定题目内容 |
| `POST /mbtitest/question/<qid>/` | 提交当前题答案，返回下一步信息 |
| `GET /mbtitest/result/` | 获取最终判定与作答摘要 |

### 示例流程

1. **初始化测试（获取第 0 题）**

   ```bash
   curl -c cookies.txt -X POST http://localhost:8000/mbtitest/start/ \
     -H 'Content-Type: application/json'
   ```

   ```json
   {
     "success": true,
     "session_initialized": true,
     "next_qid": 0,
     "question": {
       "qid": 0,
       "total": 8,
       "dimension": "E/I",
       "question": "在一个陌生的聚会上，你会怎么做？",
       "options": [
         "主动去和新朋友聊天",
         "只和熟悉的人待在一起",
         "静静地感受氛围"
       ]
     }
   }
   ```

2. **获取当前题目（GET）**

   ```bash
   curl -b cookies.txt http://localhost:8000/mbtitest/question/0/
   ```

   - 返回结构与 `question` 字段一致，便于前端重复拉取题面。

3. **提交答案并获取下一题**

   ```bash
   curl -b cookies.txt -X POST http://localhost:8000/mbtitest/question/0/ \
     -H 'Content-Type: application/json' \
     -d '{"answer": "主动去和新朋友聊天"}'
   ```

   ```json
   {
     "success": true,
     "completed": false,
     "answers_count": 1,
     "next_qid": 1,
     "question": {
       "qid": 1,
       "total": 8,
       "dimension": "E/I",
       "question": "周末时你更喜欢哪种活动？",
       "options": [
         "参加热闹的社交活动",
         "独自在家休息或读书",
         "和一两个亲密朋友小聚"
       ]
     }
   }
   ```

   - 重复 POST 第 1~7 题；当 `completed` 为 `true` 时，响应将包含 `result_endpoint`，指向 `/mbtitest/result/`。

4. **获取测试结果**

   ```bash
   curl -b cookies.txt http://localhost:8000/mbtitest/result/
   ```

   ```json
   {
     "success": true,
     "result": {
       "mbti": "INFJ",
       "intro": "理想主义者，善于共情，富有创造力。"
     },
     "answers": [
       "主动去和新朋友聊天",
       "... 共计 8 项 ..."
     ],
     "questions": [
       {
         "dimension": "E/I",
         "question": "在一个陌生的聚会上，你会怎么做？",
         "selected_answer": "主动去和新朋友聊天"
       }
     ]
   }
   ```

   - 若未答满 8 题，接口会返回 `{"success": false, "error": "Test not completed."}`，并附 `restart_endpoint`。

---

## 8. 常用脚本与工具

| 脚本 | 作用 | 主要参数 |
| --- | --- | --- |
| `import_deepfake_csv.py` | 导入 DeepFake 题库 | `--dataset`、`--table`、`--truncate` |
| `import_riskhunter_csv.py` | 导入 Risk Hunter 题库 | `--encoding`、`--delimiter`、`--dry-run` |
| `import_prize_csv.py` | 导入 Prize 奖品列表 | `--csv-path`、`--dry-run` |
| `simulate_mbtispy_game.py` | 本地模拟 MBTI Spy 对局 | `--base-url` |

所有脚本都会自动读取 `.env` 中的 `DATABASE_URL`；若需要覆盖，可使用 `--database-url` 参数。

---

## 9. 开发建议

- 新增 Django 应用后，别忘更新 `INSTALLED_APPS` 与 `games_backend/urls.py`
- 运行 `python manage.py check` 确认配置与依赖可用
- 生产环境请务必：
  - 使用强随机的 `SECRET_KEY`
  - 关闭 `DEBUG`
  - 将 `ALLOWED_HOSTS` 设置为白名单
  - 配置持久化数据库与 Redis 服务

欢迎在此基础上扩展更多小游戏或接入前端项目。
