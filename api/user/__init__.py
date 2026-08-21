"""api.user:用户管理模块(独立包,基于 RBAC)。

子模块:
- models:   ORM 模型(User / Role / Permission / 关联表)
- schemas:  Pydantic 请求/响应模型
- auth:     密码哈希 / JWT token / FastAPI 鉴权依赖
- services:用户/角色/权限业务逻辑 + 默认数据初始化
- routers:  登录 + 用户/角色/权限 CRUD 路由

在 api.main 中通过 `from api.user.routers import router` 引入。
"""
