#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam 手机令牌验证器 - Android 版 (Kivy)
==========================================

这是原 Tkinter 桌面版的 Android 移植版本。核心算法(TOTP 生成、
mobileconf 签名、账号数据模型、网络请求)与桌面版完全一致,未做任何
修改；只是把界面层从 Tkinter 换成了 Kivy, 以便通过 buildozer 打包成 APK。

依赖:
    kivy>=2.3.0
    requests>=2.31.0
    plyer>=2.1.0   (用于调用系统文件选择器 / 剪贴板, Android 上更可靠)

打包方式见同目录下的 buildozer.spec 和 README_ANDROID.md。
"""

import base64
import hashlib
import hmac
import json
import os
import struct
import threading
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.properties import StringProperty, NumericProperty, ListProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.recycleview import RecycleView
from kivy.uix.filechooser import FileChooserListView

try:
    import requests
except ImportError:
    raise SystemExit("缺少 requests 库, 请先运行: pip install requests")

try:
    from android.storage import app_storage_path  # type: ignore
    ANDROID = True
except Exception:
    ANDROID = False


# --------------------------------------------------------------------------
# 常量 (与桌面版一致)
# --------------------------------------------------------------------------

STEAM_GUARD_ALPHABET = "23456789BCDFGHJKMNPQRTVWXY"  # 真实 Steam Guard 字母表 (26 字符)
CODE_LENGTH = 5
USER_AGENT = ("Mozilla/5.0 (Linux; Android 9; Steam App) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/100.0.0.0 Mobile Safari/537.36 Steam Mobile Client")
BASE_URL = "https://steamcommunity.com"
REQUEST_TIMEOUT = 15


def _config_dir() -> str:
    if ANDROID:
        return app_storage_path()
    return os.path.expanduser("~")


CONFIG_FILE = os.path.join(_config_dir(), "steam_desktop_auth_accounts.json")


# --------------------------------------------------------------------------
# 核心算法: TOTP 验证码生成 (与桌面版逐字一致)
# --------------------------------------------------------------------------

def generate_steam_guard_code(shared_secret_b64: str, time_offset: int = 0) -> str:
    try:
        secret_bytes = base64.b64decode(shared_secret_b64)
    except Exception as exc:
        raise ValueError(f"shared_secret 不是合法的 Base64 字符串: {exc}")

    if not secret_bytes:
        raise ValueError("shared_secret 解码后为空")

    timestamp = int(time.time() + time_offset) // 30
    time_bytes = struct.pack(">Q", timestamp)
    hashed = hmac.new(secret_bytes, time_bytes, hashlib.sha1).digest()

    offset = hashed[19] & 0x0F
    part = hashed[offset:offset + 4]
    full_code = struct.unpack(">I", part)[0] & 0x7FFFFFFF

    code_value = full_code % 100000
    alphabet = STEAM_GUARD_ALPHABET
    alphabet_len = len(alphabet)

    chars = []
    value = code_value
    for _ in range(CODE_LENGTH):
        chars.append(alphabet[value % alphabet_len])
        value //= alphabet_len

    return "".join(chars)


def generate_confirmation_key(identity_secret_b64: str, tag: str, timestamp: int) -> str:
    try:
        secret_bytes = base64.b64decode(identity_secret_b64)
    except Exception as exc:
        raise ValueError(f"identity_secret 不是合法的 Base64 字符串: {exc}")

    buffer = struct.pack(">Q", timestamp) + tag.encode("utf-8")
    digest = hmac.new(secret_bytes, buffer, hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_confirmation_params(account: "SteamAccount", tag: str) -> dict:
    timestamp = int(time.time())
    key = generate_confirmation_key(account.identity_secret, tag, timestamp)
    return {
        "p": account.device_id,
        "a": account.steamid,
        "k": key,
        "t": str(timestamp),
        "m": "android",
        "tag": tag,
    }


# --------------------------------------------------------------------------
# 账号数据模型 (与桌面版一致)
# --------------------------------------------------------------------------

class SteamAccount:
    def __init__(self, data: dict, filepath: str = ""):
        self.filepath = filepath
        self.raw = data

        self.shared_secret = data.get("shared_secret", "")
        self.identity_secret = data.get("identity_secret", "")
        self.revocation_code = data.get("revocation_code", "")
        self.serial_number = data.get("serial_number", "")
        self.account_name = data.get("account_name") or data.get("AccountName") or "未知账号"

        session_info = data.get("Session") or {}
        self.steamid = str(session_info.get("SteamID") or data.get("steamid") or "")
        self.session_id = session_info.get("SessionID", "")
        self.steam_login_secure = session_info.get("SteamLoginSecure", "")
        self.web_cookie = session_info.get("WebCookie", "")

        self.device_id = data.get("device_id") or self._derive_device_id()

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._apply_cookies()

        self.time_offset = 0

    def _derive_device_id(self) -> str:
        seed = (self.steamid or self.account_name or self.shared_secret).encode("utf-8", "ignore")
        digest = hashlib.sha1(seed).hexdigest()
        return "android:" + "-".join(
            [digest[0:8], digest[8:12], digest[12:16], digest[16:20], digest[20:32]]
        )

    def _apply_cookies(self):
        if self.steam_login_secure:
            self.session.cookies.set("steamLoginSecure", self.steam_login_secure, domain="steamcommunity.com")
        if self.session_id:
            self.session.cookies.set("sessionid", self.session_id, domain="steamcommunity.com")

    def has_valid_session(self) -> bool:
        return bool(self.steam_login_secure and self.session_id and self.steamid)

    def fetch_confirmations(self) -> list:
        if not self.has_valid_session():
            raise RuntimeError("账号缺少有效的登录 Session, 请重新导出 .maFile")

        params = build_confirmation_params(self, "conf")
        url = f"{BASE_URL}/mobileconf/getlist"

        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.Timeout:
            raise RuntimeError("请求超时: 获取确认列表失败")
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"网络连接错误: {exc}")
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"请求异常: {exc}")

        if resp.status_code != 200:
            raise RuntimeError(f"获取确认列表失败, HTTP 状态码: {resp.status_code}")

        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError("服务器返回内容不是有效 JSON, 登录态可能已失效")

        if not data.get("success", False):
            raise RuntimeError(f"密钥失效或请求被拒绝: {data.get('message', '未知错误')}")

        return data.get("conf", [])

    def respond_to_confirmation(self, conf_id: str, conf_key: str, approve: bool) -> bool:
        if not self.has_valid_session():
            raise RuntimeError("账号缺少有效的登录 Session, 无法执行确认操作")

        tag = "allow" if approve else "cancel"
        params = build_confirmation_params(self, tag)
        params.update({
            "op": "allow" if approve else "deny",
            "cid": conf_id,
            "ck": conf_key,
        })
        url = f"{BASE_URL}/mobileconf/ajaxop"

        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.Timeout:
            raise RuntimeError("请求超时: 提交确认操作失败")
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"网络连接错误: {exc}")
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"请求异常: {exc}")

        if resp.status_code != 200:
            raise RuntimeError(f"操作失败, HTTP 状态码: {resp.status_code}")

        try:
            data = resp.json()
        except ValueError:
            raise RuntimeError("服务器返回内容不是有效 JSON")

        return bool(data.get("success", False))


class ConfirmationItem:
    def __init__(self, raw: dict):
        self.raw = raw
        self.id = str(raw.get("id", ""))
        self.nonce = str(raw.get("nonce", ""))
        self.creator_id = str(raw.get("creator_id", raw.get("creator", "")))
        conf_type = raw.get("type", 0)
        self.type_name = {1: "通用确认", 2: "交易报价", 3: "市场上架"}.get(conf_type, f"未知类型({conf_type})")
        self.headline = raw.get("headline", "")
        self.summary = "; ".join(raw.get("summary", [])) if isinstance(raw.get("summary"), list) else raw.get("summary", "")
        self.cid = self.id
        self.cref = self.nonce


def load_saved_account_paths() -> list:
    if not os.path.exists(CONFIG_FILE):
        return []
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("paths", [])
    except Exception:
        return []


def save_account_paths(paths: list):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"paths": paths}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Kivy UI
# --------------------------------------------------------------------------

KV = """
#:import dp kivy.metrics.dp

