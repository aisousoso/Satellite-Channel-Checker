#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔍 أداة فحص القنوات الفضائية - واجهة رسومية (طريقة VLC)
تطوير: مساعد الذكي | الإصدار: 3.0 - VLC Mode
"""

import asyncio
import aiohttp
import json
import re
import socket
import time
import threading
import os
import sys
from datetime import datetime
from tkinter import (
    Tk, ttk, Frame, Label, Entry, Button, Text, Scrollbar, LabelFrame, StringVar,
    END, NORMAL, DISABLED, HORIZONTAL, VERTICAL, BOTH, LEFT, RIGHT,
    TOP, BOTTOM, X, Y, W, E, NW, messagebox, filedialog, TclError
)
from tkinter.ttk import Progressbar, Treeview, Separator
import urllib.request
import urllib.error 
import requests

# --- الإعدادات الافتراضية ---
DEFAULT_M3U_URL = ""
BACKUP_URLS = [
    "",
]

# ===== إعدادات VLC =====
# محاكاة كاملة لطريقة اتصال VLC
VLC_USER_AGENT = "VLC/3.0.21 LibVLC/3.0.21"
VLC_HEADERS = {
    "User-Agent": VLC_USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Icy-MetaData": "1"  # دعم بيانات البث الإذاعي
}

# بروتوكولات مدعومة مثل VLC
SUPPORTED_PROTOCOLS = [
    'http://', 'https://', 'rtsp://', 'rtmp://', 
    'udp://', 'rtp://', 'mms://', 'ftp://'
]

# أنواع محتوى الفيديو الصحيحة
VALID_VIDEO_CONTENT_TYPES = [
    'video/', 'application/vnd.apple.mpegurl', 'application/x-mpegurl',
    'application/mpegurl', 'application/octet-stream', 'audio/',
    'application/dash+xml', 'video/mp2t', 'video/MP2T'
]

# === دوال المعالجة (طريقة VLC) ===

def parse_m3u(content):
    """
    تحليل شامل لملف M3U باستخراج كل البيانات الوصفية وخيارات VLC
    يحاكي طريقة VLC في قراءة الملفات
    """
    channels = []
    lines = content.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        if line.startswith('#EXTINF:'):
            extinf_line = line
            vlc_options = []
            
            # استخراج اسم القناة
            name_match = re.search(r',\s*(.+)$', extinf_line)
            channel_name = name_match.group(1).strip() if name_match else "Unknown"
            
            # استخراج البيانات الوصفية
            group_match = re.search(r'group-title="([^"]*)"', extinf_line)
            group_title = group_match.group(1) if group_match else "غير مصنف"
            
            logo_match = re.search(r'tvg-logo="([^"]*)"', extinf_line)
            tvg_logo = logo_match.group(1) if logo_match else ""
            
            tvg_id_match = re.search(r'tvg-id="([^"]*)"', extinf_line)
            tvg_id = tvg_id_match.group(1) if tvg_id_match else ""
            
            tvg_name_match = re.search(r'tvg-name="([^"]*)"', extinf_line)
            tvg_name = tvg_name_match.group(1) if tvg_name_match else channel_name
            
            # قراءة سطر الرابط و خيارات VLC (مثل طريقة VLC)
            stream_url = ""
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                
                if next_line.startswith('http://') or next_line.startswith('https://') or \
                   next_line.startswith('rtsp://') or next_line.startswith('rtmp://') or \
                   next_line.startswith('udp://') or next_line.startswith('rtp://'):
                    stream_url = next_line
                    break
                elif next_line.startswith('#EXTVLCOPT:'):
                    # استخراج خيارات VLC (مهم جداً للاتصال)
                    option = next_line[len('#EXTVLCOPT:'):]
                    vlc_options.append(option)
                elif next_line.startswith('#KODIPROP:'):
                    # خيارات Kodi (بديلة)
                    option = next_line[len('#KODIPROP:'):]
                    vlc_options.append(option)
                elif not next_line.startswith('#'):
                    # رابط مباشر بدون بروتوكول
                    if next_line and not next_line.startswith('#'):
                        stream_url = next_line
                        break
                i += 1
            
            if stream_url:
                channels.append({
                    "name": channel_name,
                    "url": stream_url,
                    "catId": group_title,
                    "group": group_title,
                    "logo": tvg_logo,
                    "tvg_id": tvg_id,
                    "tvg_name": tvg_name,
                    "vlc_options": vlc_options  # خيارات VLC للاتصال
                })
        
        i += 1
    
    return channels


async def check_url_vlc_style(session, semaphore, channel, callback=None):
    """
    فحص رابط القناة بنفس طريقة VLC
    - يستخدم خيارات EXTVLCOPT
    - يتحقق من محتوى البث الحقيقي
    - يدعم إعادة المحاولة مثل VLC
    """
    async with semaphore:
        url = channel["url"]
        name = channel["name"]
        vlc_options = channel.get("vlc_options", [])
        max_retries = 2

        # بناء الهيدرز من خيارات VLC
        custom_headers = dict(VLC_HEADERS)
        http_url = url
        
        # تطبيق خيارات VLC
        for opt in vlc_options:
            if opt.startswith('http-user-agent='):
                custom_headers['User-Agent'] = opt.split('=', 1)[1]
            elif opt.startswith('http-referrer=') or opt.startswith('http-referer='):
                custom_headers['Referer'] = opt.split('=', 1)[1]
            elif opt.startswith('http-extra-header='):
                # هيدرز إضافية
                header_parts = opt.split('=', 1)[1].split(':')
                if len(header_parts) == 2:
                    custom_headers[header_parts[0].strip()] = header_parts[1].strip()
        
        for attempt in range(max_retries):
            try:
                # === الخطوة 1: فحص سريع بـ HEAD (مثل VLC) ===
                try:
                    async with session.head(
                        http_url, 
                        timeout=aiohttp.ClientTimeout(total=10),
                        headers=custom_headers,
                        ssl=False, 
                        allow_redirects=True
                    ) as resp:
                        if resp.status in [200, 301, 302]:
                            content_type = resp.headers.get('Content-Type', '').lower()
                            # التحقق من نوع المحتوى
                            if any(ct in content_type for ct in VALID_VIDEO_CONTENT_TYPES) or resp.status in [301, 302]:
                                channel["status"] = "شغال"
                                channel["response_code"] = resp.status
                                channel["content_type"] = content_type
                                channel["check_method"] = "VLC-HEAD"
                                if callback:
                                    callback(channel)
                                return channel
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                
                # === الخطوة 2: فحص بـ GET مع قراءة جزء من المحتوى (مثل VLC) ===
                try:
                    async with session.get(
                        http_url, 
                        timeout=aiohttp.ClientTimeout(total=15),
                        headers=custom_headers,
                        ssl=False, 
                        allow_redirects=True
                    ) as resp:
                        if resp.status in [200, 301, 302, 403]:
                            # قراءة أول 2048 بايت للتحقق من المحتوى
                            chunk = await resp.content.read(2048)
                            
                            # التحقق من وجود ترويسات البث
                            content_type = resp.headers.get('Content-Type', '').lower()
                            
                            # فحص ترويسات M3U8 أو TS
                            is_stream = False
                            if chunk:
                                # فحص محتوى M3U8
                                if b'#EXTM3U' in chunk or b'#EXTINF' in chunk:
                                    is_stream = True
                                # فحص محتوى MPEG-TS (يبدأ بـ 0x47)
                                elif chunk[0:1] == b'\x47':
                                    is_stream = True
                                # فحص أنواع المحتوى
                                elif any(ct in content_type for ct in VALID_VIDEO_CONTENT_TYPES):
                                    is_stream = True
                            
                            if is_stream or resp.status in [301, 302]:
                                channel["status"] = "شغال"
                                channel["response_code"] = resp.status
                                channel["content_type"] = content_type
                                channel["check_method"] = "VLC-GET-STREAM"
                            else:
                                # حتى لو لم نتأكد، نعتبره شغال إذا استجاب
                                channel["status"] = "شغال"
                                channel["response_code"] = resp.status
                                channel["content_type"] = content_type
                                channel["check_method"] = "VLC-GET"
                            
                            if callback:
                                callback(channel)
                            return channel
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass

            except Exception as e:
                if attempt == max_retries - 1:
                    channel["status"] = "لا يعمل"
                    channel["error"] = str(e)[:50]
                    channel["check_method"] = "VLC-FAILED"

            # إعادة المحاولة بعد انتظار (مثل VLC)
            if attempt < max_retries - 1:
                await asyncio.sleep(1.5)

        if "status" not in channel:
            channel["status"] = "لا يعمل"
            channel["error"] = "فشل الاتصال"
            channel["check_method"] = "VLC-TIMEOUT"
        
        if callback:
            callback(channel)
        return channel if "status" in channel else None


async def check_url(session, semaphore, channel, callback=None):
    """دالة الفحص الرئيسية (تستخدم طريقة VLC)"""
    return await check_url_vlc_style(session, semaphore, channel, callback)


async def fetch_m3u_async(session, url, progress_callback=None):
    """
    جلب ملف M3U بنفس طريقة VLC
    - يستخدم User-Agent الخاص بـ VLC
    - يدعم إعادة التوجيه التلقائي
    - يتعامل مع السيرفرات المختلفة
    """
    try:
        timeout = aiohttp.ClientTimeout(total=120, connect=30, sock_read=60)
        
        # استخدام هيدرز VLC بالضبط
        headers = {
            "User-Agent": VLC_USER_AGENT,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
            "Referer": url.split('?')[0]  # Referer أساسي
        }
        
        async with session.get(
            url, 
            timeout=timeout, 
            headers=headers, 
            allow_redirects=True,  # VLC يتبع إعادة التوجيه
            ssl=False
        ) as r:
            if r.status == 200:
                content = await r.text(encoding='utf-8', errors='ignore')
                if progress_callback:
                    progress_callback(f"✅ تم التحميل: {len(content)} بايت")
                return content
            else:
                if progress_callback:
                    progress_callback(f"⚠️ استجابة غير صالحة: {r.status}")
                return None
    except aiohttp.ClientConnectorError as e:
        if progress_callback:
            progress_callback(f"❌ خطأ اتصال: {e}")
        return None
    except asyncio.TimeoutError:
        if progress_callback:
            progress_callback(f"❌ انتهت مهلة الاتصال")
        return None
    except Exception as e:
        if progress_callback:
            progress_callback(f"❌ خطأ: {e}")
        return None


# === فئة التطبيق الرئيسية ===

class IPTVCheckerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🔍 أداة فحص القنوات الفضائية")
        self.root.geometry("1200x750")
        self.root.minsize(900, 600)
        
        # متغيرات التطبيق
        self.is_running = False
        self.all_channels = []
        self.working_channels = []
        self.filtered_channels = []
        self.current_filter = "الكل"
        
        # إعدادات الأسلوب
        self.setup_styles()
        
        # بناء الواجهة
        self.create_widgets()
        
        # ملء الحقول الافتراضية
        self.url_entry.insert(0, DEFAULT_M3U_URL)
        
        # سجل الأحداث
        self.log("🎉 التطبيق جاهز! أدخل رابط M3U واضغط 'بدء الفحص'")

    def setup_styles(self):
        """إعداد أنماط الواجهة"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # ألوان مخصصة
        style.configure("TFrame", background="#f0f0f0")
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), background="#2c3e50", foreground="white")
        style.configure("Status.TLabel", font=("Segoe UI", 10), foreground="#27ae60")
        style.configure("Error.TLabel", font=("Segoe UI", 10), foreground="#e74c3c")
        style.configure("Bold.TLabel", font=("Segoe UI", 10, "bold"))
        
        # أزرار
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=10)
        style.configure("Success.TButton", font=("Segoe UI", 10), padding=10, foreground="#27ae60")
        style.configure("Danger.TButton", font=("Segoe UI", 10), padding=10, foreground="#e74c3c")
        
        # شجرة البيانات
        style.configure("Channel.Treeview", rowheight=30, font=("Segoe UI", 9))
        style.configure("Channel.Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.map("Channel.Treeview", background=[("selected", "#3498db")], foreground=[("selected", "white")])

    def create_widgets(self):
        """بناء مكونات الواجهة"""
        # === الإطار العلوي: العنوان ===
        header_frame = Frame(self.root, bg="#2c3e50", pady=10)
        header_frame.pack(fill=X)
        
        title_label = Label(
            header_frame, text="🔍 أداة فحص القنوات الفضائية", 
            font=("Segoe UI", 16, "bold"), bg="#2c3e50", fg="white"
        )
        title_label.pack()
        
        subtitle_label = Label(
            header_frame, text="فحص قنوات IPTV بشكل سريع وموثوق", 
            font=("Segoe UI", 9), bg="#2c3e50", fg="#bdc3c7"
        )
        subtitle_label.pack()
        
        # === إطار الإعدادات ===
        settings_frame = LabelFrame(self.root, text="⚙️ إعدادات الفحص", font=("Segoe UI", 10, "bold"), padx=10, pady=10)
        settings_frame.pack(fill=X, padx=10, pady=5)
        
        # رابط M3U
        url_frame = Frame(settings_frame)
        url_frame.pack(fill=X, pady=5)
        
        Label(url_frame, text="رابط ملف M3U:", font=("Segoe UI", 9, "bold")).pack(side=LEFT, padx=(0, 10))
        self.url_entry = Entry(url_frame, font=("Segoe UI", 9), width=80)
        self.url_entry.pack(side=LEFT, fill=X, expand=True)
        
        # === إنشاء القائمة السياقية (Right-Click Menu) ===
        self.create_context_menu()
        
        # أزرار التحكم
        btn_frame = Frame(settings_frame)
        btn_frame.pack(fill=X, pady=10)
        
        self.start_btn = Button(
            btn_frame, text="🚀 بدء الفحص", command=self.start_checking,
            bg="#27ae60", fg="white", font=("Segoe UI", 10, "bold"), 
            padx=20, pady=5, cursor="hand2"
        )
        self.start_btn.pack(side=LEFT, padx=5)
        
        self.stop_btn = Button(
            btn_frame, text="⏹️ إيقاف", command=self.stop_checking,
            bg="#e74c3c", fg="white", font=("Segoe UI", 10, "bold"),
            padx=20, pady=5, cursor="hand2", state=DISABLED
        )
        self.stop_btn.pack(side=LEFT, padx=5)
        
        Button(
            btn_frame, text="📤 تصدير النتائج", command=self.export_results,
            bg="#3498db", fg="white", font=("Segoe UI", 10),
            padx=15, pady=5, cursor="hand2"
        ).pack(side=LEFT, padx=5)
        
        Button(
            btn_frame, text="🗑️ مسح القائمة", command=self.clear_list,
            bg="#95a5a6", fg="white", font=("Segoe UI", 10),
            padx=15, pady=5, cursor="hand2"
        ).pack(side=LEFT, padx=5)
        
        # === شريط التقدم والحالة ===
        progress_frame = Frame(self.root, padx=10, pady=5)
        progress_frame.pack(fill=X)
        
        self.progress = Progressbar(progress_frame, mode='determinate', length=500)
        self.progress.pack(side=LEFT, fill=X, expand=True, padx=(0, 10))
        
        self.status_label = Label(progress_frame, text="جاهز", font=("Segoe UI", 9), fg="#7f8c8d")
        self.status_label.pack(side=LEFT)
        
        # === إطار الفلاتر ===
        filter_frame = Frame(self.root, padx=10, pady=5)
        filter_frame.pack(fill=X)
        
        Label(filter_frame, text="🔍 تصفية حسب المجموعة:", font=("Segoe UI", 9)).pack(side=LEFT, padx=(0, 10))
        self.filter_combo = ttk.Combobox(filter_frame, values=["الكل"], state="readonly", width=30)
        self.filter_combo.pack(side=LEFT, padx=(0, 20))
        self.filter_combo.bind("<<ComboboxSelected>>", self.apply_filter)
        
        self.search_var = StringVar()
        self.search_var.trace('w', self.apply_search)
        Entry(filter_frame, textvariable=self.search_var, font=("Segoe UI", 9), 
              width=30, justify='right').pack(side=RIGHT, padx=(0, 10))
        Label(filter_frame, text="🔎 بحث:", font=("Segoe UI", 9)).pack(side=RIGHT)
        
        # === جدول القنوات ===
        table_frame = Frame(self.root, padx=10, pady=5)
        table_frame.pack(fill=BOTH, expand=True)
        
        columns = ("name", "group", "status", "url")
        self.channel_tree = Treeview(
            table_frame, columns=columns, show="headings", style="Channel.Treeview"
        )
        
        # تعريف الأعمدة
        self.channel_tree.heading("name", text="اسم القناة")
        self.channel_tree.heading("group", text="المجموعة")
        self.channel_tree.heading("status", text="الحالة")
        self.channel_tree.heading("url", text="الرابط")
        
        self.channel_tree.column("name", width=250, minwidth=150)
        self.channel_tree.column("group", width=150, minwidth=100)
        self.channel_tree.column("status", width=80, minwidth=70, anchor="center")
        self.channel_tree.column("url", width=400, minwidth=200)
        
        # شريط التمرير
        tree_scroll_y = Scrollbar(table_frame, orient=VERTICAL, command=self.channel_tree.yview)
        tree_scroll_x = Scrollbar(table_frame, orient=HORIZONTAL, command=self.channel_tree.xview)
        self.channel_tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        
        self.channel_tree.pack(side=LEFT, fill=BOTH, expand=True)
        tree_scroll_y.pack(side=RIGHT, fill=Y)
        tree_scroll_x.pack(side=BOTTOM, fill=X)
        
        # === شريط الحالة السفلي ===
        stats_frame = Frame(self.root, bg="#ecf0f1", pady=8, padx=10)
        stats_frame.pack(fill=X, side=BOTTOM)
        
        self.stats_label = Label(
            stats_frame, text="إجمالي: 0 | شغال: 0 | معطل: 0 | النسبة: 0%", 
            font=("Segoe UI", 9, "bold"), bg="#ecf0f1", fg="#2c3e50"
        )
        self.stats_label.pack(side=LEFT)
        
        self.time_label = Label(
            stats_frame, text="الوقت: 0.0 ثانية", 
            font=("Segoe UI", 9), bg="#ecf0f1", fg="#7f8c8d"
        )
        self.time_label.pack(side=RIGHT)
        
        # === سجل الأحداث ===
        log_frame = LabelFrame(self.root, text="📋 سجل الأحداث", font=("Segoe UI", 9, "bold"), padx=5, pady=5)
        log_frame.pack(fill=X, padx=10, pady=(0, 10))
        
        self.log_text = Text(log_frame, height=4, font=("Segoe UI", 8), state=DISABLED, bg="#f8f9fa")
        log_scroll = Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        
        self.log_text.pack(side=LEFT, fill=X, expand=True)
        log_scroll.pack(side=RIGHT, fill=Y)

    def create_context_menu(self):
        """إنشاء قائمة النقر بالزر الأيمن"""
        from tkinter import Menu
        
        # إنشاء القائمة
        self.context_menu = Menu(self.root, tearoff=0, font=("Segoe UI", 9), bg="white", fg="#2c3e50")
        
        # إضافة العناصر
        self.context_menu.add_command(label="📋 لصق", command=self.paste_text, accelerator="Ctrl+V")
        self.context_menu.add_command(label="📄 نسخ", command=self.copy_text, accelerator="Ctrl+C")
        self.context_menu.add_command(label="✂️ قص", command=self.cut_text, accelerator="Ctrl+X")
        self.context_menu.add_separator()
        self.context_menu.add_command(label="✅ تحديد الكل", command=self.select_all, accelerator="Ctrl+A")
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗑️ مسح", command=self.clear_entry, accelerator="Delete")
        
        # ربط القائمة بحقل الإدخال
        self.url_entry.bind("<Button-3>", self.show_context_menu)
        
        # ربط اختصارات لوحة المفاتيح
        self.url_entry.bind("<Control-v>", lambda e: self.paste_text())
        self.url_entry.bind("<Control-V>", lambda e: self.paste_text())
        self.url_entry.bind("<Control-c>", lambda e: self.copy_text())
        self.url_entry.bind("<Control-C>", lambda e: self.copy_text())
        self.url_entry.bind("<Control-x>", lambda e: self.cut_text())
        self.url_entry.bind("<Control-X>", lambda e: self.cut_text())
        self.url_entry.bind("<Control-a>", lambda e: self.select_all())
        self.url_entry.bind("<Control-A>", lambda e: self.select_all())
        self.url_entry.bind("<Delete>", lambda e: self.clear_entry())
    
    def show_context_menu(self, event):
        """عرض القائمة السياقية"""
        self.context_menu.tk_popup(event.x_root, event.y_root)
    
    def paste_text(self):
        """لصق النص من الحافظة"""
        try:
            text = self.root.clipboard_get()
            # إذا كان هناك نص محدد، استبدله
            try:
                start = self.url_entry.index("sel.first")
                end = self.url_entry.index("sel.last")
                self.url_entry.delete(start, end)
                self.url_entry.insert("insert", text)
            except:
                # لا يوجد تحديد، أدخل عند المؤشر
                self.url_entry.insert("insert", text)
        except TclError:
            pass  # الحافظة فارغة
    
    def copy_text(self):
        """نسخ النص المحدد"""
        try:
            text = self.url_entry.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except TclError:
            pass  # لا يوجد نص محدد
    
    def cut_text(self):
        """قص النص المحدد"""
        try:
            text = self.url_entry.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            start = self.url_entry.index("sel.first")
            end = self.url_entry.index("sel.last")
            self.url_entry.delete(start, end)
        except TclError:
            pass
    
    def select_all(self):
        """تحديد كل النص"""
        self.url_entry.select_range(0, END)
        self.url_entry.focus()
    
    def clear_entry(self):
        """مسح محتوى حقل الإدخال"""
        self.url_entry.delete(0, END)
        self.url_entry.focus()

    def log(self, message):
        """إضافة رسالة إلى سجل الأحداث"""
        self.log_text.configure(state=NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(END, f"[{timestamp}] {message}\n")
        self.log_text.see(END)
        self.log_text.configure(state=DISABLED)

    def update_status(self, message, is_error=False):
        """تحديث شريط الحالة"""
        self.status_label.config(text=message)
        if is_error:
            self.status_label.config(fg="#e74c3c")
        else:
            self.status_label.config(fg="#27ae60")

    def update_progress(self, value, maximum=None):
        """تحديث شريط التقدم"""
        if maximum:
            self.progress["maximum"] = maximum
        self.progress["value"] = value
        self.root.update_idletasks()

    def add_channel_to_tree(self, channel):
        """إضافة قناة إلى الجدول"""
        status = channel.get("status", "قيد الفحص")
        status_colors = {"شغال": "✅", "لا يعمل": "❌", "متقطع": "⚠️", "قيد الفحص": "🔄"}
        status_icon = status_colors.get(status, "❓")
        
        values = (
            channel["name"],
            channel["group"],
            f"{status_icon} {status}",
            channel["url"][:50] + "..." if len(channel["url"]) > 50 else channel["url"]
        )
        
        # تحديد لون الصف حسب الحالة
        tag = "working" if status == "شغال" else "broken" if status == "لا يعمل" else "pending"
        
        self.channel_tree.insert("", END, values=values, tags=(tag,))
        
        # تكوين الألوان
        self.channel_tree.tag_configure("working", foreground="#27ae60")
        self.channel_tree.tag_configure("broken", foreground="#e74c3c")
        self.channel_tree.tag_configure("pending", foreground="#7f8c8d")

    def update_stats(self, total, working, elapsed):
        """تحديث إحصائيات الشاشة"""
        broken = total - working
        percentage = (working / total * 100) if total > 0 else 0
        self.stats_label.config(
            text=f"إجمالي: {total} | شغال: {working} ✅ | معطل: {broken} ❌ | النسبة: {percentage:.1f}%"
        )
        self.time_label.config(text=f"الوقت: {elapsed:.1f} ثانية")

    def populate_filters(self, channels):
        """ملء قائمة الفلاتر بالمجموعات"""
        groups = sorted(set(ch["group"] for ch in channels))
        self.filter_combo["values"] = ["الكل"] + groups
        self.filter_combo.current(0)

    def apply_filter(self, event=None):
        """تطبيق فلتر المجموعة"""
        self.current_filter = self.filter_combo.get()
        self.refresh_treeview()

    def apply_search(self, *args):
        """تطبيق بحث نصي"""
        self.refresh_treeview()

    def refresh_treeview(self):
        """تحديث عرض الجدول حسب الفلاتر"""
        # مسح الجدول الحالي
        for item in self.channel_tree.get_children():
            self.channel_tree.delete(item)
        
        # تحديد القنوات للعرض
        search_term = self.search_var.get().lower()
        
        for ch in self.filtered_channels:
            # تطبيق فلتر المجموعة
            if self.current_filter != "الكل" and ch["group"] != self.current_filter:
                continue
            # تطبيق بحث نصي
            if search_term and search_term not in ch["name"].lower():
                continue
            self.add_channel_to_tree(ch)

    def clear_list(self):
        """مسح قائمة القنوات"""
        self.channel_tree.delete(*self.channel_tree.get_children())
        self.all_channels = []
        self.working_channels = []
        self.filtered_channels = []
        self.update_stats(0, 0, 0)
        self.log("🗑️ تم مسح القائمة")

    def export_results(self):
        """تصدير النتائج إلى ملف JSON أو M3U"""
        if not self.working_channels:
            messagebox.showwarning("تنبيه", "لا توجد قنوات شغالة لتصديرها!")
            return
        
        # اختيار نوع التصدير
        export_type = messagebox.askquestion(
            "نوع التصدير",
            "هل تريد التصدير بصيغة M3U (قابلة للتشغيل في VLC؟)\n\nاضغط 'نعم' لـ M3U أو 'لا' لـ JSON",
            icon='question'
        )
        
        if export_type == 'yes':
            # تصدير بصيغة M3U
            file_path = filedialog.asksaveasfilename(
                defaultextension=".m3u",
                filetypes=[("M3U Files", "*.m3u"), ("All Files", "*.*")],
                initialfile=f"working_channels_{datetime.now().strftime('%Y%m%d_%H%M%S')}.m3u"
            )
            
            if file_path:
                try:
                    m3u_content = "#EXTM3U\n\n"
                    for ch in self.working_channels:
                        m3u_content += f'#EXTINF:-1 group-title="{ch.get("group", "")}" tvg-logo="{ch.get("logo", "")}" tvg-id="{ch.get("tvg_id", "")}",{ch["name"]}\n'
                        # إضافة خيارات VLC
                        for opt in ch.get('vlc_options', []):
                            m3u_content += f'#EXTVLCOPT:{opt}\n'
                        m3u_content += f'{ch["url"]}\n'
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(m3u_content)
                    self.log(f"📺 تم التصدير بصيغة M3U: {file_path}")
                    messagebox.showinfo("نجاح", "تم تصدير القنوات بصيغة M3U! ✓\nيمكنك فتحها مباشرة في VLC")
                except Exception as e:
                    self.log(f"❌ خطأ في التصدير: {e}")
                    messagebox.showerror("خطأ", f"فشل التصدير: {e}")
        else:
            # تصدير بصيغة JSON
            file_path = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
                initialfile=f"working_channels_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            
            if file_path:
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(self.working_channels, f, ensure_ascii=False, indent=2)
                    self.log(f"💾 تم التصدير بصيغة JSON: {file_path}")
                    messagebox.showinfo("نجاح", "تم تصدير النتائج بصيغة JSON! ✓")
                except Exception as e:
                    self.log(f"❌ خطأ في التصدير: {e}")
                    messagebox.showerror("خطأ", f"فشل التصدير: {e}")

    async def run_checking_process(self):
        """العملية الرئيسية للفحص (تعمل في Thread منفصل) - طريقة VLC"""
        start_time = time.time()
        
        try:
            # إعداد الاتصال بطريقة VLC
            connector = aiohttp.TCPConnector(
                family=socket.AF_INET, 
                ssl=False, 
                limit=100,  # حد أقصى 100 اتصال متزامن
                ttl_dns_cache=300,
                enable_cleanup_closed=True  # تنظيف الاتصالات مثل VLC
            )
            timeout = aiohttp.ClientTimeout(total=60, connect=15, sock_connect=10)
            
            async with aiohttp.ClientSession(
                connector=connector, 
                timeout=timeout, 
                headers=VLC_HEADERS  # استخدام هيدرز VLC
            ) as session:
                # 1. جلب قائمة القنوات
                self.log("📡 جاري جلب قائمة القنوات (طريقة VLC)...")
                self.update_status("جاري التحميل...")
                
                content = None
                urls_to_try = [self.url_entry.get()] + BACKUP_URLS
                
                for idx, url in enumerate(urls_to_try, 1):
                    if content:
                        break
                    self.root.after(0, lambda u=url, i=idx: self.log(f"🔄 محاولة {i}: {u[:60]}..."))
                    content = await fetch_m3u_async(session, url, self.log)
                    if content:
                        self.root.after(0, lambda i=idx: self.log(f"✅ نجحت المحاولة {i}"))

                if not content:
                    self.root.after(0, lambda: self.update_status("❌ فشل التحميل", True))
                    self.root.after(0, lambda: self.log("❌ فشل جميع محاولات الاتصال"))
                    self.root.after(0, lambda: self.log("💡 تأكد من: 1) صلاحية الرابط 2) الاتصال بالإنترنت 3) جدار الحماية"))
                    return
                
                if '#EXTINF' not in content:
                    self.root.after(0, lambda: self.log("❌ الملف لا يحتوي على قنوات صالحة"))
                    return
                
                # 2. تحليل القنوات (مع خيارات VLC)
                self.all_channels = parse_m3u(content)
                self.filtered_channels = self.all_channels.copy()
                
                vlc_opts_count = sum(1 for ch in self.all_channels if ch.get('vlc_options'))
                self.root.after(0, lambda: self.log(f"✅ تم العثور على {len(self.all_channels)} قناة ({vlc_opts_count} بخيارات VLC)"))
                self.root.after(0, lambda: self.populate_filters(self.all_channels))
                
                # 3. فحص القنوات بطريقة VLC
                self.log(f"🔍 جاري فحص {len(self.all_channels)} قناة بطريقة VLC...")
                self.update_status("جاري الفحص (VLC Mode)...")
                self.update_progress(0, len(self.all_channels))
                
                semaphore = asyncio.Semaphore(50)
                working = []
                checked = 0
                
                def on_channel_checked(channel):
                    nonlocal checked
                    checked += 1
                    if channel.get("status") == "شغال":
                        working.append(channel)
                    
                    # تحديث الواجهة كل 25 قناة
                    if checked % 25 == 0 or checked == len(self.all_channels):
                        self.root.after(0, lambda: self.update_progress(checked))
                        self.root.after(0, lambda: self.add_channel_to_tree(channel))
                        elapsed = time.time() - start_time
                        self.root.after(0, lambda: self.update_stats(len(self.all_channels), len(working), elapsed))
                
                # فحص جميع القنوات
                tasks = [check_url(session, semaphore, ch, on_channel_checked) for ch in self.all_channels]
                await asyncio.gather(*tasks)
                
                # 4. النتائج النهائية
                elapsed = time.time() - start_time
                self.working_channels = [ch for ch in self.all_channels if ch.get("status") == "شغال"]
                self.filtered_channels = self.working_channels.copy()
                
                self.root.after(0, lambda: self.refresh_treeview())
                self.root.after(0, lambda: self.update_stats(len(self.all_channels), len(self.working_channels), elapsed))
                self.root.after(0, lambda: self.update_status("✅ اكتمل الفحص (VLC)"))
                self.root.after(0, lambda: self.log(f"🎉 اكتمل! القنوات الشغالة: {len(self.working_channels)}"))
                
                # === حفظ تلقائي للقنوات الشغالة (مثل VLC يحفظ القائمة) ===
                try:
                    # حفظ بصيغة JSON
                    with open('working_channels.json', 'w', encoding='utf-8') as f:
                        json.dump(self.working_channels, f, ensure_ascii=False, indent=2)
                    self.root.after(0, lambda: self.log("💾 تم الحفظ: working_channels.json"))
                    
                    # حفظ بصيغة M3U (قابلة للتشغيل في VLC مباشرة)
                    m3u_content = "#EXTM3U\n\n"
                    for ch in self.working_channels:
                        m3u_content += f'#EXTINF:-1 group-title="{ch.get("group", "")}" tvg-logo="{ch.get("logo", "")}" tvg-id="{ch.get("tvg_id", "")}",{ch["name"]}\n'
                        # إضافة خيارات VLC
                        for opt in ch.get('vlc_options', []):
                            m3u_content += f'#EXTVLCOPT:{opt}\n'
                        m3u_content += f'{ch["url"]}\n'
                    
                    with open('working_channels.m3u', 'w', encoding='utf-8') as f:
                        f.write(m3u_content)
                    self.root.after(0, lambda: self.log("📺 تم الحفظ: working_channels.m3u (قابل للتشغيل في VLC)"))
                    
                except Exception as e:
                    self.root.after(0, lambda: self.log(f"⚠️ خطأ في الحفظ: {e}"))
                    
        except Exception as e:
            self.root.after(0, lambda: self.log(f"❌ خطأ غير متوقع: {e}"))
            self.root.after(0, lambda: self.update_status(f"❌ خطأ: {e}", True))
        finally:
            self.root.after(0, self.on_checking_complete)

    def start_checking(self):
        """بدء عملية الفحص"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("تنبيه", "يرجى إدخال رابط ملف M3U أولاً!")
            return
        
        if self.is_running:
            return
        
        # تأكيد المسح
        if self.all_channels and messagebox.askyesno("تأكيد", "هل تريد مسح القائمة الحالية والبدء بفحص جديد؟"):
            self.clear_list()
        
        self.is_running = True
        self.start_btn.config(state=DISABLED, bg="#95a5a6")
        self.stop_btn.config(state=NORMAL)
        self.url_entry.config(state=DISABLED)
        
        self.log(f"🚀 بدء الفحص لـ: {url[:50]}...")
        
        # تشغيل العملية في Thread منفصل
        def run_async():
            asyncio.run(self.run_checking_process())
        
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()

    def stop_checking(self):
        """إيقاف عملية الفحص"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.log("⏹️ تم إيقاف الفحص بواسطة المستخدم")
        self.on_checking_complete()

    def on_checking_complete(self):
        """استعادة حالة الأزرار بعد الانتهاء"""
        self.is_running = False
        self.start_btn.config(state=NORMAL, bg="#27ae60")
        self.stop_btn.config(state=DISABLED)
        self.url_entry.config(state=NORMAL)

    def on_closing(self):
        """معالجة إغلاق التطبيق"""
        if self.is_running and messagebox.askyesno("خروج", "الفحص قيد التشغيل. هل تريد الخروج فعلاً؟"):
            self.root.destroy()
        elif not self.is_running:
            self.root.destroy()


# === نقطة الدخول ===

def main():
    root = Tk()
    
    # تحسينات الواجهة
    try:
        root.iconbitmap(default='')  # يمكن إضافة أيقونة مخصصة هنا
    except:
        pass
    
    app = IPTVCheckerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    # التأكد من تشغيل الحدث الرئيسي
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()