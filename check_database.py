import sqlite3, os
DB=os.path.join(os.path.dirname(__file__),'database','artect.db')
c=sqlite3.connect(DB,timeout=30)
print('database:',DB)
print('journal_mode:',c.execute('PRAGMA journal_mode').fetchone()[0])
print('busy_timeout:',c.execute('PRAGMA busy_timeout').fetchone()[0])
print('tables:',', '.join(r[0] for r in c.execute("select name from sqlite_master where type='table' order by name")))
c.close()