<ConfRow@BoxLayout>:
    orientation: "vertical"
    size_hint_y: None
    height: dp(92)
    padding: dp(8)
    spacing: dp(4)
    canvas.before:
        Color:
            rgba: 0.93, 0.93, 0.93, 1
        Rectangle:
            pos: self.pos
            size: self.size
    conf_type: ""
    summary: ""
    peer: ""
    conf_id: ""
    on_approve: None
    on_deny: None

    BoxLayout:
        size_hint_y: None
        height: dp(20)
        Label:
            text: "[b]" + root.conf_type + "[/b]  来源ID: " + root.peer
            markup: True
            color: 0.2, 0.2, 0.2, 1
            font_size: "13sp"
            halign: "left"
            text_size: self.size

    Label:
        text: root.summary
        color: 0, 0, 0, 1
        font_size: "14sp"
        halign: "left"
        valign: "top"
        text_size: self.size

    BoxLayout:
        size_hint_y: None
        height: dp(32)
        spacing: dp(8)
        Button:
            text: "批准"
            background_color: 0.2, 0.6, 0.3, 1
            on_release: root.on_approve(root.conf_id) if root.on_approve else None
        Button:
            text: "拒绝"
            background_color: 0.7, 0.25, 0.25, 1
            on_release: root.on_deny(root.conf_id) if root.on_deny else None

