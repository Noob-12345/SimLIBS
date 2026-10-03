# 协调补充（无需重启任务）

libs_planner 已接管后续协调，原任务和顺序不变；完成后由我交现有 reviewer 独立验收。请继续当前实现与真实验证，不重复启动 agent/pane。

代码检查发现一个需要在交付前覆盖的资源边界：adapter.UISimulation.interpolate 默认仍为 .005，原 static 构造先调用它，随后 simulate 在 resample=True 时再用 p.step 插值。即使 models 按最终重采样网格限制点数，宽波段+粗步长仍可能先创建超过上限的 .005 网格。请加可复现离线测试并确保原构造期间也受资源限制（可在子类直接使用用户明确选择的步长，再调用原 interpolate），不要修改源库。其余功能按原计划继续。
