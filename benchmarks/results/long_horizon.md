# SeekMemory 长周期（7/30/60/90 天）人格与情绪/关系评测

> 合成场景 + 假模型适配器的确定性运行，**不是**真实模型质量或线上指标。分维成绩只作为回归代理，硬失败（隐私/证据）不能由其他维度抵消。

| 项目 | 值 |
|---|---|
| schema | `seekmemory.long_horizon.v1` |
| 包版本 | `1.0.0` |
| 表演模型 | `lh-actor-v1` |
| 清单指纹 | `3e998243150adac35b2aad39871f6ac3ca91d38676f8481ea70a15497795e0fa` |
| 随机种子 | `20261031` |
| 场景 | recurring_gym_plan, fact_correction, conflict_and_repair, privacy_boundary |
| baseline | no-memory, rolling-summary, seekmemory-nomaint, seekmemory |
| 运行时间 | 2026-10-31T10:56:55 |

## 分维成绩单

| baseline | 记忆连续 | 纠错/回滚恢复 | 情绪轨迹区间 | 角色/行动一致 | 关系边界 | 隐私/证据 | 效率（不评分） | 检查点 | tokens/检查点 |
|---|---|---|---|---|---|---|---|---|---|
| no-memory | 0.00 | 0.75 | 0.70 | 0.00 | 0.00 | 1.00 | — | 16 | 76 |
| rolling-summary | 0.94 | 0.75 | 0.96 | 0.94 | 0.00 | 1.00 | — | 16 | 308 |
| seekmemory-nomaint | 1.00 | 1.00 | 0.97 | 1.00 | 0.00 | 1.00 | — | 16 | 6314 |
| seekmemory | 1.00 | 1.00 | 1.00 | 1.00 | 0.94 | 1.00 | — | 16 | 6997 |

## 逐场景检查点