<RootWidget>:
    orientation: "vertical"
    padding: dp(10)
    spacing: dp(8)

    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(6)
        Spinner:
            id: account_spinner
            text: "请导入账号"
            values: []
            on_text: root.on_account_selected(self.text)
        Button:
            text: "导入 .maFile"
            size_hint_x: 0.4
            on_release: root.open_file_chooser()

    Label:
        id: status_label
        text: ""
        size_hint_y: None
        height: dp(20)
        font_size: "12sp"
        color: 0.6, 0.1, 0.1, 1

    BoxLayout:
        size_hint_y: None
        height: dp(120)
        spacing: dp(10)

        BoxLayout:
            orientation: "vertical"
            Label:
                id: code_label
                text: "-----"
                font_size: "48sp"
                bold: True
                color: 0.1, 0.4, 0.75, 1
            Button:
                text: "复制验证码"
                size_hint_y: None
                height: dp(32)
                on_release: root.copy_code()

        BoxLayout:
            orientation: "vertical"
            Label:
                text: "下次刷新倒计时"
                size_hint_y: None
                height: dp(20)
                font_size: "12sp"
            ProgressBar:
                id: progress
                max: 30
                value: 0
            Label:
                id: countdown_label
                text: "30 秒"
                size_hint_y: None
                height: dp(20)

    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(8)
        Button:
            text: "获取确认"
            on_release: root.fetch_confirmations()
        Button:
            text: "全部批准"
            on_release: root.approve_all()
        Label:
            id: fetch_status_label
            text: ""
            font_size: "12sp"

    RecycleView:
        id: rv
        viewclass: "ConfRow"
        RecycleBoxLayout:
            default_size: None, dp(92)
            default_size_hint: 1, None
            size_hint_y: None
            height: self.minimum_height
            orientation: "vertical"
