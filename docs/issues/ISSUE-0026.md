# ISSUE-0026 Recall feel fallback and shared disclosure

| item | value |
|---|---|
| id | ISSUE-0026 |
| level | P1 |
| status | open |
| date | 2026-10-22 |
| GitHub | [#9](https://github.com/NeverENG/SeekMemory/issues/9) |
| branch | feat/issue-0009-recall-feel |

# Recall feel: explicit recall fallback and shared disclosure

## Background  
- 现有系统支持**live group**共享记忆，但在显式记忆查询时常出现 `picked=0` 的问题，因为**Evidence Gate**要求词汇重叠。  
- 对第三方的共享记忆降级为 *paraphrase*，因为当前说话者的 **subject_fit** 过低。  
- 需要完善显式回忆意图处理，避免隐私泄露，保持 **private / shadow / secret** 访问限制不变。

## In scope  
- [ ] 为 `what did we talk about` 等显式回忆意图加入 **fallback** 逻辑。  
- [ ] 只在可见的 **shared / private** 记忆范围内检索，永不触及 **shadow / secret**。  
- [ ] 为同一会话的共享记忆提升 **subject_fit**，使基本共享事实可完整返回；跨会话保持 *hint/paraphrase*，秘密记忆保持不返回。  
- [ ] 编写回归测试覆盖上述新行为，确保回忆意图、记忆匹配与访问控制的正确性。  
- [ ] 保证改动不引入网络或模型调用，所有逻辑保持纯本地。

## Out of scope  
- 重新设计私密、阴影或秘密边界。  
- 修改现有模型或新增网络请求。  
- 对其它非回忆意图功能做功能扩展。  

## Acceptance Criteria  
- 对显式回忆意图（如 `what did we talk about`），系统在同会话内返回完整共享记忆；  
- 跨会话请求返回“hint/paraphrase”；  
- 隐私标记为 **shadow** 或 **secret** 的记忆永不返回；  
- 词汇重叠不足或 `subject_fit` 低时，也能利用 fallback 访问同会话共享记忆；  
- 回归测试全部通过。  

## Risks  
- 不当的 **subject_fit** 提升可能导致不相关记忆被完整返回。  
- 逻辑修改若未充分测试，可能导致新攻击向量或信息泄露。  

---  
请根据以上条目推进实现，并及时更新进展。
