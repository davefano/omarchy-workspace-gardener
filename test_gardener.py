import datetime as dt
import unittest
from unittest.mock import patch
import json
import gardener
from gardener import plan, relocate, recover_positions


def workspace(wid, **kw):
    return dict(id=wid, name=str(wid), windows=1, monitor="eDP-1", ispersistent=False, **kw)


class PlannerTests(unittest.TestCase):
    def state(self, scores):
        return {"day": dt.date.today().isoformat(), "seconds": scores}

    def test_ranks_usage_and_breaks_ties_by_original_number(self):
        rows = plan([workspace(i) for i in (13, 5, 12)], self.state({"12": 10800, "5": 5400, "13": 1200}))
        self.assertEqual([(r["from"], r["to"]) for r in rows], [(12, 1), (5, 2), (13, 3)])
        rows = plan([workspace(i) for i in (13, 5, 12)], self.state({}))
        self.assertEqual([r["from"] for r in rows], [5, 12, 13])

    def test_reserves_pins_named_persistent_empty_and_rule_bound(self):
        ws = [workspace(i) for i in (1, 2, 3, 4, 8, 12)]
        ws[0]["name"] = "inbox"
        ws[1]["ispersistent"] = True
        ws[2]["windows"] = 0
        rows = plan(ws, self.state({"12": 100}), pinned=[5], rules=[{"workspaceString": "4", "monitor": "HDMI-A-1"}])
        self.assertEqual([(r["from"], r["to"]) for r in rows], [(12, 6), (8, 7)])

    def test_ignores_yesterday_and_special_workspaces(self):
        rows = plan([workspace(-99), workspace(7), workspace(8)], {"day": "2000-01-01", "seconds": {"8": 999}})
        self.assertEqual([r["from"] for r in rows], [7, 8])

    def test_rejects_ambiguous_selector_rules(self):
        with self.assertRaises(ValueError):
            plan([], self.state({}), rules=[{"workspaceString": "r[1-5]", "monitor": "DP-1"}])

    def test_swap_and_cycle_have_no_collisions(self):
        for mapping in ({1: 2, 2: 1}, {1: 2, 2: 3, 3: 1}, {12: 1, 13: 2}):
            live = set(mapping) | {10001}
            positions = {i: i for i in mapping}
            def move(old, new):
                self.assertIn(old, live)
                self.assertNotIn(new, live)
                live.remove(old)
                live.add(new)
            relocate(mapping, positions, move, live)
            self.assertEqual(positions, mapping)
            self.assertEqual(live, set(mapping.values()) | {10001})

    def test_recovery_finds_mid_transaction_positions(self):
        journal = {"members": {"a": 1, "b": 2}}
        clients = [{"address": "a", "workspace": {"id": 10002}}, {"address": "b", "workspace": {"id": 1}}]
        self.assertEqual(recover_positions(journal, clients), {1: 10002, 2: 1})
        clients.append({"address": "new", "workspace": {"id": 1}})
        with self.assertRaises(RuntimeError):
            recover_positions(journal, clients)

    def test_stats_include_named_and_persistent_workspace_usage(self):
        ws = [workspace(1), workspace(2)]
        ws[0]["name"] = "Inbox"
        ws[1]["ispersistent"] = True
        status = {"ready": True, "counting": True, "state": self.state({"1": 120, "2": 60})}
        with patch.object(gardener, "ipc", return_value=json.dumps(status)), patch.object(gardener, "hypr", side_effect=lambda name: ws if name == "workspaces" else []):
            rows = gardener.report("stats")["workspaces"]
        self.assertEqual([(r["from"], r["seconds"]) for r in rows], [(1, 120), (2, 60)])

    def test_cleanup_restrictions_do_not_block_usage_reports(self):
        def query(name):
            if name == "workspaces":
                return [workspace(7)]
            return [{"workspaceString": "r[1-10]", "monitor": "DP-1"}]
        status = {"ready": True, "counting": False, "state": self.state({"7": 3600})}
        with patch.object(gardener, "ipc", return_value=json.dumps(status)), patch.object(gardener, "hypr", side_effect=query), patch.object(gardener, "pinned_ids", return_value={7}):
            self.assertEqual(gardener.report("stats")["workspaces"][0]["seconds"], 3600)
            with self.assertRaises(ValueError):
                gardener.report("preview")


if __name__ == "__main__":
    unittest.main()
