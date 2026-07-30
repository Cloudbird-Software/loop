# E2 操作步骤（你照着做，两步）

## 第 1 步：在 loop 工作区 ship v0.1.5（必须在建沙箱前完成）

沙箱 bootstrap 会从 `v0.1.5` tag 拉 loopd.py，没 ship 就拉不到带 reaper 的代码，E2 必失败。

在 loop 仓库工作区执行：

```bash
git add loopd/loopd.py .loop/smoke.sh Trae沙盒填写卡.md
git commit -m "$(cat <<'EOF'
v0.1.5: local reaper + ordinal reset on startup (Fix A+B)
EOF
)"
git tag v0.1.5
git push origin HEAD --tags
```

push 成功后，可选验证（两个 SHA 应都不变）：
```bash
gh api /repos/Cloudbird-Software/loop/git/trees/v0.1.5:prompts --jq .sha
# 应输出 979736b02639621256599db21f0352d2f0fc5bbe
```

## 第 2 步：建 impl-2 沙箱，让它读 E2-IMPL2.md

照 [Trae沙盒填写卡.md](Trae沙盒填写卡.md) 建 impl-2 沙箱，改 3 个值：
- `LOOP_SANDBOX_ID=impl-2`
- `LOOP_MODEL=<选一个>`
- `LOOP_ROLE=impl`（不变）

其余照填，含 `LOOP_BOOTSTRAP_REF=v0.1.5`、`LOOP_REAPER_SEC=60`、两个 SHA 不变。

沙箱起来后，**让沙箱 AI 读 `E2-IMPL2.md` 这个文件**，按里面的指示操作即可。

> E2 测试卡已投放：[#35](https://github.com/Cloudbird-Software/product-x/issues/35)，僵尸态（claimed + lease 过期），impl-2 的 reaper 会回收它。
