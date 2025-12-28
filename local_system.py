import hashlib
import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime
from tkinter import messagebox, filedialog, simpledialog, scrolledtext

import matplotlib.pyplot as plt
import pandas as pd
import ttkbootstrap as ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from ttkbootstrap.constants import *
from ttkbootstrap.widgets import DateEntry

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# ===========================
# 0. 全局日志
# ===========================
logging.basicConfig(filename='system.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    encoding='utf-8')


def log_action(user, action, details=""):
    msg = f"User: [{user}] | Action: [{action}] | {details}"
    logging.info(msg);
    print(msg)


# ===========================
# 1. 配置管理器
# ===========================
class ConfigManager:
    def __init__(self, config_file="config.json"):
        self.config_file = config_file
        self.data = self.load_config()

    def load_config(self):
        default = {"auto_login": False, "last_user": "", "theme": "cosmo"}
        if not os.path.exists(self.config_file): return default
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                d = json.load(f);
                return {**default, **d}
        except:
            return default

    def save_config(self, auto_login, last_user, theme=None):
        self.data["auto_login"] = auto_login;
        self.data["last_user"] = last_user
        if theme: self.data["theme"] = theme
        with open(self.config_file, "w", encoding="utf-8") as f: json.dump(self.data, f)

    def clear_auto_login(self):
        self.data["auto_login"] = False
        with open(self.config_file, "w", encoding="utf-8") as f: json.dump(self.data, f)


# ===========================
# 2. 后端逻辑
# ===========================
class DatabaseManager:
    def __init__(self, db_name="local_data.db"):
        self.db_name = db_name
        self.init_db()
        self.check_and_migrate()

    def init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS folders
                              (
                                  id
                                  INTEGER
                                  PRIMARY
                                  KEY
                                  AUTOINCREMENT,
                                  name
                                  TEXT
                                  NOT
                                  NULL,
                                  owner
                                  TEXT
                                  NOT
                                  NULL,
                                  created_at
                                  TIMESTAMP
                                  DEFAULT
                                  CURRENT_TIMESTAMP
                              )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS records
                              (
                                  id
                                  INTEGER
                                  PRIMARY
                                  KEY
                                  AUTOINCREMENT,
                                  user_seq
                                  INTEGER,
                                  uid
                                  TEXT,
                                  content
                                  TEXT
                                  NOT
                                  NULL,
                                  category
                                  TEXT
                                  DEFAULT
                                  '未分类',
                                  deadline
                                  TEXT,
                                  owner
                                  TEXT,
                                  status
                                  INTEGER
                                  DEFAULT
                                  0,
                                  priority
                                  TEXT
                                  DEFAULT
                                  '中',
                                  folder_id
                                  INTEGER
                                  DEFAULT
                                  0,
                                  created_at
                                  TIMESTAMP
                                  DEFAULT
                                  CURRENT_TIMESTAMP
                              )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS users
                              (
                                  username
                                  TEXT
                                  PRIMARY
                                  KEY,
                                  password_hash
                                  TEXT
                                  NOT
                                  NULL
                              )''')
            conn.commit()

    def check_and_migrate(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor();
            cursor.execute("PRAGMA table_info(records)");
            cols = [info[1] for info in cursor.fetchall()]
            if "folder_id" not in cols: cursor.execute("ALTER TABLE records ADD COLUMN folder_id INTEGER DEFAULT 0")
            if "owner" not in cols: cursor.execute("ALTER TABLE records ADD COLUMN owner TEXT")
            if "user_seq" not in cols: cursor.execute(
                "ALTER TABLE records ADD COLUMN user_seq INTEGER"); self.recalculate_all_sequences()
            if "category" not in cols: cursor.execute("ALTER TABLE records ADD COLUMN category TEXT DEFAULT '未分类'")
            if "deadline" not in cols: cursor.execute("ALTER TABLE records ADD COLUMN deadline TEXT")
            if "status" not in cols: cursor.execute("ALTER TABLE records ADD COLUMN status INTEGER DEFAULT 0")
            if "priority" not in cols: cursor.execute("ALTER TABLE records ADD COLUMN priority TEXT DEFAULT '中'")
            conn.commit()

    def recalculate_all_sequences(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor();
            cursor.execute("SELECT DISTINCT owner FROM records")
            for owner in cursor.fetchall():
                cursor.execute("SELECT id FROM records WHERE owner = ? ORDER BY id ASC", (owner[0],))
                rows = cursor.fetchall();
                current_seq = 1
                for row in rows: cursor.execute("UPDATE records SET user_seq = ? WHERE id = ?",
                                                (current_seq, row[0])); current_seq += 1
            conn.commit()

    def _hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    def has_users(self):
        with sqlite3.connect(self.db_name) as conn: return conn.execute("SELECT count(*) FROM users").fetchone()[0] > 0

    def register_user(self, username, password):
        if not username or not password: return False, "用户名密码不能为空"
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                             (username, self._hash_password(password)))
                conn.execute("INSERT INTO folders (name, owner) VALUES (?, ?)", ("默认文件夹", username))
                conn.commit()
            log_action("SYSTEM", "New User Registered", f"Username: {username}");
            return True, "注册成功"
        except sqlite3.IntegrityError:
            return False, "用户名已存在"

    def login_check(self, username, password):
        with sqlite3.connect(self.db_name) as conn:
            res = conn.execute("SELECT password_hash FROM users WHERE username = ?", (username,)).fetchone()
            if res and res[0] == self._hash_password(password): log_action(username, "Login Success"); return True
            log_action(username, "Login Failed", "Incorrect password");
            return False

    def get_folders(self, owner):
        with sqlite3.connect(self.db_name) as conn:
            folders = conn.execute("SELECT id, name FROM folders WHERE owner = ? ORDER BY id", (owner,)).fetchall()
            if not folders:
                conn.execute("INSERT INTO folders (name, owner) VALUES (?, ?)", ("默认文件夹", owner));
                conn.commit()
                folders = conn.execute("SELECT id, name FROM folders WHERE owner = ? ORDER BY id", (owner,)).fetchall()
            return folders

    def add_folder(self, name, owner):
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute("INSERT INTO folders (name, owner) VALUES (?, ?)", (name, owner)); conn.commit()
            return True, ""
        except Exception as e:
            return False, str(e)

    def delete_folder(self, folder_id, owner):
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute("DELETE FROM records WHERE folder_id = ? AND owner = ?", (folder_id, owner))
                conn.execute("DELETE FROM folders WHERE id = ? AND owner = ?", (folder_id, owner));
                conn.commit()
            return True, ""
        except Exception as e:
            return False, str(e)

    def rename_folder(self, folder_id, new_name, owner):
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute("UPDATE folders SET name = ? WHERE id = ? AND owner = ?",
                             (new_name, folder_id, owner)); conn.commit()
            return True, ""
        except Exception as e:
            return False, str(e)

    # --- 记录管理 ---
    def add_record(self, uid, cat, cont, dead, prio, owner, folder_id):
        if self.is_uid_exist(uid, owner, folder_id): return False, "当前文件夹内 UID 已存在"
        try:
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(user_seq) FROM records WHERE owner = ?", (owner,))
                res = cursor.fetchone();
                next_seq = (res[0] or 0) + 1
                cursor.execute(
                    'INSERT INTO records (uid, category, content, deadline, priority, status, owner, folder_id, user_seq) VALUES (?,?,?,?,?,0,?,?,?)',
                    (uid, cat, cont, dead, prio, owner, folder_id, next_seq))
                conn.commit()
            log_action(owner, "Add Record", f"Folder: {folder_id}, Seq: {next_seq}");
            return True, ""
        except Exception as e:
            return False, str(e)

    def is_uid_exist(self, uid, owner, folder_id, exclude_id=None):
        if uid == "无" or uid == "": return False
        with sqlite3.connect(self.db_name) as conn:
            if exclude_id:
                conn.execute('SELECT 1 FROM records WHERE uid=? AND owner=? AND folder_id=? AND id!=? LIMIT 1',
                             (uid, owner, folder_id, exclude_id))
            else:
                conn.execute('SELECT 1 FROM records WHERE uid=? AND owner=? AND folder_id=? LIMIT 1',
                             (uid, owner, folder_id))
            return conn.cursor().fetchone() is not None

    def get_all_duplicates(self, owner, folder_id):
        sql = ""
        params = []
        if folder_id == -1:
            sql = '''SELECT id, uid, content, created_at, deadline, user_seq \
                     FROM records
                     WHERE owner = ? \
                       AND (folder_id, uid) IN (SELECT folder_id, uid \
                                                FROM records \
                                                WHERE owner = ? AND uid \
                         !='无' \
                       AND uid!=''
                     GROUP BY folder_id, uid \
                     HAVING COUNT (*) \
                          >1
                         ) \
                     ORDER BY folder_id, uid, id ASC'''
            params = [owner, owner]
        else:
            sql = '''SELECT id, uid, content, created_at, deadline, user_seq \
                     FROM records
                     WHERE owner = ? \
                       AND folder_id = ? \
                       AND uid IN (SELECT uid \
                                   FROM records \
                                   WHERE owner = ? AND folder_id = ? AND uid \
                         !='无' \
                       AND uid!=''
                     GROUP BY uid \
                     HAVING COUNT (*) \
                          >1
                         ) \
                     ORDER BY uid, id ASC'''
            params = [owner, folder_id, owner, folder_id]
        with sqlite3.connect(self.db_name) as conn:
            return conn.execute(sql, params).fetchall()

    def update_uid_only(self, rid, uid, owner, folder_id):
        if self.is_uid_exist(uid, owner, folder_id, exclude_id=rid): return False, "当前文件夹内 UID 占用"
        with sqlite3.connect(self.db_name) as conn: conn.execute('UPDATE records SET uid=? WHERE id=? AND owner=?',
                                                                 (uid, rid, owner)); conn.commit()
        return True, ""

    def update_record(self, rid, uid, cat, new_content, dead, prio, owner, folder_id):
        if self.is_uid_exist(uid, owner, folder_id, exclude_id=rid): return False, "当前文件夹内 UID 占用"
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute(
                    'UPDATE records SET uid=?, category=?, content=?, deadline=?, priority=? WHERE id=? AND owner=?',
                    (uid, cat, new_content, dead, prio, rid, owner));
                conn.commit()
            return True, ""
        except Exception as e:
            return False, str(e)

    def import_from_excel(self, path, owner, folder_id):
        if folder_id == -1: return False, "请先选择一个具体文件夹进行导入"
        try:
            df = pd.read_excel(path);
            count = 0
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(user_seq) FROM records WHERE owner=?", (owner,));
                res = cursor.fetchone();
                next_seq = (res[0] or 0) + 1
                for _, row in df.iterrows():
                    uid = row.get("uid", "导入");
                    cat = row.get("category", "未分类");
                    cont = row.get("content", "");
                    dead = row.get("deadline", "");
                    prio = row.get("priority", "中")
                    if pd.isna(dead): dead = ""
                    if cont:
                        conn.execute(
                            'INSERT INTO records (uid,category,content,deadline,priority,status,owner,folder_id,user_seq) VALUES (?,?,?,?,?,0,?,?,?)',
                            (uid, cat, cont, dead, prio, owner, folder_id, next_seq));
                        next_seq += 1;
                        count += 1
                conn.commit()
            return True, f"导入 {count} 条"
        except Exception as e:
            return False, str(e)

    # --- 核心修改：精细化搜索 ---
    def get_records(self, owner, folder_id, category_filter=None, status_filter=None, search_field="全部",
                    keyword=None):
        with sqlite3.connect(self.db_name) as conn:
            sql = 'SELECT id, user_seq, uid, category, content, deadline, priority, status, folder_id FROM records WHERE owner = ?'
            params = [owner]

            if folder_id != -1: sql += ' AND folder_id = ?'; params.append(folder_id)
            if category_filter and category_filter != "全部": sql += ' AND category = ?'; params.append(category_filter)
            if status_filter == "待办":
                sql += ' AND status = 0'
            elif status_filter == "已完成":
                sql += ' AND status = 1'

            # --- 精细化搜索逻辑 ---
            if keyword:
                if search_field == "全部":
                    # 模糊搜索：UID 或 内容 (序号是数字，转成字符串搜)
                    sql += ' AND (content LIKE ? OR uid LIKE ? OR CAST(user_seq AS TEXT) LIKE ?)'
                    params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
                elif search_field == "按UID":
                    # 模糊搜索UID
                    sql += ' AND uid LIKE ?';
                    params.append(f'%{keyword}%')
                elif search_field == "按内容":
                    # 模糊搜索内容
                    sql += ' AND content LIKE ?';
                    params.append(f'%{keyword}%')
                elif search_field == "按序号":
                    # 模糊搜索序号 (转字符串匹配，方便比如搜 "1" 能出 "1", "10", "12")
                    sql += ' AND CAST(user_seq AS TEXT) LIKE ?';
                    params.append(f'%{keyword}%')

            sql += ''' ORDER BY status ASC, 
                       CASE priority WHEN '高' THEN 1 WHEN '中' THEN 2 WHEN '低' THEN 3 ELSE 4 END,
                       user_seq DESC'''
            return conn.execute(sql, params).fetchall()

    def get_stats_category(self, owner, folder_id):
        with sqlite3.connect(self.db_name) as conn:
            sql = 'SELECT category, COUNT(*) FROM records WHERE owner=?'
            params = [owner]
            if folder_id != -1: sql += ' AND folder_id=?'; params.append(folder_id)
            sql += ' GROUP BY category'
            return conn.execute(sql, params).fetchall()

    def get_stats_priority(self, owner, folder_id):
        with sqlite3.connect(self.db_name) as conn:
            sql = 'SELECT priority, COUNT(*) FROM records WHERE owner=?'
            params = [owner]
            if folder_id != -1: sql += ' AND folder_id=?'; params.append(folder_id)
            sql += ' GROUP BY priority'
            return conn.execute(sql, params).fetchall()

    def toggle_status(self, rid, owner):
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.cursor();
            cur.execute("SELECT status FROM records WHERE id=? AND owner=?", (rid, owner));
            res = cur.fetchone()
            if not res: return False, "无"
            new_status = 1 if res[0] == 0 else 0
            conn.execute("UPDATE records SET status=? WHERE id=? AND owner=?", (new_status, rid, owner));
            conn.commit()
        return True, ""

    def delete_record(self, rid, owner):
        with sqlite3.connect(self.db_name) as conn: conn.execute('DELETE FROM records WHERE id=? AND owner=?',
                                                                 (rid, owner)); conn.commit()

    def export_to_excel(self, path, owner, folder_id):
        try:
            with sqlite3.connect(self.db_name) as conn:
                sql = "SELECT user_seq as 序号, uid, category, content, deadline, priority, status FROM records WHERE owner=?"
                params = [owner]
                if folder_id != -1: sql += " AND folder_id=?"; params.append(folder_id)
                pd.read_sql_query(sql, conn, params=params).to_excel(path, index=False)
            return True, "导出成功"
        except Exception as e:
            return False, str(e)

    def update_user_credentials(self, old_u, new_u, new_p):
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute("UPDATE users SET username=?, password_hash=? WHERE username=?",
                             (new_u, self._hash_password(new_p), old_u))
                conn.execute("UPDATE records SET owner=? WHERE owner=?", (new_u, old_u))
                conn.execute("UPDATE folders SET owner=? WHERE owner=?", (new_u, old_u));
                conn.commit()
            return True, "更新成功"
        except:
            return False, "Fail"

    def restore_database(self, backup_path):
        try:
            if not os.path.exists(backup_path): return False, "File not found"
            shutil.copy2(backup_path, self.db_name);
            return True, "Restored"
        except Exception as e:
            return False, str(e)


# ===========================
# 3. 设置界面
# ===========================
class SettingsDialog(ttk.Toplevel):
    def __init__(self, parent, db_manager, current_user, on_logout):
        super().__init__(parent);
        self.title("⚙️ 设置");
        self.geometry("600x500")
        self.db = db_manager;
        self.current_user = current_user;
        self.on_logout = on_logout
        self.notebook = ttk.Notebook(self);
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=10)
        self.tab_profile = ttk.Frame(self.notebook, padding=20);
        self.notebook.add(self.tab_profile, text="个人资料")
        self.tab_account = ttk.Frame(self.notebook, padding=20);
        self.notebook.add(self.tab_account, text="账户管理")
        self.tab_maintenance = ttk.Frame(self.notebook, padding=20);
        self.notebook.add(self.tab_maintenance, text="数据维护")
        self.setup_profile_tab();
        self.setup_account_tab();
        self.setup_maintenance_tab()

    def setup_profile_tab(self):
        ttk.Label(self.tab_profile, text=f"当前: {self.current_user}", font=("bold", 12)).pack(pady=10)
        ttk.Label(self.tab_profile, text="新用户名:").pack(anchor=W);
        self.en_u = ttk.Entry(self.tab_profile);
        self.en_u.insert(0, self.current_user);
        self.en_u.pack(fill=X, pady=5)
        ttk.Label(self.tab_profile, text="新密码:").pack(anchor=W);
        self.en_p = ttk.Entry(self.tab_profile, show="*");
        self.en_p.pack(fill=X, pady=5)
        ttk.Button(self.tab_profile, text="更新", command=self.upd_prof, bootstyle="success").pack(fill=X, pady=20)

    def setup_account_tab(self):
        f = ttk.Labelframe(self.tab_account, text="新建账户", padding=10);
        f.pack(fill=X, pady=10)
        ttk.Label(f, text="用户:").pack(anchor=W);
        self.ec_u = ttk.Entry(f);
        self.ec_u.pack(fill=X, pady=5)
        ttk.Label(f, text="密码:").pack(anchor=W);
        self.ec_p = ttk.Entry(f, show="*");
        self.ec_p.pack(fill=X, pady=5)
        ttk.Button(f, text="创建", command=self.create, bootstyle="info").pack(fill=X, pady=10)
        ttk.Separator(self.tab_account).pack(fill=X, pady=20);
        ttk.Button(self.tab_account, text="🚪 退出", command=self.out, bootstyle="danger").pack(fill=X)

    def setup_maintenance_tab(self):
        f1 = ttk.Labelframe(self.tab_maintenance, text="灾备", padding=10);
        f1.pack(fill=X, pady=5)
        b_box = ttk.Frame(f1);
        b_box.pack(fill=X, pady=5)
        ttk.Button(b_box, text="📂 备份", command=self.back, bootstyle="warning").pack(side=LEFT, padx=5)
        ttk.Button(b_box, text="♻️ 还原", command=self.rest, bootstyle="info").pack(side=LEFT, padx=5)
        f2 = ttk.Labelframe(self.tab_maintenance, text="日志", padding=10);
        f2.pack(fill=BOTH, expand=True, pady=10)
        self.log_t = scrolledtext.ScrolledText(f2, height=10, state='disabled', font=("Consolas", 9));
        self.log_t.pack(fill=BOTH, expand=True)
        bf = ttk.Frame(f2);
        bf.pack(fill=X, pady=5)
        ttk.Button(bf, text="刷新", command=self.load_l, bootstyle="secondary-outline").pack(side=LEFT)
        ttk.Button(bf, text="清空", command=self.clear_l, bootstyle="danger-link").pack(side=RIGHT)
        self.load_l()

    def back(self):
        s, m = self.db.backup_database(); messagebox.showinfo("结果", m) if s else messagebox.showerror("错", m)

    def rest(self):
        p = filedialog.askopenfilename(initialdir=os.path.abspath("backups"), filetypes=[("DB", "*.db")])
        if p and messagebox.askyesno("警告", "覆盖当前数据？"):
            if self.db.restore_database(p)[0]:
                messagebox.showinfo("成功", "请重新登录"); self.out()
            else:
                messagebox.showerror("失败", "还原失败")

    def load_l(self):
        self.log_t.config(state='normal');
        self.log_t.delete(1.0, END)
        if os.path.exists("system.log"):
            with open("system.log", "r", encoding="utf-8") as f: self.log_t.insert(END, "".join(f.readlines()[-50:]))
        self.log_t.config(state='disabled');
        self.log_t.see(END)

    def clear_l(self):
        if messagebox.askyesno("清空", "确定？"): open("system.log", "w").close(); self.load_l()

    def upd_prof(self):
        if self.db.update_user_credentials(self.current_user, self.en_u.get(), self.en_p.get())[0]:
            messagebox.showinfo("OK", "请重登"); self.out()
        else:
            messagebox.showerror("Err", "Fail")

    def create(self):
        if self.db.register_user(self.ec_u.get(), self.ec_p.get())[0]:
            messagebox.showinfo("OK", "Created"); self.ec_u.delete(0, END)
        else:
            messagebox.showerror("Err", "Fail")

    def out(self):
        self.destroy(); self.on_logout()


# ... (LoginFrame, ConflictDialog 保持不变) ...
class LoginFrame(ttk.Frame):
    def __init__(self, master, db, cb):
        super().__init__(master, padding=30); self.db = db; self.cb = cb; self.cfg = ConfigManager(); self.place(
            relx=0.5, rely=0.5, anchor=CENTER); self.init()

    def init(self):
        if not self.db.has_users():
            self.reg_ui()
        else:
            c = self.cfg.load_config()
            if c.get("auto_login") and c.get("last_user"):
                self.cb(c['last_user'])
            else:
                self.log_ui()

    def reg_ui(self):
        for w in self.winfo_children(): w.destroy()
        ttk.Label(self, text="🔒", font=("微软雅黑", 24)).grid(row=0, column=0, sticky="e");
        ttk.Label(self, text="初始化", font=("bold", 20), bootstyle="primary").grid(row=0, column=1, sticky="w",
                                                                                    pady=20);
        ttk.Label(self, text="🔒", font=("微软雅黑", 24), foreground=self.master['bg']).grid(row=0, column=2, padx=5)
        ttk.Label(self, text="用户:", anchor="e").grid(row=1, column=0, sticky="e", padx=10);
        self.eu = ttk.Entry(self, width=25);
        self.eu.grid(row=1, column=1, sticky="w")
        ttk.Label(self, text="密码:", anchor="e").grid(row=2, column=0, sticky="e", padx=10);
        self.ep = ttk.Entry(self, width=25, show="*");
        self.ep.grid(row=2, column=1, sticky="w")
        ttk.Button(self, text="注册", command=self.do_reg, bootstyle="success", width=20).grid(row=3, column=0,
                                                                                               columnspan=3, pady=20)

    def log_ui(self):
        for w in self.winfo_children(): w.destroy()
        c = self.cfg.load_config();
        lu = c.get("last_user", "")
        ttk.Label(self, text="🔐", font=("微软雅黑", 24)).grid(row=0, column=0, sticky="e");
        ttk.Label(self, text="登录", font=("bold", 20), bootstyle="primary").grid(row=0, column=1, pady=20);
        ttk.Label(self, text="🔐", font=("微软雅黑", 24), foreground=self.master['bg']).grid(row=0, column=2,
                                                                                            padx=(5, 0))
        ttk.Label(self, text="用户:", anchor="e").grid(row=1, column=0, sticky="e", padx=10);
        self.eu = ttk.Entry(self, width=25);
        self.eu.insert(0, lu);
        self.eu.grid(row=1, column=1, sticky="w")
        ttk.Label(self, text="密码:", anchor="e").grid(row=2, column=0, sticky="e", padx=10);
        self.ep = ttk.Entry(self, width=25, show="*");
        self.ep.grid(row=2, column=1, sticky="w");
        self.ep.bind('<Return>', lambda e: self.do_log())
        self.v_auto = ttk.BooleanVar(value=False);
        ttk.Checkbutton(self, text="自动登录", variable=self.v_auto, bootstyle="round-toggle").grid(row=3, column=1,
                                                                                                    sticky="w", pady=5)
        ttk.Button(self, text="登录", command=self.do_log, width=20).grid(row=4, column=0, columnspan=3, pady=10);
        ttk.Button(self, text="注册", command=self.reg_ui, bootstyle="link").grid(row=5, column=0, columnspan=3)

    def do_reg(self):
        if self.db.register_user(self.eu.get(), self.ep.get())[0]:
            messagebox.showinfo("OK", "OK"); self.log_ui()
        else:
            messagebox.showerror("Err", "Fail")

    def do_log(self):
        u = self.eu.get();
        p = self.ep.get()
        if self.db.login_check(u, p):
            self.cfg.save_config(self.v_auto.get(), u); self.cb(u)
        else:
            messagebox.showerror("Err", "Fail")


class ConflictDialog(ttk.Toplevel):
    def __init__(self, p, db, u, fid):
        super().__init__(p);
        self.title("冲突");
        self.geometry("800x500");
        self.db = db;
        self.p = p;
        self.u = u;
        self.fid = fid
        ttk.Label(self, text="发现重复UID", bootstyle="danger").pack(pady=10)
        bf = ttk.Frame(self);
        bf.pack(fill=X, padx=10);
        ttk.Button(bf, text="改名", command=self.ren).pack(side=LEFT);
        ttk.Button(bf, text="删除", command=self.dele, bootstyle="danger").pack(side=LEFT)
        self.tree = ttk.Treeview(self, columns=("ID", "UID", "Cont"), show="headings");
        self.tree.heading("ID", text="SysID");
        self.tree.heading("UID", text="UID");
        self.tree.heading("Cont", text="Content");
        self.tree.pack(fill=BOTH, expand=True)
        self.load()

    def load(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        dups = self.db.get_all_duplicates(self.u, self.fid)
        if not dups: self.destroy(); self.p.load(); return
        for r in dups: self.tree.insert("", END, values=(r[0], r[1], r[2]))

    def ren(self):
        sel = self.tree.selection()
        if sel:
            nu = simpledialog.askstring("新UID", "输入:")
            if nu:
                for i in sel: self.db.update_uid_only(self.tree.item(i, 'values')[0], nu, self.u, self.fid)
                self.load()

    def dele(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("删", "删?"):
            for i in sel: self.db.delete_record(self.tree.item(i, 'values')[0], self.u)
            self.load()


# ===========================
# 5. 主程序 Frame (界面更新)
# ===========================
class MainFrame(ttk.Frame):
    def __init__(self, master, db, u, out, app_ctrl):
        super().__init__(master);
        self.db = db;
        self.u = u;
        self.out = out;
        self.app_ctrl = app_ctrl;
        self.pack(fill=BOTH, expand=True)
        self.current_folder_id = -1
        self.setup()

    def setup(self):
        h = ttk.Frame(self, bootstyle="primary");
        h.pack(fill=X)
        ttk.Label(h, text=f"👤 {self.u}", bootstyle="inverse-primary").pack(side=LEFT, padx=10, pady=5)
        t_box = ttk.Frame(h, bootstyle="primary");
        t_box.pack(side=RIGHT, padx=5)
        self.theme_var = ttk.StringVar(value="cosmo" if "cosmo" in self.app_ctrl.current_theme else "darkly")
        ttk.Checkbutton(t_box, text="深色模式", variable=self.theme_var, onvalue="darkly", offvalue="cosmo",
                        command=self.toggle_theme, bootstyle="round-toggle-inverse").pack(side=LEFT)
        ttk.Button(h, text="⚙️ 设置", command=self.conf, bootstyle="secondary").pack(side=RIGHT, padx=5)

        self.cats = ["工作", "生活", "学习", "紧急", "归档", "其他"];
        self.prios = ["高", "中", "低"];
        self.stats = ["全部", "待办", "已完成"]
        self.search_fields = ["全部", "按UID", "按内容", "按序号"]  # 新增搜索字段列表

        main_paned = ttk.Panedwindow(self, orient=HORIZONTAL);
        main_paned.pack(fill=BOTH, expand=True, padx=5, pady=5)

        f_left = ttk.Frame(main_paned, padding=5);
        main_paned.add(f_left, weight=1)
        f_tools = ttk.Frame(f_left);
        f_tools.pack(fill=X, pady=2)
        ttk.Label(f_tools, text="📂 文件夹", font=("bold", 10)).pack(side=LEFT)
        ttk.Button(f_tools, text="+", width=2, command=self.add_folder, bootstyle="success-outline").pack(side=RIGHT)

        self.folder_tree = ttk.Treeview(f_left, show="tree", selectmode="browse", bootstyle="primary")
        self.folder_tree.pack(fill=BOTH, expand=True)
        self.folder_tree.bind("<<TreeviewSelect>>", self.on_folder_select)
        self.folder_tree.bind("<Button-3>", self.folder_menu)
        self.m_folder = ttk.Menu(self, tearoff=0)
        self.m_folder.add_command(label="✏️ 重命名", command=self.ren_folder)
        self.m_folder.add_command(label="🗑️ 删除文件夹", command=self.del_folder)

        f_right = ttk.Frame(main_paned);
        main_paned.add(f_right, weight=4)
        nb = ttk.Notebook(f_right);
        nb.pack(fill=BOTH, expand=True)
        self.t1 = ttk.Frame(nb);
        nb.add(self.t1, text="📄 文件列表");
        self.ui_mgr()
        self.t2 = ttk.Frame(nb);
        nb.add(self.t2, text="📊 数据看板");
        self.ui_dash()
        nb.bind("<<NotebookTabChanged>>",
                lambda e: self.draw_trigger(None) if nb.index(nb.select()) == 1 else None)  # 确保切换时刷新图表

        self.refresh_folders()

    def toggle_theme(self):
        self.app_ctrl.change_theme(self.theme_var.get())

    def conf(self):
        SettingsDialog(self, self.db, self.u, self.out)

    def refresh_folders(self):
        for i in self.folder_tree.get_children(): self.folder_tree.delete(i)
        self.folder_tree.insert("", END, iid="-1", text="📂 全部文件", tags=("root",))
        folders = self.db.get_folders(self.u)
        for fid, fname in folders: self.folder_tree.insert("", END, iid=str(fid), text=f"📁 {fname}", values=(fid,))
        if str(self.current_folder_id) in ["-1"] + [str(f[0]) for f in folders]:
            self.folder_tree.selection_set(str(self.current_folder_id))
        else:
            self.folder_tree.selection_set("-1")

    def on_folder_select(self, event):
        sel = self.folder_tree.selection();
        if not sel: return
        self.current_folder_id = int(sel[0])
        fname = self.folder_tree.item(sel[0], "text")
        self.lbl_folder_title.configure(text=f"当前位置: {fname}")
        state = "normal" if self.current_folder_id != -1 else "disabled"
        for child in self.inp_frame.winfo_children():
            try:
                child.configure(state=state)
            except:
                pass
            for sub in child.winfo_children():
                try:
                    sub.configure(state=state)
                except:
                    pass
        self.load()
        if self.cf.winfo_exists(): self.draw_trigger(None)

    def add_folder(self):
        name = simpledialog.askstring("新建文件夹", "名称:")
        if name:
            if self.db.add_folder(name, self.u)[0]:
                self.refresh_folders()
            else:
                messagebox.showerror("错误", "创建失败")

    def folder_menu(self, e):
        item = self.folder_tree.identify_row(e.y)
        if item and item != "-1": self.folder_tree.selection_set(item); self.m_folder.post(e.x_root, e.y_root)

    def ren_folder(self):
        fid = int(self.folder_tree.selection()[0])
        old = self.folder_tree.item(str(fid), "text").replace("📁 ", "")
        new = simpledialog.askstring("重命名", f"原名: {old}\n新名:")
        if new: self.db.rename_folder(fid, new, self.u); self.refresh_folders()

    def del_folder(self):
        fid = int(self.folder_tree.selection()[0])
        if messagebox.askyesno("删除", "确定删除该文件夹及其所有内容吗？\n此操作不可恢复！"):
            self.db.delete_folder(fid, self.u);
            self.current_folder_id = -1;
            self.refresh_folders()

    def ui_mgr(self):
        top = ttk.Frame(self.t1);
        top.pack(fill=X, padx=10, pady=5)
        self.lbl_folder_title = ttk.Label(self.t1, text="当前位置: 全部文件", font=("bold", 12), bootstyle="info");
        self.lbl_folder_title.pack(anchor=W, padx=10)
        self.inp_frame = ttk.Labelframe(top, text="快速录入 (仅在具体文件夹下可用)", padding=10);
        self.inp_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=5)
        f1 = ttk.Frame(self.inp_frame);
        f1.pack(fill=X, pady=(0, 5))
        ttk.Label(f1, text="UID:").pack(side=LEFT);
        self.e_uid = ttk.Entry(f1, width=6);
        self.e_uid.pack(side=LEFT, padx=5)
        ttk.Label(f1, text="分类:").pack(side=LEFT);
        self.c_cat = ttk.Combobox(f1, values=self.cats, width=5, state="readonly");
        self.c_cat.current(0);
        self.c_cat.pack(side=LEFT, padx=5)
        ttk.Label(f1, text="优:").pack(side=LEFT);
        self.c_prio = ttk.Combobox(f1, values=self.prios, width=3, state="readonly");
        self.c_prio.current(1);
        self.c_prio.pack(side=LEFT, padx=5)
        self.v_dead = ttk.BooleanVar(value=False);
        self.c_d = ttk.Checkbutton(f1, text="止:", variable=self.v_dead, bootstyle="round-toggle", command=self.tg_d);
        self.c_d.pack(side=LEFT, padx=5)
        self.d_ent = DateEntry(f1, width=9, bootstyle="danger");
        self.d_ent.pack(side=LEFT);
        self.tg_d()
        f2 = ttk.Frame(self.inp_frame);
        f2.pack(fill=BOTH, expand=True)
        ttk.Label(f2, text="内容:").pack(side=LEFT, anchor=N, pady=5)
        self.e_cont = scrolledtext.ScrolledText(f2, height=3, width=40, font=("微软雅黑", 10));
        self.e_cont.pack(side=LEFT, fill=BOTH, expand=True, padx=5);
        self.e_cont.bind('<Control-Return>', lambda e: self.add())
        ttk.Button(f2, text="保存", command=self.add, bootstyle="success").pack(side=LEFT, anchor=S)

        right_panel = ttk.Frame(top);
        right_panel.pack(side=RIGHT, fill=Y, padx=5)
        exc = ttk.Labelframe(right_panel, text="数据", padding=5);
        exc.pack(fill=X, pady=2)
        ttk.Button(exc, text="导出Excel", command=self.exp, bootstyle="info-outline", width=10).pack(pady=2)
        ttk.Button(exc, text="导入Excel", command=self.imp, bootstyle="secondary-outline", width=10).pack(pady=2)

        # --- 核心 UI 修改：精细化筛选 ---
        fl = ttk.Labelframe(right_panel, text="视图筛选", padding=5);
        fl.pack(fill=X, pady=2)

        # Line 1: 分类 + 状态
        f_line1 = ttk.Frame(fl);
        f_line1.pack(fill=X, pady=2)
        self.c_flt = ttk.Combobox(f_line1, values=["全部"] + self.cats, width=6, state="readonly");
        self.c_flt.current(0);
        self.c_flt.pack(side=LEFT, padx=2)
        self.c_flt.bind("<<ComboboxSelected>>", lambda e: self.load())

        self.c_stat_flt = ttk.Combobox(f_line1, values=self.stats, width=6, state="readonly");
        self.c_stat_flt.current(1);
        self.c_stat_flt.pack(side=LEFT, padx=2)
        self.c_stat_flt.bind("<<ComboboxSelected>>", lambda e: self.load())

        # Line 2: 搜索字段 + 搜索框
        f_line2 = ttk.Frame(fl);
        f_line2.pack(fill=X, pady=2)
        self.c_search_field = ttk.Combobox(f_line2, values=self.search_fields, width=6, state="readonly")
        self.c_search_field.current(0)  # 默认全部
        self.c_search_field.pack(side=LEFT, padx=2)

        self.e_sch = ttk.Entry(f_line2, width=8);
        self.e_sch.pack(side=LEFT, padx=2)

        # Line 3: 按钮
        btn_row = ttk.Frame(fl);
        btn_row.pack(fill=X, pady=2)
        ttk.Button(btn_row, text="🔍", command=self.load, bootstyle="link", width=3).pack(side=LEFT)
        ttk.Button(btn_row, text="🔄", command=self.load, bootstyle="secondary-outline", width=3).pack(side=RIGHT)

        paned = ttk.Panedwindow(self.t1, orient=VERTICAL);
        paned.pack(fill=BOTH, expand=True, padx=10, pady=5)
        frame_list = ttk.Frame(paned);
        paned.add(frame_list, weight=2)
        cols = ("Seq", "UID", "Cat", "Prio", "Dead", "Cont", "Stat")
        self.tree = ttk.Treeview(frame_list, columns=cols, show="headings", bootstyle="info")
        for c in cols: self.tree.heading(c, text=c, command=lambda _c=c: self.sort_tree(_c, False))
        self.tree.column("Seq", width=30, anchor=CENTER);
        self.tree.column("UID", width=50, anchor=CENTER)
        self.tree.column("Cat", width=50, anchor=CENTER);
        self.tree.column("Prio", width=40, anchor=CENTER)
        self.tree.column("Dead", width=80, anchor=CENTER);
        self.tree.column("Cont", width=300, anchor=W)
        self.tree.column("Stat", width=60, anchor=CENTER)
        vsb = ttk.Scrollbar(frame_list, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set);
        self.tree.pack(side=LEFT, fill=BOTH, expand=True);
        vsb.pack(side=RIGHT, fill=Y)
        self.tree.tag_configure("high", foreground="red", font=("微软雅黑", 9, "bold"));
        self.tree.tag_configure("done", foreground="gray");
        self.tree.tag_configure("overdue", foreground="#d9534f", font=("bold"));
        self.tree.tag_configure("normal", foreground="black")
        self.tree.bind("<Double-1>", self.edit);
        self.tree.bind("<Button-3>", self.menu);
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        frame_detail = ttk.Labelframe(paned, text="📄 详细内容预览", padding=5);
        paned.add(frame_detail, weight=1)
        self.txt_detail = scrolledtext.ScrolledText(frame_detail, height=5, state='disabled', font=("微软雅黑", 10));
        self.txt_detail.pack(fill=BOTH, expand=True)
        self.m = ttk.Menu(self, tearoff=0)
        self.m.add_command(label="🔄 刷新列表", command=self.load)
        self.m.add_separator()
        self.m.add_command(label="✅ 标记完成", command=self.done);
        self.m.add_separator()
        self.m.add_command(label="✏️ 修改", command=self.edit);
        self.m.add_command(label="🏷️ 改名UID", command=self.ren_uid);
        self.m.add_command(label="🗑️ 批量删除", command=self.delete)

    def on_tree_select(self, event):
        sel = self.tree.selection();
        self.txt_detail.configure(state='normal');
        self.txt_detail.delete(1.0, END)
        if sel: self.txt_detail.insert(END, self.tree.item(sel[0], 'values')[5])
        self.txt_detail.configure(state='disabled')

    def ui_dash(self):
        ttk.Label(self.t2, text="数据看板 (当前文件夹)", font=("bold", 16)).pack(pady=10)
        self.cf = ttk.Frame(self.t2);
        self.cf.pack(fill=BOTH, expand=True, padx=20, pady=10)
        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.cf)
        self.canvas.get_tk_widget().pack(fill=BOTH, expand=True)
        self.cf.bind("<Configure>", self.draw_trigger)
        self.cf.bind("<Visibility>", self.draw_trigger)

    def draw_trigger(self, event):
        if hasattr(self, '_draw_timer'): self.after_cancel(self._draw_timer)
        self._draw_timer = self.after(100, self.draw_charts_safe)

    def draw_charts_safe(self):
        if not self.cf.winfo_exists(): return
        self.update_idletasks()
        w, h = self.cf.winfo_width(), self.cf.winfo_height()
        if w < 50 or h < 50: return
        self.fig.clear()
        d_cat = self.db.get_stats_category(self.u, self.current_folder_id)
        d_prio = self.db.get_stats_priority(self.u, self.current_folder_id)
        if not d_cat and not d_prio:
            self.fig.text(0.5, 0.5, "暂无数据", ha='center', va='center', fontsize=20, color='gray')
        else:
            if d_cat: ax1 = self.fig.add_subplot(121); ax1.pie([r[1] for r in d_cat], labels=[r[0] for r in d_cat],
                                                               autopct='%1.1f%%', startangle=90); ax1.set_title(
                "按分类")
            if d_prio: ax2 = self.fig.add_subplot(122); prios = [r[0] for r in d_prio]; counts = [r[1] for r in
                                                                                                  d_prio]; colors = [
                'red' if p == '高' else 'green' if p == '低' else 'blue' for p in prios]; ax2.bar(prios, counts,
                                                                                                  color=colors); ax2.set_title(
                "按优先级")
        self.fig.tight_layout();
        self.canvas.draw()

    def tg_d(self):
        self.d_ent.entry.configure(state="normal" if self.v_dead.get() else "disabled")

    # --- load 方法更新：使用 c_search_field ---
    def load(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        # 获取各筛选组件的值
        stat_val = self.c_stat_flt.get()
        search_field = self.c_search_field.get()  # 新增
        keyword = self.e_sch.get().strip()

        rs = self.db.get_records(self.u, self.current_folder_id, self.c_flt.get(), stat_val, search_field, keyword)

        today = datetime.now().date()
        for r in rs:
            rid, seq, uid, cat, cont, dead, prio, stat, fid = r
            stat_text = "✅" if stat == 1 else "⬜";
            dead_show = dead if dead else "-"
            tags = []
            if stat == 1:
                tags.append("done")
            elif prio == "高":
                tags.append("high")
            if stat == 0 and dead:
                try:
                    if datetime.strptime(dead, "%Y-%m-%d").date() < today: tags.append("overdue")
                except:
                    pass
            self.tree.insert("", END, values=(seq, uid, cat, prio, dead_show, cont, stat_text, rid, fid),
                             tags=tuple(tags))

    def sort_tree(self, col, reverse):
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        try:
            l.sort(key=lambda t: int(t[0]) if t[0].isdigit() else t[0], reverse=reverse)
        except:
            l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l): self.tree.move(k, '', index)
        self.tree.heading(col, command=lambda: self.sort_tree(col, not reverse))

    def add(self):
        if self.current_folder_id == -1: return messagebox.showwarning("提示", "请先在左侧选择一个具体的文件夹！")
        c = self.e_cont.get("1.0", END).strip();
        u = self.e_uid.get().strip() or "无";
        p = self.c_prio.get();
        d = self.d_ent.entry.get() if self.v_dead.get() else ""
        if not c: return messagebox.showwarning("提示", "空")
        if self.db.add_record(u, self.c_cat.get(), c, d, p, self.u, self.current_folder_id)[0]:
            self.e_cont.delete("1.0", END); self.load()
        else:
            messagebox.showerror("错", "加失败")

    def done(self):
        sel = self.tree.selection()
        if sel:
            for i in sel: self.db.toggle_status(self.tree.item(i, 'values')[7], self.u)
            self.load()

    def edit(self, e=None):
        sel = self.tree.selection();
        if not sel: return
        vals = self.tree.item(sel[0], 'values');
        rid = vals[7];
        od = vals[4] if vals[4] != "-" else "";
        fid = vals[8]
        top = ttk.Toplevel(self);
        top.title("编辑");
        top.geometry("600x450")
        f_top = ttk.Frame(top);
        f_top.pack(fill=X, padx=10, pady=10)
        ttk.Label(f_top, text="UID:").pack(side=LEFT);
        eu = ttk.Entry(f_top, width=10);
        eu.insert(0, vals[1]);
        eu.pack(side=LEFT, padx=5)
        ttk.Label(f_top, text="优:").pack(side=LEFT);
        ep = ttk.Combobox(f_top, values=self.prios, width=5, state="readonly");
        ep.set(vals[3]);
        ep.pack(side=LEFT, padx=5)
        ttk.Label(top, text="内容:", anchor=W).pack(fill=X, padx=10)
        ec = scrolledtext.ScrolledText(top, height=10, font=("微软雅黑", 10));
        ec.pack(fill=BOTH, expand=True, padx=10, pady=5);
        ec.insert(1.0, vals[5])

        def save():
            if self.db.update_record(rid, eu.get(), vals[2], ec.get(1.0, END).strip(), od, ep.get(), self.u, fid)[0]:
                self.load(); top.destroy()
            else:
                messagebox.showerror("Err", "Fail")

        ttk.Button(top, text="保存", command=save, bootstyle="success").pack(pady=10, fill=X, padx=10)

    def delete(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("删", "删?"):
            for i in sel: self.db.delete_record(self.tree.item(i, 'values')[7], self.u)
            self.load()

    def exp(self):
        p = filedialog.asksaveasfilename(defaultextension=".xlsx"); self.db.export_to_excel(p, self.u,
                                                                                            self.current_folder_id) if p else None

    def imp(self):
        p = filedialog.askopenfilename(); self.load() if p and \
                                                         self.db.import_from_excel(p, self.u, self.current_folder_id)[
                                                             0] else None

    def ren_uid(self):
        sel = self.tree.selection();
        if sel:
            rid = self.tree.item(sel[0], 'values')[7];
            nv = simpledialog.askstring("改", "新UID:");
            fid = self.tree.item(sel[0], 'values')[8]
            if nv: self.db.update_uid_only(rid, nv, self.u, fid); self.load()

    def menu(self, e):
        iid = self.tree.identify_row(e.y)
        if iid:
            if iid not in self.tree.selection(): self.tree.selection_set(iid)
            self.m.post(e.x_root, e.y_root)


class AppController:
    def __init__(self):
        self.cf = ConfigManager();
        cfg = self.cf.load_config();
        self.current_theme = cfg.get("theme", "cosmo")
        self.root = ttk.Window(themename=self.current_theme);
        self.root.title("智能系统 v38.0 (最终精细搜索版)");
        self.root.geometry("1100x800")
        self.db = DatabaseManager();
        self.current_frame = None;
        self.show_login()

    def change_theme(self, new_theme):
        self.root.style.theme_use(new_theme);
        self.current_theme = new_theme
        cfg = self.cf.load_config();
        self.cf.save_config(cfg.get("auto_login", False), cfg.get("last_user", ""), new_theme)

    def show_login(self):
        if self.current_frame: self.current_frame.destroy()
        self.current_frame = LoginFrame(self.root, self.db, self.on_login_success)

    def on_login_success(self, u):
        if self.current_frame: self.current_frame.destroy()
        self.current_frame = MainFrame(self.root, self.db, u, self.on_logout, self)
    def on_logout(self): self.cf.clear_auto_login(); self.show_login()
    def run(self): self.root.mainloop()

if __name__ == "__main__": AppController().run()