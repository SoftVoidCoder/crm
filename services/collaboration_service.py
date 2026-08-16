import datetime
import json
import time

from database import get_connection, next_safe_table_id


def _now_ts() -> int:
    return int(time.time())


def _now_human() -> str:
    return time.strftime("%d.%m.%Y %H:%M")


def list_meetings():
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM meetings ORDER BY id DESC")
        meetings = []
        for row in c.fetchall():
            item = dict(row)
            item["participants"] = json.loads(item.get("participants") or "[]")
            item["agenda"] = json.loads(item.get("agenda") or "[]")
            item["decisions"] = json.loads(item.get("decisions") or "{}")
            meetings.append(item)
        return meetings
    finally:
        conn.close()


def create_meeting_record(*, title: str, m_date: str, m_time: str, participants: list, agenda: list):
    conn = get_connection()
    try:
        c = conn.cursor()
        meeting_id = next_safe_table_id(conn, "meetings")
        c.execute(
            """
            INSERT INTO meetings (id, title, m_date, m_time, participants, agenda, decisions, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (meeting_id, title, m_date, m_time, json.dumps(participants), json.dumps(agenda), "{}", "planned"),
        )
        conn.commit()
        return meeting_id
    finally:
        conn.close()


def update_meeting_record(*, meeting_id: int, title: str, m_date: str, m_time: str, participants: list, agenda: list, decisions: dict, status: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            UPDATE meetings
            SET title=?, m_date=?, m_time=?, participants=?, agenda=?, decisions=?, status=?
            WHERE id=?
            """,
            (title, m_date, m_time, json.dumps(participants), json.dumps(agenda), json.dumps(decisions), status, meeting_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_chats(*, user_name: str, user_role: str):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM global_chats ORDER BY id ASC")
        chats = []
        for row in c.fetchall():
            item = dict(row)
            participants = json.loads(item.get("participants") or "[]")
            item["participants"] = participants
            if item.get("type") == "system":
                chats.append(item)
            elif item.get("type") == "role":
                if user_role == "Директор" or user_role in participants:
                    chats.append(item)
            elif item.get("type") == "custom":
                if user_name == item.get("creator") or user_name in participants or user_role == "Директор":
                    chats.append(item)
        return chats
    finally:
        conn.close()


def create_chat_record(*, name: str, creator: str, participants: list):
    conn = get_connection()
    try:
        c = conn.cursor()
        chat_id = next_safe_table_id(conn, "global_chats")
        c.execute(
            "INSERT INTO global_chats (id, name, type, creator, participants) VALUES (?, ?, ?, ?, ?)",
            (chat_id, name, "custom", creator, json.dumps(participants)),
        )
        conn.commit()
        return chat_id
    finally:
        conn.close()


def delete_chat_record(chat_id: int):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM global_chats WHERE id=?", (chat_id,))
        c.execute("DELETE FROM global_messages WHERE chat_id=?", (chat_id,))
        conn.commit()
    finally:
        conn.close()


def list_chat_messages(chat_id: int):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute('SELECT id, chat_id, "user", role, text, time FROM global_messages WHERE chat_id=? ORDER BY id ASC', (chat_id,))
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def create_chat_message(*, chat_id: int, user: str, role: str, text: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            'INSERT INTO global_messages (chat_id, "user", role, text, time) VALUES (?, ?, ?, ?, ?)',
            (chat_id, user, role, text, _now_human()),
        )
        conn.commit()
    finally:
        conn.close()


def list_tasks():
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM tasks ORDER BY id DESC")
        tasks = []
        for row in c.fetchall():
            item = dict(row)
            item["history"] = json.loads(item.get("history") or "[]")
            item["chat"] = json.loads(item.get("chat") or "[]")
            item["updated_at"] = int(item.get("updated_at") or 0)
            tasks.append(item)
        return tasks
    finally:
        conn.close()


def resolve_task_executor(executor_name: str):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT abs_start, abs_end, deputy FROM users WHERE name=?", (executor_name,))
        row = c.fetchone()
        actual_executor = executor_name
        if row and row["deputy"] and row["abs_start"] and row["abs_end"]:
            try:
                today = datetime.datetime.now()
                start = datetime.datetime.strptime(row["abs_start"], "%d.%m.%Y")
                end = datetime.datetime.strptime(row["abs_end"], "%d.%m.%Y")
                if start <= today <= end:
                    actual_executor = f"{row['deputy']} (И.О. {executor_name})"
            except Exception:
                pass
        executor_lookup_name = actual_executor.split(" (И.О.")[0].strip()
        c.execute("SELECT email FROM users WHERE name=?", (executor_lookup_name,))
        email_row = c.fetchone()
        return {
            "actual_executor": actual_executor,
            "executor_lookup_name": executor_lookup_name,
            "executor_email": email_row["email"] if email_row and email_row["email"] else "",
        }
    finally:
        conn.close()


def create_task_record(*, title: str, description: str, author: str, executor: str, deadline: str, recurrence: str, priority: str, project_id: int):
    conn = get_connection()
    try:
        c = conn.cursor()
        task_id = next_safe_table_id(conn, "tasks")
        now_human = _now_human()
        now_ts = _now_ts()
        c.execute(
            """
            INSERT INTO tasks (
                id, title, description, author, executor, deadline, status, created_at, recurrence, priority, project_id, history, chat, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, title, description, author, executor, deadline, "assigned", now_human, recurrence, priority, project_id, "[]", "[]", now_ts),
        )
        conn.commit()
        return task_id
    finally:
        conn.close()


def update_task_record(
    *,
    task_id: int,
    status: str | None = None,
    executor: str | None = None,
    history: list | None = None,
    priority: str | None = None,
    title: str | None = None,
    description: str | None = None,
    deadline: str | None = None,
    project_id: int | None = None,
    chat: list | None = None,
):
    conn = get_connection()
    try:
        c = conn.cursor()
        fields = []
        values = []
        if status is not None:
            fields.append("status=?")
            values.append(status)
        if executor is not None:
            fields.append("executor=?")
            values.append(executor)
        if history is not None:
            fields.append("history=?")
            values.append(json.dumps(history))
        if priority is not None:
            fields.append("priority=?")
            values.append(priority)
        if title is not None:
            fields.append("title=?")
            values.append(title)
        if description is not None:
            fields.append("description=?")
            values.append(description)
        if deadline is not None:
            fields.append("deadline=?")
            values.append(deadline)
        if project_id is not None:
            fields.append("project_id=?")
            values.append(project_id)
        if chat is not None:
            fields.append("chat=?")
            values.append(json.dumps(chat))
        fields.append("updated_at=?")
        values.append(_now_ts())
        values.append(task_id)
        c.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", tuple(values))
        conn.commit()
    finally:
        conn.close()


def delete_task_record(task_id: int):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE documents SET resolution_task_id=0 WHERE resolution_task_id=?", (task_id,))
        c.execute("UPDATE document_linked_tasks SET task_id=0 WHERE task_id=?", (task_id,))
        c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        deleted = c.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def add_task_message(*, task_id: int, user: str, role: str, text: str):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute("SELECT chat FROM tasks WHERE id=?", (task_id,))
        row = c.fetchone()
        if not row:
            return None
        chat = json.loads((row["chat"] if isinstance(row, dict) else row["chat"]) or "[]")
        message = {
            "user": user,
            "role": role,
            "text": text,
            "time": _now_human(),
            "created_at": _now_ts(),
        }
        chat.append(message)
        c.execute("UPDATE tasks SET chat=?, updated_at=? WHERE id=?", (json.dumps(chat), _now_ts(), task_id))
        conn.commit()
        return message
    finally:
        conn.close()


def list_company_feed(*, user_email: str, user_role: str):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT id, author_name, author_role, post_type, title, content, poll_options, target_roles, is_pinned, created_at, updated_at
            FROM company_feed_posts
            ORDER BY is_pinned DESC, updated_at DESC, id DESC
            """
        )
        posts = []
        for row in c.fetchall():
            item = dict(row)
            item["poll_options"] = json.loads(item.get("poll_options") or "[]")
            item["target_roles"] = json.loads(item.get("target_roles") or "[]")
            if item["target_roles"] and user_role != "Директор" and user_role not in item["target_roles"]:
                continue

            c.execute(
                "SELECT id, user_name, user_role, comment_text, created_at FROM company_feed_comments WHERE post_id=? ORDER BY id ASC",
                (item["id"],),
            )
            item["comments"] = [dict(comment) for comment in c.fetchall()]

            c.execute(
                "SELECT reaction_key, COUNT(*) AS total FROM company_feed_reactions WHERE post_id=? GROUP BY reaction_key",
                (item["id"],),
            )
            reactions = [dict(reaction) for reaction in c.fetchall()]
            item["reactions"] = reactions
            c.execute(
                "SELECT reaction_key FROM company_feed_reactions WHERE post_id=? AND user_email=? LIMIT 1",
                (item["id"], user_email),
            )
            my_reaction = c.fetchone()
            item["my_reaction"] = my_reaction["reaction_key"] if my_reaction else ""

            votes_by_option = {}
            c.execute(
                "SELECT option_key, COUNT(*) AS total FROM company_feed_votes WHERE post_id=? GROUP BY option_key",
                (item["id"],),
            )
            for vote in c.fetchall():
                votes_by_option[str(vote["option_key"])] = int(vote["total"] or 0)
            for option in item["poll_options"]:
                option_key = str(option.get("id") or "")
                option["votes"] = votes_by_option.get(option_key, 0)

            c.execute(
                "SELECT option_key FROM company_feed_votes WHERE post_id=? AND user_email=? LIMIT 1",
                (item["id"], user_email),
            )
            my_vote = c.fetchone()
            item["my_vote"] = my_vote["option_key"] if my_vote else ""

            c.execute(
                "SELECT 1 FROM company_feed_reads WHERE post_id=? AND user_email=? LIMIT 1",
                (item["id"], user_email),
            )
            item["is_read"] = 1 if c.fetchone() else 0
            posts.append(item)
        return posts
    finally:
        conn.close()


def create_company_feed_post(*, author_name: str, author_role: str, post_type: str, title: str, content: str, poll_options: list, target_roles: list, is_pinned: int = 0):
    conn = get_connection()
    try:
        c = conn.cursor()
        post_id = next_safe_table_id(conn, "company_feed_posts")
        now_ts = _now_ts()
        c.execute(
            """
            INSERT INTO company_feed_posts (
                id, author_name, author_role, post_type, title, content, poll_options, target_roles, is_pinned, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (post_id, author_name, author_role, post_type, title, content, json.dumps(poll_options), json.dumps(target_roles), int(is_pinned or 0), now_ts, now_ts),
        )
        conn.commit()
        return post_id
    finally:
        conn.close()


def add_company_feed_comment(*, post_id: int, user_name: str, user_role: str, comment_text: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO company_feed_comments (post_id, user_name, user_role, comment_text, created_at) VALUES (?, ?, ?, ?, ?)",
            (post_id, user_name, user_role, comment_text, _now_ts()),
        )
        c.execute("UPDATE company_feed_posts SET updated_at=? WHERE id=?", (_now_ts(), post_id))
        conn.commit()
    finally:
        conn.close()


def toggle_company_feed_reaction(*, post_id: int, user_email: str, user_name: str, reaction_key: str):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, reaction_key FROM company_feed_reactions WHERE post_id=? AND user_email=? LIMIT 1",
            (post_id, user_email),
        )
        row = c.fetchone()
        if row and row["reaction_key"] == reaction_key:
            c.execute("DELETE FROM company_feed_reactions WHERE id=?", (row["id"],))
        elif row:
            c.execute("UPDATE company_feed_reactions SET reaction_key=?, user_name=?, created_at=? WHERE id=?", (reaction_key, user_name, _now_ts(), row["id"]))
        else:
            c.execute(
                "INSERT INTO company_feed_reactions (post_id, user_email, user_name, reaction_key, created_at) VALUES (?, ?, ?, ?, ?)",
                (post_id, user_email, user_name, reaction_key, _now_ts()),
            )
        c.execute("UPDATE company_feed_posts SET updated_at=? WHERE id=?", (_now_ts(), post_id))
        conn.commit()
    finally:
        conn.close()


def vote_company_feed_poll(*, post_id: int, user_email: str, user_name: str, option_key: str):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM company_feed_votes WHERE post_id=? AND user_email=? LIMIT 1",
            (post_id, user_email),
        )
        row = c.fetchone()
        if row:
            c.execute("UPDATE company_feed_votes SET option_key=?, user_name=?, created_at=? WHERE id=?", (option_key, user_name, _now_ts(), row["id"]))
        else:
            c.execute(
                "INSERT INTO company_feed_votes (post_id, user_email, user_name, option_key, created_at) VALUES (?, ?, ?, ?, ?)",
                (post_id, user_email, user_name, option_key, _now_ts()),
            )
        c.execute("UPDATE company_feed_posts SET updated_at=? WHERE id=?", (_now_ts(), post_id))
        conn.commit()
    finally:
        conn.close()


def mark_company_feed_read(*, post_id: int, user_email: str):
    conn = get_connection(row_factory=True)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM company_feed_reads WHERE post_id=? AND user_email=? LIMIT 1",
            (post_id, user_email),
        )
        row = c.fetchone()
        if row:
            c.execute("UPDATE company_feed_reads SET read_at=? WHERE id=?", (_now_ts(), row["id"]))
        else:
            c.execute(
                "INSERT INTO company_feed_reads (post_id, user_email, read_at) VALUES (?, ?, ?)",
                (post_id, user_email, _now_ts()),
            )
        conn.commit()
    finally:
        conn.close()


def set_company_feed_pin(*, post_id: int, is_pinned: int):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE company_feed_posts SET is_pinned=?, updated_at=? WHERE id=?", (int(is_pinned or 0), _now_ts(), post_id))
        conn.commit()
    finally:
        conn.close()
