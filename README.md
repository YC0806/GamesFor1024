# GamesFor1024

后端基于 Django 框架，包含“Spot the DeepFake 深伪识图”与“Risk Hunter - AI 内容审查大挑战”小游戏的数据接口。

## 快速开始

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## 数据库配置

必须通过配置文件指定数据库，仅支持 `DATABASE_URL`（不读取环境变量）。若未配置或无法连接，将在启动时直接报错并终止。

1) 在项目根目录创建文件 `.env`，内容示例：

```
# PostgreSQL 示例
DATABASE_URL=postgres://user:password@host:5432/dbname

# MySQL/MariaDB 示例
# DATABASE_URL=mysql://user:password@host:3306/dbname

# SQLite 示例
# DATABASE_URL=sqlite:///absolute/path/to/db.sqlite3
# 或内存数据库
# DATABASE_URL=sqlite://:memory:

# Redis 配置
REDIS_URL=redis://127.0.0.1:6379/0
MBTISPY_SESSION_TTL=7200
MBTISPY_SESSION_PREFIX=mbtispy:session:
```

2) 安装依赖（MySQL 连接方式二选一）：

```bash
# 方案 A：纯 Python 驱动（推荐，易安装）
pip install PyMySQL

# 或 方案 B：原生 C 扩展（性能更好，需系统库）
pip install mysqlclient
```

项目已在 `games_backend/__init__.py` 内置了 PyMySQL 兼容层：若未安装 `mysqlclient`，且已安装 `PyMySQL`，会自动以 `MySQLdb` 方式接入。

3) 运行迁移与启动服务：

```bash
python manage.py migrate
python manage.py runserver
```

## 导入 Deepfake 数据

`import_deepfake_csv.py` 可将 `Resources/deepfake/deepfake_data.csv` 文件中的题目导入数据库。脚本不依赖 Django，可直接使用 PyMySQL 连接数据库。

```bash
# 默认读取项目根目录下 .env 的 DATABASE_URL
python import_deepfake_csv.py

# 指定数据库、CSV、目标表等参数
python import_deepfake_csv.py \
  --database-url mysql://user:pass@127.0.0.1:3306/1024 \
  --csv-path Resources/deepfake/deepfake_data.csv \
  --table deepfake_deepfakequestion \
  --truncate
```

常用参数说明：
- `--database-url`：可选，覆盖 `.env` 中的 `DATABASE_URL`
- `--csv-path`：CSV 文件路径（默认 `Resources/deepfake/deepfake_data.csv`）
- `--table`：目标表名（默认 `deepfake_deepfakequestion`）
- `--truncate`：导入前清空目标表
- `--dry-run`：仅检查 CSV，不写入数据库


## 深伪识图接口

- 请求：`GET /deepfake/questions/?count=<需要的题目数量>`
- 参数：`count`（可选，默认为 3），表示需要随机抽取的图片组数
- 响应示例：

```json
{
  "count": 2,
  "questions": [
    {
      "id": 1,
      "real_img": "Resources/deepfake/01_no.jpg",
      "ai_img": "Resources/deepfake/01_yes.png",
      "analysis": "1. 左侧沙发扶手与坐垫接缝处存在 1 像素宽的错位；2. 茶几木纹在中心点呈现 2×2 像素的重复噪点；3. 右侧玻璃护栏固定螺丝出现镜像反转；4. 地面瓷砖缝隙在右下角突然变宽 0.5mm；5. 背景窗格倒影呈现非物理规律的波浪扭曲。"
    }
  ]
}
```

当数据库中题目数量少于 `count` 时，接口会返回全部可用题目；当数据库为空或参数非法时，会返回相应的错误信息。

## 导入 Risk Hunter CSV 数据

提供两种方式将 CSV 导入数据库（适配常见中文/英文表头）。

- 方式 A（独立脚本，不依赖 Django）：

  ```bash
  # 使用根目录的独立工具脚本（默认读取 .env 中的 DATABASE_URL，或通过 --database-url 指定）
  python import_riskhunter_csv.py "RISKHUNETER活动素材.csv" \
    --encoding utf-8-sig \
    --delimiter , \
    --truncate
  ```

  可选参数：
  - `--database-url`：MySQL 连接串，如 `mysql://user:password@host:3306/dbname`
  - `--table`：目标表名（默认 `riskhunter_riskscenario`）
  - `--encoding`：CSV 编码（默认 `utf-8-sig`；如需可用 `gbk`）
  - `--delimiter`：分隔符（默认 `,`）
  - `--truncate`：导入前清空表
  - `--batch-size`：批量大小（默认 500）
  - `--dry-run`：只解析不写库

- 方式 B（Django 管理命令）：

  ```bash
  python manage.py import_riskhunter_csv "RISKHUNETER活动素材.csv" \
    --encoding utf-8-sig \
    --delimiter , \
    --truncate
  ```

字段映射：
- 标题：`title`、`标题`、`场景`、`题目`
- 内容：`content`、`文本`、`内容`、`题干`、`生成内容`
- 解析：`analysis`、`解析`、`答案解析`、`说明`、`点评`
- 标签：`risk_label`、`label`、`标签`、`是否合规`、`判定`、`正确答案`、`结论`

