# T005 根目录交付补核

- taskId：T005
- dispatchId：16a6adbb-5162-4d9f-a23d-44b91e20f0e1
- revision：1
- 补核结论：**pass**

先前 T005 review 记录的“未执行 collect、根目录仍保持 T003 产物”是当时用户程序运行中的历史状态。用户退出 SimLIBS 后，desktop-collect.log 显示 npm run desktop:collect exitCode=0，当前已完成 T005 根目录交付。

## 独立只读核对

- dist-desktop/artifact-manifest.json 记录 SimLIBS.exe 为 5143040 bytes、SHA256 为 4f3c96b0e5891e693e3c259cd60e06d71d6844fe33c8174dc83b146f7537ba5b；SimLIBS-Setup.exe 为 6009642 bytes、SHA256 为 3151fa632c7230af718c4f8c8d66b9cac09fb4d2adfb408b80deb06ebf6b6d2e。
- dist-desktop/SHA256SUMS.txt 对两个根目录文件记录相同哈希。
- 实际根目录文件哈希与 manifest、SHA256SUMS 和对应 release 源文件一致：
  - dist-desktop/SimLIBS.exe: 4f3c96b0e5891e693e3c259cd60e06d71d6844fe33c8174dc83b146f7537ba5b
  - dist-desktop/SimLIBS-Setup.exe: 3151fa632c7230af718c4f8c8d66b9cac09fb4d2adfb408b80deb06ebf6b6d2e

未运行浏览器测试或构建，未修改源码、task.json 或原 review.md。该补核与原 T005 pass 结论一致，只更新交付事实：T005 现在已有根目录 EXE/NSIS 正式产物。

COLLECTION_COMPLETE taskId=T005 dispatchId=16a6adbb-5162-4d9f-a23d-44b91e20f0e1 revision=1 verdict=pass
