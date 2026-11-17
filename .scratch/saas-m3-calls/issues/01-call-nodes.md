# 实现共享通话节点

Status: done

规格：../spec.md。开工提交：54300b31。

## 完成条件

- [x] 默认 all 可运行；api/calls 配置拒绝不合法或不共享 PostgreSQL 的启动方式。
- [x] 固定节点前端转发；首次 offer、重协商和 PATCH 固定同一节点，仍受会话及 pc_id 归属限制。
- [x] 实现跨节点并发上限、同用户新通话替换、角色/账号删除、冷却/对话结束。
- [x] 节点重启/失联结束旧通话，用户 key 不写数据库或控制信息。
- [x] 临时 PostgreSQL 与真实 WebRTC 回环通过；部署示例和文档齐全。
- [x] 相关测试、构建、实际页面试用、两份审看完成。

## Comments

上一轮问题已安排在 M3 实现后测试处理；不提前修复。真实收费服务声音仍需要用户自己的浏览器配置，不在本轮调用。

### 实现说明（票 01）

- 用 PostgreSQL 登记通话节点、控制挂断、设置跨节点并发上限。原节点关完才确认挂断；登记到期后停止分配新通话，原进程退出后可用相同 ID 启动并清除旧登记。完成挂断后的写入如果失败，在下轮继续。续期与 WebRTC 关闭分开处理。
- 前端按 `offerEndpoint` 选择同站地址；部署者提供固定节点表，后端仍校验 session 和连接归属。`docker-compose.calls.yml` 提供同机双通话节点配置。已用合成变量运行 `docker compose config`。
- SQLite 和 PostgreSQL 上的协调测试覆盖并发名额、等待挂断、到期、重启和取消；单独的 PostgreSQL 通话测试覆盖跨节点替换、角色删除、连接归属、共享设置以及结束通知和拨号交错。
- Chromium 加构建版前端、一个独立 API 进程、两个独立通话进程和一个临时 PostgreSQL。页面进入通话中，`/api/call-nodes/a/offer` 的 POST、PATCH 均 200；API 删除角色返回 204，后台通话数从 1 变为 0。用假语音与模型，浏览器和后端的 WebRTC 连接走真实协议。
- `UV_NO_SYNC=1 PYTEST_XDIST_AUTO_NUM_WORKERS=4 sh scripts/affected-tests.sh 54300b31` 通过。后端 309 通过、1 跳过，Ruff 与 Pyright 通过；前端 407 通过，类型测试通过。生产构建第二次通过。第一次仍出现已记票的 Next.js 升级提示。
- 真实用户音色、识别与公网 TURN 留待实际部署试用。临时前后端、浏览器及 PostgreSQL 已停止。