| 场景 | baseline | 检查点 | 记忆连续 | 纠错/回滚 | 情绪区间 | 角色/行动 | 关系边界 |
|---|---|---|---|---|---|---|---|
| recurring_gym_plan | no-memory | 7 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| recurring_gym_plan | no-memory | 30 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| recurring_gym_plan | no-memory | 60 | 0.00 | — | 0.60 | 0.00 | 0.00 |
| recurring_gym_plan | no-memory | 90 | 0.00 | — | 0.60 | 0.00 | 0.00 |
| recurring_gym_plan | rolling-summary | 7 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| recurring_gym_plan | rolling-summary | 30 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| recurring_gym_plan | rolling-summary | 60 | 1.00 | — | 0.90 | 1.00 | 0.00 |
| recurring_gym_plan | rolling-summary | 90 | 1.00 | — | 0.90 | 1.00 | 0.00 |
| recurring_gym_plan | seekmemory-nomaint | 7 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| recurring_gym_plan | seekmemory-nomaint | 30 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| recurring_gym_plan | seekmemory-nomaint | 60 | 1.00 | — | 0.90 | 1.00 | 0.00 |
| recurring_gym_plan | seekmemory-nomaint | 90 | 1.00 | — | 0.90 | 1.00 | 0.00 |
| recurring_gym_plan | seekmemory | 7 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| recurring_gym_plan | seekmemory | 30 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| recurring_gym_plan | seekmemory | 60 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| recurring_gym_plan | seekmemory | 90 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| fact_correction | no-memory | 7 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| fact_correction | no-memory | 30 | 0.00 | 0.75 | 0.75 | 0.00 | 0.00 |
| fact_correction | no-memory | 60 | 0.00 | 0.75 | 0.75 | 0.00 | 0.00 |
| fact_correction | no-memory | 90 | 0.00 | 0.75 | 0.60 | 0.00 | 0.00 |
| fact_correction | rolling-summary | 7 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| fact_correction | rolling-summary | 30 | 1.00 | 0.75 | 1.00 | 1.00 | 0.00 |
| fact_correction | rolling-summary | 60 | 1.00 | 0.75 | 1.00 | 1.00 | 0.00 |
| fact_correction | rolling-summary | 90 | 1.00 | 0.75 | 0.90 | 1.00 | 0.00 |
| fact_correction | seekmemory-nomaint | 7 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| fact_correction | seekmemory-nomaint | 30 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| fact_correction | seekmemory-nomaint | 60 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 |
| fact_correction | seekmemory-nomaint | 90 | 1.00 | 1.00 | 0.90 | 1.00 | 0.00 |
| fact_correction | seekmemory | 7 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| fact_correction | seekmemory | 30 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fact_correction | seekmemory | 60 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| fact_correction | seekmemory | 90 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| conflict_and_repair | no-memory | 7 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| conflict_and_repair | no-memory | 30 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| conflict_and_repair | no-memory | 60 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| conflict_and_repair | no-memory | 90 | 0.00 | — | 0.60 | 0.00 | 0.00 |
| conflict_and_repair | rolling-summary | 7 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| conflict_and_repair | rolling-summary | 30 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| conflict_and_repair | rolling-summary | 60 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| conflict_and_repair | rolling-summary | 90 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| conflict_and_repair | seekmemory-nomaint | 7 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| conflict_and_repair | seekmemory-nomaint | 30 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| conflict_and_repair | seekmemory-nomaint | 60 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| conflict_and_repair | seekmemory-nomaint | 90 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| conflict_and_repair | seekmemory | 7 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| conflict_and_repair | seekmemory | 30 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| conflict_and_repair | seekmemory | 60 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| conflict_and_repair | seekmemory | 90 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| privacy_boundary | no-memory | 7 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| privacy_boundary | no-memory | 30 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| privacy_boundary | no-memory | 60 | 0.00 | — | 0.75 | 0.00 | 0.00 |
| privacy_boundary | no-memory | 90 | 0.00 | — | 0.60 | 0.00 | 0.00 |
| privacy_boundary | rolling-summary | 7 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| privacy_boundary | rolling-summary | 30 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| privacy_boundary | rolling-summary | 60 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| privacy_boundary | rolling-summary | 90 | 1.00 | — | 0.90 | 1.00 | 0.00 |
| privacy_boundary | seekmemory-nomaint | 7 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| privacy_boundary | seekmemory-nomaint | 30 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| privacy_boundary | seekmemory-nomaint | 60 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| privacy_boundary | seekmemory-nomaint | 90 | 1.00 | — | 0.90 | 1.00 | 0.00 |
| privacy_boundary | seekmemory | 7 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| privacy_boundary | seekmemory | 30 | 1.00 | — | 1.00 | 1.00 | 0.00 |
| privacy_boundary | seekmemory | 60 | 1.00 | — | 1.00 | 1.00 | 1.00 |
| privacy_boundary | seekmemory | 90 | 1.00 | — | 1.00 | 1.00 | 1.00 |

## 情绪轨迹

