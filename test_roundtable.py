import json
import unittest

from providers import parse_reply
from roundtable import ballot_result


class ProviderTests(unittest.TestCase):
    def test_codex_real_event_shape(self):
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "ROUND_OK"}},
            {"type": "turn.completed", "usage": {"input_tokens": 15480, "cached_input_tokens": 11392,
                                                  "output_tokens": 6, "reasoning_output_tokens": 0}}
        ]
        reply, usage = parse_reply("codex", "\n".join(map(json.dumps, events)))
        self.assertEqual((reply, usage["total"], usage["cached"]), ("ROUND_OK", 15486, 11392))

    def test_agy_actual_response(self):
        reply, usage = parse_reply("gemini", json.dumps({
            "status": "SUCCESS", "response": "ROUND_OK\n", "usage": {
                "input_tokens": 9395, "output_tokens": 29, "thinking_tokens": 25,
                "cache_read_tokens": 0, "total_tokens": 9424}}))
        self.assertEqual((reply, usage["total"], usage["thinking"]), ("ROUND_OK", 9424, 25))

    def test_agy_structured_ballot_has_priority_over_repeated_display_text(self):
        ballot = {"vote": "accept", "reason": "clear"}
        result = {"status": "SUCCESS", "response": json.dumps(ballot) * 2, "structured_output": ballot}
        text, _ = parse_reply("gemini", json.dumps({"event": "result", "result": result}))
        self.assertEqual(json.loads(text), ballot)

    def test_agy_denied_command_is_an_error_even_with_success_status(self):
        result = {"status":"SUCCESS","response":"","denied_actions":[{"action":"command","display_name":"Bash"}]}
        with self.assertRaisesRegex(ValueError,"权限被拒绝：Bash"):
            parse_reply("gemini",json.dumps(result))

    def test_missing_usage_stays_unknown(self):
        _, usage = parse_reply("gemini", '{"status":"SUCCESS","response":"ok"}')
        self.assertIsNone(usage["total"])

    def test_incomplete_or_failed_messages_are_not_answers(self):
        for agent, raw in [
            ("codex", '{"type":"item.completed","item":{"type":"agent_message","text":"partial"}}'),
            ("gemini", '{"status":"ERROR","response":"partial","error":"quota"}')]:
            with self.subTest(agent=agent), self.assertRaises(ValueError):
                parse_reply(agent, raw)


class BallotTests(unittest.TestCase):
    def test_repeated_equivalent_json_ballots_with_different_key_order(self):
        first = '{"vote":"accept","reason":"clear"}'
        again = '{"reason":"clear","vote":"accept"}'
        self.assertEqual("consensus", ballot_result({"gemini": first + "\n" + again, "codex": first}))
        self.assertNotEqual("consensus", ballot_result({"gemini": first + "\n" + again.replace("accept", "object"), "codex": first}))

    def test_only_two_explicit_acceptances_count(self):
        yes = '{"vote":"accept","reason":"条件清楚"}'
        self.assertEqual("consensus", ballot_result({"codex": yes, "gemini": yes}))
        for other in ('{"vote":"object","reason":"缺少对照"}', "同意，但...", '{}', '{"vote":"accept"}'):
            self.assertNotEqual("consensus", ballot_result({"codex": yes, "gemini": other}))
        self.assertNotEqual("consensus", ballot_result({"codex": yes}))


if __name__ == "__main__":
    unittest.main()
