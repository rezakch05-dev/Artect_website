from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
from markupsafe import Markup
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, re, time, uuid, qrcode, json, html, zipfile, mimetypes, io, shutil, hashlib, struct, math
from PIL import Image
import hmac, logging, secrets, ssl
from datetime import timedelta
from urllib.parse import urlsplit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database', 'artect.db')
IMAGE_DIR = os.path.join(BASE_DIR, 'images')
ICON_DIR = os.path.join(BASE_DIR, 'icons')
PROJECT_MEDIA_DIR = os.path.join(BASE_DIR, 'project_media')
QR_DIR = os.path.join(BASE_DIR, 'static', 'images', 'qr')
MODEL_DIR = os.path.join(BASE_DIR, 'models')
VIDEO_DIR = os.path.join(BASE_DIR, 'videos')
CONFIG_DIR = os.path.join(BASE_DIR, 'model_configs')
for d in (os.path.dirname(DB_PATH), IMAGE_DIR, ICON_DIR, PROJECT_MEDIA_DIR, QR_DIR, MODEL_DIR, VIDEO_DIR, CONFIG_DIR): os.makedirs(d, exist_ok=True)

app = Flask(__name__)
APP_ENV = os.environ.get('ARTECT_ENV', 'development').strip().lower()
IS_PRODUCTION = APP_ENV in ('production', 'prod')
_configured_secret_key = os.environ.get('ARTECT_SECRET_KEY', '').strip()
if IS_PRODUCTION and (len(_configured_secret_key) < 32 or any(marker in _configured_secret_key.lower() for marker in ('replace_', 'change-this', 'your_secret', 'generate_me'))):
    raise RuntimeError('Production requires a private, randomly generated ARTECT_SECRET_KEY of at least 32 characters; placeholders are not accepted.')
# Never use a known, hard-coded signing key. A random per-process key is fine for local
# development; production must supply one stable value shared by all application workers.
app.secret_key = _configured_secret_key or secrets.token_urlsafe(48)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
logger = logging.getLogger('artect')


# Final rich-text compiler.
# The database/editor always stores marker syntax as plain characters.
# Immediately before HTML is sent to the browser, this function scans every
# HTML text node and compiles only the supported markers:
#   [text]            -> inline box
#   {text|url}        -> hyperlink
#   {text||url}       -> button
# Existing HTML tags/attributes are never parsed as marker syntax.
def compile_rich_markers_in_response(data):
    # Stored content comes from contenteditable and therefore may contain
    # escaped HTML entities. Restore those entities first, then compile only
    # text portions of the final HTML document.
    data = html.unescape(data)
    token_re = re.compile(r'(\[[^\[\]\n]+\]|\{[^{}\n|]+\|\|[^{}\n|]+\}|\{[^{}\n|]+\|[^{}\n|]+\})')
    tag_re = re.compile(r'(<[^>]*>)')
    safe_url_re = re.compile(r'^(https?://|/|#|mailto:|tel:)', re.I)

    def esc_text(v):
        return (str(v).replace('&', '&amp;').replace('<', '&lt;')
                .replace('>', '&gt;').replace('"', '&quot;'))

    def compile_text(chunk):
        out=[]
        last=0
        for m in token_re.finditer(chunk):
            out.append(chunk[last:m.start()])
            token=m.group(0)
            if token.startswith('['):
                label=token[1:-1]
                out.append('<span class="rich-box">'+esc_text(label)+'</span>')
            else:
                body=token[1:-1]
                is_button='||' in body
                sep='||' if is_button else '|'
                label,url=body.split(sep,1)
                url=url.strip()
                safe=url if safe_url_re.match(url) else '#'
                attrs=' class="rich-button"' if is_button else ' class="rich-link"'
                out.append('<a'+attrs+' href="'+esc_text(safe)+'">'+esc_text(label)+'</a>')
            last=m.end()
        out.append(chunk[last:])
        return ''.join(out)

    # Never compile inside script/style/textarea blocks. Those areas can contain
    # arbitrary JavaScript/CSS/text and must remain byte-for-byte compatible.
    parts=tag_re.split(data)
    in_raw=set()
    result=[]
    for part in parts:
        if not part:
            continue
        if part.startswith('<'):
            result.append(part)
            m=re.match(r'</?\s*([a-zA-Z0-9]+)', part)
            if m:
                name=m.group(1).lower()
                if part.startswith('</'):
                    in_raw.discard(name)
                elif not part.rstrip().endswith('/>') and name in {'script','style','textarea','code','pre'}:
                    in_raw.add(name)
        else:
            result.append(part if in_raw else compile_text(part))
    return ''.join(result)

def inject_csrf_markup(data, token):
    """Add CSRF tokens to rendered POST forms and bootstrap same-origin fetch requests.

    Markup is inserted only in HTML tag contexts. Existing application JavaScript and
    form behavior remain in place; a submit listener also covers forms created at runtime.
    """
    token_attr = html.escape(token, quote=True)
    tag_re = re.compile(r'(<[^>]*>)')
    parts = tag_re.split(data)
    output = []
    in_raw = set()
    for part in parts:
        if not part:
            continue
        if part.startswith('<'):
            tag_match = re.match(r'<\s*(/?)\s*([a-zA-Z0-9]+)', part)
            if tag_match:
                closing, name = tag_match.group(1), tag_match.group(2).lower()
                if not closing and not in_raw and name == 'form':
                    method_match = re.search(r'\bmethod\s*=\s*(?:"post"|\'post\'|post\b)', part, re.I)
                    if method_match:
                        part += f'<input type="hidden" name="_csrf_token" value="{token_attr}">'
                if closing:
                    in_raw.discard(name)
                elif not part.rstrip().endswith('/>') and name in {'script', 'style', 'textarea', 'code', 'pre'}:
                    in_raw.add(name)
            output.append(part)
        else:
            output.append(part)
    data = ''.join(output)
    bootstrap = f"""<meta name="csrf-token" content="{token_attr}">
<script data-artect-csrf-bootstrap>
(function () {{
  var meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) return;
  var csrfToken = meta.content;
  var nativeFetch = window.fetch;
  var unsafeMethods = {{ POST: true, PUT: true, PATCH: true, DELETE: true }};
  window.fetch = function (input, init) {{
    var requestObject = typeof Request !== 'undefined' && input instanceof Request;
    var method = String((init && init.method) || (requestObject ? input.method : 'GET')).toUpperCase();
    var rawUrl = typeof input === 'string' ? input : (input && input.url) || String(input);
    var target;
    try {{ target = new URL(rawUrl, window.location.href); }} catch (_) {{ return nativeFetch.call(this, input, init); }}
    if (target.origin !== window.location.origin || !unsafeMethods[method])
      return nativeFetch.call(this, input, init);
    var options = Object.assign({{}}, init || {{}});
    var headers = new Headers(options.headers || (requestObject ? input.headers : undefined) || {{}});
    headers.set('X-CSRF-Token', csrfToken);
    options.headers = headers;
    return nativeFetch.call(this, input, options);
  }};
  document.addEventListener('submit', function (event) {{
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toUpperCase() !== 'POST') return;
    if (!form.querySelector('input[name="_csrf_token"]')) {{
      var input = document.createElement('input');
      input.type = 'hidden'; input.name = '_csrf_token'; input.value = csrfToken;
      form.appendChild(input);
    }}
  }}, true);
}})();
</script>"""
    charset_match = re.search(r'<meta\b[^>]*charset\s*=\s*[\"\']?[^\"\'\s>]+[^>]*>', data, re.I)
    if charset_match:
        data = data[:charset_match.end()] + bootstrap + data[charset_match.end():]
    else:
        head_match = re.search(r'<head\b[^>]*>', data, re.I)
        if head_match:
            data = data[:head_match.end()] + bootstrap + data[head_match.end():]
        else:
            data = bootstrap + data
    return data


@app.before_request
def enforce_csrf_for_state_changes():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return None
    expected = session.get('_csrf_token')
    supplied = request.form.get('_csrf_token', '') or request.headers.get('X-CSRF-Token', '')
    if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
        return ('درخواست معتبر نیست یا نشست شما منقضی شده است. صفحه را تازه‌سازی و دوباره تلاش کنید.', 400)
    return None


@app.after_request
def compile_rich_response(response):
    # Safe baseline headers; no restrictive CSP is imposed because the site currently
    # depends on inline scripts and third-party model-viewer/3D assets.
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    try:
        content_type=response.headers.get('Content-Type','')
        if 'text/html' in content_type:
            data=response.get_data(as_text=True)
            # Inject CSRF bootstrap only into complete HTML documents, not plain-text error bodies.
            if re.search(r'<html\b', data, re.I):
                csrf_token = session.setdefault('_csrf_token', secrets.token_urlsafe(32))
                data=inject_csrf_markup(data, csrf_token)
                response.headers['Cache-Control'] = 'no-store'
            response.set_data(compile_rich_markers_in_response(data))
    except Exception:
        logger.exception('HTML response processing failed')
    return response
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
ALLOWED_IMAGES = {'png','jpg','jpeg','webp','gif','avif'}
ALLOWED_VIDEOS = {'mp4','webm','ogv','ogg','mov','m4v'}
ALLOWED_VIDEOS = {'mp4','webm','mov','m4v'}
PALETTE_ROLES = ['primary','primary_hover','secondary','background','surface','card','model_background','text_primary','text_secondary','border','accent','success','warning','error','icon_color','header']
ROLE_LABELS = {
    'primary':'رنگ اصلی','primary_hover':'رنگ اصلی هنگام قرارگیری موس','secondary':'رنگ مکمل','background':'پس‌زمینه اصلی',
    'surface':'سطح و پس‌زمینه ثانویه','card':'پس‌زمینه کارت‌ها','model_background':'پس‌زمینه مدل‌های سه‌بعدی','text_primary':'رنگ متن اصلی','text_secondary':'رنگ متن فرعی',
    'border':'رنگ خطوط و حاشیه‌ها','accent':'رنگ تأکیدی','success':'رنگ موفقیت','warning':'رنگ هشدار','error':'رنگ خطا','icon_color':'رنگ آیکون‌ها','header':'رنگ هدر و منوی سایت'
}
DEFAULT_COLORS = {'primary':'#B6E23A','primary_hover':'#C8F24B','secondary':'#7E9C1E','background':'#070B0C','surface':'#0D1314','card':'#101819','model_background':'#101819','text_primary':'#F5F7F2','text_secondary':'#AEB6AD','border':'#39491B','accent':'#B6E23A','success':'#B6E23A','warning':'#E5C14D','error':'#E45B5B','icon_color':'#B6E23A','header':'#070B0C'}


def connect_db():
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('PRAGMA foreign_keys=ON')
    return c


