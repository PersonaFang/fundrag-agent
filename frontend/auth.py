# frontend/auth.py
"""
Streamlit 用户认证模块
支持两种模式：
  simple   → 用户名/密码存 .streamlit/secrets.toml（适合小团队）
  database → 可扩展到 SQLite（适合多用户）

🌰 类比：门卫系统——进门前要验证工牌

secrets.toml 格式：
[auth]
mode = "simple"
session_timeout_hours = 8

[auth.users.admin]
password_hash = "<sha256 of password>"
role = "admin"
display_name = "管理员"
"""

from __future__ import annotations
import hashlib
import time
import streamlit as st
from typing import Optional


# ============================================================
# 密码工具
# ============================================================

def _hash_password(password: str) -> str:
    """SHA-256 哈希"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _check_password_bcrypt(password: str, hashed: str) -> bool:
    """bcrypt 校验，降级到 sha256"""
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ImportError:
        return _hash_password(password) == hashed


# ============================================================
# 配置加载
# ============================================================

def _load_users_from_secrets() -> dict:
    """从 st.secrets 加载用户配置"""
    try:
        auth_cfg = st.secrets.get("auth", {})
        return dict(auth_cfg.get("users", {}))
    except Exception:
        return {}


def _get_session_timeout() -> int:
    """获取会话超时秒数，默认 8 小时"""
    try:
        hours = st.secrets.get("auth", {}).get("session_timeout_hours", 8)
        return int(hours) * 3600
    except Exception:
        return 8 * 3600


# ============================================================
# Session State 键
# ============================================================
_KEY_LOGGED_IN    = "auth_logged_in"
_KEY_USERNAME     = "auth_username"
_KEY_ROLE         = "auth_role"
_KEY_DISPLAY_NAME = "auth_display_name"
_KEY_LOGIN_TIME   = "auth_login_time"
_KEY_FAIL_COUNT   = "auth_fail_count"


def _init_session():
    defaults = {
        _KEY_LOGGED_IN:    False,
        _KEY_USERNAME:     "",
        _KEY_ROLE:         "guest",
        _KEY_DISPLAY_NAME: "访客",
        _KEY_LOGIN_TIME:   0,
        _KEY_FAIL_COUNT:   0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ============================================================
# 认证 API
# ============================================================

def is_authenticated() -> bool:
    """检查当前会话是否已登录且未超时"""
    _init_session()
    if not _load_users_from_secrets():
        return True   # 未配置用户时直接放行（开发模式）
    if not st.session_state[_KEY_LOGGED_IN]:
        return False
    elapsed = time.time() - st.session_state[_KEY_LOGIN_TIME]
    if elapsed > _get_session_timeout():
        logout()
        return False
    return True


def get_current_user() -> dict:
    return {
        "username":     st.session_state.get(_KEY_USERNAME, ""),
        "role":         st.session_state.get(_KEY_ROLE, "guest"),
        "display_name": st.session_state.get(_KEY_DISPLAY_NAME, "访客"),
    }


def logout():
    for k in [_KEY_LOGGED_IN, _KEY_USERNAME, _KEY_ROLE, _KEY_DISPLAY_NAME, _KEY_LOGIN_TIME]:
        st.session_state[k] = False if k == _KEY_LOGGED_IN else ""
    st.session_state[_KEY_FAIL_COUNT] = 0


def _attempt_login(username: str, password: str) -> tuple:
    """
    尝试登录。返回 (success, error_message)。
    登录失败累计 5 次后锁定（防暴力破解）。
    """
    fail_count = st.session_state.get(_KEY_FAIL_COUNT, 0)
    if fail_count >= 5:
        return False, "⛔ 登录失败次数过多，请等待 5 分钟后重试"

    users = _load_users_from_secrets()
    if not users:
        # 未配置用户时任意输入都可登录（开发模式）
        st.session_state[_KEY_LOGGED_IN]    = True
        st.session_state[_KEY_USERNAME]     = username or "dev"
        st.session_state[_KEY_DISPLAY_NAME] = "开发模式"
        st.session_state[_KEY_ROLE]         = "admin"
        st.session_state[_KEY_LOGIN_TIME]   = time.time()
        return True, ""

    user_cfg = users.get(username)
    if not user_cfg:
        st.session_state[_KEY_FAIL_COUNT] = fail_count + 1
        return False, f"❌ 用户「{username}」不存在（失败 {fail_count+1}/5 次）"

    stored_hash = user_cfg.get("password_hash", "")
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        ok = _check_password_bcrypt(password, stored_hash)
    else:
        ok = (_hash_password(password) == stored_hash)

    if not ok:
        st.session_state[_KEY_FAIL_COUNT] = fail_count + 1
        return False, f"❌ 密码错误（失败 {fail_count+1}/5 次）"

    st.session_state[_KEY_LOGGED_IN]    = True
    st.session_state[_KEY_USERNAME]     = username
    st.session_state[_KEY_DISPLAY_NAME] = user_cfg.get("display_name", username)
    st.session_state[_KEY_ROLE]         = user_cfg.get("role", "analyst")
    st.session_state[_KEY_LOGIN_TIME]   = time.time()
    st.session_state[_KEY_FAIL_COUNT]   = 0
    return True, ""


# ============================================================
# 登录页面渲染
# ============================================================

def render_login_page():
    """渲染登录页（整页替换）"""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
<div style="text-align:center; margin-bottom:2rem;">
    <h1 style="font-size:2rem;">📈 FundRAG</h1>
    <p style="color:#888;">基金智能投研助手 | 请登录后使用</p>
</div>
""", unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            username  = st.text_input("用户名", placeholder="请输入用户名")
            password  = st.text_input("密码", type="password", placeholder="请输入密码")
            submitted = st.form_submit_button("🔐 登录", use_container_width=True, type="primary")

        if submitted:
            if not username or not password:
                st.warning("请输入用户名和密码")
            else:
                success, error_msg = _attempt_login(username, password)
                if success:
                    st.success("✅ 登录成功，正在跳转...")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(error_msg)

        st.markdown("""
---
<small style="color:#aaa;">
💡 如需获取账号请联系管理员<br>
⚠️ 本系统仅供学习演示，不构成投资建议
</small>
""", unsafe_allow_html=True)


# ============================================================
# 侧边栏用户信息组件
# ============================================================

def render_user_sidebar():
    """
    在侧边栏渲染用户信息 + 登出按钮。
    在 main() 中调用：
      with st.sidebar:
          from frontend.auth import render_user_sidebar
          render_user_sidebar()
    """
    user = get_current_user()
    if not user["username"]:
        return

    st.markdown(f"""
**👤 {user['display_name']}**
`{user['role']}` · {user['username']}
""")
    login_duration = int(
        (time.time() - st.session_state.get(_KEY_LOGIN_TIME, time.time())) / 60
    )
    st.caption(f"已登录 {login_duration} 分钟")

    if st.button("🚪 退出登录", use_container_width=True):
        logout()
        st.rerun()