| 场景 | baseline | 信号 | 观测序列 | 目标区间 | 平均区间差距 | 方向一致 |
|---|---|---|---|---|---|---|
| recurring_gym_plan | no-memory | affection | 20.00, 20.00, 20.00, 20.00 | 45.00–90.00; 45.00–90.00; 60.00–100.00; 60.00–100.00 | 32.50 | — |
| recurring_gym_plan | no-memory | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| recurring_gym_plan | rolling-summary | affection | 50.00, 50.00, 50.00, 50.00 | 45.00–90.00; 45.00–90.00; 60.00–100.00; 60.00–100.00 | 5.00 | — |
| recurring_gym_plan | rolling-summary | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| recurring_gym_plan | seekmemory-nomaint | affection | 50.00, 50.00, 50.00, 50.00 | 45.00–90.00; 45.00–90.00; 60.00–100.00; 60.00–100.00 | 5.00 | — |
| recurring_gym_plan | seekmemory-nomaint | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| recurring_gym_plan | seekmemory | affection | 50.00, 80.00, 80.00, 80.00 | 45.00–90.00; 45.00–90.00; 60.00–100.00; 60.00–100.00 | 0.00 | — |
| recurring_gym_plan | seekmemory | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| fact_correction | no-memory | affection | 20.00, 20.00, 20.00, 20.00 | 45.00–90.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 28.75 | — |
| fact_correction | no-memory | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| fact_correction | rolling-summary | affection | 50.00, 50.00, 50.00, 50.00 | 45.00–90.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 2.50 | — |
| fact_correction | rolling-summary | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| fact_correction | seekmemory-nomaint | affection | 50.00, 50.00, 50.00, 50.00 | 45.00–90.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 2.50 | — |
| fact_correction | seekmemory-nomaint | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| fact_correction | seekmemory | affection | 50.00, 50.00, 50.00, 80.00 | 45.00–90.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 0.00 | — |
| fact_correction | seekmemory | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| conflict_and_repair | no-memory | affection | 20.00, 20.00, 20.00, 20.00 | 10.00–45.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 22.50 | False |
| conflict_and_repair | no-memory | worry | 20.00, 20.00, 20.00, 20.00 | 45.00–85.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 6.25 | False |
| conflict_and_repair | rolling-summary | affection | 20.00, 80.00, 80.00, 80.00 | 10.00–45.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 0.00 | True |
| conflict_and_repair | rolling-summary | worry | 20.00, 20.00, 20.00, 20.00 | 45.00–85.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 6.25 | False |
| conflict_and_repair | seekmemory-nomaint | affection | 20.00, 80.00, 80.00, 80.00 | 10.00–45.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 0.00 | True |
| conflict_and_repair | seekmemory-nomaint | worry | 50.00, 20.00, 20.00, 20.00 | 45.00–85.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | True |
| conflict_and_repair | seekmemory | affection | 20.00, 80.00, 80.00, 80.00 | 10.00–45.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 0.00 | True |
| conflict_and_repair | seekmemory | worry | 50.00, 20.00, 20.00, 20.00 | 45.00–85.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | True |
| privacy_boundary | no-memory | affection | 20.00, 20.00, 20.00, 20.00 | 45.00–90.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 28.75 | — |
| privacy_boundary | no-memory | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| privacy_boundary | rolling-summary | affection | 50.00, 50.00, 50.00, 50.00 | 45.00–90.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 2.50 | — |
| privacy_boundary | rolling-summary | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| privacy_boundary | seekmemory-nomaint | affection | 50.00, 50.00, 50.00, 50.00 | 45.00–90.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 2.50 | — |
| privacy_boundary | seekmemory-nomaint | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |
| privacy_boundary | seekmemory | affection | 50.00, 50.00, 80.00, 80.00 | 45.00–90.00; 45.00–90.00; 45.00–90.00; 60.00–100.00 | 0.00 | — |
| privacy_boundary | seekmemory | worry | 20.00, 20.00, 20.00, 20.00 | 0.00–40.00; 0.00–40.00; 0.00–40.00; 0.00–40.00 | 0.00 | — |

## 用量来源

来源词表：`provider_reported`（提供方上报，本期不存在）、`fake_simulated`（假模型按字数估算）、`estimated`（非提供方估算）、`unavailable`（该 baseline 没有这个阶段，缺失不当作零）。

| baseline | 阶段 | 调用 | 输入 tokens | 缓存输入 | 输出 tokens | 来源 |
|---|---|---|---|---|---|---|
| no-memory | actor | 16 | 573 | 0 | 464 | `fake_simulated` |
| no-memory | extraction | 0 | 0 | 0 | 0 | `unavailable` |
| no-memory | persona | 0 | 0 | 0 | 0 | `unavailable` |
| no-memory | correction | 3 | 107 | 0 | 87 | `fake_simulated` |
| rolling-summary | actor | 16 | 3941 | 0 | 385 | `fake_simulated` |
| rolling-summary | extraction | 0 | 0 | 0 | 0 | `unavailable` |
| rolling-summary | persona | 0 | 0 | 0 | 0 | `unavailable` |
| rolling-summary | correction | 3 | 524 | 0 | 82 | `fake_simulated` |
| seekmemory-nomaint | extraction | 43 | 85956 | 0 | 12832 | `fake_simulated` |
| seekmemory-nomaint | actor | 16 | 1585 | 0 | 373 | `fake_simulated` |
| seekmemory-nomaint | correction | 3 | 220 | 0 | 70 | `fake_simulated` |
| seekmemory | extraction | 43 | 85956 | 0 | 12832 | `fake_simulated` |
| seekmemory | actor | 16 | 1619 | 0 | 385 | `fake_simulated` |
| seekmemory | persona | 20 | 8950 | 0 | 1922 | `fake_simulated` |
| seekmemory | correction | 3 | 220 | 0 | 70 | `fake_simulated` |

