# Security Policy / 安全政策

## Supported versions / 支持版本

Security fixes are applied to the latest commit on `main` and to the latest
published release. Older commits are not maintained separately.

安全修复适用于 `main` 最新提交和最新发布版本；更早的提交不单独维护。

## Reporting a vulnerability / 报告漏洞

Please use GitHub's private vulnerability reporting page:

<https://github.com/Baba88611/detroit-ai-player/security/advisories/new>

请通过上述 GitHub 私密安全报告入口提交漏洞。不要在公开 Issue、Discussion、
Pull Request 或日志中粘贴 API key、`.env` 内容、认证信息或能够复现密钥的完整输出。

Useful reports include:

- affected commit or release;
- affected backend (`default`, another API model, or `claude-code`);
- minimal reproduction steps with all secrets removed;
- expected and actual behavior;
- security impact, especially information-isolation bypasses, secret exposure,
  unsafe subprocess behavior, or unintended outbound requests.

For ordinary bugs without sensitive information, use the public bug-report
template instead.

## Response expectations / 处理预期

The maintainer will acknowledge a private report when reviewed, reproduce it
where possible, and coordinate disclosure after a fix is available. No bounty
program is offered.
