#!/usr/bin/env python
import argparse
import logging
import socket
import sqlite3
from typing import Literal, Tuple

# ref: https://en.wikiversity.org/wiki/Chromium_browsing_history_database
# Time offset of chromium to unixepoch
CHROMIUM_TIME_OFFSET = 11644473600 * 1_000_000

def init_db(
    root_con: sqlite3.Connection, root_cur: sqlite3.Cursor, args: argparse.Namespace
):
    print("Initialize db")
    logging.info("Initializing db")

    # Create db
    res = root_cur.execute(
        """
        SELECT
            *
        FROM
            sqlite_master
        WHERE
            type = 'table' AND name='browsers'
        """
    )

    if res.fetchone() is None:
        print("Creating root db")
        root_cur.execute(
            """
            CREATE TABLE browsers (
                id INTEGER PRIMARY KEY,
                name LONGVARCHAR NOT NULL UNIQUE,
                hostname LONGVARCHAR,
                visits_time_max INTEGER NOT NULL,
                database_path LONGVARCHAR NOT NULL
            )
            """
        )
        root_cur.execute(
            """
            CREATE TABLE urls (
                id INTEGER,
                browser INTEGER NOT NULL,
                original_id INTEGER,
                url LONGVARCHAR,
                title LONGVARCHAR,
                PRIMARY KEY("id" AUTOINCREMENT),
                FOREIGN KEY("browser") REFERENCES "browsers"("id")
            )
            """
        )
        # `visits` table
        # - id: visits id
        # - browser:
        # - url:
        # - title: urls.title at the time when the `add` is executed
        # - visit_time: usec with chromium offset
        root_cur.execute(
            """
            CREATE TABLE visits (
                id INTEGER,
                browser INTEGER NOT NULL,
                original_id INTEGER,
                url_id INTEGER NOT NULL,
                url LONGVARCHAR NOT NULL,
                title LONGVARCHAR,
                visit_time INTEGER NOT NULL,
                from_visit INTEGER,
                transition_qualifier INTEGER DEFAULT 0,
                transition_type INTEGER,
                PRIMARY KEY("id" AUTOINCREMENT),
                FOREIGN KEY("browser") REFERENCES "browsers"("id")
                FOREIGN KEY("transition_type") REFERENCES "transition_type"("id")
            )
            """
        )
        # `transition_type`
        root_cur.execute(
            """
            CREATE TABLE transition_type (
                id INTEGER NOT NULL,
                name LONGVARCHAR,
                PRIMARY KEY("id")
            )
            """
        )
        visit_types = [
            (1, "link"),
            (2, "typed"),
            (3, "auto_bookmark"),
            (4, "auto_subframe"),
            (5, "manual_subframe"),
            (6, "generated"),
            (7, "auto_toplevel"),
            (8, "form_submit"),
            (9, "reload"),
            (10, "keyword"),
            (11, "keyword_generated"),
            (12, "redirect_permanent"),
            (13, "redirect_temporary"),
            (14, "download"),
            (0, "unknown"),
        ]
        root_cur.executemany(
            """
            INSERT INTO transition_type VALUES(?, ?)
            """,
            visit_types,
        )
        root_con.commit()

    res = root_cur.execute(
        """
        SELECT
            browsers.name
        FROM
            browsers
        WHERE
            browsers.name = (?)
        """,
        [args.name]
    )
    if res.fetchone() is not None:
        print(f"The name {args.name} is already used")
        raise ValueError("The provided name for the browser is already used")
    root_cur.execute(
        """
        INSERT INTO browsers VALUES(NULL, ?, ?, 0, ?)
        """,
        [args.name, socket.gethostname(), args.database],
    )
    root_con.commit()

    # cleanup
    root_con.close()


def open_browser_db(database_path: str) -> Tuple[sqlite3.Connection, Literal["firefox", "chromium"]]:
    dburi = f"file:{database_path}?mode=ro&nolock=1"
    logging.info(f"DB uri: {dburi}")
    con = sqlite3.connect(dburi, uri=True)
    cur = con.cursor()

    logging.debug(f"{con=}")
    logging.debug(f"{cur=}")
    try:
        res = cur.execute(
            """
            SELECT
                *
            FROM
                sqlite_master
            WHERE
                type='table' AND name='urls'
            """
        )
        res.fetchone()
    except sqlite3.OperationalError as e:
        if "unable to open database file" in str(e):
            # might be firefox
            logging.debug("Failed to open db while executing SELECT from sqlite_master")
            dburi = f"file:{database_path}?mode=ro"
            con = sqlite3.connect(dburi, uri=True)
            cur = con.cursor()
        else:
            raise e
    db_type = get_db_type(cur)
    logging.info(f"DB type: {db_type}")
    return con, db_type


def get_db_type(cur: sqlite3.Cursor) -> Literal["firefox", "chromium"]:
    res = cur.execute(
        """
        SELECT
            *
        FROM
            sqlite_master
        WHERE
            type='table' AND name='urls'
        """
    )
    db_type = "firefox" if res.fetchone() is None else "chromium"
    return db_type


def get_browser_info(root_cur: sqlite3.Cursor, name: str) -> tuple[int, int, str]:
    res = root_cur.execute(
        """
        SELECT
            id,
            visits_time_max,
            database_path
        FROM
            browsers
        WHERE
            browsers.name = (?)
        """,
        (name,),
    )
    browser_id, visits_time_max, database_path = res.fetchone()
    return (browser_id, visits_time_max, database_path)


def convert_chromium_transition_type(transition_qualifier: int) -> int:
    """
    Convert transition qualifier of chromium to transition type id defined in doc.
    """
    match transition_qualifier % 0x100:
        case x if 0 <= x <= 10:
            return x + 1
        case _:
            return 0  # unknown


