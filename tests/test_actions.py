import os
import unittest
import uuid

from main import TOKEN_ENV_CANDIDATES, CommandInput, command, notion_ping, selftest


def _get_token() -> str:
    for name in TOKEN_ENV_CANDIDATES:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _extract_plain_text(rich_text):
    return "".join(part.get("plain_text", "") for part in rich_text or [])


def _find_check(checks, name):
    for check in checks:
        if check.get("name") == name:
            return check
    return {}


class NotionActionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _get_token():
            raise unittest.SkipTest("Missing Notion token env var")

    def test_notion_actions_flow(self):
        ping_payload = notion_ping()
        self.assertEqual(ping_payload["status"], "ok")

        selftest_payload = selftest()
        self.assertEqual(selftest_payload["status"], "PASS")

        database_check = _find_check(selftest_payload["checks"], "database_discovery")
        page_check = _find_check(selftest_payload["checks"], "database_query")
        database_id = database_check.get("database_id")
        page_id = page_check.get("page_id")
        self.assertTrue(database_id and page_id)

        db_list = command(CommandInput(action="db.list", params={"page_size": 1}))
        self.assertEqual(db_list["status"], "ok")

        db_schema = command(
            CommandInput(action="db.schema", params={"database_id": database_id})
        )
        self.assertEqual(db_schema["status"], "ok")
        schema_properties = {
            prop["name"]: prop for prop in db_schema["result"].get("properties", [])
        }

        page_read = command(CommandInput(action="page.read", params={"page_id": page_id}))
        self.assertEqual(page_read["status"], "ok")
        page_properties = page_read["result"]["page"].get("properties", {})

        update_properties = {}
        checkbox_name = next(
            (name for name, prop in schema_properties.items() if prop.get("type") == "checkbox"),
            None,
        )
        if checkbox_name and checkbox_name in page_properties:
            current = page_properties[checkbox_name].get("checkbox", False)
            update_properties[checkbox_name] = not current
        else:
            title_name = next(
                (name for name, prop in schema_properties.items() if prop.get("type") == "title"),
                None,
            )
            rich_text_name = next(
                (name for name, prop in schema_properties.items() if prop.get("type") == "rich_text"),
                None,
            )
            suffix = f" [test-{uuid.uuid4().hex[:6]}]"
            if title_name and title_name in page_properties:
                current_text = _extract_plain_text(page_properties[title_name].get("title"))
                update_properties[title_name] = f"{current_text}{suffix}"
            elif rich_text_name and rich_text_name in page_properties:
                current_text = _extract_plain_text(page_properties[rich_text_name].get("rich_text"))
                update_properties[rich_text_name] = f"{current_text}{suffix}"
            else:
                self.fail("No checkbox, title, or rich_text property available for update")

        page_update = command(
            CommandInput(
                action="page.update",
                params={"page_id": page_id, "properties": update_properties},
            )
        )
        self.assertEqual(page_update["status"], "ok")

        block_append = command(
            CommandInput(
                action="block.append",
                params={
                    "block_id": page_id,
                    "blocks": [{"type": "paragraph", "text": "Selftest append"}],
                },
            )
        )
        self.assertEqual(block_append["status"], "ok")


if __name__ == "__main__":
    unittest.main()