"""


class RootWidget(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.accounts = {}          # name -> SteamAccount
        self.current_account = None
        self.confirmations = []
        self._file_popup = None

        Clock.schedule_once(lambda dt: self._load_persisted_accounts(), 0.2)
        Clock.schedule_interval(self._tick, 0.2)

    # ---------------- 账号管理 ----------------

    def open_file_chooser(self):
        chooser = FileChooserListView(filters=["*.maFile", "*.json"], path=os.path.expanduser("~"))
        btn_box = BoxLayout(size_hint_y=None, height="44dp", spacing="8dp")
        select_btn = Button(text="选择")
        cancel_btn = Button(text="取消")
        btn_box.add_widget(select_btn)
        btn_box.add_widget(cancel_btn)

        layout = BoxLayout(orientation="vertical")
        layout.add_widget(chooser)
        layout.add_widget(btn_box)

        popup = Popup(title="选择 .maFile 文件", content=layout, size_hint=(0.9, 0.9))
        self._file_popup = popup

        def do_select(_):
            if chooser.selection:
                path = chooser.selection[0]
                ok = self._load_account_from_path(path)
                if ok:
                    self._refresh_spinner()
                    self._persist_account_paths()
                    self._set_status(f"成功导入账号: {path}", error=False)
                else:
                    self._set_status(f"导入失败: {path}", error=True)
            popup.dismiss()

        select_btn.bind(on_release=do_select)
        cancel_btn.bind(on_release=lambda _: popup.dismiss())
        popup.open()

    def _load_account_from_path(self, path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            self._show_error(f"读取文件出错: {exc}")
            return False

        if not data.get("shared_secret") or not data.get("identity_secret"):
            self._show_error("文件缺少 shared_secret/identity_secret 字段")
            return False

        try:
            account = SteamAccount(data, filepath=path)
        except Exception as exc:
            self._show_error(f"解析账号数据出错: {exc}")
            return False

        key = account.account_name or account.steamid or os.path.basename(path)
        if key in self.accounts and self.accounts[key].steamid != account.steamid:
            key = f"{key} ({account.steamid[-4:]})"
        self.accounts[key] = account
        return True

    def _load_persisted_accounts(self):
        for p in load_saved_account_paths():
            if os.path.exists(p):
                self._load_account_from_path(p)
        self._refresh_spinner()

    def _persist_account_paths(self):
        paths = [acc.filepath for acc in self.accounts.values() if acc.filepath]
        save_account_paths(paths)

    def _refresh_spinner(self):
        names = list(self.accounts.keys())
        spinner = self.ids.account_spinner
        spinner.values = names
        if names and (not spinner.text or spinner.text == "请导入账号"):
            spinner.text = names[0]
            self.on_account_selected(names[0])

    def on_account_selected(self, name: str):
        self.current_account = self.accounts.get(name)
        self.confirmations = []
        self._refresh_conf_list()
        if self.current_account and not self.current_account.has_valid_session():
            self._set_status("警告: 该账号缺少登录 Session, 无法拉取/操作确认 (验证码仍可正常生成)", error=True)
        else:
            self._set_status("", error=False)

    def _set_status(self, text: str, error: bool):
        self.ids.status_label.text = text
        self.ids.status_label.color = (0.7, 0.1, 0.1, 1) if error else (0.3, 0.3, 0.3, 1)

    def _show_error(self, message: str):
        popup = Popup(title="错误", content=Label(text=message), size_hint=(0.8, 0.4))
        popup.open()

    # ---------------- 验证码刷新 ----------------

    def _tick(self, dt):
        remaining = 30 - (int(time.time()) % 30)
        self.ids.progress.value = 30 - remaining
        self.ids.countdown_label.text = f"{remaining} 秒"

        if self.current_account:
            try:
                code = generate_steam_guard_code(
                    self.current_account.shared_secret,
                    time_offset=self.current_account.time_offset,
                )
                self.ids.code_label.text = code
            except Exception as exc:
                self.ids.code_label.text = "ERROR"
                self._set_status(f"验证码生成失败: {exc}", error=True)
        else:
            self.ids.code_label.text = "-----"

    def copy_code(self):
        code = self.ids.code_label.text
        if code and code not in ("-----", "ERROR"):
            Clipboard.copy(code)
            self._set_status("验证码已复制到剪贴板", error=False)

    # ---------------- 确认列表 ----------------

    def fetch_confirmations(self):
        if not self.current_account:
            self._show_error("请先选择一个账号")
            return
        self.ids.fetch_status_label.text = "正在获取..."
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        account = self.current_account
        try:
            raw_list = account.fetch_confirmations()
            items = [ConfirmationItem(r) for r in raw_list]
            Clock.schedule_once(lambda dt: self._on_fetch_success(items), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt: self._on_fetch_error(str(exc)), 0)

    def _on_fetch_success(self, items):
        self.confirmations = items
        self._refresh_conf_list()
        self.ids.fetch_status_label.text = f"共 {len(items)} 条待确认"

    def _on_fetch_error(self, message):
        self.ids.fetch_status_label.text = "获取失败"
        self._show_error(message)

    def _refresh_conf_list(self):
        data = []
        for item in self.confirmations:
            data.append({
                "conf_type": item.type_name,
                "summary": item.summary or item.headline or "(无摘要)",
                "peer": item.creator_id,
                "conf_id": item.id,
                "on_approve": self._approve_one,
                "on_deny": self._deny_one,
            })
        self.ids.rv.data = data

    def _approve_one(self, conf_id: str):
        self._respond_one(conf_id, True)

    def _deny_one(self, conf_id: str):
        self._respond_one(conf_id, False)

    def _respond_one(self, conf_id: str, approve: bool):
        item = next((c for c in self.confirmations if c.id == conf_id), None)
        if not item or not self.current_account:
            return
        threading.Thread(target=self._respond_worker, args=(item, approve), daemon=True).start()

    def _respond_worker(self, item, approve: bool):
        account = self.current_account
        try:
            success = account.respond_to_confirmation(item.cid, item.cref, approve)
            Clock.schedule_once(lambda dt: self._on_respond_done(item, approve, success, None), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt: self._on_respond_done(item, approve, False, str(exc)), 0)

    def _on_respond_done(self, item, approve, success, error):
        action_word = "批准" if approve else "拒绝"
        if error:
            self._show_error(f"{action_word}失败: {error}")
            return
        if success:
            self.confirmations = [c for c in self.confirmations if c.id != item.id]
            self._refresh_conf_list()
            self.ids.fetch_status_label.text = f"已{action_word}: {item.summary or item.id}"
        else:
            self._show_error(f"{action_word}未成功, 可能是登录态失效")

    def approve_all(self):
        if not self.confirmations:
            self._show_error("当前没有待确认项")
            return
        threading.Thread(target=self._approve_all_worker, daemon=True).start()

    def _approve_all_worker(self):
        account = self.current_account
        items = list(self.confirmations)
        succeeded, failed = [], []
        for item in items:
            try:
                ok = account.respond_to_confirmation(item.cid, item.cref, True)
                if ok:
                    succeeded.append(item)
                else:
                    failed.append((item, "服务器返回失败"))
            except Exception as exc:
                failed.append((item, str(exc)))
            time.sleep(0.3)
        Clock.schedule_once(lambda dt: self._on_approve_all_done(succeeded, failed), 0)

    def _on_approve_all_done(self, succeeded, failed):
        if succeeded:
            ids_done = {i.id for i in succeeded}
            self.confirmations = [c for c in self.confirmations if c.id not in ids_done]
            self._refresh_conf_list()
        self.ids.fetch_status_label.text = f"成功批准 {len(succeeded)} 条, 失败 {len(failed)} 条"


class SteamAuthAndroidApp(App):
    def build(self):
        self.title = "Steam 手机令牌验证器"
        return Builder.load_string(KV)()


if __name__ == "__main__":
    SteamAuthAndroidApp().run()