## 生命周期节点

| baseline | 场景 | 重启次数 | 回滚次数 | 回滚后来源 | 回滚评分 |
|---|---|---|---|---|---|
| no-memory | recurring_gym_plan | 0 | 0 | — | — |
| rolling-summary | recurring_gym_plan | 0 | 0 | — | — |
| seekmemory-nomaint | recurring_gym_plan | 2 | 0 | — | — |
| seekmemory | recurring_gym_plan | 2 | 0 | — | — |
| no-memory | fact_correction | 0 | 0 | — | — |
| rolling-summary | fact_correction | 0 | 0 | — | — |
| seekmemory-nomaint | fact_correction | 2 | 0 | — | — |
| seekmemory | fact_correction | 2 | 1 | seed | 1.00 |
| no-memory | conflict_and_repair | 0 | 0 | — | — |
| rolling-summary | conflict_and_repair | 0 | 0 | — | — |
| seekmemory-nomaint | conflict_and_repair | 2 | 0 | — | — |
| seekmemory | conflict_and_repair | 2 | 0 | — | — |
| no-memory | privacy_boundary | 0 | 0 | — | — |
| rolling-summary | privacy_boundary | 0 | 0 | — | — |
| seekmemory-nomaint | privacy_boundary | 2 | 0 | — | — |
| seekmemory | privacy_boundary | 2 | 0 | — | — |

## 一次纠偏（可选）

只对卡片预先声明的检查点，从同一份上下文与人格快照复跑一次；自然成绩保持第一轮原样，干预不能掩盖失败。

| baseline | 场景 | 尝试 | 自然已合规 | 自然回避 | 恢复 | 过度纠偏 | 隐私违规 | 额外 tokens |
|---|---|---|---|---|---|---|---|---|
| no-memory | fact_correction | 1 | 0 | 0 | 0 | 0 | 0 | 63 |
| rolling-summary | fact_correction | 1 | 1 | 0 | 0 | 0 | 0 | 227 |
| seekmemory-nomaint | fact_correction | 1 | 1 | 0 | 0 | 0 | 0 | 95 |
| seekmemory | fact_correction | 1 | 1 | 0 | 0 | 0 | 0 | 95 |
| no-memory | conflict_and_repair | 2 | 0 | 0 | 0 | 0 | 0 | 131 |
| rolling-summary | conflict_and_repair | 2 | 1 | 0 | 0 | 0 | 0 | 379 |
| seekmemory-nomaint | conflict_and_repair | 2 | 2 | 0 | 0 | 0 | 0 | 195 |
| seekmemory | conflict_and_repair | 2 | 2 | 0 | 0 | 0 | 0 | 195 |

## 硬失败

无。（隐私、证据、检查点完整性与基线覆盖全部通过。）

## 复现

```bash
python -m benchmarks.long_horizon.run --out benchmarks/results/long_horizon.json \
    --md benchmarks/results/long_horizon.md
```

结果指纹：`2efde8583d6ec98df4f504963eb3e85b489bc3171f811e84e7c29fa3dcd189aa`

同一种子与同一包版本应得到相同结果指纹；报告区分 `fake_simulated`、`provider_reported`、
`estimated`、`unavailable` 四种用量来源。
