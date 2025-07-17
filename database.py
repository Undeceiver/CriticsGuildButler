import sqlite3

database_name = "database.db"

def connect():
    return sqlite3.connect(database_name,autocommit=True)

def init_database():
    db = connect()

    cur = db.cursor()

    res = cur.execute("SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name='user'")
    count = res.fetchone()[0]

    if count == 0:
        create_database(db)

    return db

# The log is a very very basic print log, since the more serious log relies on the database to begin with.
def create_database(db,log=True):        
    if log:
        print("Creating database schema...")

    cur = db.cursor()

    try:
        cur.execute("""
            CREATE TABLE user
            (
                user_id INTEGER NOT NULL PRIMARY KEY,
                tokens INTEGER DEFAULT 0 NOT NULL,
                mapper_upvotes INTEGER DEFAULT 0 NOT NULL,
                historic_mapper_upvotes INTEGER DEFAULT 0 NOT NULL,
                critic_upvotes INTEGER DEFAULT 0 NOT NULL,
                historic_critic_upvotes INTEGER DEFAULT 0 NOT NULL,
                stars INTEGER DEFAULT 0 NOT NULL,
                historic_stars INTEGER DEFAULT 0 NOT NULL,
                penalties INTEGER DEFAULT 0 NOT NULL,
                stakes INTEGER DEFAULT 0 NOT NULL,
                claimed_tokens INTEGER DEFAULT 0 NOT NULL,
                completed_mapper_requests INTEGER DEFAULT 0 NOT NULL,
                completed_critic_requests INTEGER DEFAULT 0 NOT NULL
            )
            """)

        cur.execute("""
            CREATE TABLE request
            (
                thread_id INTEGER NOT NULL PRIMARY KEY,
                author_id INTEGER NOT NULL REFERENCES user (user_id),
                list INTEGER NOT NULL,
                critic_id INTEGER REFERENCES user (user_id),
                type INTEGER NOT NULL,
                state INTEGER NOT NULL
            )
            """)

        cur.execute("""
            CREATE TABLE log
            (
                log_id INTEGER NOT NULL PRIMARY KEY,
                user_id INTEGER REFERENCES user (user_id),
                request_id INTEGER REFERENCES request (thread_id),
                timestamp INTEGER NOT NULL,
                class INTEGER NOT NULL,
                cause_id INTEGER REFERENCES log (log_id),
                summary TEXT
            )
            """)

        cur.execute("CREATE INDEX idx_author ON request (author_id)")
        cur.execute("CREATE INDEX idx_critic ON request (critic_id)")
        cur.execute("CREATE INDEX idx_user ON log (user_id)")
        cur.execute("CREATE INDEX idx_request ON log (request_id)")
        cur.execute("CREATE INDEX idx_cause ON log (cause_id)")
    except sqlite3.Error as e:
        print(f"SQLite error when creating new database: {e}")
        return

    if log:
        print("Database schema created!")

def check_user(db, user_id):
    cur = db.cursor()

    res = cur.execute("SELECT COUNT(*) FROM user WHERE user_id = ?", (user_id,))
    count = res.fetchone()[0]

    if count == 0:
        cur.execute("INSERT INTO user (user_id) VALUES (?)", (user_id,))    

def check_request(db, thread_id):
    cur = db.cursor()

    res = cur.execute("SELECT COUNT(*) FROM request WHERE thread_id = ?", (thread_id,))
    count = res.fetchone()[0]

    if count == 0:
        return False
    else:
        return True