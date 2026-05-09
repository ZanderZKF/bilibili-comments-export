# Bilibili Comments Export

用于导出指定 B 站视频的评论与楼中楼，并生成结构化 `JSON` 与平铺 `CSV` 文件。

## 当前项目内容

- `bilibili_comments_scraper.py`: 抓取脚本
- `requirements.txt`: 依赖说明

## 环境准备

建议使用 Python 3.11+。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行方式

默认会抓取当前项目内置的示例视频：

```bash
python3 bilibili_comments_scraper.py
```

也可以手动传入参数：

```bash
python3 bilibili_comments_scraper.py <video_url> <bvid> <oid>
```

示例：

```bash
python3 bilibili_comments_scraper.py \
  "https://www.bilibili.com/video/BV1eiwFz1EQx/" \
  "BV1eiwFz1EQx" \
  "116210842803834"
```

## 输出文件

- `*_comments.json`: 包含视频信息、根评论、楼中楼回复
- `*_comments_flat.csv`: 平铺后的评论表，便于检索、筛选和导入 Excel
- 导出文件默认只保留在本地，不纳入 Git 版本管理

## 说明

- 当前 B 站评论接口存在较强风控，部分高回复楼层的楼中楼可能触发 `412/-352` 风控，导致无法完全抓全。
- 根评论抓取走 WBI 接口，楼中楼依赖 `bilibili-api-python`。
- 若需要进一步补全缺失楼中楼，通常需要额外使用登录态 Cookie、浏览器指纹模拟或更换网络环境。
