import unittest

from harness.scenario import (
    CONTEXT_ORDER,
    diff,
    expand,
    json_path_delete,
    json_path_get,
    load_contexts,
    load_scenarios,
    media_type,
    normalise_body,
    parse_body,
)


class ExpandTest(unittest.TestCase):
    def test_repeat_generator(self):
        self.assertEqual(expand({"t": {"$repeat": "ab", "times": 3}}, {}), {"t": "ababab"})

    def test_placeholders_in_nested_values(self):
        self.assertEqual(expand({"p": "/x/{id}", "l": ["{id}"]}, {"id": 7}), {"p": "/x/7", "l": ["7"]})


class NormaliseTest(unittest.TestCase):
    def test_instants_replaced_anywhere(self):
        body = {"createdAt": "2026-09-29T18:00:00.123456Z", "items": [{"timestamp": "2026-09-29T18:00:00.000+00:00"}]}
        self.assertEqual(normalise_body(body, []), {"createdAt": "<instant>", "items": [{"timestamp": "<instant>"}]})

    def test_non_instant_strings_kept(self):
        self.assertEqual(normalise_body({"title": "2026-09-29"}, []), {"title": "2026-09-29"})

    def test_ignore_paths(self):
        self.assertEqual(normalise_body({"a": 1, "service": "x"}, ["$.service"]), {"a": 1})

    def test_ignore_missing_path_is_noop(self):
        doc = {"a": {"b": 1}}
        json_path_delete(doc, "$.x.y")
        self.assertEqual(doc, {"a": {"b": 1}})


class DiffTest(unittest.TestCase):
    def test_key_order_irrelevant(self):
        self.assertEqual(diff({"a": 1, "b": 2}, {"b": 2, "a": 1}), [])

    def test_list_order_significant(self):
        self.assertTrue(diff([1, 2], [2, 1]))

    def test_bool_is_not_int(self):
        self.assertTrue(diff(True, 1))

    def test_int_vs_float_differs(self):
        self.assertTrue(diff(0.0, 0))

    def test_missing_and_unexpected_keys(self):
        self.assertEqual(
            diff({"a": 1}, {"b": 1}),
            ["$.a: missing (expected 1)", "$.b: unexpected 1"],
        )


class ParseTest(unittest.TestCase):
    def test_media_type(self):
        self.assertEqual(media_type("application/json;charset=UTF-8"), "application/json")
        self.assertIsNone(media_type(None))

    def test_parse_json_and_text(self):
        self.assertEqual(parse_body(b'{"a":1}', "application/json"), {"a": 1})
        self.assertEqual(parse_body(b"hi", "text/plain"), {"$text": "hi"})
        self.assertIsNone(parse_body(b"", None))

    def test_json_path_get(self):
        self.assertEqual(json_path_get({"a": [{"id": 3}]}, "$.a.0.id"), 3)


class ScenarioFilesTest(unittest.TestCase):
    def test_every_context_loads_with_unique_step_names(self):
        for ctx in CONTEXT_ORDER:
            sf = load_scenarios(ctx)
            keys = [(s.id, st.name) for s in sf.scenarios for st in s.steps]
            self.assertEqual(len(keys), len(set(keys)), ctx)
            self.assertTrue(keys, ctx)

    def test_contexts_map_routes_to_distinct_services_and_ports(self):
        cfg = load_contexts()
        services = [c["service"] for c in cfg["contexts"].values()]
        ports = [c["port"] for c in cfg["contexts"].values()] + [cfg["monolith"]["port"]]
        self.assertEqual(len(services), len(set(services)))
        self.assertEqual(len(ports), len(set(ports)))
        self.assertEqual(set(cfg["contexts"]), set(CONTEXT_ORDER) - {"platform"})


if __name__ == "__main__":
    unittest.main()