`risk_label` 映射到布尔：
- True（不合规/有风险）：`不合规`、`非合规`、`违规`、`风险`、`有风险`、`客户数据泄露`、`数据泄露`、`虚假信息`、`non_compliant`、`data_leak`、`misinformation`、`1`、`true`、`yes`、`否`（针对“是否合规”场景）等。
- False（合规/安全）：`合规`、`内容合规`、`安全`、`compliant`、`0`、`false`、`no`、`是`（针对“是否合规”场景）。

## Risk Hunter 接口

- 请求：`GET /riskhunter/scenarios/?count=<需要的题目数量>`
- 参数：`count`（可选，默认为 5），表示需要随机抽取的题目组数
- 响应示例：

```json
{
  "count": 2,
  "scenarios": [
    {
      "id": 1,
      "title": "场景 1",
      "content": "这是一段需要审核的AI生成内容。",
      "risk_label": true,
      "analysis": "文本提及不合规的宣传措辞。"
    }
  ]
}
```

当数据库中题目数量少于 `count` 时，接口会返回全部可用题目；当数据库为空或参数非法时，会返回相应的错误信息。

## MBTI 守护挑战接口

> 依赖 Redis 存储实时对局状态。默认连接串为 `redis://127.0.0.1:6379/0`，可通过环境变量 `REDIS_URL` 覆盖。

- 创建房间：`POST /mbtispy/session/`
  - 游戏固定 3 名玩家，若传入 `expected_players` 会报错
  - 返回：`{"session_code": "ABC123", "expected_players": 3}`

### 注册阶段
- 玩家注册：`POST /mbtispy/session/<session_code>/register/`
  - 请求体：`{"player_name": "Alice", "mbti": "INTJ"}`
  - 返回玩家编号（`player_id`）、当前阵营（`spy` / `detective`）以及房间状态
- 当三名玩家就位且主持人确认后，后台根据 MBTI 分布推断 `spy_mbti`（规则：三人各异则随机选其一；若两人相同则第三人所属 MBTI 为 `spy_mbti`；若三人完全相同则三人皆为 Spy）并同步玩家阵营
  - 字段 `roles_assigned` 为 `true` 时表示 `spy_mbti` 已确定，响应中会附带该值
  - 未达到三名玩家前，`role` 会返回 `unknown`

### 游戏开始
- 主持人确认注册：`GET /mbtispy/session/<session_code>/register/status/`
  - 若仍在报名阶段，返回 `success=false` 及当前已注册人数；达到 3 人后将自动分配阵营、生成 `spy_mbti` 并返回 `success=true`
- 公布 Spy MBTI：`GET /mbtispy/session/<session_code>/spy/`
  - 用于主持人获知隐藏阵营 MBTI（不会泄露姓名）
- 查看同场玩家：`GET /mbtispy/session/<session_code>/players/`
  - 返回已报名玩家的编号、姓名与登记的 MBTI，用于线下互相核对
- 查询个人身份：`GET /mbtispy/session/<session_code>/role/<player_id>/`
  - 返回玩家身份以及本场游戏的spy_mbti

### 投票阶段
- 主持人开启投票：`POST /mbtispy/session/<session_code>/vote/start/`
  - 仅在状态为 `ready` 时生效；若状态不符，返回 `success=false`
- 投票：`GET /mbtispy/session/<session_code>/vote/` 或 `POST /mbtispy/session/<session_code>/vote/`
  - `GET`：投票开启后返回房间内所有玩家的 `id` 与 `name`，便于前端展示；若投票未开始则返回 `success=false` 及提示信息
  - `POST`：请求体可为 `{"player_id": 2, "vote_for": 1}`（投票某位玩家）或在全员都是 Spy 时使用 `{"player_id": 2, "vote_for": "all_spies"}`；若投票未开始同样返回 `success=false`
- 结算：`GET /mbtispy/session/<session_code>/results/`
  - 若 Spy 玩家被选出，侦探阵营胜利；若 Spy 未被选出（包括平票），Spy 阵营直接胜利
  - 当全员都是 Spy（同一 MBTI）时，选择 `all_spies` 的 Spy 被判定为胜者，未选择者视为失败；返回字段会包含 `spy_winners` / `spy_losers`

可选环境变量（如未设置则使用默认值）：
- `MBTISPY_LOCK_TIMEOUT`：Redis 分布式锁超时（秒，默认 5）
- `MBTISPY_LOCK_WAIT`：获取锁的等待时间（秒，默认 5）
- `MBTISPY_SESSION_LOCK_PREFIX`：锁 key 前缀（默认 `mbtispy:lock:`）

### 本地联调脚本

根目录提供 `simulate_mbtispy_game.py`，可直接向运行中的服务发送 HTTP 请求，模拟完整对局（覆盖平票重投等分支逻辑）。

```bash
# 服务默认监听 http://localhost:8000
python simulate_mbtispy_game.py

# 自定义服务地址
python simulate_mbtispy_game.py --base-url http://127.0.0.1:8000
```

脚本依赖 `requests`，如未安装，可执行：

```bash
pip install requests
```
