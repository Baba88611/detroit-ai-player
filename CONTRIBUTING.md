# Contributing / 参与贡献

感谢你帮助改进 Detroit AI Player。提交内容必须同时守住可复现性、信息隔离和版权边界。

## 先选择正确入口

- 部署问题、模型使用问题和实验结果分享：使用
  [Discussions](https://github.com/Baba88611/detroit-ai-player/discussions)。
- 可复现的程序缺陷：使用 Bug report Issue 模板。
- 新功能或研究设计建议：先使用 Feature request 模板说明动机与边界。
- 安全问题或可能暴露密钥的问题：使用 [SECURITY.md](SECURITY.md) 中的私密入口。

## 本地开发

```bash
git clone https://github.com/Baba88611/detroit-ai-player.git
cd detroit-ai-player/03_runner
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest tests -v
```

Windows PowerShell 激活命令为 `.\.venv\Scripts\Activate.ps1`。

## Pull Request 要求

1. 每个 PR 聚焦一个问题，并说明用户可见的变化。
2. 新行为必须有测试；修复缺陷时优先添加能复现旧问题的回归测试。
3. 保持现有目录职责：`01_json` 数据、`02_setting` 配置、`03_runner` 运行器、
   `04_execution` 结果说明。
4. 不要提交 `.env`、API key、token、个人实验结果或包含密钥的日志。
5. 不要给被测模型增加工具、联网能力或 `system` 层数据。任何可能改变
   `player_facing` / `system` 隔离边界的改动，都必须在 PR 中单独说明并测试。
6. 不要提交游戏原始剧本、逐字对白、截图、音视频或其他第三方游戏素材。
7. 确认改动适用的许可证，参见 [docs/legal/README.md](docs/legal/README.md)。

提交前运行：

```bash
cd 03_runner
python -m pytest tests -v
```
