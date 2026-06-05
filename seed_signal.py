import sqlite3, hashlib

conn = sqlite3.connect('data/intelligence.db')

row = conn.execute(
    'SELECT id, content_text FROM page_snapshots WHERE source_type=? ORDER BY scraped_at DESC LIMIT 1',
    ('news',)
).fetchone()

if row:
    new_text = row[1] + '\nWed, 04 Jun 2026 | TechCrunch | Razorpay raises Series F at 10B valuation'
    new_hash = hashlib.sha256(new_text.encode()).hexdigest()
    conn.execute(
        'UPDATE page_snapshots SET content_text=?, content_hash=? WHERE id=?',
        (new_text, new_hash, row[0])
    )
    conn.commit()
    print('Done - now run: from scheduler.jobs import scrape_news; scrape_news()')
else:
    print('No news snapshot found - run scrape_news() first.')
