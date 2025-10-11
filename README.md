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
  - 请求体：`{"expected_players": 3}`（可选，默认 3，最少 3，最多 10）
  - 返回：`{"session_code": "ABC123", "expected_players": 3}`
- 玩家注册：`POST /mbtispy/register/`
  - 请求体：`{"session_code": "ABC123", "player_name": "Alice", "mbti": "INTJ"}`
  - 返回玩家编号（`player_id`）、阵营（守护者/侦探）以及房间状态
  - 当注册人数达到 `expected_players` 时后台会自动抽取一名守护者并锁定其 MBTI
- 查看同场玩家：`GET /mbtispy/session/<session_code>/players/`
  - 返回已报名玩家的编号、姓名与登记的 MBTI，用于线下互相核对
- 查询个人身份：`GET /mbtispy/session/<session_code>/role/<player_id>/`
  - 守护者可获知自己的隐藏 MBTI，侦探只会收到“detective”身份描述
- 公布守护者 MBTI：`GET /mbtispy/session/<session_code>/guardian/`
  - 用于主持人确认隐藏阵营 MBTI（不会泄露姓名）
- 投票：`POST /mbtispy/session/<session_code>/vote/`
  - 请求体：`{"player_id": 2, "vote_for": 1}`，每名玩家可多次提交，后一次将覆盖前一次
- 结算：`GET /mbtispy/session/<session_code>/results/`
  - 返回票数统计、淘汰玩家及胜负结果；若出现平票则提示重新投票