def convert_firefox_transition_type(transition_type: int) -> int:
    """
    Convert `visit_type` of chromium to transition type id defined in doc.
    """
    match transition_type:
        case x if 1 <= x <= 4:
            return x
        case 8:
            return 5
        case 9:
            return 9
        case 5:
            return 12
        case 6:
            return 13
        case 7:
            return 14
        case _:
            return 0


def convert_firefox_datetime_to_choromium(time: str) -> str:
    """
    Convert time in Firefox to Chromium format.
    """
    num = int(time)
    return str(num + CHROMIUM_TIME_OFFSET)


def add_db(
    root_con: sqlite3.Connection, root_cur: sqlite3.Cursor, args: argparse.Namespace
):
    print("Add history to root db")
    browser_id, visits_time_max, database_path = get_browser_info(root_cur, args.name)
    logging.info(f"{browser_id=}, {visits_time_max=}")

    logging.info(f"Source: {database_path}")
    logging.info(f"Root:   {args.root_db}")

    con, db_type = open_browser_db(database_path)
    cur = con.cursor()

    match db_type:
        case "firefox":
            select_url_toupdate_sql = """
            SELECT
                moz_places.id,
                moz_places.url,
                moz_places.title
            FROM
                moz_historyvisits,
                moz_places
            WHERE
                moz_historyvisits.visit_date > (?)
                AND moz_historyvisits.place_id = moz_places.id
            """
            select_visit_sql = """
            SELECT
                moz_historyvisits.id,
                moz_historyvisits.place_id,
                moz_places.url,
                moz_places.title,
                moz_historyvisits.visit_date,
                moz_historyvisits.from_visit,
                moz_historyvisits.visit_type
            FROM
                moz_historyvisits,
                moz_places
            WHERE
                moz_historyvisits.visit_date > (?)
                AND moz_historyvisits.place_id = moz_places.id
            """
            convert_transition_type = convert_firefox_transition_type
            # Firefox doesn't have transition_qualifier
            convert_transition_qualifier = lambda _: None
            convert_visit_time = convert_firefox_datetime_to_choromium
        case "chromium":
            select_url_toupdate_sql = """
            SELECT
                urls.id,
                urls.url,
                urls.title
            FROM
                visits,
                urls
            WHERE
                visits.visit_time > (?)
                AND visits.url = urls.id
            """
            select_visit_sql = """
            SELECT
                visits.id,
                visits.url,
                urls.url,
                urls.title,
                visits.visit_time,
                visits.from_visit,
                visits.transition
            FROM
                visits,
                urls
            WHERE
                visits.visit_time > (?)
                AND visits.url = urls.id
            """
            convert_transition_type = convert_chromium_transition_type
            convert_transition_qualifier = lambda x: x
            convert_visit_time = lambda x: x
    res = cur.execute(select_url_toupdate_sql, [visits_time_max])
    updating_urls = (
        (
            browser_id,
            id,
            url,
            title,
        )
        for id, url, title in res
    )
    root_cur.executemany(
        """
        REPLACE INTO urls
        VALUES(NULL, ?, ?, ?, ?)
        """,
        updating_urls,
    )
    print(f"Wrote {root_cur.rowcount} urls")
    logging.info("updated urls in new visits")
    res = cur.execute(select_visit_sql, [visits_time_max])
    new_visits = (
        (
            browser_id,
            id,
            url_id,
            url,
            title,
            convert_visit_time(visit_time),
            from_visit,
            convert_transition_qualifier(transition),
            convert_transition_type(transition),
        )
        for id, url_id, url, title, visit_time, from_visit, transition in res
    )
    root_cur.executemany(
        """
        INSERT INTO visits
        VALUES(NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        new_visits,
    )
    print(f"Wrote {root_cur.rowcount} visits")
    logging.info("added new visits")

    # update visits_time_max
    res = root_cur.execute(
        """
        SELECT
            max(visits.visit_time)
        FROM
            visits
        WHERE
            visits.browser = (?)
        """,
        [browser_id],
    )
    (new_urls_time_max,) = res.fetchone()
    logging.info(f"{new_urls_time_max=}")
    root_cur.execute(
        """
        UPDATE
            browsers
        SET
            visits_time_max = (?)
        WHERE
            browsers.id = (?)
        """,
        (new_urls_time_max, browser_id),
    )
    root_con.commit()
    logging.info("Updated browser information")

    # cleanup
    root_con.close()
    con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Browser history merger")
    parser.add_argument("root_db", help="Merged database path")
    parser.add_argument(
        "-v", "--verbosity", action="count", default=0, help="Increase log verbosity"
    )
    subparsers = parser.add_subparsers()
    parser_init = subparsers.add_parser("init", help="Initialize root db")
    parser_init.add_argument("name", help="Unique name for the browser")
    parser_init.add_argument("database", help="Path to the browser's history db")
    parser_init.set_defaults(func=init_db)
    parse_add = subparsers.add_parser("add", help="Add history to root db")
    # parse_add.add_argument("db", help="Source db file")
    parse_add.add_argument(
        "name", help="Source browser name(which was added to root db before)"
    )
    parse_add.set_defaults(func=add_db)
    args = parser.parse_args()

    match args.verbosity:
        case 0:
            logging.basicConfig(level=logging.WARN)
        case 1:
            logging.basicConfig(level=logging.INFO)
        case _:
            logging.basicConfig(level=logging.DEBUG)
    logging.debug(f"{args=}")

    root_db_path = args.root_db
    root_con = sqlite3.connect(root_db_path)
    root_cur = root_con.cursor()

    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    args.func(root_con, root_cur, args)
    return 0


if __name__ == "__main__":
    main()