def init_db():
    c = connect_db(); c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS admin_users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, status INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS admin_user_meta(user_id INTEGER PRIMARY KEY, is_owner INTEGER DEFAULT 0, FOREIGN KEY(user_id) REFERENCES admin_users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS site_settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS color_palettes(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, active INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS palette_colors(id INTEGER PRIMARY KEY AUTOINCREMENT, palette_id INTEGER NOT NULL, role TEXT NOT NULL, value TEXT NOT NULL, UNIQUE(palette_id, role));
    CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, kind TEXT NOT NULL, alt_text TEXT DEFAULT '', background_filename TEXT DEFAULT '', background_width INTEGER DEFAULT 0, background_height INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, enabled INTEGER DEFAULT 1, seo_description TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS page_sections(id INTEGER PRIMARY KEY AUTOINCREMENT, page_id INTEGER NOT NULL, section_key TEXT NOT NULL, title TEXT DEFAULT '', body TEXT DEFAULT '', image TEXT DEFAULT '', icon TEXT DEFAULT '', button_text TEXT DEFAULT '', button_url TEXT DEFAULT '', enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS menus(id INTEGER PRIMARY KEY AUTOINCREMENT, location TEXT NOT NULL, label TEXT NOT NULL, url TEXT NOT NULL, enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, short_desc TEXT DEFAULT '', full_desc TEXT DEFAULT '', image TEXT DEFAULT '', ar_url TEXT DEFAULT '', button_text TEXT DEFAULT 'تجربه AR', enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0, show_home INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS project_images(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, filename TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS team_members(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, role TEXT DEFAULT '', bio TEXT DEFAULT '', image TEXT DEFAULT '', show_home INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS content_cards(id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE, card_type TEXT NOT NULL, title TEXT DEFAULT '', subtitle TEXT DEFAULT '', short_desc TEXT DEFAULT '', full_desc TEXT DEFAULT '', image TEXT DEFAULT '', icon TEXT DEFAULT '', link TEXT DEFAULT '', tag TEXT DEFAULT '', video TEXT DEFAULT '', enabled INTEGER DEFAULT 1, show_home INTEGER DEFAULT 0, show_artect INTEGER DEFAULT 0, show_mrar INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0, extra_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS model_showcase_cards(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', model_file TEXT DEFAULT '', config_dir TEXT DEFAULT '', config_json TEXT DEFAULT '', enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS mr_ar_animation_cards(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', model_file TEXT NOT NULL DEFAULT '', enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0, extra_json TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS artect_annotation_cards(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', model_file TEXT NOT NULL DEFAULT '', annotations_json TEXT NOT NULL DEFAULT '{}', enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS contact_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, first_name TEXT DEFAULT '', last_name TEXT DEFAULT '', phone TEXT DEFAULT '', company TEXT DEFAULT '', industry TEXT DEFAULT '', services TEXT DEFAULT '', details TEXT DEFAULT '', heard_from TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS footer_columns(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', body TEXT DEFAULT '', links TEXT DEFAULT '', enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0);
    ''')
    cols={r['name'] for r in c.execute('PRAGMA table_info(media)').fetchall()}
    if 'background_filename' not in cols: c.execute("ALTER TABLE media ADD COLUMN background_filename TEXT DEFAULT ''")
    if 'background_width' not in cols: c.execute("ALTER TABLE media ADD COLUMN background_width INTEGER DEFAULT 0")
    if 'background_height' not in cols: c.execute("ALTER TABLE media ADD COLUMN background_height INTEGER DEFAULT 0")
    if not c.execute('SELECT 1 FROM admin_users LIMIT 1').fetchone():
        if IS_PRODUCTION:
            bootstrap_user = os.environ.get('ARTECT_BOOTSTRAP_ADMIN_USERNAME', '').strip()
            bootstrap_password = os.environ.get('ARTECT_BOOTSTRAP_ADMIN_PASSWORD', '')
            if not bootstrap_user or len(bootstrap_password) < 14:
                c.close()
                raise RuntimeError('No admin account exists. Run manage_admin_password.py to create a strong admin account before starting production.')
            c.execute('INSERT INTO admin_users(username,password_hash,status) VALUES(?,?,1)', (bootstrap_user, generate_password_hash(bootstrap_password)))
        else:
            # Development-only convenience. Never seed this account on a production database.
            c.execute('INSERT INTO admin_users(username,password_hash) VALUES(?,?)', ('admin', generate_password_hash('admin1234')))
    if not c.execute('SELECT 1 FROM color_palettes LIMIT 1').fetchone():
        c.execute("INSERT INTO color_palettes(name,active) VALUES(?,1)", ('پالت پیش‌فرض Artect',))
        pid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.executemany('INSERT INTO palette_colors(palette_id,role,value) VALUES(?,?,?)', [(pid,k,v) for k,v in DEFAULT_COLORS.items()])
    c.execute("INSERT OR IGNORE INTO palette_colors(palette_id,role,value) SELECT id, 'icon_color', ? FROM color_palettes", (DEFAULT_COLORS['icon_color'],))
    c.execute("INSERT OR IGNORE INTO palette_colors(palette_id,role,value) SELECT id, 'header', ? FROM color_palettes", (DEFAULT_COLORS['header'],))
    if not c.execute("SELECT 1 FROM site_settings WHERE key='logo'").fetchone(): c.execute("INSERT INTO site_settings(key,value) VALUES('logo','/images/placeholder-logo.png')")
    defaults_settings={'phone':'---','telegram':'---','email':'---','address':'---','company_name':'شرکت واقعیت پردازان داده گستر','company_slogan':'راهی ساده‌تر برای دیدن، تجربه کردن و بهتر ارائه دادن.','admin_email':'---','home_btn_primary_text':'تماس با ما','home_btn_secondary_text':'درخواست Demo','home_btn_primary_link':'/contact','home_btn_secondary_link':'/contact'}
    for _k,_v in defaults_settings.items():
        if not c.execute('SELECT 1 FROM site_settings WHERE key=?',(_k,)).fetchone(): c.execute('INSERT INTO site_settings(key,value) VALUES(?,?)',(_k,_v))
    if not c.execute('SELECT 1 FROM menus LIMIT 1').fetchone():
        menus=[('header','صفحه اصلی','/',0),('header','Artect','/artect',1),('header','Mr.AR','/mr-ar',2),('header','راهکارها','/solutions',3),('header','قابلیت‌ها','/features',4),('header','تجربه‌ها','/experiences',5),('header','تیم','/team',6),('header','تماس با ما','/contact',7)]
        c.executemany('INSERT INTO menus(location,label,url,sort_order) VALUES(?,?,?,?)',menus)
    if not c.execute('SELECT 1 FROM footer_columns LIMIT 1').fetchone():
        cols=[('منو','دسترسی سریع به بخش‌های اصلی سایت.','صفحه اصلی | /\nArtect | /artect\nMr.AR | /mr-ar\nراهکارها | /solutions'),('تجربه‌ها','نمونه‌های واقعی و تجربه‌های AR.','نمونه‌های واقعی | /experiences\nقابلیت‌ها | /features'),('تماس','برای همکاری و دریافت Demo با ما در ارتباط باشید.','تماس با ما | /contact')]
        c.executemany('INSERT INTO footer_columns(title,body,links,sort_order) VALUES(?,?,?,?)',[(a,b,d,i) for i,(a,b,d) in enumerate(cols)])
    if not c.execute('SELECT 1 FROM pages LIMIT 1').fetchone():
        pages=[('صفحه اصلی','home'),('Artect','artect'),('راهکارها','solutions'),('قابلیت‌ها','features'),('تجربه‌ها','experiences'),('Mr.AR','mr-ar'),('تیم ما','team'),('تماس با ما','contact')]
        c.executemany('INSERT INTO pages(title,slug) VALUES(?,?)',pages)
    try: c.execute('ALTER TABLE projects ADD COLUMN show_home INTEGER DEFAULT 0')
    except sqlite3.OperationalError: pass
    try: c.execute("ALTER TABLE page_sections ADD COLUMN inline_json TEXT DEFAULT '{}'")
    except sqlite3.OperationalError: pass
    try: c.execute('ALTER TABLE admin_users ADD COLUMN is_owner INTEGER DEFAULT 0')
    except sqlite3.OperationalError: pass
    if c.execute('SELECT COUNT(*) n FROM admin_users').fetchone()['n']:
        c.execute('UPDATE admin_users SET is_owner=1 WHERE id=(SELECT MIN(id) FROM admin_users)')
    # Final-version section structure and shared card seed data. Existing content is preserved; only missing records are added.
    final_sections={
      'home':[('hero','تصویری که می‌بینید را به دنیای واقعی بیاورید','قبل از ساخت، خرید یا اجرا، نتیجه را در فضای واقعی ببینید.','placeholder-hero.png','placeholder-icon.svg','درخواست Demo','/contact'),('home-how','چطور کار می‌کند؟','سه قدم ساده برای دیدن و بررسی نتیجه.','','','', ''),('home-steps','در چند قدم ساده','از دیدن تا تصمیم‌گیری، مسیر تجربه روشن و کوتاه است.','','','', ''),('home-solutions','راهکارهایی برای دیدن بهتر','راهکار متناسب با نیاز و فضای کاری خود را پیدا کنید.','','','', ''),('home-scenarios','در موقعیت‌های واقعی','سناریوهایی که دیدن نتیجه در آن‌ها مهم است.','','','', ''),('home-capabilities','قابلیت‌ها','امکاناتی که تجربه را کامل‌تر می‌کنند.','','','', ''),('home-projects','تجربه‌های واقعی','نمونه‌ها را ببینید و خودتان امتحان کنید.','','','', ''),('home-contact','با ما در ارتباط باشید','برای شروع یک تجربه جدید با ما صحبت کنید.','','','', '')],
      'artect':[('hero','تصویری که می‌بینید را به دنیای واقعی بیاورید','مدل سه‌بعدی را با اندازه واقعی در محیط واقعی ببینید و نتیجه را قبل از اجرا بررسی کنید.','placeholder-hero.png','placeholder-icon.svg','تجربه Artect','/experiences'),('summary','Artect را ساده ببینید','دیدن نتیجه در فضای واقعی، تصمیم‌گیری را روشن‌تر می‌کند.','placeholder-summary.png','','',''),('problems','چه چیزهایی سخت می‌شوند؟','وقتی نتیجه را فقط تصور می‌کنیم، اندازه، جایگیری و ظاهر ممکن است مبهم بماند.','','','', ''),('process','از مدل تا تجربه','مسیر کار از آماده‌سازی مدل تا تجربه نهایی، مرحله‌به‌مرحله انجام می‌شود.','','','', ''),('visual','چیزی که مخاطب می‌بیند','نمونه‌ای از تجربه بصری Artect.','','','', ''),('applications','Artect کجا کاربرد دارد؟','راهکارهای مختلف برای موقعیت‌های واقعی.','','','مشاهده راهکارها','/solutions'),('scenarios','سناریوهای Artect','چند نمونه از استفاده‌های واقعی.','','','', ''),('projects','تجربه‌های واقعی Artect','نمونه‌ها را با گوشی خودتان امتحان کنید.','','','مشاهده تجربه‌ها','/experiences'),('capabilities','قابلیت‌های Artect','امکاناتی که تجربه را کامل‌تر می‌کنند.','','','مشاهده قابلیت‌ها','/features'),('usage','مشتری چطور استفاده می‌کند؟','یک مسیر ساده از دیدن تا اقدام.','','','', ''),('modeling','مدل‌سازی','اگر مدل سه‌بعدی آماده ندارید، امکان آماده‌سازی آن وجود دارد.','placeholder-modeling.png','','درخواست مدلسازی','/contact'),('contact','شروع کنیم','برای اجرای تجربه AR یا دریافت اطلاعات بیشتر با ما در تماس باشید.','placeholder-contact.png','','تماس با ما','/contact')],
      'mr-ar':[('hero','قبل از خرید، ببینید محصول در خانه شما چطور دیده می‌شود.','محصول را در محیط واقعی خودتان ببینید و قبل از خرید، اندازه، ظاهر و جایگیری آن را بررسی کنید.','placeholder-hero.png','placeholder-icon.svg','تجربه Mr.AR','/experiences'),('summary','محصول را در دنیای واقعی ببینید و بعد تصمیم بگیرید','تجربه محصول را پیش از تصمیم‌گیری به فضای واقعی مشتری بیاورید.','placeholder-summary.png','','',''),('problems','چه چیزهایی تصمیم‌گیری را سخت می‌کنند؟','مشتری ممکن است بدون دیدن محصول در فضای خودش، درباره اندازه و جایگیری مطمئن نباشد.','','','', ''),('solution','راه‌حل چیست؟','محصول را در محیط واقعی مشتری نمایش دهید تا انتخاب ملموس‌تر شود.','placeholder-solution.png','','',''),('process','از محصول تا تجربه','مسیر ساده‌ای برای آماده‌سازی، انتشار و تجربه محصول.','','','', ''),('visual','تجربه‌ای که مشتری می‌بیند','نمایش محصول در فضای واقعی.','','','', ''),('scenarios','Mr.AR در موقعیت‌های مختلف','دو مسیر رایج استفاده از تجربه محصول.','','','', ''),('projects','تجربه‌های واقعی Mr.AR','نمونه‌ها را با گوشی خودتان امتحان کنید.','','','مشاهده تجربه‌ها','/experiences'),('capabilities','قابلیت‌های Mr.AR','امکاناتی برای تجربه بهتر محصول.','','','مشاهده قابلیت‌ها','/features'),('usage','مشتری چطور استفاده می‌کند؟','یک مسیر ساده از دیدن تا اقدام.','','','', ''),('modeling','مدل‌سازی محصول','اگر مدل سه‌بعدی آماده ندارید، امکان آماده‌سازی آن وجود دارد.','placeholder-modeling.png','','درخواست مدلسازی','/contact'),('contact','شروع کنیم','برای اجرای تجربه محصول با ما در تماس باشید.','placeholder-contact.png','','تماس با ما','/contact')],
      'solutions':[('hero','راهکارها','هر جا که دیدن نتیجه مهم است، یک تجربه واقعی می‌تواند تصمیم‌گیری را ساده‌تر کند.','placeholder-page-hero.png','','',''),('cards','نمایش کارت‌های راهکارها','ترتیب کارت‌ها را مدیریت کنید.','','','','')],
      'features':[('hero','قابلیت‌ها','امکاناتی برای دیدن بهتر، بررسی دقیق‌تر و ساختن تجربه‌ای کامل‌تر.','placeholder-page-hero.png','','',''),('cards','نمایش کارت‌های قابلیت‌ها','ترتیب کارت‌ها را مدیریت کنید.','','','','')],
      'experiences':[('hero','تجربه‌های واقعی','نمونه‌ها را ببینید و با گوشی خودتان امتحان کنید.','placeholder-page-hero.png','','',''),('cards','نمایش نمونه‌کارها','ترتیب نمونه‌کارها را مدیریت کنید.','','','','')],
      'team':[('hero','تیم ما','آدم‌هایی که برای ساختن تجربه‌های بهتر کنار هم کار می‌کنند.','placeholder-page-hero.png','','',''),('cards','نمایش اعضای تیم','ترتیب اعضای تیم را مدیریت کنید.','','','','')],
      'contact':[('hero','تماس با ما','برای شروع همکاری، دریافت Demo یا درخواست مدلسازی با ما در تماس باشید.','placeholder-page-hero.png','','','')]
    }
    page_ids={r['slug']:r['id'] for r in c.execute('SELECT id,slug FROM pages')}
    for slug, defs in final_sections.items():
        pid=page_ids.get(slug)
        if not pid: continue
        for i,(key,title,body,img,icon,bt,bu) in enumerate(defs):
            if not c.execute('SELECT 1 FROM page_sections WHERE page_id=? AND section_key=?',(pid,key)).fetchone():
                c.execute('INSERT INTO page_sections(page_id,section_key,title,body,image,icon,button_text,button_url,sort_order) VALUES(?,?,?,?,?,?,?,?,?)',(pid,key,title,body,img,icon,bt,bu,i))
    if not c.execute("SELECT 1 FROM site_settings WHERE key='final_structure_migrated'").fetchone():
        # 'applications' is still the active key for the Artect solutions section.
        # Do not treat it as legacy during migration: the page template and section sorter use it.
        legacy_keys={'home':{'features','businesses','scenarios','experiences'},'artect':{'problem','what-you-see','features','experiences'},'mr-ar':{'intro','online-store','brands','exhibition','features'},'solutions':{'building','architecture','furniture','equipment','exhibition'},'features':{'scale','move','rotate','appearance','info','qr'},'experiences':{'experiences'},'team':{'team'},'contact':{'contact'}}
        for slug,keys in legacy_keys.items():
            pid=page_ids.get(slug)
            if pid:
                for k in keys: c.execute('DELETE FROM page_sections WHERE page_id=? AND section_key=?',(pid,k))
        # Apply the final section copy to existing matching records; this keeps the editor model unchanged.
        for slug, defs in final_sections.items():
            pid=page_ids.get(slug)
            if not pid: continue
            for i,(key,title,body,img,icon,bt,bu) in enumerate(defs):
                c.execute('UPDATE page_sections SET title=?,body=?,image=?,icon=?,button_text=?,button_url=?,sort_order=?,enabled=1 WHERE page_id=? AND section_key=?',(title,body,img,icon,bt,bu,i,pid,key))
        c.execute("INSERT INTO site_settings(key,value) VALUES('final_structure_migrated','1')")

    # Keep the Artect solutions section available even for databases where an older
    # migration already removed the 'applications' row. Fill only blank headings so
    # any existing user-authored title/body is preserved and remains editable.
    artect_pid=page_ids.get('artect')
    if artect_pid:
        app_def=next((item for item in final_sections['artect'] if item[0]=='applications'),None)
        if app_def:
            app_order=next(i for i,item in enumerate(final_sections['artect']) if item[0]=='applications')
            app_row=c.execute("SELECT id,title,body FROM page_sections WHERE page_id=? AND section_key='applications' ORDER BY id LIMIT 1",(artect_pid,)).fetchone()
            if not app_row:
                _,app_title,app_body,app_img,app_icon,app_button,app_url=app_def
                c.execute('INSERT INTO page_sections(page_id,section_key,title,body,image,icon,button_text,button_url,enabled,sort_order) VALUES(?,?,?,?,?,?,?,?,1,?)',(artect_pid,'applications',app_title,app_body,app_img,app_icon,app_button,app_url,app_order))
            else:
                _,app_title,app_body,_,_,_,_=app_def
                c.execute("UPDATE page_sections SET title=CASE WHEN TRIM(COALESCE(title,''))='' THEN ? ELSE title END, body=CASE WHEN TRIM(COALESCE(body,''))='' THEN ? ELSE body END WHERE id=?",(app_title,app_body,app_row['id']))

    card_seed=[
      ('solution','ساختمان و املاک','قبل از ساخت، نتیجه را ببینید.','برای ارائه پروژه و پیش‌فروش، مدل را در محیط واقعی نمایش دهید.','building',''),
      ('solution','معماری و طراحی داخلی','طرح را از روی نقشه بیرون بیاورید.','چیدمان و ظاهر فضا را پیش از اجرا در محیط واقعی بررسی کنید.','interior',''),
      ('solution','مبلمان، کابینت و دکوراسیون','قبل از خرید یا اجرا، نتیجه را ببینید.','محصول را در فضای واقعی قرار دهید تا جایگیری و ظاهر روشن شود.','furniture',''),
      ('solution','تجهیزات و تأسیسات','اگر تجهیز را نمی‌توانید بیاورید، مدل آن را بیاورید.','تجهیزات بزرگ یا حساس را به شکل سه‌بعدی در محل نمایش دهید.','equipment',''),
      ('solution','نمایشگاه‌ها','محصول را حتی بدون نمونه واقعی نمایش دهید.','مدل محصول یا غرفه را در فضای نمایشگاه در اختیار بازدیدکننده قرار دهید.','exhibition',''),
    ]
    for typ,title,short,full,img,icon in card_seed:
        if not c.execute('SELECT 1 FROM content_cards WHERE card_type=? AND title=?',(typ,title)).fetchone(): c.execute('INSERT INTO content_cards(card_type,title,short_desc,full_desc,image,icon,link,sort_order) VALUES(?,?,?,?,?,?,?,?)',(typ,title,short,full,'placeholder-card.png','placeholder-icon.svg','/contact',0))
    cap=[('main_capability','اندازه واقعی','محصول یا پروژه را با مقیاس واقعی ببینید.'),('main_capability','جابجایی','مدل را در فضای واقعی حرکت دهید.'),('main_capability','چرخش','از زاویه‌های مختلف بررسی کنید.'),('main_capability','رنگ و ظاهر','در صورت تعریف مدل، ظاهر و متریال را تغییر دهید.'),('main_capability','اطلاعات','توضیحات مرتبط را کنار مدل نمایش دهید.'),('main_capability','QR Code','تجربه را با یک QR Code در اختیار مخاطب قرار دهید.')]
    for typ,title,short in cap:
        if not c.execute('SELECT 1 FROM content_cards WHERE card_type=? AND title=?',(typ,title)).fetchone(): c.execute('INSERT INTO content_cards(card_type,title,short_desc,image,icon,sort_order) VALUES(?,?,?,?,?,?)',(typ,title,short,'','placeholder-icon.svg',0))
    supp=[('supp_capability','مدل‌سازی','اگر مدل سه‌بعدی آماده ندارید، امکان آماده‌سازی آن وجود دارد.'),('supp_capability','تجربه وب','تجربه می‌تواند از طریق وب و لینک مستقیم در دسترس باشد.'),('supp_capability','اپلیکیشن اختصاصی','در صورت نیاز، تجربه می‌تواند در اپلیکیشن اختصاصی ارائه شود.')]
    for typ,title,short in supp:
        if not c.execute('SELECT 1 FROM content_cards WHERE card_type=? AND title=?',(typ,title)).fetchone(): c.execute('INSERT INTO content_cards(card_type,title,short_desc,image,icon,sort_order) VALUES(?,?,?,?,?,?)',(typ,title,short,'','placeholder-icon.svg',0))
    scenarios=[('scenario_home','پیش‌فروش پروژه','پروژه را پیش از ساخت در فضای واقعی معرفی کنید.'),('scenario_home','نمایش محصول در نمایشگاه','محصولات بزرگ یا غیرقابل‌حمل را سه‌بعدی نمایش دهید.'),('scenario_home','بررسی چیدمان','چیدمان را پیش از اجرا ببینید.'),('scenario_home','نگهداری و تأسیسات','مدل تجهیزات را در محل واقعی بررسی کنید.')]
    for typ,title,short in scenarios:
        if not c.execute('SELECT 1 FROM content_cards WHERE card_type=? AND title=?',(typ,title)).fetchone(): c.execute('INSERT INTO content_cards(card_type,title,short_desc,image,icon,link,sort_order) VALUES(?,?,?,?,?,?,?)',(typ,title,short,'placeholder-scenario.png','placeholder-icon.svg','/solutions',0))
    try: c.execute('ALTER TABLE content_cards ADD COLUMN slug TEXT UNIQUE')
    except sqlite3.OperationalError: pass
    # Migrate legacy project cards into the shared card engine without deleting the legacy table.
    for pr in c.execute('SELECT * FROM projects').fetchall():
        if not c.execute("SELECT 1 FROM content_cards WHERE card_type='work' AND slug=?",(pr['slug'],)).fetchone():
            c.execute('INSERT INTO content_cards(slug,card_type,title,short_desc,full_desc,image,link,tag,enabled,show_home,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(pr['slug'],'work',pr['title'],pr['short_desc'],pr['full_desc'],pr['image'],pr['ar_url'],'Artect',pr['enabled'],pr['show_home'],pr['sort_order']))
    for pr in c.execute('SELECT * FROM projects').fetchall():
        c.execute("UPDATE content_cards SET link=COALESCE(NULLIF(link,''),?), tag=COALESCE(NULLIF(tag,''),'Artect') WHERE card_type='work' AND slug=?",(pr['ar_url'],pr['slug']))
    c.execute("UPDATE content_cards SET image='placeholder-card.png' WHERE card_type='work' AND (image IS NULL OR image='' OR image IN ('hero.jpg','equipment.jpg','interior.jpg','building.jpg','exhibition.jpg','furniture.jpg','product.jpg'))")
    c.execute("UPDATE team_members SET image='placeholder-card.png' WHERE image IS NULL OR image='' OR image IN ('hero.jpg','equipment.jpg','interior.jpg','building.jpg','exhibition.jpg','furniture.jpg','product.jpg')")
    c.execute("DELETE FROM media WHERE filename IN ('cube.svg','eye.svg')")
    if not c.execute("SELECT 1 FROM media WHERE kind='icon' AND filename='placeholder-icon.svg'").fetchone(): c.execute("INSERT INTO media(filename,kind,alt_text) VALUES('placeholder-icon.svg','icon','256 × 256px placeholder')")
    for _f in ['placeholder-hero.png','placeholder-summary.png','placeholder-page-hero.png','placeholder-card.png','placeholder-scenario.png','placeholder-modeling.png','placeholder-contact.png','placeholder-solution.png','placeholder-logo.png']:
        if not c.execute("SELECT 1 FROM media WHERE kind='image' AND filename=?",(_f,)).fetchone(): c.execute("INSERT INTO media(filename,kind,alt_text) VALUES(?,?,?)",(_f,'image',_f))
    homecards=[('process_home','دیدن','تجربه را شروع کنید.'),('process_home','بررسی','مدل را در فضای واقعی بررسی کنید.'),('process_home','تصمیم','پس از دیدن نتیجه تصمیم بگیرید.') ,('home_step','دیدن','نتیجه را در فضای واقعی ببینید.'),('home_step','بررسی','ابعاد، ظاهر و جایگیری را بررسی کنید.'),('home_step','تصمیم','با اطلاعات روشن‌تر اقدام کنید.')]
    for typ,title,short in homecards:
        if not c.execute('SELECT 1 FROM content_cards WHERE card_type=? AND title=?',(typ,title)).fetchone(): c.execute('INSERT INTO content_cards(card_type,title,short_desc,icon,sort_order) VALUES(?,?,?,?,?)',(typ,title,short,'placeholder-icon.svg',0))
    sol_ids=[r['id'] for r in c.execute("SELECT id FROM content_cards WHERE card_type='solution' ORDER BY sort_order,id").fetchall()]
    for i,r in enumerate(c.execute("SELECT id FROM content_cards WHERE card_type='scenario_home' ORDER BY sort_order,id").fetchall()):
        if sol_ids: c.execute('UPDATE content_cards SET link=? WHERE id=?',(f'/solutions?open={sol_ids[i%len(sol_ids)]}',r['id']))
    c.execute("UPDATE content_cards SET show_home=1 WHERE card_type IN ('solution','main_capability')")
    # Capability cards are icon-only; their image field is intentionally unused.
    c.execute("UPDATE content_cards SET image='' WHERE card_type IN ('main_capability','supp_capability')")
    c.execute("UPDATE content_cards SET show_home=1 WHERE card_type='work' AND show_home IS NULL")
    c.execute("UPDATE content_cards SET show_artect=1 WHERE card_type='main_capability'")
    c.execute("UPDATE content_cards SET show_mrar=1 WHERE card_type='main_capability'")
    c.execute("UPDATE content_cards SET show_artect=1 WHERE card_type='work' AND show_artect=0")
    c.execute("UPDATE content_cards SET show_mrar=1 WHERE card_type='work' AND show_mrar=0")
    # Page-specific process/usage/problem/visual/application cards use the same shared entity.
    seed2=[
      ('problem_artect','مقیاس و جایگیری','اندازه و محل قرارگیری را بدون تصور ذهنی بررسی کنید.'),('problem_artect','ظاهر و انتخاب','رنگ، متریال و اجزای قابل تغییر را ببینید.'),('problem_artect','دسترسی به اطلاعات','اطلاعات و لینک اقدام را کنار تجربه قرار دهید.'),
      ('problem_mrar','اندازه محصول','قبل از خرید، اندازه را در فضای واقعی ببینید.'),('problem_mrar','جایگیری','محل قرارگیری محصول را در محیط خودتان بررسی کنید.'),('problem_mrar','اطمینان پیش از خرید','تصمیم را با یک تجربه ملموس‌تر انجام دهید.'),
      ('visual_artect','نمایش سه‌بعدی','مدل سه‌بعدی در فضای واقعی.'),('visual_artect','تغییر ظاهر','تغییرات تعریف‌شده را مشاهده کنید.'),('visual_artect','اطلاعات محصول','اطلاعات در کنار تجربه.'),('visual_mrar','محصول در خانه','محصول را در فضای واقعی مشتری ببینید.'),('visual_mrar','اندازه و جایگیری','اندازه و محل قرارگیری را بررسی کنید.'),
      ('application_artect','پیش‌فروش و املاک','پروژه را پیش از ساخت بهتر معرفی کنید.'),('application_artect','معماری و طراحی','طرح را در فضای واقعی بررسی کنید.'),('application_artect','نمایشگاه','محصول را حتی بدون نمونه واقعی نمایش دهید.'),('application_artect','تجهیزات','تجهیزات را در محل موردنظر نمایش دهید.'),('application_artect','مبلمان و دکوراسیون','نتیجه را پیش از خرید یا اجرا ببینید.'),
      ('scenario_artect','ساختمان و املاک','پروژه را در محل واقعی ببینید.'),('scenario_artect','طراحی داخلی','چیدمان را پیش از اجرا بررسی کنید.'),('scenario_artect','تأسیسات','تجهیزات را بدون جابه‌جایی فیزیکی بررسی کنید.'),('scenario_artect','نمایشگاه','محصول را در فضای نمایشگاه تجربه کنید.'),
      ('process_artect','مدل‌سازی','مدل سه‌بعدی آماده یا ایجاد می‌شود.'),('process_artect','آماده‌سازی تجربه','مدل برای تجربه AR تنظیم می‌شود.'),('process_artect','قرارگیری در فضا','مدل با اندازه واقعی در محیط قرار می‌گیرد.'),('process_artect','تجربه و اقدام','مخاطب تجربه می‌کند و اطلاعات یا لینک را می‌بیند.'),
      ('process_mrar','مدل محصول','مدل سه‌بعدی محصول آماده می‌شود.'),('process_mrar','آماده‌سازی','تجربه محصول برای محیط واقعی تنظیم می‌شود.'),('process_mrar','انتشار','تجربه در صفحه یا مسیر موردنظر قرار می‌گیرد.'),('process_mrar','تجربه مشتری','مشتری محصول را در محیط خود می‌بیند.'),('process_mrar','تصمیم','مشتری پس از دیدن نتیجه تصمیم می‌گیرد.'),
      ('usage_artect','ورود به تجربه','مخاطب از لینک یا QR وارد می‌شود.'),('usage_artect','دسترسی به دوربین','محیط برای قرارگیری مدل شناسایی می‌شود.'),('usage_artect','دیدن و تغییر','مدل دیده و در صورت تعریف، تغییر داده می‌شود.'),('usage_artect','اقدام','اطلاعات، لینک یا درخواست بعدی در دسترس است.'),
      ('usage_mrar','انتخاب محصول','مشتری محصول را انتخاب می‌کند.'),('usage_mrar','باز کردن تجربه','تجربه AR از صفحه محصول اجرا می‌شود.'),('usage_mrar','دیدن در خانه','محصول در فضای واقعی دیده می‌شود.'),('usage_mrar','تصمیم','مشتری با دیدن نتیجه تصمیم می‌گیرد.'),
      ('scenario_mrar_left','فروشگاه آنلاین','گزینه دیدن محصول در خانه به صفحه محصول اضافه می‌شود.'),('scenario_mrar_left','مبلمان و دکوراسیون','محصول پیش از خرید در فضای مشتری دیده می‌شود.'),('scenario_mrar_left','لوازم خانگی','اندازه و جایگیری پیش از خرید بررسی می‌شود.'),('scenario_mrar_left','خودرو و محصولات بزرگ','مدل محصول برای معرفی و مقایسه نمایش داده می‌شود.'),
      ('scenario_mrar_right','برندها','تجربه محصول بخشی از معرفی برند می‌شود.'),('scenario_mrar_right','نمایشگاه','محصول بدون نمونه فیزیکی قابل نمایش است.'),('scenario_mrar_right','محصولات لوکس','مخاطب پیش از تصمیم محصول را در فضای خود می‌بیند.'),('scenario_mrar_right','فروش و ارائه','دیدن نتیجه به مسیر تصمیم‌گیری کمک می‌کند.')
    ]
    for typ,title,short in seed2:
        if not c.execute('SELECT 1 FROM content_cards WHERE card_type=? AND title=?',(typ,title)).fetchone(): c.execute('INSERT INTO content_cards(card_type,title,short_desc,image,icon,sort_order) VALUES(?,?,?,?,?,?)',(typ,title,short,'placeholder-card.png','placeholder-icon.svg',0))

    # Make sure current pages have useful editable sections.
    page_ids={r['slug']:r['id'] for r in c.execute('SELECT id,slug FROM pages')}
    defaults={
      'home':[('hero','اگر اینجا بود، چه شکلی می‌شد؟ همین‌جا ببینید.','محصولات، پروژه‌ها و فضاهای سه‌بعدی خود را با اندازه واقعی در محیط موردنظر ببینید؛ قبل از اینکه آن‌ها را بسازید، بخرید یا اجرا کنید.','hero.jpg','cube.svg','تجربه Artect','/experiences'),('features','قابلیت‌ها','فقط آن را نبینید؛ بررسی‌اش کنید.','product.jpg','eye.svg','',''),('businesses','کسب‌وکارها','هر جا که دیدن نتیجه مهم است، Artect می‌تواند کمک کند.','building.jpg','cube.svg','','/solutions'),('scenarios','سناریوها','قبل از ساخت، خرید یا اجرا، نتیجه را ببینید.','interior.jpg','eye.svg','',''),('experiences','تجربه‌های واقعی','درباره Artect نخوانید؛ خودتان تجربه‌اش کنید.','exhibition.jpg','cube.svg','مشاهده همه تجربه‌ها','/experiences')],
      'artect':[('hero','آنچه می‌بینید را به دنیای واقعی بیاورید.','به‌جای تصور کردن نتیجه، آن را ببینید. Artect مدل سه‌بعدی را با اندازه واقعی در محیط واقعی قرار می‌دهد.','building.jpg','cube.svg','تجربه کنید','/experiences'),('problem','وقتی دیدن نتیجه مهم است، تصور کردن کافی نیست.','یک تصویر یا نقشه همیشه برای درک اندازه، ظاهر و جایگیری کافی نیست.','building.jpg','eye.svg','',''),('what-you-see','هر چیزی که باید در یک فضا دیده شود.','ساختمان، محصول، فضای داخلی، تجهیزات و نمایشگاه‌ها.','interior.jpg','cube.svg','',''),('applications','هر جا که دیدن نتیجه مهم است.','راهکارهای مختلف Artect برای ارائه بهتر.','exhibition.jpg','cube.svg','مشاهده راهکارها','/solutions'),('features','فقط آن را نبینید؛ بررسی‌اش کنید.','اندازه واقعی، جابه‌جایی، چرخش، ظاهر و اطلاعات.','product.jpg','eye.svg','',''),('experiences','درباره Artect نخوانید؛ خودتان تجربه‌اش کنید.','نمونه‌های واقعی را با گوشی خودتان امتحان کنید.','furniture.jpg','cube.svg','مشاهده تجربه‌ها','/experiences')],
      'mr-ar':[('hero','قبل از خرید، ببینید محصول در خانه شما چطور دیده می‌شود.','Mr.AR به مشتری اجازه می‌دهد محصول را با دوربین گوشی در محیط واقعی ببیند و قبل از خرید، اندازه، ظاهر و جایگیری آن را بررسی کند.','furniture.jpg','eye.svg','تجربه Mr.AR','/experiences'),('intro','محصول را در دنیای واقعی ببینید و بعد تصمیم بگیرید.','قبل از تصمیم، محصول را در فضای خودتان ببینید.','furniture.jpg','cube.svg','',''),('online-store','یک قدم ساده برای تجربه‌ای متفاوت در فروشگاه شما.','گزینه «محصول را در خانه خود ببینید» را به صفحه محصول اضافه کنید.','product.jpg','eye.svg','',''),('brands','تجربه‌ای که بخشی از برند شماست.','تجربه محصول را متناسب با هویت برند ارائه کنید.','interior.jpg','cube.svg','',''),('exhibition','اگر محصول نمی‌تواند به مشتری بیاید، محصول را به مشتری نشان دهید.','محصولات بزرگ یا بدون نمونه واقعی را سه‌بعدی نمایش دهید.','exhibition.jpg','cube.svg','',''),('features','مشتری چه کارهایی می‌تواند انجام دهد؟','اندازه واقعی، جابه‌جایی، چرخش، ظاهر و لینک خرید.','product.jpg','eye.svg','','')],
      'solutions':[('building','ساختمان و املاک','قبل از اینکه ساخته شود، ببینید چه شکلی خواهد بود.','building.jpg','cube.svg','درخواست Demo','/contact'),('architecture','معماری و طراحی داخلی','طرح را از روی نقشه بیرون بیاورید.','interior.jpg','eye.svg','',''),('furniture','مبلمان، کابینت و دکوراسیون','قبل از خرید یا اجرا، نتیجه را ببینید.','furniture.jpg','cube.svg','',''),('equipment','تجهیزات و تأسیسات','اگر نمی‌توانید تجهیز را به محل بیاورید، مدل آن را بیاورید.','equipment.jpg','cube.svg','',''),('exhibition','نمایشگاه‌ها','اگر محصولتان نمی‌توانست به نمایشگاه بیاید، چه می‌شد؟','exhibition.jpg','cube.svg','','')],
      'features':[('scale','اندازه واقعی','محصول یا پروژه را با مقیاس واقعی ببینید.','product.jpg','cube.svg','',''),('move','جابجایی','مدل را در فضای واقعی حرکت دهید.','interior.jpg','cube.svg','',''),('rotate','چرخش','از زاویه‌های مختلف بررسی کنید.','furniture.jpg','eye.svg','',''),('appearance','رنگ و ظاهر','در صورت تعریف مدل، ظاهر و متریال را تغییر دهید.','product.jpg','eye.svg','',''),('info','اطلاعات','توضیحات مرتبط را کنار مدل نمایش دهید.','building.jpg','cube.svg','',''),('qr','QR Code','تجربه را با یک QR Code در اختیار مخاطب قرار دهید.','exhibition.jpg','cube.svg','','')],
      'experiences':[('experiences','تجربه‌های واقعی','نمونه‌های واقعی را ببینید و با گوشی خودتان تجربه کنید.','exhibition.jpg','cube.svg','','')],
      'team':[('team','تیم ما','تیمی برای ساختن تجربه‌های بهتر.','furniture.jpg','cube.svg','','')],
      'contact':[('contact','بیایید تجربه‌ای بسازیم که دیده شود.','برای معرفی محصول، پروژه یا فضای خود در دنیای واقعی با ما صحبت کنید.','hero.jpg','cube.svg','تماس با ما','/contact')]
    }
    for slug,defs in defaults.items():
        pid=page_ids.get(slug)
        if pid and not c.execute('SELECT 1 FROM page_sections WHERE page_id=? LIMIT 1',(pid,)).fetchone():
            for i,(key,title,body,img,icon,bt,bu) in enumerate(defs): c.execute('INSERT INTO page_sections(page_id,section_key,title,body,image,icon,button_text,button_url,sort_order) VALUES(?,?,?,?,?,?,?,?,?)',(pid,key,title,body,img,icon,bt,bu,i))
    # Dedicated homepage 3D showcase section; included in the normal section ordering list.
    home_id=page_ids.get('home')
    if home_id and not c.execute("SELECT 1 FROM page_sections WHERE page_id=? AND section_key='home-3d-showcase'",(home_id,)).fetchone():
        c.execute("INSERT INTO page_sections(page_id,section_key,title,body,enabled,sort_order) VALUES(?,?,?,?,1,?)",
                  (home_id,'home-3d-showcase','','',4))
        c.execute("UPDATE page_sections SET sort_order=sort_order+1 WHERE page_id=? AND section_key!='home-3d-showcase' AND sort_order>=4",(home_id,))
    # Dedicated Mr.AR animation carousel section: participates in normal page section ordering.
    mr_id=page_ids.get('mr-ar')
    if mr_id and not c.execute("SELECT 1 FROM page_sections WHERE page_id=? AND section_key='mr-ar-animations'",(mr_id,)).fetchone():
        c.execute("INSERT INTO page_sections(page_id,section_key,title,body,enabled,sort_order) VALUES(?,?,?,?,1,?)",
                  (mr_id,'mr-ar-animations','','',2))
        c.execute("UPDATE page_sections SET sort_order=sort_order+1 WHERE page_id=? AND section_key!='mr-ar-animations' AND sort_order>=2",(mr_id,))
    # Artect annotation-tour carousel; the section is part of the ordinary page-ordering system.
    artect_id=page_ids.get('artect')
    if artect_id and not c.execute("SELECT 1 FROM page_sections WHERE page_id=? AND section_key='artect-annotation-showcase'",(artect_id,)).fetchone():
        # Place it after the hero and summary by default; admins can drag it anywhere later.
        order=2
        c.execute('UPDATE page_sections SET sort_order=sort_order+1 WHERE page_id=? AND sort_order>=?',(artect_id,order))
        c.execute("INSERT INTO page_sections(page_id,section_key,title,body,enabled,sort_order) VALUES(?,?,?,?,1,?)",
                  (artect_id,'artect-annotation-showcase','تجربهٔ تعاملی مدل‌های سه‌بعدی','',order))
    try:
        c.execute("ALTER TABLE mr_ar_animation_cards ADD COLUMN extra_json TEXT DEFAULT '{}'")
    except sqlite3.OperationalError:
        pass

    # Backward-compatible migration for homepage visibility of projects.
    try:
        c.execute('ALTER TABLE projects ADD COLUMN show_home INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    # SMTP credentials must not be stored in SQLite. Remove secrets written by older versions.
    legacy_smtp_secret = c.execute("SELECT 1 FROM site_settings WHERE key='smtp_password' LIMIT 1").fetchone()
    if legacy_smtp_secret:
        c.execute("DELETE FROM site_settings WHERE key='smtp_password'")
        logger.warning('Removed legacy SMTP password from the database. Configure ARTECT_SMTP_PASSWORD in the server environment.')
    c.commit(); c.close()


def db_read(fn):
    c=connect_db()
    try: return fn(c)
    finally: c.close()

def db_write(fn,retries=8):
    last=None
    for i in range(retries):
        c=connect_db()
        try:
            c.execute('BEGIN IMMEDIATE'); result=fn(c); c.execute('COMMIT'); c.close(); return result
        except sqlite3.OperationalError as e:
            last=e
            try:c.execute('ROLLBACK')
            except Exception:pass
            c.close()
            if 'locked' not in str(e).lower() and 'busy' not in str(e).lower(): raise
            time.sleep(.12*(i+1))
        except Exception:
            try:c.execute('ROLLBACK')
            except Exception:pass
            c.close(); raise
    raise last


def active_palette():
    def r(c):
        p=c.execute('SELECT id FROM color_palettes WHERE active=1 LIMIT 1').fetchone()
        if not p:return DEFAULT_COLORS.copy()
        out=DEFAULT_COLORS.copy(); out.update({x['role']:x['value'] for x in c.execute('SELECT role,value FROM palette_colors WHERE palette_id=?',(p['id'],))}); return out
    return db_read(r)

@app.context_processor
def inject():
    def r(c):
        settings={x['key']:x['value'] for x in c.execute('SELECT key,value FROM site_settings')}
        hm=list(c.execute("SELECT * FROM menus WHERE location='header' AND enabled=1 ORDER BY sort_order,id")); fm=list(c.execute("SELECT * FROM menus WHERE location='footer' AND enabled=1 ORDER BY sort_order,id")); cols=list(c.execute("SELECT * FROM footer_columns WHERE enabled=1 ORDER BY sort_order,id")); return settings,hm,fm,cols
    settings,hm,fm,cols=db_read(r)
    return {'palette':active_palette(),'settings':settings,'header_menu':hm,'footer_menu':fm,'footer_columns':cols,'role_labels':ROLE_LABELS}

@app.template_filter('render_rich')
def render_rich(value):
    # IMPORTANT: do not compile marker syntax here. The value must remain a
    # plain string until the final response compiler runs in @after_request.
    # Markup is kept because normal contenteditable HTML formatting is part of
    # the stored value and is restored by the final response pass.
    return Markup('' if value is None else str(value))

@app.template_filter('asset_url')
def asset_url(name):
    if not name:return ''
    if name.startswith('/') or name.startswith('http'):return name
    kind='icon' if name.lower().endswith('.svg') else 'image'
    return url_for('serve_icon' if kind=='icon' else 'serve_image',filename=name)

@app.template_global('model_asset')
def model_asset(name):
    if not name:return None
    filename=name[6:] if str(name).startswith('model:') else str(name)
    row=db_read(lambda c:c.execute("SELECT filename,background_filename,background_width,background_height FROM media WHERE kind='model' AND filename=?",(filename,)).fetchone())
    if not row:return None
    return {'filename':row['filename'],'url':url_for('serve_model',filename=row['filename']),'background_url':url_for('serve_image',filename=row['background_filename']) if row['background_filename'] else '', 'background_width':row['background_width'] or 0,'background_height':row['background_height'] or 0}

def get_page(slug):
    return db_read(lambda c:c.execute('SELECT * FROM pages WHERE slug=? AND enabled=1',(slug,)).fetchone())
def get_sections(slug):
    return db_read(lambda c:list(c.execute('SELECT * FROM page_sections ps JOIN pages p ON p.id=ps.page_id WHERE p.slug=? AND ps.enabled=1 ORDER BY ps.sort_order,ps.id',(slug,))))

@app.route('/images/<path:filename>')
def serve_image(filename): return send_from_directory(IMAGE_DIR,filename)
@app.route('/icons/<path:filename>')
def serve_icon(filename): return send_from_directory(ICON_DIR,filename)
@app.route('/videos/<path:filename>')
def serve_video(filename): return send_from_directory(VIDEO_DIR,filename)
@app.route('/models/<path:filename>')
def serve_model(filename): return send_from_directory(MODEL_DIR,filename)

@app.route('/')
def home():
    projects=db_read(lambda c:list(c.execute('SELECT * FROM projects WHERE enabled=1 AND show_home=1 ORDER BY sort_order,id')))
    members=db_read(lambda c:list(c.execute('SELECT * FROM team_members WHERE enabled=1 AND show_home=1 ORDER BY sort_order,id')))
    showcase_cards=[dict(r) for r in db_read(lambda c:list(c.execute('SELECT * FROM model_showcase_cards WHERE enabled=1 ORDER BY sort_order,id')))]
    for showcase_card in showcase_cards:
        try: showcase_card['actual_model_hash']=_sha256_file(os.path.join(MODEL_DIR,showcase_card['model_file'])) if showcase_card['model_file'] else ''
        except OSError: showcase_card['actual_model_hash']=''
    return render_template('site_page.html', page_data=get_page('home'), sections=get_sections('home'), projects=projects, members=members, cards=db_read(lambda c:list(c.execute('SELECT * FROM content_cards WHERE enabled=1 ORDER BY sort_order,id'))), showcase_cards=showcase_cards, page='home', page_kind='home', admin_preview=request.args.get('admin_preview')=='1')
@app.route('/artect')
def artect():
    annotation_cards=[dict(r) for r in db_read(lambda c:list(c.execute('SELECT * FROM artect_annotation_cards WHERE enabled=1 ORDER BY sort_order,id')))]
    for annotation_card in annotation_cards:
        try:
            parsed=json.loads(annotation_card.get('annotations_json') or '{}')
            annotation_card['annotations']=parsed.get('tour',{}).get('annotations',[]) if isinstance(parsed,dict) else []
        except Exception:
            annotation_card['annotations']=[]
    return render_template('site_page.html', page_data=get_page('artect'), sections=get_sections('artect'), cards=db_read(lambda c:list(c.execute('SELECT * FROM content_cards WHERE enabled=1 ORDER BY sort_order,id'))), artect_annotation_cards=annotation_cards, page='artect', page_kind='artect', admin_preview=request.args.get('admin_preview')=='1')
@app.route('/mr-ar')
def mr_ar():
    animation_cards=db_read(lambda c:list(c.execute('SELECT * FROM mr_ar_animation_cards WHERE enabled=1 ORDER BY sort_order,id')))
    return render_template('site_page.html', page_data=get_page('mr-ar'), sections=get_sections('mr-ar'), cards=db_read(lambda c:list(c.execute('SELECT * FROM content_cards WHERE enabled=1 ORDER BY sort_order,id'))), mr_ar_animation_cards=animation_cards, page='mr-ar', page_kind='mr-ar', admin_preview=request.args.get('admin_preview')=='1')
@app.route('/solutions')
def solutions(): return render_template('site_page.html', page_data=get_page('solutions'), sections=get_sections('solutions'), cards=db_read(lambda c:list(c.execute('SELECT * FROM content_cards WHERE enabled=1 ORDER BY sort_order,id'))), page='solutions', page_kind='solutions', admin_preview=request.args.get('admin_preview')=='1')
@app.route('/features')
def features(): return render_template('site_page.html', page_data=get_page('features'), sections=get_sections('features'), cards=db_read(lambda c:list(c.execute('SELECT * FROM content_cards WHERE enabled=1 ORDER BY sort_order,id'))), page='features', page_kind='features', admin_preview=request.args.get('admin_preview')=='1')
@app.route('/experiences')
def experiences():
    projects=db_read(lambda c:list(c.execute('SELECT * FROM projects WHERE enabled=1 ORDER BY sort_order,id')))
    return render_template('site_page.html', page_data=get_page('experiences'), sections=get_sections('experiences'), projects=projects, cards=db_read(lambda c:list(c.execute('SELECT * FROM content_cards WHERE enabled=1 ORDER BY sort_order,id'))), page='experiences', page_kind='experiences', admin_preview=request.args.get('admin_preview')=='1')
@app.route('/team')
def team():
    members=db_read(lambda c:list(c.execute('SELECT * FROM team_members WHERE enabled=1 ORDER BY sort_order,id')))
    return render_template('site_page.html', page_data=get_page('team'), sections=get_sections('team'), members=members, cards=[], page='team', page_kind='team', admin_preview=request.args.get('admin_preview')=='1')
@app.route('/contact',methods=['GET','POST'])
def contact():
    if request.method=='POST':
        vals={k:request.form.get(k,'').strip() for k in ['first_name','last_name','phone','company','industry','services','details','heard_from']}
        db_write(lambda c:c.execute('INSERT INTO contact_messages(first_name,last_name,phone,company,industry,services,details,heard_from) VALUES(?,?,?,?,?,?,?,?)',tuple(vals.values())))
        try:
            import smtplib
            from email.message import EmailMessage
            cfg=db_read(lambda c:{x['key']:x['value'] for x in c.execute('SELECT * FROM site_settings') if x['key'] != 'smtp_password'})
            smtp_host=(cfg.get('smtp_host') or '').strip()
            smtp_user=(cfg.get('smtp_user') or '').strip()
            smtp_password=os.environ.get('ARTECT_SMTP_PASSWORD', '').replace(' ', '').strip()
            smtp_to=(cfg.get('admin_email') or '').strip()
            smtp_from=(cfg.get('smtp_from') or '').strip()
            if smtp_from in ('', '---'):
                smtp_from=smtp_user
            try:
                smtp_port=int(cfg.get('smtp_port') or 587)
            except (TypeError, ValueError):
                smtp_port=587
                logger.warning('SMTP port is invalid; using 587.')
            smtp_tls=cfg.get('smtp_tls', '1') != '0'
            valid_email=lambda value: bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value or ''))
            if not smtp_host or not valid_email(smtp_to):
                logger.info('Email notification skipped: SMTP host or destination email is not configured.')
            elif smtp_user and not smtp_password:
                logger.error('Email notification skipped: set ARTECT_SMTP_PASSWORD in the server environment; credentials are not read from the database.')
            elif smtp_password and not smtp_user:
                logger.error('Email notification skipped: SMTP password is configured but SMTP user is missing.')
            elif smtp_user and not smtp_tls and smtp_port != 465:
                logger.error('Email notification skipped: authenticated SMTP requires TLS.')
            else:
                msg=EmailMessage()
                msg['Subject']='درخواست جدید Demo - Artect'
                msg['From']=smtp_from or smtp_user
                msg['To']=smtp_to
                msg.set_content('\n'.join(f'{k}: {v}' for k,v in vals.items()))
                timeout=15
                if smtp_port == 465:
                    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout, context=ssl.create_default_context()) as smtp:
                        if smtp_user:
                            smtp.login(smtp_user, smtp_password)
                        smtp.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as smtp:
                        smtp.ehlo()
                        if smtp_tls:
                            smtp.starttls(context=ssl.create_default_context())
                            smtp.ehlo()
                        if smtp_user:
                            smtp.login(smtp_user, smtp_password)
                        smtp.send_message(msg)
        except Exception:
            # The contact record is already persisted; keep the public flow stable but
            # log the delivery failure so the operator can diagnose SMTP configuration.
            logger.exception('SMTP notification delivery failed; contact message remains stored in the admin panel.')
        flash('درخواست شما با موفقیت ثبت شد.')
        return redirect('/contact')
    return render_template('site_page.html', page_data=get_page('contact'), sections=get_sections('contact'), page='contact', page_kind='contact', admin_preview=request.args.get('admin_preview')=='1')
def load_project_media(row):
    try:
        data=json.loads(row['extra_json'] or '{}') if row and row['extra_json'] else {}
    except Exception:
        data={}
    items=[]
    for item in data.get('detail_media',[]) if isinstance(data,dict) else []:
        if not isinstance(item,dict) or item.get('type') not in ('image','video','model') or not item.get('file'): continue
        items.append({'type':item['type'],'file':item['file'],'url':'/project-media/'+item['file']})
    return items

@app.route('/project-media/<path:filename>')
def project_media(filename):
    return send_from_directory(PROJECT_MEDIA_DIR, filename)

@app.route('/admin/api/project/<int:pid>/media',methods=['GET','POST'])
def admin_project_media(pid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute("SELECT * FROM content_cards WHERE id=? AND card_type='work'",(pid,)).fetchone())
    if not row:return jsonify({'error':'not found'}),404
    try: data=json.loads(row['extra_json'] or '{}')
    except Exception: data={}
    if not isinstance(data,dict): data={}
    items=data.setdefault('detail_media',[])
    if request.method=='POST':
        kind=request.form.get('kind','').strip()
        if kind not in ('image','video','model'): return jsonify({'error':'invalid kind'}),400
        files=request.files.getlist('files')
        allowed={'image':{'png','jpg','jpeg','webp','gif','avif'},'video':{'mp4','webm','mov','m4v'},'model':{'glb'}}
        added=[]
        for f in files:
            if not f or not f.filename: continue
            ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
            if ext not in allowed[kind]: continue
            stem=secure_filename(f.filename.rsplit('.',1)[0]) or 'project-media'
            name=f'{stem}-{uuid.uuid4().hex[:10]}.{ext}'
            f.save(os.path.join(PROJECT_MEDIA_DIR,name))
            item={'type':kind,'file':name}
            items.append(item); added.append(item)
        db_write(lambda c:c.execute('UPDATE content_cards SET extra_json=? WHERE id=?', (json.dumps(data,ensure_ascii=False),pid)))
        return jsonify({'ok':True,'items':load_project_media(db_read(lambda c:c.execute('SELECT * FROM content_cards WHERE id=?',(pid,)).fetchone()))})
    return jsonify({'ok':True,'items':load_project_media(row)})

@app.route('/admin/api/project/<int:pid>/media/delete',methods=['POST'])
def admin_project_media_delete(pid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute("SELECT * FROM content_cards WHERE id=? AND card_type='work'",(pid,)).fetchone())
    if not row:return jsonify({'error':'not found'}),404
    filename=(request.get_json(silent=True) or {}).get('file','')
    try: data=json.loads(row['extra_json'] or '{}')
    except Exception: data={}
    items=data.get('detail_media',[]) if isinstance(data,dict) else []
    new=[]
    for item in items:
        if isinstance(item,dict) and item.get('file')==filename:
            path=os.path.join(PROJECT_MEDIA_DIR,filename)
            if os.path.isfile(path):
                try: os.remove(path)
                except OSError: pass
        else:new.append(item)
    data['detail_media']=new
    db_write(lambda c:c.execute('UPDATE content_cards SET extra_json=? WHERE id=?',(json.dumps(data,ensure_ascii=False),pid)))
    return jsonify({'ok':True,'items':load_project_media(db_read(lambda c:c.execute('SELECT * FROM content_cards WHERE id=?',(pid,)).fetchone()))})

@app.route('/project/<slug>')
def project(slug):
    p=db_read(lambda c:c.execute("SELECT * FROM content_cards WHERE card_type='work' AND slug=? AND enabled=1",(slug,)).fetchone())
    if not p:return 'نمونه‌کار پیدا نشد',404
    qr=None
    if p['link']:
        path=os.path.join(QR_DIR,f"card-{p['id']}.png"); qrcode.make(p['link']).save(path); qr=url_for('static',filename=f'images/qr/card-{p["id"]}.png')
    return render_template('project.html',project=p,qr=qr,project_images=[],detail_media=load_project_media(p),page='project')

def current_admin():
    aid=session.get('admin_id')
    if not aid:return None
    return db_read(lambda c:c.execute('SELECT u.*,COALESCE(u.is_owner,0) is_owner FROM admin_users u WHERE u.id=?',(aid,)).fetchone())

def owner_required():
    u=current_admin()
    if not u:return redirect(url_for('admin_login'))
    if not u['is_owner']:
        flash('این بخش فقط برای حساب اصلی مدیر قابل دسترسی است.')
        return redirect('/admin')
    return None

@app.route('/admin/accounts',methods=['GET','POST'])
def admin_accounts():
    g=admin_guard()
    if g:return g
    me=current_admin()
    if not me:return redirect('/admin/login')
    if me['is_owner']:
        if request.method=='POST':
            u=request.form.get('username','').strip(); pw=request.form.get('password','')
            if u and pw:
                try: db_write(lambda c:c.execute('INSERT INTO admin_users(username,password_hash,status,is_owner) VALUES(?,?,1,0)',(u,generate_password_hash(pw))))
                except sqlite3.IntegrityError: flash('نام کاربری تکراری است.')
        users=db_read(lambda c:list(c.execute('SELECT id,username,status,created_at,is_owner FROM admin_users ORDER BY id')))
    else:
        users=[dict(me)]
    return render_template('admin_accounts.html',users=users,current_admin=me)

@app.route('/admin/account/<int:uid>',methods=['POST'])
def admin_account_edit(uid):
    g=admin_guard()
    if g:return g
    me=current_admin()
    if not me:return redirect('/admin/login')
    if not me['is_owner'] and uid!=me['id']:
        flash('دسترسی به حساب‌های دیگر مجاز نیست.'); return redirect('/admin')
    username=request.form.get('username','').strip(); pw=request.form.get('password','')
    def w(c):
        row=c.execute('SELECT status FROM admin_users WHERE id=?',(uid,)).fetchone()
        current_status=1 if row and row['status'] else 0
        new_status = 1 if request.form.get('status') else 0 if 'status' in request.form else current_status
        if pw:
            c.execute('UPDATE admin_users SET username=?,password_hash=?,status=? WHERE id=?',(username,generate_password_hash(pw),new_status,uid))
        else:
            c.execute('UPDATE admin_users SET username=?,status=? WHERE id=?',(username,new_status,uid))
    try:
        db_write(w)
        flash('اطلاعات حساب با موفقیت ذخیره شد.')
    except sqlite3.IntegrityError:
        flash('نام کاربری تکراری است.')
    return redirect('/admin/accounts')

@app.route('/admin/account/<int:uid>/delete',methods=['POST'])
def admin_account_delete(uid):
    g=admin_guard()
    if g:return g
    own=owner_required()
    if own:return own
    row=db_read(lambda c:c.execute('SELECT is_owner FROM admin_users WHERE id=?',(uid,)).fetchone())
    if row and row['is_owner']:
        flash('حساب اصلی قابل حذف نیست.')
    else:
        db_write(lambda c:c.execute('DELETE FROM admin_users WHERE id=? AND COALESCE(is_owner,0)=0',(uid,)))
    return redirect('/admin/accounts')

# Shared card engine
def get_cards(card_type=None, **flags):
    def r(c):
        q='SELECT * FROM content_cards WHERE enabled=1'; params=[]
        if card_type: q+=' AND card_type=?'; params.append(card_type)
        for key,val in flags.items():
            if val: q+=f' AND {key}=1'
        q+=' ORDER BY sort_order,id'; return list(c.execute(q,params))
    return db_read(r)

@app.route('/admin/solution-cards')
def admin_solution_cards():
    g=admin_guard()
    if g:return g
    cards=db_read(lambda c:list(c.execute("SELECT * FROM content_cards WHERE card_type='solution' ORDER BY sort_order,id")))
    return render_template('admin_card_collection.html',cards=cards,collection='solution',title='کارت راهکارها',description='پیش‌نمایش کامل کارت‌های راهکارها و ویرایش هر کارت در همان محل.')

@app.route('/admin/capability-cards')
def admin_capability_cards():
    g=admin_guard()
    if g:return g
    cards=db_read(lambda c:list(c.execute("SELECT * FROM content_cards WHERE card_type IN ('main_capability','supp_capability') ORDER BY card_type,sort_order,id")))
    return render_template('admin_card_collection.html',cards=cards,collection='capability',title='کارت قابلیت‌ها',description='پیش‌نمایش کامل کارت‌های قابلیت‌ها و ویرایش هر کارت در همان محل.')

@app.route('/admin/scenario-cards')
def admin_scenario_cards():
    g=admin_guard()
    if g:return g
    cards=db_read(lambda c:list(c.execute("SELECT * FROM content_cards WHERE card_type='scenario_artect' ORDER BY sort_order,id")))
    return render_template('admin_card_collection.html',cards=cards,collection='scenario',title='کارت سناریوهای Artect',description='افزودن، حذف، ویرایش و مرتب‌سازی کارت‌های سناریوهای صفحه Artect.')

def save_card_video(file):
    if not file or not file.filename: return ''
    ext=file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_VIDEOS: return None
    stem=secure_filename(file.filename.rsplit('.',1)[0]) or 'card-video'
    name=f'{stem}-{uuid.uuid4().hex[:8]}.{ext}'
    file.save(os.path.join(VIDEO_DIR,name))
    return '/videos/'+name

@app.route('/admin/card-create',methods=['POST'])
def admin_card_create():
    g=admin_guard()
    if g:return g
    uploaded=save_card_video(request.files.get('video_file')) if request.files.get('video_file') else ''
    if uploaded is None:
        flash('فرمت ویدئو مجاز نیست.'); return redirect(request.referrer or '/admin')
    video=uploaded or request.form.get('video','')
    db_write(lambda c:c.execute('INSERT INTO content_cards(slug,card_type,title,subtitle,short_desc,full_desc,image,icon,link,tag,video,enabled,show_home,show_artect,show_mrar,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(request.form.get('slug','').strip() or uuid.uuid4().hex,request.form.get('card_type','generic'),request.form.get('title',''),request.form.get('subtitle',''),request.form.get('short_desc',''),request.form.get('full_desc',''),request.form.get('image',''),request.form.get('icon',''),request.form.get('link',''),request.form.get('tag',''),video,1 if request.form.get('enabled') else 0,1 if request.form.get('show_home') else 0,1 if request.form.get('show_artect') else 0,1 if request.form.get('show_mrar') else 0,999)))
    return redirect(request.referrer or '/admin')

@app.route('/admin/card/<int:cid>/video', methods=['POST'])
def admin_card_video(cid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute("SELECT card_type FROM content_cards WHERE id=?",(cid,)).fetchone())
    if not row or row['card_type'] != 'solution':
        flash('آپلود ویدئو فقط برای کارت‌های راهکار امکان‌پذیر است.')
        return redirect(request.referrer or '/admin/solution-cards')
    file=request.files.get('video_file')
    if not file or not file.filename:
        flash('فایلی برای آپلود انتخاب نشده است.')
        return redirect(request.referrer or '/admin/solution-cards')
    uploaded=save_card_video(file)
    if uploaded is None:
        flash('فرمت ویدئو مجاز نیست. فرمت‌های مجاز: MP4، WebM، MOV و M4V.')
        return redirect(request.referrer or '/admin/solution-cards')
    db_write(lambda c:c.execute('UPDATE content_cards SET video=? WHERE id=?',(uploaded,cid)))
    flash('ویدئوی جزئیات کارت با موفقیت آپلود شد.')
    return redirect(request.referrer or '/admin/solution-cards')

@app.route('/admin/card/<int:cid>',methods=['POST'])
def admin_card_edit(cid):
    g=admin_guard()
    if g:return g
    # Full card editing endpoint. Keep the visibility-only form separate so a
    # checkbox change never rewrites unrelated card fields (or the unique slug).
    row=db_read(lambda c:c.execute('SELECT card_type FROM content_cards WHERE id=?',(cid,)).fetchone())
    if not row:
        flash('کارت موردنظر پیدا نشد.')
        return redirect(request.referrer or '/admin')
    uploaded=save_card_video(request.files.get('video_file')) if request.files.get('video_file') else ''
    if uploaded is None:
        flash('فرمت ویدئو مجاز نیست.')
        return redirect(request.referrer or '/admin')
    video=uploaded or request.form.get('video','')
    db_write(lambda c:c.execute('UPDATE content_cards SET slug=?,card_type=?,title=?,subtitle=?,short_desc=?,full_desc=?,image=?,icon=?,link=?,tag=?,video=?,enabled=?,show_home=?,show_artect=?,show_mrar=? WHERE id=?',(request.form.get('slug','').strip() or uuid.uuid4().hex,request.form.get('card_type',row['card_type']),request.form.get('title',''),request.form.get('subtitle',''),request.form.get('short_desc',''),request.form.get('full_desc',''),request.form.get('image',''),request.form.get('icon',''),request.form.get('link',''),request.form.get('tag',''),video,1 if request.form.get('enabled') else 0,1 if request.form.get('show_home') else 0,1 if request.form.get('show_artect') else 0,1 if request.form.get('show_mrar') else 0,cid)))
    target='/admin/solution-cards' if row['card_type']=='solution' else '/admin/capability-cards' if row['card_type'] in ('main_capability','supp_capability') else '/admin/scenario-cards' if row['card_type']=='scenario_artect' else (request.referrer or '/admin')
    return redirect(target)

@app.route('/admin/card/<int:cid>/visibility',methods=['POST'])
def admin_card_visibility(cid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute('SELECT card_type FROM content_cards WHERE id=?',(cid,)).fetchone())
    if not row:
        flash('کارت موردنظر پیدا نشد.')
        return redirect(request.referrer or '/admin')
    # Only visibility flags are changed here. All content, order, links and
    # media remain untouched. This avoids the previous save failure caused by
    # re-submitting unrelated card fields together with the checkboxes.
    db_write(lambda c:c.execute('UPDATE content_cards SET enabled=?,show_home=?,show_artect=?,show_mrar=? WHERE id=?',(1 if request.form.get('enabled') else 0,1 if request.form.get('show_home') else 0,1 if request.form.get('show_artect') else 0,1 if request.form.get('show_mrar') else 0,cid)))
    target='/admin/solution-cards' if row['card_type']=='solution' else '/admin/capability-cards' if row['card_type'] in ('main_capability','supp_capability') else '/admin/scenario-cards' if row['card_type']=='scenario_artect' else (request.referrer or '/admin')
    flash('وضعیت نمایش کارت با موفقیت ذخیره شد.')
    return redirect(target)

@app.route('/admin/card/<int:cid>/delete',methods=['POST'])
def admin_card_delete(cid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute('SELECT card_type FROM content_cards WHERE id=?',(cid,)).fetchone())
    db_write(lambda c:c.execute('DELETE FROM content_cards WHERE id=?',(cid,)))
    target='/admin/solution-cards' if row and row['card_type']=='solution' else '/admin/capability-cards' if row and row['card_type'] in ('main_capability','supp_capability') else '/admin/scenario-cards' if row and row['card_type']=='scenario_artect' else (request.referrer or '/admin')
    return redirect(target)

@app.route('/admin/card-collection-reorder',methods=['POST'])
def admin_cards_reorder():
    g=admin_guard()
    if g:return g
    ids=(request.get_json(silent=True) or {}).get('ids',[])
    db_write(lambda c:[c.execute('UPDATE content_cards SET sort_order=? WHERE id=?',(i,cid)) for i,cid in enumerate(ids)])
    return jsonify({'ok':True})

@app.route('/admin/messages')
def admin_messages():
    g=admin_guard()
    if g:return g
    msgs=db_read(lambda c:list(c.execute('SELECT * FROM contact_messages ORDER BY id DESC')))
    return render_template('admin_messages.html',messages=msgs)

@app.route('/admin/message/<int:mid>/delete',methods=['POST'])
def admin_message_delete(mid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('DELETE FROM contact_messages WHERE id=?',(mid,)))
    flash('پیام حذف شد.')
    return redirect('/admin/messages')

# Admin

def is_mobile_request():
    ua=(request.headers.get('User-Agent') or '').lower()
    mobile_tokens=('android','iphone','ipad','ipod','mobile','windows phone','opera mini','blackberry')
    return any(token in ua for token in mobile_tokens)

def mobile_admin_blocked():
    return render_template('admin_mobile_blocked.html')

def login_required(): return session.get('admin_id') is not None
def admin_guard():
    if is_mobile_request():
        session.pop('admin_id', None)
        return mobile_admin_blocked()
    return None if login_required() else redirect(url_for('admin_login'))

@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        u=db_read(lambda c:c.execute('SELECT * FROM admin_users WHERE username=? AND status=1',(request.form.get('username',''),)).fetchone())
        if u and check_password_hash(u['password_hash'],request.form.get('password','')):
            if is_mobile_request():
                session.pop('admin_id', None)
                return mobile_admin_blocked()
            session.clear()
            session['admin_id']=u['id']
            session.permanent=True
            return redirect('/admin')
        flash('نام کاربری یا رمز عبور اشتباه است.')
    return render_template('admin_login.html')
@app.route('/admin/logout', methods=['POST'])
def admin_logout(): session.clear(); return redirect('/admin/login')
@app.route('/admin')
def admin_dashboard():
    g=admin_guard()
    if g:return g
    counts=db_read(lambda c:{k:c.execute(q).fetchone()['n'] for k,q in {'pages':'SELECT COUNT(*) n FROM pages','sections':'SELECT COUNT(*) n FROM page_sections','projects':"SELECT COUNT(*) n FROM content_cards WHERE card_type='work'",'cards':'SELECT COUNT(*) n FROM content_cards','messages':'SELECT COUNT(*) n FROM contact_messages','team':'SELECT COUNT(*) n FROM team_members','images':"SELECT COUNT(*) n FROM media WHERE kind='image'",'icons':"SELECT COUNT(*) n FROM media WHERE kind='icon'",'models':"SELECT COUNT(*) n FROM media WHERE kind='model'"}.items()})
    pages=db_read(lambda c:list(c.execute('SELECT * FROM pages ORDER BY id')))
    return render_template('admin_dashboard.html',counts=counts,pages=pages)
@app.route('/admin/pages')
def admin_pages():
    g=admin_guard()
    if g:return g
    return render_template('admin_pages.html',pages=db_read(lambda c:list(c.execute('SELECT * FROM pages ORDER BY id'))))
@app.route('/admin/page/<int:pid>',methods=['GET','POST'])
def admin_page(pid):
    g=admin_guard()
    if g:return g
    if request.method=='POST':
        db_write(lambda c:c.execute('UPDATE pages SET title=?,slug=?,seo_description=?,enabled=? WHERE id=?',(request.form.get('title',''),request.form.get('slug',''),request.form.get('seo_description',''),1 if request.form.get('enabled') else 0,pid)))
        flash('اطلاعات صفحه ذخیره شد.'); return redirect(url_for('admin_page',pid=pid))
    def r(c):
        p=c.execute('SELECT * FROM pages WHERE id=?',(pid,)).fetchone(); s=list(c.execute('SELECT * FROM page_sections WHERE page_id=? ORDER BY sort_order,id',(pid,))); return p,s
    p,s=db_read(r); return render_template('admin_page.html',page_data=p,sections=s)
@app.route('/admin/section/<int:sid>',methods=['POST'])
def admin_section(sid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('UPDATE page_sections SET section_key=?,title=?,body=?,image=?,icon=?,button_text=?,button_url=?,enabled=?,sort_order=? WHERE id=?',(request.form.get('section_key','section'),request.form.get('title',''),request.form.get('body',''),request.form.get('image',''),request.form.get('icon',''),request.form.get('button_text',''),request.form.get('button_url',''),1 if request.form.get('enabled') else 0,int(request.form.get('sort_order') or 0),sid)))
    return jsonify({'ok':True}) if request.headers.get('X-Requested-With')=='XMLHttpRequest' else redirect(request.referrer or '/admin/pages')
@app.route('/admin/section/<int:sid>/delete',methods=['POST'])
def admin_section_delete(sid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('DELETE FROM page_sections WHERE id=?',(sid,))); return redirect(request.referrer or '/admin/pages')
@app.route('/admin/page/<int:pid>/section/add',methods=['POST'])
def admin_section_add(pid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('INSERT INTO page_sections(page_id,section_key,title,body,enabled,sort_order) VALUES(?,?,?,?,1,?)',(pid,request.form.get('section_key','new-section'),request.form.get('title','بخش جدید'),request.form.get('body',''),int(request.form.get('sort_order') or 999))))
    return redirect(url_for('admin_page',pid=pid))
@app.route('/admin/page/<int:pid>/reorder',methods=['POST'])
def admin_reorder(pid):
    g=admin_guard()
    if g:return g
    ids=request.get_json(silent=True).get('ids',[]) if request.is_json else request.form.getlist('section_id')
    def w(c):
        for i,sid in enumerate(ids): c.execute('UPDATE page_sections SET sort_order=? WHERE id=? AND page_id=?',(i,sid,pid))
    db_write(w); return jsonify({'ok':True}) if request.is_json else redirect(url_for('admin_page',pid=pid))


# Strict validation helpers for artect-3d-config packages.
def _sha256_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def _read_glb_document(path):
    with open(path, 'rb') as f: data=f.read()
    if len(data) < 20 or data[:4] != b'glTF':
        raise ValueError('فایل مدل، GLB معتبر نیست.')
    version, total = struct.unpack_from('<II', data, 4)
    if version != 2 or total != len(data):
        raise ValueError('نسخه یا اندازه فایل GLB معتبر نیست.')
    offset=12; doc=None
    while offset+8 <= len(data):
        length, chunk_type=struct.unpack_from('<II', data, offset); offset += 8
        if length < 0 or offset+length > len(data): raise ValueError('ساختار داخلی GLB خراب است.')
        if chunk_type == 0x4E4F534A:
            try: doc=json.loads(data[offset:offset+length].decode('utf-8').rstrip('\x00 \t\r\n'))
            except Exception: raise ValueError('JSON داخلی مدل GLB معتبر نیست.')
            break
        offset += length
    if not isinstance(doc,dict): raise ValueError('بخش JSON در فایل GLB پیدا نشد.')
    return data,doc

def _validate_showcase_config(config, model_path, config_folder):
    errors=[]
    if not isinstance(config,dict) or config.get('format')!='artect-3d-config' or config.get('formatVersion')!='1.0.0':
        raise ValueError('فرمت کانفیگوریشن پشتیبانی نمی‌شود؛ artect-3d-config نسخه 1.0.0 لازم است.')
    groups=config.get('groups')
    if not isinstance(groups,list): raise ValueError('فیلد groups باید آرایه باشد.')
    data,gltf=_read_glb_document(model_path)
    digest=hashlib.sha256(data).hexdigest()
    model=config.get('model') or {}
    integrity=model.get('integrity') or {}
    expected=integrity.get('modelHash')
    if expected:
        if str(integrity.get('algorithm','sha256')).lower()!='sha256': errors.append('الگوریتم هش مدل پشتیبانی نمی‌شود؛ فقط SHA-256 مجاز است.')
        elif str(expected).lower()!=digest: errors.append('هش SHA-256 فایل GLB با هش ثبت‌شده در کانفیگوریشن یکسان نیست.')
    nodes=gltf.get('nodes') or []; meshes=gltf.get('meshes') or []; scenes=gltf.get('scenes') or []
    scene_index=gltf.get('scene',0)
    scene=scenes[scene_index] if isinstance(scene_index,int) and 0<=scene_index<len(scenes) else (scenes[0] if scenes else {})
    # Three.js GLTFLoader exposes the glTF scene as a named root Group. The
    # configurator includes that root in nodePath, so mirror it when building
    # paths from the raw GLB JSON instead of starting at the first glTF node.
    scene_root_name=str(scene.get('name') or 'Scene')
    paths={}
    mesh_name_paths={}
    def canonical_name(value):
        # Tolerate naming differences introduced by Three.js/importers (spaces,
        # underscores, dots and separators) only as a unique fallback.
        return ''.join(ch.casefold() for ch in str(value or '') if ch.isalnum())
    def walk(idx,parent,stack):
        if not isinstance(idx,int) or idx<0 or idx>=len(nodes) or idx in stack: return
        node=nodes[idx]; name=str(node.get('name') or ('Node_'+str(idx))); path=parent+'/'+name
        paths.setdefault(path,[]).append((node,idx))
        if isinstance(node.get('mesh'),int):
            mesh_name_paths.setdefault(canonical_name(name),[]).append((node,idx,path))
        for child in node.get('children') or []: walk(child,path,stack|{idx})
    for idx in (scene.get('nodes') or []): walk(idx,'/'+scene_root_name,set())
    if model.get('meshCount') is not None:
        actual=len(meshes)
        if model.get('meshCount') != actual: errors.append(f'تعداد مش‌ها با مدل تطبیق ندارد (ثبت‌شده: {model.get("meshCount")}، واقعی: {actual}).')
    asset_paths=[]
    for asset in config.get('assets') or []:
        if isinstance(asset,dict) and asset.get('file'): asset_paths.append(str(asset['file']))
    occupied={}
    for gi,group in enumerate(groups):
        if not isinstance(group,dict): errors.append(f'گروه شماره {gi+1} ساختار معتبری ندارد.'); continue
        gid=str(group.get('id') or f'group-{gi+1}')
        options=group.get('options')
        if not isinstance(options,list) or not options: errors.append(f'گروه «{group.get("name",gid)}» گزینه‌ای ندارد.'); options=[]
        option_ids=[o.get('id') for o in options if isinstance(o,dict)]
        if len(option_ids)!=len(set(option_ids)): errors.append(f'شناسه گزینه‌ها در گروه «{group.get("name",gid)}» تکراری است.')
        default=group.get('defaultOptionId')
        if default is not None and default not in option_ids: errors.append(f'گزینه پیش‌فرض گروه «{group.get("name",gid)}» معتبر نیست.')
        if group.get('required',False) and (default is None or default not in option_ids): errors.append(f'گروه اجباری «{group.get("name",gid)}» باید گزینه پیش‌فرض معتبر داشته باشد.')
        targets=group.get('targets')
        if not isinstance(targets,list) or not targets: errors.append(f'گروه «{group.get("name",gid)}» هدفی برای اتصال به مدل ندارد.'); targets=[]
        for ti,target in enumerate(targets):
            if not isinstance(target,dict): errors.append(f'هدف {ti+1} گروه «{group.get("name",gid)}» معتبر نیست.'); continue
            path=str(target.get('nodePath') or '').rstrip('/')
            found=paths.get(path,[]) if path else []
            mesh_name=str(target.get('meshName') or '')
            # Older configurator exports can normalize node names differently
            # (e.g. "Loose_seat002" vs "Loose seat.002"). Only accept this
            # fallback when the model hash has been checked and the mesh name
            # resolves to exactly one mesh in the GLB.
            if not found and mesh_name and expected and str(expected).lower()==digest:
                candidates=mesh_name_paths.get(canonical_name(mesh_name),[])
                if len(candidates)==1:
                    node_candidate,idx_candidate,_actual_path=candidates[0]
                    found=[(node_candidate,idx_candidate)]
            if len(found)!=1:
                errors.append(f'قطعه با مسیر «{path or "(خالی)"}» در گروه «{group.get("name",gid)}» '+('پیدا نشد.' if not found else 'چند نتیجه هم‌مسیر دارد و مبهم است.'))
                continue
            node,_=found[0]
            if not mesh_name: errors.append(f'نام مش برای مسیر «{path}» ثبت نشده است.')
            if not isinstance(node.get('mesh'),int): errors.append(f'گره «{path}» مش قابل تنظیم نیست.'); continue
            actual_mesh_name=str(node.get('name') or '')
            if actual_mesh_name!=mesh_name and canonical_name(actual_mesh_name)!=canonical_name(mesh_name):
                errors.append(f'نام مش در مسیر «{path}» با «{mesh_name}» مطابقت ندارد.')
            mesh_index=node['mesh']
            if mesh_index<0 or mesh_index>=len(meshes): errors.append(f'مش مسیر «{path}» به داده معتبر متصل نیست.'); continue
            primitives=meshes[mesh_index].get('primitives') or []
            slots=target.get('materialSlots')
            if not isinstance(slots,list) or not slots: errors.append(f'اسلات‌های متریال برای قطعه «{path}» مشخص نشده‌اند.'); continue
            for slot in slots:
                if not isinstance(slot,int) or slot<0 or slot>=len(primitives):
                    errors.append(f'اسلات متریال {slot} در قطعه «{path}» وجود ندارد.'); continue
                primitive=primitives[slot]
                material_index=primitive.get('material')
                if not isinstance(material_index,int) or material_index<0 or material_index>=len(gltf.get('materials') or []):
                    errors.append(f'اسلات {slot} در قطعه «{path}» متریال قابل تنظیم معتبری ندارد.')
                key=(path,slot)
                if key in occupied and occupied[key]!=gid: errors.append(f'تعارض گروه‌ها: قطعه «{path}» و اسلات {slot} هم‌زمان در دو گروه استفاده شده‌اند.')
                occupied[key]=gid
        for option in options:
            if not isinstance(option,dict): continue
            appearance=option.get('appearance') or {}; typ=appearance.get('type')
            if typ not in ('color','texture'): errors.append(f'نوع ظاهر گزینه «{option.get("name",option.get("id","?"))}» پشتیبانی نمی‌شود.'); continue
            if typ=='color' and not re.fullmatch(r'#[0-9a-fA-F]{6}',str(appearance.get('color') or '')): errors.append(f'کد رنگ گزینه «{option.get("name",option.get("id","?"))}» معتبر نیست.')
            if typ=='texture':
                texture=appearance.get('texture') or {}; rel=str(texture.get('file') or '').replace('\\','/')
                if not rel or rel.startswith('/') or re.match(r'^[A-Za-z]:',rel) or '..' in rel.split('/'): errors.append(f'مسیر بافت گزینه «{option.get("name",option.get("id","?"))}» امن یا معتبر نیست.')
                else:
                    candidate=os.path.realpath(os.path.join(config_folder,*rel.split('/')))
                    if os.path.commonpath([os.path.realpath(config_folder),candidate])!=os.path.realpath(config_folder) or not os.path.isfile(candidate): errors.append(f'فایل بافت «{rel}» در بسته وجود ندارد.')
    if errors: raise ValueError('اعتبارسنجی کانفیگوریشن ناموفق بود:\n• '+'\n• '.join(dict.fromkeys(errors)))
    # Bind configurations that predate the integrity field to this exact uploaded model,
    # but only after all target paths, mesh names, slots, assets and conflicts pass.
    integrity=model.get('integrity')
    if not isinstance(integrity,dict): integrity={}; model['integrity']=integrity
    integrity['algorithm']='sha256'; integrity['modelHash']=digest
    return config

# Artect annotation-tour showcase card management.
def _annotation_vector(value):
    if not isinstance(value, list) or len(value) != 3 or not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in value):
        return False
    try: return all(math.isfinite(float(n)) for n in value)
    except (OverflowError, TypeError, ValueError): return False

def _parse_annotation_upload(upload):
    raw=upload.read()
    ext=upload.filename.rsplit('.',1)[-1].lower() if '.' in upload.filename else ''
    manifest=None
    if ext=='json':
        try: data=json.loads(raw.decode('utf-8-sig'))
        except Exception as e: raise ValueError('فایل JSON قابل‌خواندن نیست.') from e
    elif ext=='zip':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                infos=zf.infolist(); total=0; valid=[]
                for info in infos:
                    name=info.filename.replace('\\','/')
                    mode=(info.external_attr >> 16) & 0o170000
                    if name.startswith('/') or re.match(r'^[A-Za-z]:',name) or '..' in name.split('/') or mode==0o120000:
                        raise ValueError('مسیر داخل ZIP معتبر نیست.')
                    if info.file_size > 25*1024*1024: raise ValueError('حجم یک فایل داخل ZIP بیش از حد مجاز است.')
                    total+=info.file_size
                    if total>100*1024*1024: raise ValueError('حجم محتوای ZIP بیش از حد مجاز است.')
                    valid.append(info)
                ann_info=next((i for i in valid if i.filename.replace('\\','/').lower().split('/')[-1]=='annotations.json'),None)
                man_info=next((i for i in valid if i.filename.replace('\\','/').lower().split('/')[-1]=='manifest.json'),None)
                if ann_info is None or man_info is None:
                    raise ValueError('فایل ZIP باید شامل annotations.json و manifest.json باشد.')
                data=json.loads(zf.read(ann_info).decode('utf-8-sig'))
                manifest=json.loads(zf.read(man_info).decode('utf-8-sig'))
        except ValueError:
            raise
        except Exception as e:
            raise ValueError('فایل ZIP یا JSONهای داخل آن معتبر نیستند.') from e
    else:
        raise ValueError('فقط فایل annotation با فرمت JSON یا ZIP پذیرفته می‌شود.')
    if not isinstance(data,dict) or data.get('schema')!='artect.annotation-tour' or data.get('schemaVersion')!=1 or not isinstance((data.get('tour') or {}).get('annotations'),list):
        raise ValueError('ساختار Annotation باید از نوع artect.annotation-tour نسخهٔ ۱ باشد.')
    annotations=data['tour']['annotations']
    if len(annotations)>1000: raise ValueError('تعداد Annotationها بیش از حد مجاز است.')
    for i,a in enumerate(annotations):
        if not isinstance(a,dict) or not _annotation_vector(a.get('position')) or not _annotation_vector((a.get('camera') or {}).get('position')) or not _annotation_vector((a.get('camera') or {}).get('target')):
            raise ValueError(f'مختصات Annotation شمارهٔ {i+1} معتبر نیست.')
        a['title']=str(a.get('title') or f'Annotation {i+1}')[:300]
        a['description']=str(a.get('description') or '')[:10000]
        if a.get('pivotMode') not in ('annotation','camera','model'): a['pivotMode']='annotation'
    if manifest is not None:
        if manifest.get('schema')!='artect.annotation-tour-package' or manifest.get('schemaVersion')!=1 or manifest.get('annotationFile')!='annotations.json':
            raise ValueError('manifest.json از نوع artect.annotation-tour-package نسخهٔ ۱ نیست.')
        ann_model=data.get('model') or {}; man_model=manifest.get('model') or {}
        ann_hash=str(ann_model.get('sha256') or '').lower(); man_hash=str(man_model.get('sha256') or '').lower()
        if not re.fullmatch(r'[0-9a-f]{64}',ann_hash) or ann_hash!=man_hash:
            raise ValueError('اثر انگشت SHA-256 در annotations.json و manifest.json باید معتبر و یکسان باشد.')
        if ann_model.get('fileSize') is not None and man_model.get('fileSize') is not None and int(ann_model['fileSize'])!=int(man_model['fileSize']):
            raise ValueError('اندازهٔ مدل در دو فایل ZIP یکسان نیست.')
    return data

def _check_annotation_model_match(data, model_hash, model_size):
    model=data.get('model') or {}
    digest=str(model.get('sha256') or '').lower()
    if digest and digest!=model_hash.lower():
        raise ValueError('این فایل Annotation برای فایل GLB دیگری ساخته شده است؛ فایل جفت‌شدهٔ مدل را بارگذاری کنید.')
    if model.get('fileSize') is not None:
        try:
            if int(model['fileSize'])!=int(model_size):
                raise ValueError('اندازهٔ GLB با اطلاعات فایل Annotation مطابقت ندارد.')
        except (TypeError,ValueError) as e:
            if isinstance(e,ValueError) and str(e).startswith('اندازهٔ GLB'): raise
            raise ValueError('اندازهٔ مدل داخل Annotation معتبر نیست.') from e

def _annotation_card_payload(row):
    obj=dict(row)
    try: obj['annotations_count']=len((json.loads(obj.get('annotations_json') or '{}').get('tour') or {}).get('annotations') or [])
    except Exception: obj['annotations_count']=0
    obj.pop('annotations_json',None)
    return obj

@app.route('/admin/api/artect-annotations', methods=['GET','POST'])
def admin_artect_annotations():
    g=admin_guard()
    if g:return g
    if request.method=='GET':
        rows=db_read(lambda c:list(c.execute('SELECT * FROM artect_annotation_cards ORDER BY sort_order,id')))
        return jsonify([_annotation_card_payload(r) for r in rows])
    card_id=request.form.get('id','').strip()
    title=request.form.get('title','').strip()[:300]
    existing=None
    if card_id:
        existing=db_read(lambda c:c.execute('SELECT * FROM artect_annotation_cards WHERE id=?',(card_id,)).fetchone())
        if not existing:return jsonify({'error':'کارت پیدا نشد.'}),404
    model_upload=request.files.get('model')
    annotation_upload=request.files.get('annotations')
    model_raw=None
    if model_upload and model_upload.filename:
        if model_upload.filename.rsplit('.',1)[-1].lower()!='glb': return jsonify({'error':'فقط فایل GLB مجاز است.'}),400
        model_raw=model_upload.read()
        if len(model_raw)<20 or model_raw[:4]!=b'glTF': return jsonify({'error':'فایل انتخاب‌شده یک GLB معتبر نیست.'}),400
        model_hash=hashlib.sha256(model_raw).hexdigest(); model_size=len(model_raw)
    elif existing and existing['model_file']:
        existing_path=os.path.join(MODEL_DIR,existing['model_file'])
        if not os.path.isfile(existing_path): return jsonify({'error':'فایل GLB فعلی پیدا نشد؛ یک مدل جدید بارگذاری کنید.'}),400
        model_hash=_sha256_file(existing_path); model_size=os.path.getsize(existing_path)
    else:
        return jsonify({'error':'برای کارت، یک فایل GLB انتخاب کنید.'}),400
    if annotation_upload and annotation_upload.filename:
        try: annotation_obj=_parse_annotation_upload(annotation_upload)
        except Exception as e: return jsonify({'error':str(e) or 'فایل Annotation معتبر نیست.'}),400
        annotation_json=json.dumps(annotation_obj,ensure_ascii=False,separators=(',',':'))
    elif model_raw is not None:
        # A newly uploaded/replaced model may intentionally have no annotations.
        # Do not carry over points bound to a different GLB.
        annotation_obj={'schema':'artect.annotation-tour','schemaVersion':1,'model':{'fileName':model_upload.filename,'fileSize':model_size,'sha256':model_hash},'tour':{'annotations':[]}}
        annotation_json=json.dumps(annotation_obj,ensure_ascii=False,separators=(',',':'))
    elif existing and existing['annotations_json']:
        annotation_json=existing['annotations_json']
        try: annotation_obj=json.loads(annotation_json)
        except Exception: return jsonify({'error':'فایل Annotation ذخیره‌شده معتبر نیست؛ فایل جدید انتخاب کنید.'}),400
    else:
        annotation_obj={'schema':'artect.annotation-tour','schemaVersion':1,'model':{'fileSize':model_size,'sha256':model_hash},'tour':{'annotations':[]}}
        annotation_json=json.dumps(annotation_obj,ensure_ascii=False,separators=(',',':'))
    try: _check_annotation_model_match(annotation_obj,model_hash,model_size)
    except Exception as e: return jsonify({'error':str(e)}),400
    old_model=existing['model_file'] if existing else ''
    model_file=old_model
    if model_raw is not None:
        model_file=f'{uuid.uuid4().hex}.glb'
        try:
            with open(os.path.join(MODEL_DIR,model_file),'wb') as f: f.write(model_raw)
            def save_card(c):
                if card_id:
                    c.execute('UPDATE artect_annotation_cards SET title=?,model_file=?,annotations_json=? WHERE id=?',(title,model_file,annotation_json,card_id))
                    return int(card_id)
                order=c.execute('SELECT COALESCE(MAX(sort_order),-1)+1 n FROM artect_annotation_cards').fetchone()['n']
                c.execute('INSERT INTO artect_annotation_cards(title,model_file,annotations_json,sort_order) VALUES(?,?,?,?)',(title,model_file,annotation_json,order))
                return c.execute('SELECT last_insert_rowid()').fetchone()[0]
            result_id=db_write(save_card)
        except Exception as e:
            try: os.remove(os.path.join(MODEL_DIR,model_file))
            except OSError: pass
            return jsonify({'error':'ذخیرهٔ کارت انجام نشد.'}),500
        if old_model and old_model!=model_file:
            try: os.remove(os.path.join(MODEL_DIR,old_model))
            except OSError: pass
    else:
        if card_id:
            db_write(lambda c:c.execute('UPDATE artect_annotation_cards SET title=?,annotations_json=? WHERE id=?',(title,annotation_json,card_id)))
            result_id=int(card_id)
        else:
            return jsonify({'error':'برای کارت جدید باید فایل GLB بارگذاری شود.'}),400
    return jsonify({'ok':True,'id':result_id})

@app.route('/admin/api/artect-annotations-order',methods=['POST'])
def admin_artect_annotations_order():
    g=admin_guard()
    if g:return g
    ids=(request.get_json(silent=True) or {}).get('ids',[])
    if not isinstance(ids,list): return jsonify({'error':'فهرست ترتیب معتبر نیست.'}),400
    def save_order(c):
        for i,cid in enumerate(ids):
            try: cid=int(cid)
            except (TypeError,ValueError): continue
            c.execute('UPDATE artect_annotation_cards SET sort_order=? WHERE id=?',(i,cid))
    db_write(save_order)
    return jsonify({'ok':True})

@app.route('/admin/api/artect-annotations/<int:cid>/delete',methods=['POST'])
def admin_artect_annotations_delete(cid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute('SELECT * FROM artect_annotation_cards WHERE id=?',(cid,)).fetchone())
    if row:
        db_write(lambda c:c.execute('DELETE FROM artect_annotation_cards WHERE id=?',(cid,)))
        if row['model_file']:
            try: os.remove(os.path.join(MODEL_DIR,row['model_file']))
            except OSError: pass
    return jsonify({'ok':True})

# Homepage 3D showcase card management
@app.route('/admin/api/showcase', methods=['GET','POST'])
def admin_showcase():
    g=admin_guard()
    if g: return g
    if request.method=='GET':
        rows=db_read(lambda c:list(c.execute('SELECT * FROM model_showcase_cards ORDER BY sort_order,id')))
        return jsonify([dict(r) for r in rows])
    card_id=request.form.get('id','').strip()
    title=request.form.get('title','').strip()
    extra_json=request.form.get('extra_json','{}').strip() or '{}'
    try:
        parsed_settings=json.loads(extra_json)
        if not isinstance(parsed_settings,dict): raise ValueError()
        extra_json=json.dumps(parsed_settings,ensure_ascii=False)
    except Exception:
        return jsonify({'error':'تنظیمات انیمیشن معتبر نیست.'}),400
    model=request.files.get('model')
    bundle=request.files.get('config')
    existing=None
    if card_id:
        existing=db_read(lambda c:c.execute('SELECT * FROM model_showcase_cards WHERE id=?',(card_id,)).fetchone())
        if not existing: return jsonify({'error':'کارت پیدا نشد.'}),404
    model_file=existing['model_file'] if existing else ''
    config_dir=existing['config_dir'] if existing else ''
    config_json=existing['config_json'] if existing else ''
    if model and model.filename:
        if model.filename.rsplit('.',1)[-1].lower()!='glb': return jsonify({'error':'فقط فایل GLB مجاز است.'}),400
        model_file=f'{uuid.uuid4().hex}.glb'
        model.save(os.path.join(MODEL_DIR,model_file))
    if bundle and bundle.filename:
        ext=bundle.filename.rsplit('.',1)[-1].lower()
        if ext not in ('json','zip'): return jsonify({'error':'فقط فایل JSON یا ZIP مجاز است.'}),400
        folder=uuid.uuid4().hex
        target=os.path.join(CONFIG_DIR,folder); os.makedirs(target,exist_ok=True)
        if ext=='json':
            try:
                raw=bundle.read()
                obj=json.loads(raw.decode('utf-8-sig'))
                if obj.get('format')!='artect-3d-config' or obj.get('formatVersion')!='1.0.0' or not isinstance(obj.get('groups'),list):
                    raise ValueError('ساختار artect-3d-config نسخه 1.0.0 معتبر نیست.')
                config_json=json.dumps(obj,ensure_ascii=False)
                with open(os.path.join(target,'config.json'),'w',encoding='utf-8') as f: f.write(config_json)
            except Exception as e:
                shutil.rmtree(target,ignore_errors=True)
                return jsonify({'error':str(e) or 'فایل JSON معتبر نیست.'}),400
        else:
            try:
                raw=bundle.read()
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    total=0
                    for info in zf.infolist():
                        name=info.filename.replace('\\','/')
                        mode=(info.external_attr >> 16) & 0o170000
                        if name.startswith('/') or re.match(r'^[A-Za-z]:',name) or '..' in name.split('/') or mode==0o120000 or info.file_size>25*1024*1024:
                            raise ValueError('مسیر یا اندازه فایل داخل ZIP مجاز نیست.')
                        total+=info.file_size
                        if total>100*1024*1024: raise ValueError('حجم محتوای ZIP بیش از حد مجاز است.')
                    zf.extractall(target)
                cfg=os.path.join(target,'config.json')
                if not os.path.isfile(cfg): raise ValueError('فایل config.json باید در ریشه ZIP باشد.')
                with open(cfg,'r',encoding='utf-8-sig') as f: obj=json.load(f)
                if obj.get('format')!='artect-3d-config' or obj.get('formatVersion')!='1.0.0' or not isinstance(obj.get('groups'),list):
                    raise ValueError('ساختار artect-3d-config نسخه 1.0.0 معتبر نیست.')
                config_json=json.dumps(obj,ensure_ascii=False)
            except Exception as e:
                shutil.rmtree(target,ignore_errors=True)
                return jsonify({'error':str(e) or 'بسته ZIP معتبر نیست.'}),400
        config_dir=folder
    if not model_file: return jsonify({'error':'برای هر کارت باید مدل سه‌بعدی GLB انتخاب شود.'}),400
    if config_json:
        try:
            config_obj=json.loads(config_json)
            config_folder=os.path.join(CONFIG_DIR,config_dir) if config_dir else CONFIG_DIR
            config_obj=_validate_showcase_config(config_obj,os.path.join(MODEL_DIR,model_file),config_folder)
            config_json=json.dumps(config_obj,ensure_ascii=False)
            if config_dir:
                with open(os.path.join(config_folder,'config.json'),'w',encoding='utf-8') as f: f.write(config_json)
        except Exception as e:
            if bundle and bundle.filename and 'folder' in locals(): shutil.rmtree(os.path.join(CONFIG_DIR,folder),ignore_errors=True)
            return jsonify({'error':str(e) or 'اعتبارسنجی مدل و کانفیگوریشن ناموفق بود.'}),400
    if card_id:
        db_write(lambda c:c.execute('UPDATE model_showcase_cards SET title=?,model_file=?,config_dir=?,config_json=? WHERE id=?',(title,model_file,config_dir,config_json,card_id)))
        result_id=int(card_id)
    else:
        def add(c):
            order=c.execute('SELECT COALESCE(MAX(sort_order),-1)+1 n FROM model_showcase_cards').fetchone()['n']
            c.execute('INSERT INTO model_showcase_cards(title,model_file,config_dir,config_json,sort_order) VALUES(?,?,?,?,?)',(title,model_file,config_dir,config_json,order))
            return c.execute('SELECT last_insert_rowid()').fetchone()[0]
        result_id=db_write(add)
    return jsonify({'ok':True,'id':result_id})

@app.route('/admin/api/showcase-order',methods=['POST'])
def admin_showcase_order():
    g=admin_guard()
    if g:return g
    ids=(request.get_json(silent=True) or {}).get('ids',[])
    def save_order(c):
        for i,cid in enumerate(ids):
            c.execute('UPDATE model_showcase_cards SET sort_order=? WHERE id=?',(i,cid))
    db_write(save_order)
    return jsonify({'ok':True})

@app.route('/admin/api/showcase/<int:cid>/delete',methods=['POST'])
def admin_showcase_delete(cid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute('SELECT * FROM model_showcase_cards WHERE id=?',(cid,)).fetchone())
    if row:
        db_write(lambda c:c.execute('DELETE FROM model_showcase_cards WHERE id=?',(cid,)))
        if row['config_dir']: shutil.rmtree(os.path.join(CONFIG_DIR,row['config_dir']),ignore_errors=True)
        if row['model_file']:
            try: os.remove(os.path.join(MODEL_DIR,row['model_file']))
            except OSError: pass
    return jsonify({'ok':True})

@app.route('/model-config-assets/<path:filename>')
def serve_model_config_asset(filename):
    # Restrict all requested assets to the configuration root.
    return send_from_directory(CONFIG_DIR,filename)

# Mr.AR animation viewer cards
@app.route('/admin/api/mr-ar-animations', methods=['GET', 'POST'])
def admin_mr_ar_animations():
    g=admin_guard()
    if g: return g
    if request.method == 'GET':
        rows=db_read(lambda c:list(c.execute('SELECT * FROM mr_ar_animation_cards ORDER BY sort_order,id')))
        return jsonify([dict(r) for r in rows])
    card_id=request.form.get('id','').strip()
    title=request.form.get('title','').strip()
    extra_json=request.form.get('extra_json','{}').strip() or '{}'
    try:
        parsed_settings=json.loads(extra_json)
        if not isinstance(parsed_settings,dict): raise ValueError()
        extra_json=json.dumps(parsed_settings,ensure_ascii=False)
    except Exception:
        return jsonify({'error':'تنظیمات انیمیشن معتبر نیست.'}),400
    model=request.files.get('model')
    existing=None
    if card_id:
        existing=db_read(lambda c:c.execute('SELECT * FROM mr_ar_animation_cards WHERE id=?',(card_id,)).fetchone())
        if not existing: return jsonify({'error':'کارت پیدا نشد.'}),404
    model_file=existing['model_file'] if existing else ''
    replaced_old=''
    if model and model.filename:
        ext=model.filename.rsplit('.',1)[-1].lower() if '.' in model.filename else ''
        if ext not in ('glb','gltf'):
            return jsonify({'error':'فقط فایل‌های GLB یا GLTF مجاز هستند. برای جلوگیری از مشکل فایل‌های وابسته، GLB پیشنهاد می‌شود.'}),400
        model_file=f'{uuid.uuid4().hex}.{ext}'
        model.save(os.path.join(MODEL_DIR,model_file))
        if existing: replaced_old=existing['model_file']
    if not model_file:
        return jsonify({'error':'برای هر کارت باید یک فایل مدل سه‌بعدی انتخاب شود.'}),400
    if card_id:
        db_write(lambda c:c.execute('UPDATE mr_ar_animation_cards SET title=?,model_file=?,extra_json=? WHERE id=?',(title,model_file,extra_json,card_id)))
        result_id=int(card_id)
    else:
        def add(c):
            order=c.execute('SELECT COALESCE(MAX(sort_order),-1)+1 n FROM mr_ar_animation_cards').fetchone()['n']
            c.execute('INSERT INTO mr_ar_animation_cards(title,model_file,sort_order,extra_json) VALUES(?,?,?,?)',(title,model_file,order,extra_json))
            return c.execute('SELECT last_insert_rowid()').fetchone()[0]
        result_id=db_write(add)
    if replaced_old and replaced_old != model_file:
        try: os.remove(os.path.join(MODEL_DIR,replaced_old))
        except OSError: pass
    return jsonify({'ok':True,'id':result_id})

@app.route('/admin/api/mr-ar-animations-order', methods=['POST'])
def admin_mr_ar_animations_order():
    g=admin_guard()
    if g: return g
    ids=(request.get_json(silent=True) or {}).get('ids',[])
    def save_order(c):
        for i,cid in enumerate(ids):
            c.execute('UPDATE mr_ar_animation_cards SET sort_order=? WHERE id=?',(i,cid))
    db_write(save_order)
    return jsonify({'ok':True})

@app.route('/admin/api/mr-ar-animations/<int:cid>/delete', methods=['POST'])
def admin_mr_ar_animations_delete(cid):
    g=admin_guard()
    if g: return g
    row=db_read(lambda c:c.execute('SELECT * FROM mr_ar_animation_cards WHERE id=?',(cid,)).fetchone())
    if row:
        db_write(lambda c:c.execute('DELETE FROM mr_ar_animation_cards WHERE id=?',(cid,)))
        if row['model_file']:
            try: os.remove(os.path.join(MODEL_DIR,row['model_file']))
            except OSError: pass
    return jsonify({'ok':True})

# Assets
@app.route('/admin/media/images',methods=['GET'])
def admin_images():
    g=admin_guard()
    if g:return g
    media=db_read(lambda c:list(c.execute("SELECT * FROM media WHERE kind='image' ORDER BY id DESC"))); return render_template('admin_images.html',media=media)
@app.route('/admin/media/icons',methods=['GET'])
def admin_icons():
    g=admin_guard()
    if g:return g
    media=db_read(lambda c:list(c.execute("SELECT * FROM media WHERE kind='icon' ORDER BY id DESC"))); return render_template('admin_icons.html',media=media)
@app.route('/admin/media/models',methods=['GET'])
def admin_models():
    g=admin_guard()
    if g:return g
    media=db_read(lambda c:list(c.execute("SELECT * FROM media WHERE kind='model' ORDER BY id DESC"))); return render_template('admin_models.html',media=media)
@app.route('/admin/media/upload/image',methods=['POST'])
def upload_image(): return _upload_asset('image')
@app.route('/admin/media/upload/icon',methods=['POST'])
def upload_icon(): return _upload_asset('icon')
@app.route('/admin/media/upload/model',methods=['POST'])
def upload_model(): return _upload_asset('model')

def _upload_asset(kind):
    g=admin_guard()
    if g:return g
    files=request.files.getlist('file')
    files=[f for f in files if f and f.filename]
    if not files:
        flash('فایلی انتخاب نشده است.'); return redirect(request.referrer or '/admin')

    # Image/icon upload windows support true bulk selection. Allowed extensions are unchanged.
    if kind in ('image','icon'):
        added=0
        for f in files:
            ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
            if (kind=='image' and ext not in (ALLOWED_IMAGES | ALLOWED_VIDEOS)) or (kind=='icon' and ext!='svg'):
                continue
            stem=secure_filename(f.filename.rsplit('.',1)[0]) or 'asset'
            name=f'{stem}-{uuid.uuid4().hex[:8]}.{ext}'
            target_dir=IMAGE_DIR if kind=='image' else ICON_DIR
            f.save(os.path.join(target_dir,name))
            db_write(lambda c,n=name,k=kind:c.execute(
                'INSERT INTO media(filename,kind,alt_text) VALUES(?,?,?)',
                (n,k,request.form.get('alt_text',''))))
            added+=1
        if not added:
            flash('هیچ‌یک از فایل‌های انتخاب‌شده فرمت مجاز نداشتند.')
        else:
            flash(f'{added} فایل با موفقیت آپلود شد.')
        return redirect(request.referrer or ('/admin/media/images' if kind=='image' else '/admin/media/icons'))

    # A 3D model remains a model/background pair, so the existing one-to-one
    # relationship is preserved; only the file chooser is multi-select capable.
    f=files[0]
    ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext!='glb':
        flash('فرمت فایل مجاز نیست.'); return redirect(request.referrer or '/admin/media/models')
    bg=request.files.get('background')
    if not bg or not bg.filename:
        flash('برای هر مدل سه‌بعدی باید یک تصویر پس‌زمینه نیز انتخاب کنید.'); return redirect(request.referrer or '/admin/media/models')
    bg_ext=bg.filename.rsplit('.',1)[-1].lower() if '.' in bg.filename else ''
    if bg_ext not in ALLOWED_IMAGES:
        flash('فرمت تصویر پس‌زمینه مجاز نیست.'); return redirect(request.referrer or '/admin/media/models')
    try:
        bg.seek(0); img=Image.open(bg); bg_w,bg_h=img.size; img.verify(); bg.seek(0)
    except Exception:
        flash('تصویر پس‌زمینه معتبر نیست.'); return redirect(request.referrer or '/admin/media/models')
    stem=secure_filename(f.filename.rsplit('.',1)[0]) or 'asset'
    name=f'{stem}-{uuid.uuid4().hex[:8]}.{ext}'
    f.save(os.path.join(MODEL_DIR,name))
    bg_stem=secure_filename(bg.filename.rsplit('.',1)[0]) or 'model-background'
    bg_name=f'{bg_stem}-{uuid.uuid4().hex[:8]}.{bg_ext}'
    bg.save(os.path.join(IMAGE_DIR,bg_name))
    db_write(lambda c:c.execute(
        'INSERT INTO media(filename,kind,alt_text,background_filename,background_width,background_height) VALUES(?,?,?,?,?,?)',
        (name,'model',request.form.get('alt_text',''),bg_name,bg_w,bg_h)))
    flash('مدل سه‌بعدی و تصویر پس‌زمینه با موفقیت آپلود شدند.')
    return redirect(request.referrer or '/admin/media/models')

@app.route('/admin/media/model/<int:mid>/background',methods=['POST'])
def update_model_background(mid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute("SELECT * FROM media WHERE id=? AND kind='model'",(mid,)).fetchone())
    bg=request.files.get('background')
    if not row or not bg or not bg.filename:
        flash('تصویر پس‌زمینه انتخاب نشده است.'); return redirect(request.referrer or '/admin/media/models')
    ext=bg.filename.rsplit('.',1)[-1].lower() if '.' in bg.filename else ''
    if ext not in ALLOWED_IMAGES:
        flash('فرمت تصویر پس‌زمینه مجاز نیست.'); return redirect(request.referrer or '/admin/media/models')
    try:
        bg.seek(0); img=Image.open(bg); w,h=img.size; img.verify(); bg.seek(0)
    except Exception:
        flash('تصویر پس‌زمینه معتبر نیست.'); return redirect(request.referrer or '/admin/media/models')
    stem=secure_filename(bg.filename.rsplit('.',1)[0]) or 'model-background'; name=f'{stem}-{uuid.uuid4().hex[:8]}.{ext}'
    bg.save(os.path.join(IMAGE_DIR,name))
    old=row['background_filename']
    if old:
        oldpath=os.path.join(IMAGE_DIR,old)
        if os.path.isfile(oldpath): os.remove(oldpath)
    db_write(lambda c:c.execute('UPDATE media SET background_filename=?,background_width=?,background_height=? WHERE id=?',(name,w,h,mid)))
    flash('تصویر پس‌زمینه مدل با موفقیت به‌روزرسانی شد.'); return redirect(request.referrer or '/admin/media/models')

@app.route('/admin/media/<int:mid>/delete',methods=['POST'])
def delete_media(mid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute('SELECT * FROM media WHERE id=?',(mid,)).fetchone())
    if row:
        path=os.path.join(IMAGE_DIR if row['kind']=='image' else ICON_DIR if row['kind']=='icon' else MODEL_DIR,row['filename'])
        if os.path.isfile(path): os.remove(path)
        if row['kind']=='model' and row['background_filename']:
            bgpath=os.path.join(IMAGE_DIR,row['background_filename'])
            if os.path.isfile(bgpath): os.remove(bgpath)
        db_write(lambda c:c.execute('DELETE FROM media WHERE id=?',(mid,)))
    return redirect(request.referrer or '/admin')
@app.route('/admin/api/assets/<kind>')
def api_assets(kind):
    g=admin_guard()
    if g:return jsonify([])
    if kind not in ('image','icon','model','page-media'):return jsonify([]),400
    kinds=('image','model') if kind=='page-media' else (kind,)
    placeholders=','.join('?' for _ in kinds)
    rows=db_read(lambda c:list(c.execute(f'SELECT id,filename,alt_text,kind,background_filename,background_width,background_height FROM media WHERE kind IN ({placeholders}) ORDER BY id DESC',kinds)))
    def asset_item(x):
        base='/images/' if x['kind']=='image' else '/icons/' if x['kind']=='icon' else '/models/'
        return {'id':x['id'],'filename':x['filename'],'alt_text':x['alt_text'],'kind':x['kind'],'url':base+x['filename'], 'background_url':('/images/'+x['background_filename']) if x['background_filename'] else '', 'background_width':x['background_width'] or 0, 'background_height':x['background_height'] or 0}
    return jsonify([asset_item(x) for x in rows])

# Menus
@app.route('/admin/menus',methods=['GET','POST'])
def admin_menus():
    g=admin_guard()
    if g:return g
    if request.method=='POST': db_write(lambda c:c.execute('INSERT INTO menus(location,label,url,sort_order) VALUES(?,?,?,?)',(request.form.get('location','header'),request.form.get('label',''),request.form.get('url','/'),int(request.form.get('sort_order') or 0))))
    menus=db_read(lambda c:list(c.execute('SELECT * FROM menus ORDER BY location,sort_order,id'))); cols=db_read(lambda c:list(c.execute('SELECT * FROM footer_columns ORDER BY sort_order,id'))); return render_template('admin_menus.html',header_menus=[m for m in menus if m['location']=='header'],footer_menus=[m for m in menus if m['location']=='footer'],columns=cols)
@app.route('/admin/menus/reorder',methods=['POST'])
def admin_menus_reorder():
    g=admin_guard()
    if g:return g
    data=request.get_json(silent=True) or {}; location=data.get('location','header'); ids=data.get('ids',[])
    db_write(lambda c:[c.execute('UPDATE menus SET sort_order=? WHERE id=? AND location=?',(i,mid,location)) for i,mid in enumerate(ids)])
    return jsonify({'ok':True})

@app.route('/admin/menu/<int:mid>',methods=['POST'])
def admin_menu_edit(mid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('UPDATE menus SET location=?,label=?,url=?,enabled=?,sort_order=? WHERE id=?',(request.form.get('location','header'),request.form.get('label',''),request.form.get('url','/'),1 if request.form.get('enabled') else 0,int(request.form.get('sort_order') or 0),mid))); return redirect('/admin/menus')
@app.route('/admin/menu/<int:mid>/delete',methods=['POST'])
def admin_menu_delete(mid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('DELETE FROM menus WHERE id=?',(mid,))); return redirect('/admin/menus')

@app.route('/admin/footer')
def admin_footer_legacy():
    g=admin_guard()
    if g:return g
    return redirect('/admin/menus')
@app.route('/admin/footer/reorder',methods=['POST'])
def admin_footer_reorder():
    g=admin_guard()
    if g:return g
    data=request.get_json(silent=True) or {}; ids=data.get('ids',[])
    db_write(lambda c:[c.execute('UPDATE footer_columns SET sort_order=? WHERE id=?',(i,cid)) for i,cid in enumerate(ids)])
    return jsonify({'ok':True})
@app.route('/admin/footer/column/add',methods=['POST'])
def admin_footer_add():
    g=admin_guard()
    if g:return g
    mx=db_read(lambda c:c.execute('SELECT COALESCE(MAX(sort_order),-1) FROM footer_columns').fetchone()[0])
    db_write(lambda c:c.execute('INSERT INTO footer_columns(title,body,links,enabled,sort_order) VALUES(?,?,?,?,?)',('ستون جدید','','',1,mx+1)))
    return redirect('/admin/menus')
@app.route('/admin/footer/column/<int:cid>',methods=['POST'])
def admin_footer_edit(cid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('UPDATE footer_columns SET title=?,body=?,links=?,enabled=? WHERE id=?',(request.form.get('title',''),request.form.get('body',''),request.form.get('links',''),1 if request.form.get('enabled') else 0,cid)))
    return redirect('/admin/menus')
@app.route('/admin/footer/column/<int:cid>/delete',methods=['POST'])
def admin_footer_delete(cid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('DELETE FROM footer_columns WHERE id=?',(cid,)))
    return redirect('/admin/menus')

# Palette
@app.route('/admin/palettes',methods=['GET','POST'])
def admin_palettes():
    g=admin_guard()
    if g:return g
    if request.method=='POST':
        name=request.form.get('name','پالت جدید').strip() or 'پالت جدید'
        active=active_palette()
        def create(c):
            c.execute('INSERT INTO color_palettes(name,active) VALUES(?,0)',(name,)); pid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.executemany('INSERT INTO palette_colors(palette_id,role,value) VALUES(?,?,?)',[(pid,r,active.get(r,DEFAULT_COLORS[r])) for r in PALETTE_ROLES])
        db_write(create); flash('پالت ساخته شد.')
    def r(c):
        ps=list(c.execute('SELECT * FROM color_palettes ORDER BY id DESC')); mp={p['id']:{x['role']:x['value'] for x in c.execute('SELECT role,value FROM palette_colors WHERE palette_id=?',(p['id'],))} for p in ps}; return ps,mp
    ps,mp=db_read(r); return render_template('admin_palettes.html',palettes=ps,palette_map=mp,roles=PALETTE_ROLES)
@app.route('/admin/palette/<int:pid>',methods=['POST'])
def admin_palette_edit(pid):
    g=admin_guard()
    if g:return g
    vals={r:request.form.get(r,'') for r in PALETTE_ROLES}
    if any(not re.fullmatch(r'#[0-9A-Fa-f]{6}',v) for v in vals.values()): flash('یکی از رنگ‌ها HEX معتبر نیست.')
    else:
        def w(c):
            c.execute('UPDATE color_palettes SET name=? WHERE id=?',(request.form.get('name','پالت'),pid))
            c.executemany('INSERT INTO palette_colors(palette_id,role,value) VALUES(?,?,?) ON CONFLICT(palette_id,role) DO UPDATE SET value=excluded.value',[(pid,r,v) for r,v in vals.items()])
        db_write(w); flash('پالت ذخیره شد.')
    return redirect('/admin/palettes')
@app.route('/admin/palette/<int:pid>/activate',methods=['POST'])
def activate_palette(pid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:(c.execute('UPDATE color_palettes SET active=0'),c.execute('UPDATE color_palettes SET active=1 WHERE id=?',(pid,)))); flash('پالت فعال شد.'); return redirect('/admin/palettes')
@app.route('/admin/palette/<int:pid>/delete',methods=['POST'])
def delete_palette(pid):
    g=admin_guard()
    if g:return g
    row=db_read(lambda c:c.execute('SELECT active FROM color_palettes WHERE id=?',(pid,)).fetchone())
    if row and row['active']: flash('پالت فعال را نمی‌توان حذف کرد.')
    else: db_write(lambda c:(c.execute('DELETE FROM palette_colors WHERE palette_id=?',(pid,)),c.execute('DELETE FROM color_palettes WHERE id=?',(pid,))))
    return redirect('/admin/palettes')

# Settings / logo
@app.route('/admin/settings',methods=['GET','POST'])
def admin_settings():
    g=admin_guard()
    if g:return g
    if request.method=='POST':
        # The SMTP password is intentionally not accepted through the browser or stored in SQLite.
        items=[(k,v) for k,v in request.form.items() if k not in ('smtp_password', '_csrf_token')]
        db_write(lambda c:[c.execute('INSERT INTO site_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v)) for k,v in items]); flash('تنظیمات ذخیره شد.')
    settings=db_read(lambda c:{x['key']:x['value'] for x in c.execute("SELECT * FROM site_settings WHERE key!='smtp_password'")})
    return render_template('admin_settings.html',settings=settings,smtp_password_configured=bool(os.environ.get('ARTECT_SMTP_PASSWORD', '').strip()))
@app.route('/admin/logo/upload',methods=['POST'])
def logo_upload():
    g=admin_guard()
    if g:return g
    f=request.files.get('logo')
    if not f or not f.filename: flash('لوگو انتخاب نشده است.'); return redirect('/admin/settings')
    ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED_IMAGES and ext!='svg': flash('فرمت لوگو مجاز نیست.'); return redirect('/admin/settings')
    name=f'logo-{uuid.uuid4().hex[:8]}.{ext}'; target=IMAGE_DIR if ext!='svg' else ICON_DIR; f.save(os.path.join(target,name)); public=('/images/' if ext!='svg' else '/icons/')+name
    db_write(lambda c:c.execute('INSERT INTO site_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('logo',public))); flash('لوگو تغییر کرد.'); return redirect('/admin/settings')


@app.route('/admin/projects',methods=['GET','POST'])
def admin_projects():
    g=admin_guard()
    if g:return g
    if request.method=='POST':
        title=request.form.get('title','').strip(); slug=request.form.get('slug','').strip() or uuid.uuid4().hex
        try:
            db_write(lambda c:c.execute('INSERT INTO content_cards(slug,card_type,title,short_desc,full_desc,image,link,tag,enabled,show_home,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(slug,'work',title,request.form.get('short_desc',''),request.form.get('full_desc',''),request.form.get('image',''),request.form.get('ar_url',''),request.form.get('tag','Artect'),1,0,999)))
        except sqlite3.IntegrityError: flash('Slug تکراری است.')
    projects=db_read(lambda c:list(c.execute("SELECT * FROM content_cards WHERE card_type='work' ORDER BY sort_order,id")))
    return render_template('admin_projects.html',projects=projects)

@app.route('/admin/project/<int:pid>/delete',methods=['POST'])
def admin_project_delete(pid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute("DELETE FROM content_cards WHERE id=? AND card_type='work'",(pid,)))
    return redirect('/admin/projects')

@app.route('/admin/project/<int:pid>',methods=['POST'])
def admin_project_edit(pid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute("UPDATE content_cards SET slug=?,title=?,short_desc=?,full_desc=?,image=?,link=?,tag=? WHERE id=? AND card_type='work'",(request.form.get('slug',''),request.form.get('title',''),request.form.get('short_desc',''),request.form.get('full_desc',''),request.form.get('image',''),request.form.get('ar_url',''),request.form.get('tag','Artect'),pid)))
    return redirect('/admin/projects')

@app.route('/admin/projects/reorder',methods=['POST'])
def admin_projects_reorder():
    g=admin_guard()
    if g:return g
    ids=(request.get_json(silent=True) or {}).get('ids',[])
    db_write(lambda c:[c.execute("UPDATE content_cards SET sort_order=? WHERE id=? AND card_type='work'",(i,pid)) for i,pid in enumerate(ids)])
    return jsonify({'ok':True})

@app.route('/admin/projects/manage/<int:pid>',methods=['POST'])
def admin_project_manage(pid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute("UPDATE content_cards SET enabled=?, show_home=?, show_artect=?, show_mrar=? WHERE id=? AND card_type='work'",(1 if request.form.get('enabled') else 0,1 if request.form.get('show_home') else 0,1 if request.form.get('show_artect') else 0,1 if request.form.get('show_mrar') else 0,pid)))
    return redirect('/admin/projects')

@app.route('/admin/team',methods=['GET','POST'])
def admin_team():
    g=admin_guard()
    if g:return g
    if request.method=='POST':
        db_write(lambda c:c.execute('INSERT INTO team_members(name,role,bio,image,show_home,enabled,sort_order) VALUES(?,?,?,?,0,1,999)',(request.form.get('name','عضو جدید'),request.form.get('role',''),request.form.get('bio',''),request.form.get('image','placeholder-card.png'))))
        return redirect('/admin/team')
    return render_template('admin_team.html',members=db_read(lambda c:list(c.execute('SELECT * FROM team_members ORDER BY sort_order,id'))))

@app.route('/admin/team/reorder',methods=['POST'])
def admin_team_reorder():
    g=admin_guard()
    if g:return g
    ids=(request.get_json(silent=True) or {}).get('ids',[])
    db_write(lambda c:[c.execute('UPDATE team_members SET sort_order=? WHERE id=?',(i,mid)) for i,mid in enumerate(ids)])
    return jsonify({'ok':True})

@app.route('/admin/team/<int:mid>/delete',methods=['POST'])
def admin_team_delete(mid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('DELETE FROM team_members WHERE id=?',(mid,)))
    return redirect('/admin/team')

@app.route('/admin/team/manage/<int:mid>',methods=['POST'])
def admin_team_manage(mid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('UPDATE team_members SET enabled=?, show_home=? WHERE id=?',(1 if request.form.get('enabled') else 0,1 if request.form.get('show_home') else 0,mid)))
    return redirect('/admin/team')

@app.route('/admin/team/<int:mid>',methods=['POST'])
def admin_team_edit(mid):
    g=admin_guard()
    if g:return g
    db_write(lambda c:c.execute('UPDATE team_members SET name=?,role=?,bio=?,image=? WHERE id=?',(request.form.get('name',''),request.form.get('role',''),request.form.get('bio',''),request.form.get('image',''),mid)))
    return redirect('/admin/team')

@app.route('/admin/api/section/<int:sid>')
def api_section(sid):
    g=admin_guard()
    if g:return jsonify({'error':'unauthorized'}),401
    row=db_read(lambda c:c.execute('SELECT * FROM page_sections WHERE id=?',(sid,)).fetchone())
    return jsonify(dict(row)) if row else (jsonify({'error':'not found'}),404)


INLINE_CARD_FIELDS={'title','subtitle','short_desc','full_desc','image','icon','link','tag','video'}
INLINE_SECTION_FIELDS={'title','body','image','icon','button_text','button_url'}
INLINE_TEAM_FIELDS={'name','role','bio','image'}


@app.route('/api/page-inline/<slug>')
def page_inline(slug):
    rows=db_read(lambda c:list(c.execute("SELECT id,inline_json FROM page_sections ps JOIN pages p ON p.id=ps.page_id WHERE p.slug=? AND ps.enabled=1",(slug,))))
    return jsonify({str(r['id']):json.loads(r['inline_json'] or '{}') for r in rows})

@app.route('/admin/api/inline-save',methods=['POST'])
def admin_inline_save():
    g=admin_guard()
    if g:return g
    payload=request.get_json(silent=True) or {}
    changes=payload.get('changes',[])
    def w(c):
        for ch in changes:
            kind=ch.get('kind'); ident=int(ch.get('id',0)) if ch.get('id') else 0; field=ch.get('field'); value=ch.get('value','')
            if kind=='reorder':
                ids=[int(x) for x in ch.get('ids',[])]; rk=ch.get('reorder_kind')
                if rk=='team':
                    for i,xid in enumerate(ids): c.execute('UPDATE team_members SET sort_order=? WHERE id=?',(i,xid))
                else:
                    ctype=ch.get('card_type','work')
                    if ctype=='all_capabilities':
                        for i,xid in enumerate(ids): c.execute("UPDATE content_cards SET sort_order=? WHERE id=? AND card_type IN ('main_capability','supp_capability')",(i,xid))
                    elif ctype=='scenario_mrar':
                        for i,xid in enumerate(ids): c.execute("UPDATE content_cards SET sort_order=? WHERE id=? AND card_type IN ('scenario_mrar_left','scenario_mrar_right')",(i,xid))
                    elif ctype in ('scenario_mrar_left','scenario_mrar_right'):
                        for i,xid in enumerate(ids): c.execute('UPDATE content_cards SET sort_order=? WHERE id=? AND card_type=?',(i,xid,ctype))
                    else:
                        for i,xid in enumerate(ids): c.execute('UPDATE content_cards SET sort_order=? WHERE id=? AND card_type=?',(i,xid,ctype))
            elif kind=='section' and field in INLINE_SECTION_FIELDS:
                c.execute(f'UPDATE page_sections SET {field}=? WHERE id=?',(value,ident))
            elif kind=='section-inline':
                row=c.execute('SELECT inline_json FROM page_sections WHERE id=?',(ident,)).fetchone(); obj=json.loads(row['inline_json'] or '{}') if row else {}; obj[field]=value; c.execute('UPDATE page_sections SET inline_json=? WHERE id=?',(json.dumps(obj,ensure_ascii=False),ident))
            elif kind=='card' and field in INLINE_CARD_FIELDS:
                c.execute(f'UPDATE content_cards SET {field}=? WHERE id=?',(value,ident))
            elif kind=='team' and field in INLINE_TEAM_FIELDS:
                c.execute(f'UPDATE team_members SET {field}=? WHERE id=?',(value,ident))
    db_write(w)
    return jsonify({'ok':True})

@app.route('/admin/api/scenario/create',methods=['POST'])
def admin_scenario_create_inline():
    g=admin_guard()
    if g:return g
    payload=request.get_json(silent=True) or {}
    ctype=payload.get('card_type','')
    if ctype not in ('scenario_home','scenario_artect','scenario_mrar'):
        return jsonify({'error':'invalid scenario type'}),400
    actual='scenario_mrar_left' if ctype=='scenario_mrar' else ctype
    def w(c):
        mx=c.execute("SELECT COALESCE(MAX(sort_order),-1) AS n FROM content_cards WHERE card_type IN ('scenario_mrar_left','scenario_mrar_right')" if ctype=='scenario_mrar' else "SELECT COALESCE(MAX(sort_order),-1) AS n FROM content_cards WHERE card_type=?", (() if ctype=='scenario_mrar' else (actual,))).fetchone()['n']
        c.execute('INSERT INTO content_cards(slug,card_type,title,short_desc,full_desc,image,icon,link,enabled,show_home,show_artect,show_mrar,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,actual,'...','...','','placeholder-scenario.png','placeholder-icon.svg','/solutions',1,1 if ctype=='scenario_home' else 0,1 if ctype=='scenario_artect' else 0,1 if ctype=='scenario_mrar' else 0,mx+1))
        return c.execute('SELECT last_insert_rowid()').fetchone()[0]
    cid=db_write(w)
    return jsonify({'ok':True,'id':cid})

@app.route('/admin/api/scenario/<int:cid>/delete',methods=['POST'])
def admin_scenario_delete_inline(cid):
    g=admin_guard()
    if g:return g
    payload=request.get_json(silent=True) or {}
    ctype=payload.get('card_type','')
    if ctype=='scenario_home': allowed=('scenario_home',)
    elif ctype=='scenario_artect': allowed=('scenario_artect',)
    elif ctype=='scenario_mrar': allowed=('scenario_mrar_left','scenario_mrar_right')
    else:return jsonify({'error':'invalid scenario type'}),400
    db_write(lambda c:c.execute("DELETE FROM content_cards WHERE id=? AND card_type IN (%s)" % ','.join('?'*len(allowed)), (cid,*allowed)))
    return jsonify({'ok':True})

@app.route('/admin/api/solution-links')
def admin_solution_links():
    g=admin_guard()
    if g:return g
    rows=db_read(lambda c:list(c.execute("SELECT id,title FROM content_cards WHERE card_type='solution' AND enabled=1 ORDER BY sort_order,id")))
    return jsonify([{'id':r['id'],'title':r['title'],'url':'/solutions?open='+str(r['id'])} for r in rows])

@app.route('/admin/api/section-inline/<int:sid>')
def admin_api_section_inline(sid):
    g=admin_guard()
    if g:return jsonify({'error':'unauthorized'}),401
    row=db_read(lambda c:c.execute('SELECT inline_json FROM page_sections WHERE id=?',(sid,)).fetchone())
    if not row:return jsonify({'error':'not found'}),404
    try:
        obj=json.loads(row['inline_json'] or '{}')
    except Exception:
        obj={}
    return jsonify({'inline_json':obj})


@app.route('/admin/api/card/<int:cid>')
def admin_api_card(cid):
    g=admin_guard()
    if g:return jsonify({'error':'unauthorized'}),401
    row=db_read(lambda c:c.execute('SELECT * FROM content_cards WHERE id=?',(cid,)).fetchone())
    return jsonify(dict(row)) if row else (jsonify({'error':'not found'}),404)

@app.route('/admin/api/team/<int:mid>')
def admin_api_team(mid):
    g=admin_guard()
    if g:return jsonify({'error':'unauthorized'}),401
    row=db_read(lambda c:c.execute('SELECT * FROM team_members WHERE id=?',(mid,)).fetchone())
    return jsonify(dict(row)) if row else (jsonify({'error':'not found'}),404)

@app.route('/admin/api/reorder-items',methods=['POST'])
def admin_api_reorder_items():
    g=admin_guard()
    if g:return g
    data=request.get_json(silent=True) or {}; ids=[int(x) for x in data.get('ids',[])]; kind=data.get('kind')
    def w(c):
        table='team_members' if kind=='team' else 'content_cards'
        extra='' if kind=='team' else " AND card_type=?"
        for i,ident in enumerate(ids):
            if kind=='team': c.execute('UPDATE team_members SET sort_order=? WHERE id=?',(i,ident))
            else:
                if data.get('card_type')=='all_capabilities': c.execute("UPDATE content_cards SET sort_order=? WHERE id=? AND card_type IN ('main_capability','supp_capability')",(i,ident))
                else: c.execute('UPDATE content_cards SET sort_order=? WHERE id=? AND card_type=?',(i,ident,data.get('card_type','work')))
    db_write(w); return jsonify({'ok':True})


init_db()
if __name__=='__main__':
    if IS_PRODUCTION:
        raise SystemExit('Do not use app.py as a production server. Start with a WSGI server, e.g. gunicorn wsgi:app.')
    app.run(host=os.environ.get('ARTECT_DEV_HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '5000')), debug=False)
