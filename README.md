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
      "prompt": "场景 1",
      "images": [
        {"path": "/static/images/1_real.jpg", "label": "real"},
        {"path": "/static/images/1_fake.jpg", "label": "fake"}
      ],
      "key_flaw": "观察眼睛反光的细节。",
      "technique_tip": "先看光影，再看边缘。"
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
