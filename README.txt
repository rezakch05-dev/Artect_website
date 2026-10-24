Artect / Mr.AR - نسخه نهایی مبتنی بر v2.6

این نسخه بازطراحی نشده است؛ ساختار Flask + SQLite، پنل مدیریت، ویرایشگر صفحات، Drag & Drop، مدیریت پالت، رسانه و Header/Footer حفظ شده و اصلاحات نهایی به آن اضافه شده‌اند.

اجرای محلی:
1) Python 3.10+
2) pip install -r requirements.txt
3) python app.py
4) http://127.0.0.1:5000

پنل: /admin
در دیتابیس تازه و محیط توسعه، حساب اولیه فقط برای اجرای محلی ساخته می‌شود (admin / admin1234). این مشخصات را در اینترنت استفاده نکنید.

انتشار اینترنتی:
- راهنمای DEPLOYMENT.md را کامل اجرا کنید.
- قبل از اجرا در محیط production، ARTECT_ENV=production و یک ARTECT_SECRET_KEY محرمانه و پایدار تنظیم کنید.
- رمز مدیر را با python manage_admin_password.py admin تنظیم/بازیابی کنید.
- سرور را با Gunicorn/WSGI و HTTPS اجرا کنید؛ اجرای python app.py فقط برای توسعه محلی است.
- رمز Gmail App Password فقط از متغیر محیطی ARTECT_SMTP_PASSWORD خوانده می‌شود و در پنل یا دیتابیس ذخیره نمی‌شود.

امکانات اضافه‌شده در نسخه نهایی:
- ساختار کامل صفحات Home / Artect / Mr.AR / راهکارها / قابلیت‌ها / تجربه‌ها / تیم / تماس
- موتور مشترک content_cards برای کارت‌های راهکار، قابلیت، سناریو، فرایند، تجربه و ... با Renderer جداگانه برای هر محل
- مدیریت کارت‌های مشترک از /admin/cards
- نمونه‌کارها از همان موتور مشترک کارت‌ها استفاده می‌کنند
- QR Code نمونه‌کار بر اساس لینک و به‌صورت زنده تولید می‌شود
- فرم کامل درخواست Demo و ذخیره پیام‌ها در /admin/messages
- تنظیم ایمیل مقصد و SMTP در /admin/settings؛ در صورت تکمیل SMTP، اعلان ایمیل ارسال می‌شود
- مدیریت حساب مدیران در /admin/accounts
- Placeholderهای سفید با نسبت واقعی محل استفاده و نمایش ابعاد در مرکز
- Placeholder آیکون مربعی 256×256
- منوی موبایل مطابق ساختار نهایی و Header چسبان
- Footer واکنش‌گرا با اطلاعات تماس، دسترسی سریع و برند
- صفحه راهکارها با باز شدن فقط یک کارت و امکان بازشدن خودکار از لینک سناریو

نکته: اطلاعاتی که قبلاً در SQLite وجود داشته باشند هنگام اولین اجرای نسخه نهایی به ساختار جدید منتقل می‌شوند و داده‌های جدید بدون نیاز به بازسازی کد قابل مدیریت هستند.

LOCAL WINDOWS FUNCTIONAL TESTING
--------------------------------
Run Run_Artect_Project.bat to create/use an isolated .venv, install requirements,
prepare a local-only secret, set up the local admin account on first run, and start
the development server bound only to 127.0.0.1.

First-run local-only credentials: username admin, password ArtectLocal@2026!
Change this password after first login if you want to keep using the local copy.
The launcher does not reset it on subsequent runs. If you forget it, run:
    .venv\Scripts\python.exe manage_admin_password.py admin

Gmail testing is optional. When prompted, enter only a Google App Password. It is
read without displaying characters, kept in process memory for that run, and not
saved to the project or database. Do not expose this development server to the internet
and never use the local default password in a production deployment.
