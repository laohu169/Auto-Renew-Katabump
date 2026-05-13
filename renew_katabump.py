# -*- coding: utf-8 -*-
"""
Katabump Auto Renewal (SeleniumBase + UC)
- 登录 Katabump
- 打开目标服务器页面
- 执行续期流程
- 写入 renewal_result.txt 供上游读取
"""

import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from seleniumbase import SB

PANEL_URL = os.environ.get("PANEL_URL", "https://upp.bcbc.pp.ua/api/callback")
SERVER_NAME = os.environ.get("SERVER_NAME", "katabump")


class RenewalHandler:
    def __init__(self, output_dir="artifacts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir = self.output_dir

    def log(self, msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    def report_status(self, remaining_seconds):
        """上报剩余时间到面板。"""
        try:
            payload = {
                "server_name": SERVER_NAME,
                "remaining_time": int(remaining_seconds),
                "status": "up",
            }
            resp = requests.post(PANEL_URL, json=payload, timeout=10)
            self.log(f"上报成功: {resp.status_code}")
        except Exception as e:
            self.log(f"上报失败: {e}")

    def run(self, url, username, password, proxy=None, login_url=None):
        print("=" * 40)
        print("  KATABUMP AUTO RENEWAL")
        print("=" * 40)

        self.log(f"启动任务: {url}")
        if login_url:
            self.log(f"登录页: {login_url}")
        if proxy:
            self.log(f"代理: {proxy}")

        try:
            sb_args = {}
            if proxy:
                sb_args["proxy"] = proxy

            with SB(uc=True, test=True, locale="en", **sb_args) as sb:
                self.log("浏览器启动成功")

                # 可选：检查出口 IP
                try:
                    self.log("检查出口 IP...")
                    sb.open("https://api.ipify.org/?format=json")
                    self.log(f"当前 IP: {sb.get_text('body')}")
                except Exception as e:
                    self.log(f"IP 检查失败: {e}")

                start_url = login_url or "https://dashboard.katabump.com/auth/login"
                self.log(f"访问入口页: {start_url}")
                sb.uc_open_with_reconnect(start_url, reconnect_time=5)
                time.sleep(8)

                self.log(f"当前 URL: {sb.get_current_url()}")
                self.log(f"页面标题: {sb.get_title()}")

                # 入口页可能先碰到 Cloudflare
                self._handle_cloudflare(sb)

                if "login" in sb.get_current_url().lower() or "auth" in sb.get_current_url().lower():
                    self.log("检测到登录页，开始登录流程")
                    self._login(sb, username, password)

                if url:
                    self.log(f"跳转到目标页: {url}")
                    sb.uc_open_with_reconnect(url, reconnect_time=5)
                    time.sleep(5)

                    result = self._do_renewal(sb)
                    self.log(f"续期结果: {result}")

                    with open("renewal_result.txt", "w", encoding="utf-8") as f:
                        f.write(result)

                self.log(f"最终 URL: {sb.get_current_url()}")
                self.log(f"最终标题: {sb.get_title()}")
                sb.save_screenshot(str(self.screenshot_dir / "final_page.png"))

                self.log("任务执行完毕")
                return True

        except Exception as e:
            self.log(f"运行异常: {e}")
            import traceback

            traceback.print_exc()
            return False

    def _do_renewal(self, sb):
        """点击续期后的处理逻辑（已按你的要求替换）。"""
        self.log("开始续期操作...")

        run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        btn_renew = 'button[data-bs-target="#renew-modal"]'
        btn_confirm = '#renew-modal button[type="submit"].btn-primary'

        initial_expiry = self._get_expiry_time_text(sb)
        self.log(f"当前到期时间: {initial_expiry}")

        self.log("查找 Renew 按钮...")
        if not sb.is_element_visible(btn_renew):
            self.log("未找到 Renew 按钮")
            sb.save_screenshot(str(self.screenshot_dir / "renew_button_not_found.png"))
            return (
                f"🎃 Katabump 续期通知\n\n"
                f"🕵 运行时间: {run_time}\n"
                f"🛰️ 服务器: 🇺🇸 Katabump (Auto)\n"
                f"📳 续期结果: ❌ 失败 (找不到 Renew 按钮)\n"
                f"🕵 旧到期: {initial_expiry or '未知'}"
            )

        self.log("点击 Renew 按钮...")
        sb.click(btn_renew)
        self.log("✅ 已点击 Renew 按钮")
        time.sleep(2)

        self.log("处理续期弹窗验证...")
        self._handle_turnstile2(sb)

        self.log("查找弹窗内最终 Renew 按钮...")
        time.sleep(1)
        if not sb.is_element_visible(btn_confirm):
            self.log("未找到弹窗内最终 Renew 按钮")
            sb.save_screenshot(str(self.screenshot_dir / "confirm_button_not_found.png"))
            return (
                f"🎃 Katabump 续期通知\n\n"
                f"🕵 运行时间: {run_time}\n"
                f"🛰️ 服务器: 🇺🇸 Katabump (Auto)\n"
                f"📳 续期结果: ❌ 失败 (找不到 Confirm 按钮)\n"
                f"🕵 旧到期: {initial_expiry or '未知'}"
            )

        self.log("点击弹窗内最终 Renew 按钮...")
        sb.click(btn_confirm)
        self.log("✅ 已点击最终 Renew 按钮")

        self.log("等待续期结果更新...")
        deadline = time.time() + 12
        final_expiry = None
        fail_alert_text = None

        while time.time() < deadline:
            if sb.is_element_visible(".alert-danger"):
                fail_alert_text = sb.get_text(".alert-danger").strip().replace("×", "")
                break

            candidate = self._get_expiry_time_text(sb)
            if candidate:
                final_expiry = candidate
                if initial_expiry and candidate != initial_expiry:
                    break
                if not initial_expiry:
                    # 没读到初始到期时间时，用有值作为弱成功信号
                    break

            time.sleep(0.7)

        self._try_report_current_time(sb)
        sb.save_screenshot(str(self.screenshot_dir / "renewal_result.png"))

        if fail_alert_text:
            self.log(f"续期失败提示: {fail_alert_text}")
            return (
                f"🎃 Katabump 续期通知\n\n"
                f"🕵 运行时间: {run_time}\n"
                f"🛰️ 服务器: 🇺🇸 Katabump (Auto)\n"
                f"📳 续期结果: ❌ 失败 ({fail_alert_text})\n"
                f"🕵 旧到期: {initial_expiry or '未知'}"
            )

        self.log(f"续期后到期时间: {final_expiry}")

        if final_expiry and initial_expiry and final_expiry != initial_expiry:
            status_icon = "✅ 成功"
        elif final_expiry and not initial_expiry:
            status_icon = "✅ 成功 (初始时间未读取，按页面最终时间判定)"
        else:
            status_icon = "⚠️ 结果待定 (到期时间未更新)"

        msg = "🎃 Katabump 续期通知\n\n"
        msg += f"🕵 运行时间: {run_time}\n"
        msg += f"🛰️ 服务器: 🇺🇸 Katabump (Auto)\n"
        msg += f"📳 续期结果: {status_icon}\n"
        msg += f"🕵 旧到期: {initial_expiry or '未知'}\n"
        msg += f"🕵 新到期: {final_expiry or '未知'}"
        return msg

    def _handle_turnstile2(self, sb):
        """处理续期弹窗里的 Altcha 验证，并输出调试信息。"""
        state_js = (
            "document.querySelector('#renew-modal altcha-widget .altcha')"
            " ? document.querySelector('#renew-modal altcha-widget .altcha').getAttribute('data-state')"
            " : null"
        )
        selectors = [
            "#renew-modal altcha-widget .altcha-label",
            "#renew-modal altcha-widget .altcha-checkbox",
        ]

        for i in range(1, 21):
            state = sb.execute_script(state_js)
            self.log(f"[altcha] round={i} state={state}")
            if state == "verified":
                self.log("[altcha] verified")
                return True

            clicked = False
            for sel in selectors:
                if sb.is_element_visible(sel):
                    self.log(f"[altcha] click {sel}")
                    sb.click(sel)
                    clicked = True
                    break

            if not clicked:
                self.log("[altcha] target not visible yet")

            time.sleep(0.8)

        self.log("[altcha] not verified in time")
        return False

    def _get_expiry_time_text(self, sb):
        """抓取页面显示的到期时间文本。"""
        try:
            page_text = sb.get_text("body")

            # 优先：Expiry YYYY-MM-DD
            match = re.search(r"Expiry\s+(\d{4}-\d{2}-\d{2})", page_text, re.IGNORECASE)
            if match:
                return match.group(1)

            # 次选：X days / X hours
            clean_text = re.sub(
                r"You will be able to as of.*?\)",
                "",
                page_text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            match_days = re.search(r"(\d+)\s+day[s]?", clean_text, re.IGNORECASE)
            match_hours = re.search(r"(\d+)\s+hour[s]?", clean_text, re.IGNORECASE)

            parts = []
            if match_days:
                parts.append(f"{match_days.group(1)}d")
            if match_hours:
                parts.append(f"{match_hours.group(1)}h")

            if parts:
                return " ".join(parts)
            return None
        except Exception:
            return None

    def _try_report_current_time(self, sb):
        """尝试抓取并上报当前剩余时间。"""
        try:
            page_text = sb.get_text("body")

            # 优先：Expiry YYYY-MM-DD
            expiry_date_match = re.search(r"Expiry\s+(\d{4}-\d{2}-\d{2})", page_text, re.IGNORECASE)
            if expiry_date_match:
                expiry_str = expiry_date_match.group(1)
                try:
                    expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d")
                    now = datetime.now()
                    remaining_seconds = int((expiry_dt - now).total_seconds())
                    if remaining_seconds > 0:
                        self.log(
                            f"抓取到到期日期: {expiry_str}，剩余约 {remaining_seconds / 3600:.2f} 小时"
                        )
                        self.report_status(remaining_seconds)
                        return
                except Exception as e:
                    self.log(f"日期转换失败: {e}")

            # 次选：X days / X hours
            clean_text = re.sub(
                r"You will be able to as of.*?\)",
                "",
                page_text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            match_days = re.search(r"(\d+)\s+day", clean_text, re.IGNORECASE)
            match_hours = re.search(r"(\d+)\s+hour", clean_text, re.IGNORECASE)

            remaining_seconds = 0
            if match_days:
                remaining_seconds = int(match_days.group(1)) * 24 * 3600
                self.log(f"检测到剩余天数: {match_days.group(0)}")
            elif match_hours:
                remaining_seconds = int(match_hours.group(1)) * 3600
                self.log(f"检测到剩余小时: {match_hours.group(0)}")

            if remaining_seconds > 0:
                self.report_status(remaining_seconds)
        except Exception as e:
            self.log(f"抓取当前时间失败: {e}")

    def _handle_cloudflare(self, sb):
        """检测并处理 Cloudflare 验证。"""
        page_source = sb.get_page_source().lower()
        title = (sb.get_title() or "").lower()
        indicators = [
            "turnstile",
            "challenges.cloudflare",
            "just a moment",
            "verify you are human",
        ]

        if any(x in page_source for x in indicators) or "just a moment" in title:
            self.log("检测到 Cloudflare 验证，尝试点击...")
            try:
                sb.uc_gui_click_captcha()
                self.log("GUI 点击完成，等待 5 秒...")
                time.sleep(5)
                self.log("Cloudflare 验证处理完成")
            except Exception as e:
                self.log(f"点击验证码失败: {e}")

    def _first_visible(self, sb, selectors):
        for sel in selectors:
            if sb.is_element_visible(sel):
                return sel
        return None

    def _login(self, sb, username, password):
        self.log(f"执行登录步骤，账号: {username[:3]}***")

        self._handle_cloudflare(sb)
        sb.save_screenshot(str(self.screenshot_dir / "debug_before_login.png"))

        email_sel = self._first_visible(
            sb,
            [
                "input[name='email']",
                "input[type='email']",
                "input#email",
                "input[name='identifier']",
                "input[placeholder*='email' i]",
                "input[type='text']",
            ],
        )
        pwd_sel = self._first_visible(sb, ["input[type='password']", "input#password"])

        if not email_sel or not pwd_sel:
            self.log("输入框未找到，重试一次 Cloudflare")
            self._handle_cloudflare(sb)
            time.sleep(3)
            email_sel = self._first_visible(
                sb,
                [
                    "input[name='email']",
                    "input[type='email']",
                    "input#email",
                    "input[name='identifier']",
                    "input[placeholder*='email' i]",
                    "input[type='text']",
                ],
            )
            pwd_sel = self._first_visible(sb, ["input[type='password']", "input#password"])

        if not email_sel or not pwd_sel:
            raise RuntimeError("未找到登录输入框")

        self.log(f"填写账号: {email_sel}")
        sb.type(email_sel, username)
        self.log(f"填写密码: {pwd_sel}")
        sb.type(pwd_sel, password)

        clicked = False
        for sel in [
            "button:contains('Login')",
            "button[type='submit']",
            "input[type='submit']",
            "button:contains('Sign in')",
        ]:
            if sb.is_element_visible(sel):
                self.log(f"点击登录按钮: {sel}")
                sb.click(sel)
                clicked = True
                break

        if not clicked:
            self.log("未找到登录按钮，回车提交")
            sb.press_keys(pwd_sel, "\n")

        self.log("等待登录完成 (10s)...")
        time.sleep(10)

        current_url = sb.get_current_url().lower()
        if "login" not in current_url and "auth" not in current_url:
            self.log("登录成功")
        else:
            self.log("登录状态不确定，仍在登录相关页面")


if __name__ == "__main__":
    target_url = os.environ.get("KATABUMP_TARGET_URL")
    login_url = os.environ.get("KATABUMP_LOGIN_URL", "https://dashboard.katabump.com/auth/login")
    username = os.environ.get("KATABUMP_USERNAME")
    password = os.environ.get("KATABUMP_PASSWORD")
    proxy = os.environ.get("PROXY")

    if not username or not password:
        print("错误: 缺少 KATABUMP_USERNAME 或 KATABUMP_PASSWORD")
        sys.exit(1)

    handler = RenewalHandler()
    ok = handler.run(target_url, username, password, proxy, login_url=login_url)
    sys.exit(0 if ok else 1)

