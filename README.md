# GamesFor1024

后端基于 Django 框架，包含“Spot the DeepFake 深伪识图”与“Risk Hunter - AI 内容审查大挑战”小游戏的数据接口。

## 快速开始

```bash
pip install -r requirements.txt
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
      "risk_label": "non_compliant",
      "analysis": "文本提及不合规的宣传措辞。",
      "technique_tip": "留意夸张承诺或违规营销语言。"
    }
  ]
}
```

当数据库中题目数量少于 `count` 时，接口会返回全部可用题目；当数据库为空或参数非法时，会返回相应的错误信息。
