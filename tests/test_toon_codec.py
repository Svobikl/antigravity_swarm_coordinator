import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOON_SCRIPT = REPO_ROOT / ".antigravity" / "scripts" / "toon_codec.py"
MIRROR_TOON_SCRIPT = REPO_ROOT / "core_framework" / "scripts" / "toon_codec.py"


def _load_toon():
    spec = importlib.util.spec_from_file_location("toon_codec", TOON_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestToonCodec(unittest.TestCase):
    """Comprehensive unit, boundary, negative, and CLI tests for TOON & STE-100 (M1-M3, M7)."""

    def test_m1_uniform_table_and_min_rows_boundary(self):
        tc = _load_toon()

        # Boundary: N=2 (< min_rows=3) falls back to compact JSON; N=3 uses TOON
        two_rows = [
            {"id": 1, "name": "alpha_task_item", "status": "completed", "score": 95},
            {"id": 2, "name": "beta_task_item", "status": "completed", "score": 88},
        ]
        res_two = tc.encode_smart(two_rows, name="tasks", min_rows=3)
        self.assertEqual(res_two["format_used"], "json")
        self.assertEqual(json.loads(res_two["text"]), two_rows)
        self.assertEqual(res_two["saved_vs_compact_pct"], 0.0)

        three_rows = two_rows + [
            {"id": 3, "name": "gamma_task_item", "status": "in_progress", "score": 77},
        ]
        res_three = tc.encode_smart(three_rows, name="tasks", min_rows=3)
        self.assertEqual(res_three["format_used"], "toon")
        self.assertTrue(res_three["text"].startswith("tasks[3]{id,name,status,score}:"))
        self.assertLess(res_three["toon_tokens"], res_three["compact_json_tokens"])
        self.assertEqual(tc.decode_toon(res_three["text"]), three_rows)
        self.assertEqual(tc.dumps_smart(three_rows, name="tasks", min_rows=3), res_three["text"])

        # Higher min_rows boundary
        res_min4 = tc.encode_smart(three_rows, name="tasks", min_rows=4)
        self.assertEqual(res_min4["format_used"], "json")

        # Larger tabular payload achieves >=35% savings vs pretty JSON
        large_rows = [
            {
                "req_id": f"REQ-{i}",
                "file_path": f"src/module_{i}/handler.py",
                "status": "verified" if i % 2 == 0 else "pending",
                "latency_ms": 12 + i,
                "passed": i % 2 == 0,
            }
            for i in range(15)
        ]
        encoded = tc.encode_toon(large_rows, name="coverage")
        self.assertEqual(tc.decode_toon(encoded), large_rows)
        smart = tc.encode_smart(large_rows, name="coverage")
        self.assertEqual(smart["format_used"], "toon")
        self.assertGreaterEqual(smart["saved_vs_pretty_pct"], 35.0)
        self.assertLess(smart["toon_tokens"], smart["compact_json_tokens"])
        self.assertGreater(smart["saved_vs_compact_pct"], 0.0)

    def test_m1_top_level_dict_toon_object_preserves_order_and_types(self):
        tc = _load_toon()
        payload = {
            "ok": True,
            "total_findings": 4,
            "summary": "All gates checked",
            "findings": [
                {"category": "placeholder", "severity": "high", "line": 10},
                {"category": "ad_id", "severity": "medium", "line": 22},
                {"category": "ad_fields", "severity": "high", "line": 35},
                {"category": "version_pin", "severity": "low", "line": 48},
            ],
            "metadata": {"version": 2, "tags": ["spine", "v7"]},
        }
        encoded = tc.encode_toon(payload)
        self.assertTrue(encoded.startswith("# TOON-OBJECT\n"))
        self.assertIn('@table "findings"[4]{category,severity,line}:', encoded)
        self.assertIn('@field "ok": true', encoded)
        decoded = tc.decode_toon(encoded)
        self.assertEqual(decoded, payload)
        self.assertEqual(list(decoded.keys()), list(payload.keys()))

        smart = tc.encode_smart(payload)
        self.assertEqual(smart["format_used"], "toon")
        self.assertEqual(tc.decode_toon(smart["text"]), payload)

        # Dict whose table has < min_rows falls back to compact JSON in encode_smart
        small_dict = {
            "ok": True,
            "findings": [
                {"category": "placeholder", "severity": "high"},
                {"category": "ad_id", "severity": "low"},
            ],
        }
        smart_small = tc.encode_smart(small_dict, min_rows=3)
        self.assertEqual(smart_small["format_used"], "json")
        self.assertEqual(json.loads(smart_small["text"]), small_dict)

    def test_m2_fallbacks_preserve_universal_round_trip(self):
        tc = _load_toon()
        fallbacks = [
            [],
            {},
            [{"a": 1}, {"a": 1, "b": 2}, {"a": 3}, {"c": 4}],
            [1, "two", True, None],
            {"config": {"nested": {"deep": [1, 2, 3]}, "enabled": False}},
            42,
            "plain_scalar",
            None,
            False,
        ]
        for item in fallbacks:
            smart = tc.encode_smart(item)
            self.assertEqual(smart["format_used"], "json", f"Expected json fallback for {item!r}")
            self.assertEqual(json.loads(smart["text"]), item)
            toon_str = tc.encode_toon(item)
            self.assertTrue(
                toon_str.startswith("# JSON\n") or toon_str.startswith("# TOON-OBJECT\n"),
                f"Unexpected header for {item!r}: {toon_str!r}",
            )
            self.assertEqual(tc.decode_toon(toon_str), item)

    def test_m3_lossless_cell_types_escapes_and_utf8_zero_coercion(self):
        tc = _load_toon()
        tricky_rows = [
            {
                "s_int": "42",
                "n_int": 42,
                "s_neg": "-3.5",
                "n_neg": -3.5,
                "s_sci": "1e5",
                "n_sci": 1e5,
                "s_zero": "0",
                "n_zero": 0,
                "f_zero": 0.0,
                "s_null": "null",
                "v_null": None,
                "s_true": "true",
                "v_true": True,
                "s_false": "false",
                "v_false": False,
                "empty": "",
                "padded": "  spaced  ",
                "punct": 'a,b|c:d\ne\rf\t"g"\\h',
                "bracket_str": "[not_json",
                "brace_str": "{not_json",
                "nested_list": [1, "a,b", {"k": "v|w"}, True, None],
                "nested_dict": {"x": [10, 20], "quote": 'say "hi"'},
                "utf8": "Příliš žluťoučký kůň úpěl ďábelské ódy",
            },
            {
                "s_int": "007",
                "n_int": -99,
                "s_neg": "+1.25",
                "n_neg": 3.14159,
                "s_sci": "NaN",
                "n_sci": 0.00025,
                "s_zero": "-0",
                "n_zero": 1,
                "f_zero": -0.5,
                "s_null": "Null",
                "v_null": None,
                "s_true": "True",
                "v_true": False,
                "s_false": "False",
                "v_false": True,
                "empty": " ",
                "padded": "\tindented",
                "punct": "pipe|and,comma",
                "bracket_str": "a[b",
                "brace_str": "a{b",
                "nested_list": [],
                "nested_dict": {},
                "utf8": "Řehoř & Žofie — €100",
            },
            {
                "s_int": "999",
                "n_int": 0,
                "s_neg": ".5",
                "n_neg": 2.0,
                "s_sci": "inf",
                "n_sci": 12.5,
                "s_zero": "1_000",
                "n_zero": 7,
                "f_zero": 1.25,
                "s_null": "none",
                "v_null": None,
                "s_true": "yes",
                "v_true": True,
                "s_false": "no",
                "v_false": False,
                "empty": "",
                "padded": "plain_ok",
                "punct": "back\\slash\\",
                "bracket_str": "[1,2]",
                "brace_str": '{"a":1}',
                "nested_list": ["only,one"],
                "nested_dict": {"nested": [1, 2, {"deep": "x,y"}]},
                "utf8": "Česká republika",
            },
        ]
        encoded = tc.encode_toon(tricky_rows, name="edge_cases")
        decoded = tc.decode_toon(encoded)
        self.assertEqual(decoded, tricky_rows)

        # Strict type checks to prevent silent str<->int/float/bool/None coercion
        r0 = decoded[0]
        self.assertIs(type(r0["s_int"]), str)
        self.assertIs(type(r0["n_int"]), int)
        self.assertIs(type(r0["s_neg"]), str)
        self.assertIs(type(r0["n_neg"]), float)
        self.assertIs(type(r0["s_sci"]), str)
        self.assertIs(type(r0["n_sci"]), float)
        self.assertIs(type(r0["s_zero"]), str)
        self.assertIs(type(r0["n_zero"]), int)
        self.assertIs(type(r0["f_zero"]), float)
        self.assertIs(type(r0["s_null"]), str)
        self.assertIsNone(r0["v_null"])
        self.assertIs(type(r0["s_true"]), str)
        self.assertIs(r0["v_true"], True)
        self.assertIs(type(r0["s_false"]), str)
        self.assertIs(r0["v_false"], False)
        self.assertIs(type(r0["bracket_str"]), str)
        self.assertIs(type(r0["brace_str"]), str)

        # Special characters in table name and dict keys
        weird_keys = [{"a,b": 1, "k:2": "v", "x[0]": True}, {"a,b": 2, "k:2": "w", "x[0]": False}]
        self.assertEqual(tc.decode_toon(tc.encode_toon(weird_keys, name="t[1]:x")), weird_keys)

        # Corrupted TOON raises ValueError
        with self.assertRaises(ValueError):
            tc.decode_toon("")
        with self.assertRaises(ValueError):
            tc.decode_toon("items[2]{a,b}:\n  1,2\n")
        with self.assertRaises(ValueError):
            tc.decode_toon("items[1]{a,b}:\n  1\n")

    def test_m7_lint_ste100_fillers_boundaries_and_stripping(self):
        tc = _load_toon()

        # Exact 22-word boundary passes; 23-word sentence fails
        words_22 = " ".join(f"word{i}" for i in range(22)) + "."
        res_22 = tc.lint_ste100_text(f"- {words_22}", max_words_per_bullet=22)
        self.assertTrue(res_22["ok"])
        self.assertEqual(res_22["total_violations"], 0)
        self.assertEqual(res_22["max_prose_words_seen"], 22)

        words_23 = " ".join(f"word{i}" for i in range(23)) + "."
        res_23 = tc.lint_ste100_text(f"- {words_23}", max_words_per_bullet=22)
        self.assertFalse(res_23["ok"])
        self.assertEqual(res_23["total_violations"], 1)
        self.assertEqual(res_23["max_prose_words_seen"], 23)
        self.assertEqual(res_23["violations"][0]["category"], "sentence_too_long")

        # All 9 banned conversational filler phrases rejected case-insensitively
        fillers = [
            "In order to pass tests, run pytest.",
            "Please note that gates stay active.",
            "Make sure to verify outputs.",
            "It is important to check bounds.",
            "It might be worth checking logs.",
            "Keep in mind that limits apply.",
            "Be sure to clean scratch dirs.",
            "As a reminder, read the plan.",
            "You may want to inspect diffs.",
        ]
        for line in fillers:
            res = tc.lint_ste100_text(line)
            self.assertFalse(res["ok"], f"Filler should fail: {line}")
            self.assertTrue(
                any(v["category"] == "banned_filler" for v in res["violations"]),
                f"Expected banned_filler for {line}: {res}",
            )

        # Stripping: banner, headings, fenced code, inline code, CLI flags, paths, calls, ALL_CAPS, e.g./i.e./vs./decimals
        compliant = (
            "ASW TEST MODE ENABLED! (Very long banner header line that should be skipped from prose checks entirely)\n"
            "## Very Long Heading That Should Be Skipped Regardless Of How Many Words Are Inside It\n"
            "- Run `make sure to` inside .antigravity/scripts/toon_codec.py via invoke_subagent(TypeName=\"asw\", Model=\"pro\") "
            "with --format --include-packet-text under ZERO_HEURISTIC and BLOCKED_ON_HARDWARE_AUTH, e.g. 5.5 vs. 0.75, i.e. 1.2 ratio.\n"
            "```python\n"
            "# In order to test fenced code, please note that this 30 word filler comment must be ignored completely.\n"
            "x = 1\n"
            "```\n"
            "1. Keep prose concise and verifiable.\n"
        )
        res_ok = tc.lint_ste100_text(compliant, max_words_per_bullet=22)
        self.assertTrue(res_ok["ok"], f"Unexpected STE-100 violations: {res_ok}")
        self.assertEqual(res_ok["total_violations"], 0)
        self.assertLessEqual(res_ok["max_prose_words_seen"], 22)

    def test_cli_benchmark_and_lint_ste100_real_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            bench_out = tmp_dir / "bench.json"

            proc_bench = subprocess.run(
                [sys.executable, str(TOON_SCRIPT), "--benchmark", "--json", "--output", str(bench_out)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc_bench.returncode, 0, proc_bench.stderr)
            report = json.loads(bench_out.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(len(report["payloads"]), 10)
            tabular = [p for p in report["payloads"] if p["kind"] == "tabular"]
            fallbacks = [p for p in report["payloads"] if p["kind"] == "fallback"]
            self.assertEqual(len(tabular), 6)
            self.assertEqual(len(fallbacks), 4)
            for p in tabular:
                self.assertTrue(p["round_trip_ok"])
                self.assertEqual(p["format_used"], "toon")
                self.assertGreaterEqual(p["saved_vs_pretty_pct"], 35.0)
                self.assertLess(p["toon_tokens"], p["compact_json_tokens"])
            for p in fallbacks:
                self.assertTrue(p["round_trip_ok"])
                self.assertEqual(p["format_used"], "json")

            # --lint-ste100 on .txt (exit 0 and exit 1)
            good_txt = tmp_dir / "good.txt"
            good_txt.write_text("- Verify all outputs before exit.\n", encoding="utf-8")
            p_good = subprocess.run(
                [sys.executable, str(TOON_SCRIPT), "--lint-ste100", str(good_txt), "--json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(p_good.returncode, 0, p_good.stdout)
            self.assertTrue(json.loads(p_good.stdout)["ok"])

            bad_txt = tmp_dir / "bad.txt"
            bad_txt.write_text("- Please note that you must check outputs.\n", encoding="utf-8")
            p_bad = subprocess.run(
                [sys.executable, str(TOON_SCRIPT), "--lint-ste100", str(bad_txt), "--json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(p_bad.returncode, 1, p_bad.stdout)
            self.assertFalse(json.loads(p_bad.stdout)["ok"])

            # --lint-ste100 on .mjs with escaped backticks inside template literals
            good_mjs = tmp_dir / "good_hook.mjs"
            good_mjs.write_text(
                'const DEMO_DIRECTIVE = `ASW DEMO MODE ENABLED!\n'
                '- Run \\`please note that\\` via \\`--scan-public-repo\\` before push.\n'
                '- Keep every bullet short.`;\n',
                encoding="utf-8",
            )
            p_mjs_ok = subprocess.run(
                [sys.executable, str(TOON_SCRIPT), "--lint-ste100", str(good_mjs), "--json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(p_mjs_ok.returncode, 0, p_mjs_ok.stdout)
            mjs_data = json.loads(p_mjs_ok.stdout)
            self.assertTrue(mjs_data["ok"])
            self.assertEqual(mjs_data["directive_count"], 1)

            bad_mjs = tmp_dir / "bad_hook.mjs"
            bad_mjs.write_text(
                'const BAD_DIRECTIVE = `ASW BAD MODE ENABLED!\n'
                '- In order to verify, run tests.`;\n',
                encoding="utf-8",
            )
            p_mjs_bad = subprocess.run(
                [sys.executable, str(TOON_SCRIPT), "--lint-ste100", str(bad_mjs), "--json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(p_mjs_bad.returncode, 1, p_mjs_bad.stdout)
            self.assertFalse(json.loads(p_mjs_bad.stdout)["ok"])

    def test_m3_unicode_line_breaks_round_trip(self):
        tc = _load_toon()
        special_chars = ["\u2028", "\u2029", "\x85", "\v", "\f", "\x1c", "\x1d", "\x1e"]
        table_rows = [
            {
                "id": idx,
                "char_val": f"before{ch}after",
                "k\u2028\u2029\x85": f"key{idx}{ch}",
                "nested": {"inner": f"x{ch}y"},
            }
            for idx, ch in enumerate(special_chars)
        ]
        encoded_table = tc.encode_toon(table_rows, name="unicode_breaks")
        self.assertEqual(tc.decode_toon(encoded_table), table_rows)

        obj_payload = {
            "field_u2028": "line\u2028sep",
            "field_u2029": "para\u2029sep",
            "field_x85": "nel\x85sep",
            "field_ctrl": "a\vb\fc\x1cd\x1de\x1ef",
            "key\u2028with\x85breaks": {"v": "ok\u2029here"},
            "table\u2028key": table_rows,
        }
        encoded_obj = tc.encode_toon(obj_payload)
        self.assertTrue(encoded_obj.startswith("# TOON-OBJECT\n"))
        decoded_obj = tc.decode_toon(encoded_obj)
        self.assertEqual(decoded_obj, obj_payload)
        self.assertEqual(list(decoded_obj.keys()), list(obj_payload.keys()))

    def test_mirror_script_parity(self):
        self.assertTrue(TOON_SCRIPT.exists())
        self.assertTrue(MIRROR_TOON_SCRIPT.exists())
        self.assertEqual(
            TOON_SCRIPT.read_bytes().replace(b"\r\n", b"\n"),
            MIRROR_TOON_SCRIPT.read_bytes().replace(b"\r\n", b"\n"),
        )


if __name__ == "__main__":
    unittest.main()
