## R13-4: product-x 机制副本清零

### 删除清单
[由 purge-mechanism-copies.sh --dry-run 输出粘贴]

### 删除前 CI 运行
[粘贴删除前最后一次完整 CI 全绿的运行链接]

### 删除后 CI 运行
[粘贴删除后（薄壳跑通后）完整 CI 全绿的运行链接]

### required check 名一致性
删除前后 required check 名保持一致：
- [ ] lint
- [ ] test
- [ ] gates / loop-gates
- [ ] verify / loop-review

### gate/loop-conformance 检查 5 验证
- [ ] 删除前：gate/loop-conformance 报告副本数 > 0
- [ ] 删除后：gate/loop-conformance 报告副本数 = 0

### product-x 保留的目录结构
[见 README.md 中的目录树]
