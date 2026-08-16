import unittest

from fastapi.testclient import TestClient

from database import get_connection
from main import app
from tests.test_helpers import create_test_user, delete_test_user


class TaskPermissionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.author = create_test_user(role="Менеджер", name_prefix="Task Author")
        self.executor = create_test_user(role="Сотрудник", name_prefix="Task Executor")
        self.outsider = create_test_user(role="Сотрудник", name_prefix="Task Outsider")
        self.director = create_test_user(role="Директор", name_prefix="Task Director")
        self.clients = {}
        for key, user in (("author", self.author), ("executor", self.executor), ("outsider", self.outsider), ("director", self.director)):
            client = TestClient(app)
            response = client.post("/api/login", json={"email": user["email"], "password": user["password"]})
            self.assertEqual(response.status_code, 200)
            self.clients[key] = client
        self.task_ids = []

    def tearDown(self):
        conn = get_connection()
        try:
            for task_id in self.task_ids:
                conn.execute("DELETE FROM notifications WHERE entity_type='task' AND entity_id=?", (str(task_id),))
                conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            conn.commit()
        finally:
            conn.close()
        for user in (self.author, self.executor, self.outsider, self.director):
            delete_test_user(user["email"])

    def create_task(self):
        response = self.clients["author"].post("/api/tasks", json={
            "title": "Permission task",
            "description": "Check task-specific permissions",
            "author": self.author["name"],
            "executor": self.executor["name"],
            "deadline": "20.08.2026",
            "recurrence": "none",
            "priority": "normal",
            "project_id": 0,
        })
        self.assertEqual(response.json().get("status"), "success")
        task_id = int(response.json()["id"])
        self.task_ids.append(task_id)
        return task_id

    def test_executor_can_comment_and_change_status_but_cannot_manage_or_delete(self):
        task_id = self.create_task()
        self.assertEqual(self.clients["executor"].post(f"/api/tasks/{task_id}/messages", json={"text": "Вопрос по поручению"}).json().get("status"), "success")
        self.assertEqual(self.clients["executor"].put(f"/api/tasks/{task_id}", json={"status": "completed"}).json().get("status"), "success")
        self.assertEqual(self.clients["executor"].put(f"/api/tasks/{task_id}", json={"priority": "high"}).json().get("error"), "forbidden")
        self.assertEqual(self.clients["executor"].delete(f"/api/tasks/{task_id}").json().get("error"), "forbidden")

    def test_outsider_cannot_work_with_task(self):
        task_id = self.create_task()
        self.assertEqual(self.clients["outsider"].post(f"/api/tasks/{task_id}/messages", json={"text": "Чужой комментарий"}).json().get("error"), "forbidden")
        self.assertEqual(self.clients["outsider"].put(f"/api/tasks/{task_id}", json={"status": "completed"}).json().get("error"), "forbidden")

    def test_author_and_director_can_delete_task(self):
        author_task_id = self.create_task()
        self.assertEqual(self.clients["author"].delete(f"/api/tasks/{author_task_id}").json().get("status"), "success")
        director_task_id = self.create_task()
        self.assertEqual(self.clients["director"].delete(f"/api/tasks/{director_task_id}").json().get("status"), "success")


if __name__ == "__main__":
    unittest.main()
