import importlib.util, hashlib, unittest
import json, os, tempfile
import io, contextlib
import stat
import subprocess
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
TOOL = HERE / "kp_context_measure.py"
_spec = importlib.util.spec_from_file_location("kpcm", HERE / "kp_context_measure.py")
kpcm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(kpcm)

class TestCore(unittest.TestCase):
    def test_whitespace_set_is_exact_unicode_15_property(self):
        expected = ({0x09,0x0A,0x0B,0x0C,0x0D,0x20,0x85,0xA0,0x1680,
                     0x2028,0x2029,0x202F,0x205F,0x3000} | set(range(0x2000,0x200A+1)))
        self.assertEqual(set(kpcm.WHITE_SPACE), expected)
        self.assertEqual(len(kpcm.WHITE_SPACE), 25)
    def test_newline_normalization_crlf_then_cr_only(self):
        self.assertEqual(kpcm.normalize_newlines("a\r\nb\rc\nd"), "a\nb\nc\nd")
        self.assertEqual(kpcm.normalize_newlines("x\u2028y"), "x\u2028y")  # LS untouched
    def test_astral_scalar_counts_as_one_character(self):
        self.assertEqual(kpcm.count_characters("A\U0001F600B"), 3)
    def test_word_runs_use_pinned_set_not_python_isspace(self):
        # U+001C is whitespace to str.split() but NOT in Unicode White_Space
        self.assertEqual("a\x1cb".split().__len__(), 2)       # documents the drift we avoid
        self.assertEqual(kpcm.count_words("a\x1cb"), 1)        # pinned set: one run
        self.assertEqual(kpcm.count_words("a\u200bb"), 1)      # ZWSP not in set
        self.assertEqual(kpcm.count_words("a\u00a0b"), 2)      # NBSP in set
        self.assertEqual(kpcm.count_words("  a\t\n b  "), 2)   # runs + leading/trailing
        self.assertEqual(kpcm.count_words(""), 0)
    def test_strict_utf8_rejects_lone_surrogate_and_invalid(self):
        for bad in (b"\xed\xa0\x80", b"\xff", b"\xc3\x28"):
            with self.assertRaises(UnicodeDecodeError):
                kpcm.decode_strict_utf8(bad)
        self.assertEqual(kpcm.decode_strict_utf8(b"A\xf0\x9f\x98\x80B"), "A\U0001F600B")
    def test_sha256_hex_matches_hashlib(self):
        self.assertEqual(kpcm.sha256_hex(b""), hashlib.sha256(b"").hexdigest())

class TestSelectionAndReceipt(unittest.TestCase):
    def _tmp(self, data: bytes) -> str:
        fd, p = tempfile.mkstemp(); os.write(fd, data); os.close(fd); self.addCleanup(os.remove, p); return p
    def test_full_file_counts_and_digests(self):
        p = self._tmp(b"alpha beta\r\ngamma\n")
        rec, code = kpcm.build_receipt("c/r", "b1",
            [{"projection_id": "f", "path": p, "select": {"kind": "full"}}])
        self.assertEqual(code, 0)
        e = rec["projections"][0]
        self.assertEqual(e["status"], "OK")
        self.assertEqual(e["characters"], len("alpha beta\ngamma\n"))
        self.assertEqual(e["words"], 3)
        self.assertEqual(e["raw_sha256"], kpcm.sha256_hex(b"alpha beta\r\ngamma\n"))
        self.assertEqual(rec["totals"], {"bytes": 18, "characters": 17, "words": 3})
    def test_region_inclusive_of_markers(self):
        body = b"pre\n<!-- BEGIN x -->\nmid one\n<!-- END x -->\npost\n"
        p = self._tmp(body)
        rec, code = kpcm.build_receipt("c/r", "b1", [{"projection_id": "r", "path": p,
            "select": {"kind": "region", "begin": "<!-- BEGIN x -->", "end": "<!-- END x -->"}}])
        self.assertEqual(code, 0)
        region = "<!-- BEGIN x -->\nmid one\n<!-- END x -->"
        self.assertEqual(rec["projections"][0]["raw_sha256"], kpcm.sha256_hex(region.encode()))
        # maximal non-whitespace runs, marker-inclusive:
        # <!-- BEGIN x --> mid one <!-- END x -->  => 10 runs
        self.assertEqual(rec["projections"][0]["words"], 10)
    def test_invalid_utf8_blocks_with_raw_digest_only(self):
        p = self._tmp(b"\xff\xfe")
        rec, code = kpcm.build_receipt("c/r", "b1", [{"projection_id": "b", "path": p, "select": {"kind": "full"}}])
        self.assertEqual(code, 2)
        e = rec["projections"][0]
        self.assertEqual((e["status"], e["failure_class"]), ("BLOCKED_PREREQUISITE", "INVALID_UTF8"))
        self.assertEqual(e["raw_sha256"], kpcm.sha256_hex(b"\xff\xfe"))
        self.assertIsNone(e["characters"]); self.assertIsNone(rec["totals"])
    def test_region_not_found_blocks(self):
        p = self._tmp(b"no markers here\n")
        rec, code = kpcm.build_receipt("c/r", "b1", [{"projection_id": "r", "path": p,
            "select": {"kind": "region", "begin": "<!-- BEGIN x -->", "end": "<!-- END x -->"}}])
        self.assertEqual(code, 2)
        self.assertEqual(rec["projections"][0]["failure_class"], "REGION_NOT_FOUND")
    def test_empty_file(self):
        p = self._tmp(b"")
        rec, code = kpcm.build_receipt("c/r", "b1", [{"projection_id": "e", "path": p, "select": {"kind": "full"}}])
        self.assertEqual((code, rec["projections"][0]["characters"], rec["projections"][0]["words"]), (0, 0, 0))
        self.assertEqual(rec["projections"][0]["raw_sha256"], kpcm.sha256_hex(b""))
    def test_content_never_disclosed(self):
        p = self._tmp(b"TOKEN_SENTINEL_SECRET stuff\n")
        rec, _ = kpcm.build_receipt("c/r", "b1", [{"projection_id": "s", "path": p, "select": {"kind": "full"}}])
        self.assertNotIn("SENTINEL", json.dumps(rec))

class TestCli(unittest.TestCase):
    def _tmp_named(self, data: bytes) -> str:
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(data); f.close(); self.addCleanup(os.remove, f.name); return f.name
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = kpcm.main(argv)
        return code, buf.getvalue()
    def _valid_receipt(self, totals):
        row = {
            "projection_id": "x",
            "path": "/logical/x",
            "select": {"kind": "full"},
            "status": "OK",
            "failure_class": None,
            "raw_sha256": "0" * 64,
            "normalized_sha256": "1" * 64,
            "bytes": totals["bytes"],
            "characters": totals["characters"],
            "words": totals["words"],
        }
        return {
            "schema": kpcm.RECEIPT_SCHEMA,
            "algorithm": kpcm.ALGORITHM,
            "tool": kpcm.TOOL,
            "tool_contract": kpcm.TOOL_CONTRACT,
            "whitespace_set_version": kpcm.WHITESPACE_SET_VERSION,
            "status": "OK",
            "client_root_class": "c/r",
            "baseline_id": "b1",
            "projection_order": ["x"],
            "projections": [row],
            "totals": totals,
        }
    def test_measure_path_is_deterministic_byte_identical(self):
        p = self._tmp_named(b"one two three\n")
        a = self._run(["measure", "--path", p, "--projection-id", "x",
                       "--client-root-class", "c/r", "--baseline-id", "b1"])
        b = self._run(["measure", "--path", p, "--projection-id", "x",
                       "--client-root-class", "c/r", "--baseline-id", "b1"])
        self.assertEqual(a, b)                       # byte-identical output + exit
        self.assertEqual(a[0], 0)
        self.assertEqual(json.loads(a[1])["totals"]["words"], 3)
    def test_compare_ok_and_target(self):
        base = self._valid_receipt(
            {"bytes": 100, "characters": 100, "words": 20}
        )
        cand = self._valid_receipt(
            {"bytes": 60, "characters": 60, "words": 12}
        )
        out, code = kpcm.compare_receipts(base, cand)
        self.assertEqual(code, 0)
        self.assertTrue(out["target_30pct"]["meets_characters"])
        self.assertEqual(out["delta"]["characters"], -40)
    def test_compare_refuses_identity_mismatch(self):
        base = self._valid_receipt(
            {"bytes": 1, "characters": 1, "words": 1}
        )
        cand = json.loads(json.dumps(base))
        cand["projection_order"] = ["y"]
        cand["projections"][0]["projection_id"] = "y"
        cand["baseline_id"] = "b2"
        out, code = kpcm.compare_receipts(base, cand)
        self.assertEqual(code, 4)
        self.assertEqual(out["status"], "COMPARISON_REFUSED")
        self.assertIn("PROJECTION_ORDER_MISMATCH", out["reasons"])
        self.assertIn("BASELINE_ID_MISMATCH", out["reasons"])
    def test_bad_manifest_is_usage_error(self):
        p = self._tmp_named(b'{"schema":"wrong"}')
        with self.assertRaises(kpcm.InputError) as ctx:
            kpcm.load_manifest(p)
        self.assertEqual(ctx.exception.location, "manifest")
        self.assertEqual(ctx.exception.error_class, "MANIFEST_SCHEMA")


class TestContractV2(unittest.TestCase):
    SENTINEL = "TOKEN_SENTINEL_SECRET"

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _file(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _json_file(self, name, value, canonical=True):
        path = self.root / name
        if canonical:
            raw = (
                json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)
                + "\n"
            ).encode("ascii")
        else:
            raw = json.dumps(value).encode("utf-8")
        path.write_bytes(raw)
        return path

    def _manifest(self, projections, **updates):
        value = {
            "schema": "kp-context-measurement-input/v2",
            "client_root_class": "cursor-desktop/dev-primary",
            "baseline_id": "baseline-1",
            "projections": projections,
        }
        value.update(updates)
        return self._json_file("manifest.json", value)

    def _run(self, *argv, cwd=None):
        return subprocess.run(
            [sys.executable, str(TOOL), *[str(item) for item in argv]],
            cwd=str(cwd or self.root),
            capture_output=True,
            check=False,
        )

    def _assert_no_traceback_or_sentinel(self, completed):
        combined = completed.stdout + completed.stderr
        self.assertNotIn(b"Traceback", combined)
        self.assertNotIn(self.SENTINEL.encode("ascii"), combined)

    def _assert_usage(self, completed, location, error_class):
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(
            completed.stderr,
            (
                "kp_context_measure: USAGE_ERROR: "
                f"{location}: {error_class}\n"
            ).encode("ascii"),
        )
        self._assert_no_traceback_or_sentinel(completed)

    def _ok_row(self, projection_id="a", path="/logical/a", select=None,
                raw="0" * 64, normalized="1" * 64, count=1):
        return {
            "projection_id": projection_id,
            "path": path,
            "select": select or {"kind": "full"},
            "status": "OK",
            "failure_class": None,
            "raw_sha256": raw,
            "normalized_sha256": normalized,
            "bytes": count,
            "characters": count,
            "words": count,
        }

    def _receipt(self, rows=None, **updates):
        rows = rows or [self._ok_row()]
        all_ok = all(row["status"] == "OK" for row in rows)
        value = {
            "schema": "kp-context-measurement-receipt/v2",
            "algorithm": "kp-context-measurement/v1",
            "tool": "kp_context_measure",
            "tool_contract": "kp-context-measurement-tool/v2",
            "whitespace_set_version": "unicode-15.0-White_Space",
            "status": "OK" if all_ok else "BLOCKED_PREREQUISITE",
            "client_root_class": "cursor-desktop/dev-primary",
            "baseline_id": "baseline-1",
            "projection_order": [row["projection_id"] for row in rows],
            "projections": rows,
            "totals": (
                {
                    key: sum(row[key] for row in rows)
                    for key in ("bytes", "characters", "words")
                }
                if all_ok else None
            ),
        }
        value.update(updates)
        return value

    def _blocked_receipt(self, failure_class="PATH_UNREADABLE"):
        row = self._ok_row()
        row.update({
            "status": "BLOCKED_PREREQUISITE",
            "failure_class": failure_class,
            "raw_sha256": None,
            "normalized_sha256": None,
            "bytes": None,
            "characters": None,
            "words": None,
        })
        if failure_class == "INVALID_UTF8":
            row["raw_sha256"] = "0" * 64
            row["bytes"] = 1
        return self._receipt(
            [row], status="BLOCKED_PREREQUISITE", totals=None
        )

    def _compare_values(self, baseline, candidate):
        baseline_path = self._json_file("baseline.json", baseline)
        candidate_path = self._json_file("candidate.json", candidate)
        return self._run(
            "compare", "--baseline", baseline_path,
            "--candidate", candidate_path,
        )

    def test_manifest_order_is_canonical_projection_id_order(self):
        z_path = self._file("z.txt", b"z\n")
        a_path = self._file("a.txt", b"a\n")
        manifest = self._manifest([
            {"projection_id": "z", "path": str(z_path),
             "select": {"kind": "full"}},
            {"projection_id": "a", "path": str(a_path),
             "select": {"kind": "full"}},
        ])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["projection_order"], ["a", "z"])
        self.assertEqual(
            [row["projection_id"] for row in receipt["projections"]],
            ["a", "z"],
        )

    def test_null_projection_is_usage_error_without_traceback(self):
        manifest = self._manifest([None])
        completed = self._run("measure", "--manifest", manifest)
        self._assert_usage(completed, "projection", "MANIFEST_SCHEMA")

    def test_unknown_select_field_is_rejected_without_value_echo(self):
        source = self._file("source.txt", b"safe\n")
        manifest = self._manifest([{
            "projection_id": "a",
            "path": str(source),
            "select": {
                "kind": "full",
                "unexpected_payload": self.SENTINEL,
            },
        }])
        completed = self._run("measure", "--manifest", manifest)
        self._assert_usage(completed, "select", "MANIFEST_SCHEMA")

    def test_missing_compare_argument_is_usage_error(self):
        completed = self._run("compare", "--baseline", "x")
        self._assert_usage(completed, "cli", "CLI_ARGUMENTS")

    def test_malformed_receipt_is_refused_without_traceback(self):
        completed = self._compare_values({}, {})
        self.assertEqual(completed.returncode, 4)
        self.assertEqual(completed.stderr, b"")
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "schema": "kp-context-measurement-comparison/v2",
                "status": "COMPARISON_REFUSED",
                "reasons": [
                    "BASELINE_RECEIPT_INVALID",
                    "CANDIDATE_RECEIPT_INVALID",
                ],
            },
        )
        self._assert_no_traceback_or_sentinel(completed)

    def test_v1_receipt_is_refused(self):
        historical = {
            "schema": "kp-context-measurement/v1",
            "algorithm": "kp-context-measurement/v1",
        }
        completed = self._compare_values(historical, historical)
        self.assertEqual(completed.returncode, 4)
        self.assertEqual(
            json.loads(completed.stdout)["reasons"],
            ["UNSUPPORTED_RECEIPT_SCHEMA"],
        )

    def test_equal_region_markers_are_usage_error(self):
        source = self._file("source.txt", b"same\n")
        manifest = self._manifest([{
            "projection_id": "a",
            "path": str(source),
            "select": {"kind": "region", "begin": "same", "end": "same"},
        }])
        completed = self._run("measure", "--manifest", manifest)
        self._assert_usage(completed, "select", "MANIFEST_VALUE")

    def test_overlapping_region_markers_are_misordered(self):
        source = self._file("source.txt", b"abcd")
        manifest = self._manifest([{
            "projection_id": "a",
            "path": str(source),
            "select": {"kind": "region", "begin": "abc", "end": "bcd"},
        }])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 2)
        row = json.loads(completed.stdout)["projections"][0]
        self.assertEqual(row["failure_class"], "REGION_MISORDERED")

    def test_repeated_overlapping_marker_is_ambiguous(self):
        source = self._file("source.txt", b"aaaZ")
        manifest = self._manifest([{
            "projection_id": "a",
            "path": str(source),
            "select": {"kind": "region", "begin": "aa", "end": "Z"},
        }])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 2)
        row = json.loads(completed.stdout)["projections"][0]
        self.assertEqual(row["failure_class"], "REGION_AMBIGUOUS")

    def test_receipt_rejects_unknown_fields(self):
        baseline = self._receipt()
        baseline["projections"][0]["unexpected"] = self.SENTINEL
        completed = self._compare_values(baseline, self._receipt())
        self.assertEqual(completed.returncode, 4)
        self.assertEqual(
            json.loads(completed.stdout)["reasons"],
            ["BASELINE_RECEIPT_INVALID"],
        )
        self._assert_no_traceback_or_sentinel(completed)

    def test_compare_refuses_descriptor_mismatch(self):
        region = {
            "kind": "region",
            "begin_sha256": "2" * 64,
            "end_sha256": "3" * 64,
        }
        cases = []
        candidate = self._receipt()
        candidate["projections"][0]["path"] = "/logical/other"
        cases.append(candidate)
        baseline_region = self._receipt([
            self._ok_row(select=region)
        ])
        candidate_region = json.loads(json.dumps(baseline_region))
        candidate_region["projections"][0]["select"]["end_sha256"] = "4" * 64
        cases.append((baseline_region, candidate_region))
        for index, case in enumerate(cases):
            with self.subTest(case=index):
                if isinstance(case, tuple):
                    baseline, candidate = case
                else:
                    baseline, candidate = self._receipt(), case
                completed = self._compare_values(baseline, candidate)
                self.assertEqual(completed.returncode, 4)
                self.assertEqual(
                    json.loads(completed.stdout)["reasons"],
                    ["PROJECTION_DESCRIPTOR_MISMATCH"],
                )

    def test_valid_errors_use_only_public_exit_classes(self):
        missing = self.root / "missing.txt"
        valid_source = self._file("valid.txt", b"abc")
        malformed_manifest = self._json_file(
            "null-manifest.json", None
        )
        blocked_manifest = self._manifest([{
            "projection_id": "a", "path": str(missing),
            "select": {"kind": "full"},
        }])
        blocked_result = self._run(
            "measure", "--manifest", blocked_manifest
        )
        equal_manifest = self._manifest([{
            "projection_id": "a", "path": str(valid_source),
            "select": {"kind": "region", "begin": "a", "end": "a"},
        }])
        bad_receipt = self._json_file("bad-receipt.json", None)
        cases = [
            self._run("measure"),
            self._run("measure", "--manifest", malformed_manifest),
            blocked_result,
            self._run("measure", "--manifest", equal_manifest),
            self._run(
                "compare", "--baseline", bad_receipt,
                "--candidate", bad_receipt,
            ),
        ]
        self.assertEqual(
            {completed.returncode for completed in cases}, {2, 3, 4}
        )
        for completed in cases:
            self.assertIn(completed.returncode, {2, 3, 4})
            self._assert_no_traceback_or_sentinel(completed)

    def test_manifest_rejects_scalar_empty_unknown_and_invalid_ids(self):
        source = self._file("source.txt", b"x\n")
        cases = [
            (None, "manifest", "MANIFEST_SCHEMA"),
            ({
                "schema": "kp-context-measurement-input/v2",
                "client_root_class": "c",
                "baseline_id": "b",
                "projections": [],
            }, "manifest", "MANIFEST_VALUE"),
            ({
                "schema": "kp-context-measurement-input/v2",
                "client_root_class": "c",
                "baseline_id": "b",
                "projections": [{
                    "projection_id": "a", "path": str(source),
                    "select": {"kind": "full"},
                }],
                "unknown": self.SENTINEL,
            }, "manifest", "MANIFEST_SCHEMA"),
            ({
                "schema": "kp-context-measurement-input/v2",
                "client_root_class": "bad space",
                "baseline_id": "b",
                "projections": [{
                    "projection_id": "a", "path": str(source),
                    "select": {"kind": "full"},
                }],
            }, "manifest", "MANIFEST_VALUE"),
            ({
                "schema": "kp-context-measurement-input/v2",
                "client_root_class": "c",
                "baseline_id": "b",
                "projections": [{
                    "projection_id": "-bad", "path": str(source),
                    "select": {"kind": "full"},
                }],
            }, "projection", "MANIFEST_VALUE"),
        ]
        for index, (value, location, error_class) in enumerate(cases):
            with self.subTest(case=index):
                path = self._json_file(f"invalid-{index}.json", value)
                completed = self._run("measure", "--manifest", path)
                self._assert_usage(completed, location, error_class)

    def test_manifest_rejects_duplicate_ids_and_unknown_projection_key(self):
        source = self._file("source.txt", b"x\n")
        entry = {
            "projection_id": "a", "path": str(source),
            "select": {"kind": "full"},
        }
        duplicate = self._manifest([entry, dict(entry)])
        completed = self._run("measure", "--manifest", duplicate)
        self._assert_usage(completed, "projection", "MANIFEST_VALUE")

        unknown_entry = dict(entry)
        unknown_entry["unknown"] = self.SENTINEL
        unknown = self._manifest([unknown_entry])
        completed = self._run("measure", "--manifest", unknown)
        self._assert_usage(completed, "projection", "MANIFEST_SCHEMA")

    def test_manifest_rejects_duplicate_json_keys_and_nonstandard_constants(self):
        duplicate = self._file(
            "duplicate.json",
            b'{"schema":"kp-context-measurement-input/v2",'
            b'"schema":"kp-context-measurement-input/v2"}',
        )
        constant = self._file(
            "constant.json",
            b'{"schema":"kp-context-measurement-input/v2",'
            b'"client_root_class":"c","baseline_id":"b",'
            b'"projections":NaN}',
        )
        for path in (duplicate, constant):
            with self.subTest(path=path.name):
                completed = self._run("measure", "--manifest", path)
                self._assert_usage(
                    completed, "manifest", "MANIFEST_INVALID_JSON"
                )

    def test_large_json_integer_is_normalized_at_all_decoder_boundaries(self):
        large_integer = b"9" * 5000
        manifest = self._file("large-manifest.json", large_integer)
        measured = self._run("measure", "--manifest", manifest)
        self.assertEqual(measured.returncode, 3)
        self.assertEqual(measured.stdout, b"")
        self.assertIn(
            measured.stderr,
            {
                b"kp_context_measure: USAGE_ERROR: manifest: MANIFEST_INVALID_JSON\n",
                b"kp_context_measure: USAGE_ERROR: manifest: MANIFEST_SCHEMA\n",
            },
        )
        self._assert_no_traceback_or_sentinel(measured)
        self.assertNotIn(large_integer[:100], measured.stderr)

        baseline = self._file("large-baseline.json", large_integer)
        candidate = self._file("large-candidate.json", large_integer)
        compared = self._run(
            "compare", "--baseline", baseline,
            "--candidate", candidate,
        )
        self.assertEqual(compared.returncode, 4)
        self.assertEqual(compared.stderr, b"")
        self.assertEqual(
            json.loads(compared.stdout)["reasons"],
            [
                "BASELINE_RECEIPT_INVALID",
                "CANDIDATE_RECEIPT_INVALID",
            ],
        )
        self.assertNotIn(b"Traceback", compared.stdout + compared.stderr)
        self.assertNotIn(large_integer[:100], compared.stdout + compared.stderr)

    def test_manifest_enforces_token_path_and_marker_scalar_boundaries(self):
        source = self._file("source.txt", b"x\n")
        valid_identifier = "A" + ("x" * 123) + "._/-"
        self.assertEqual(len(valid_identifier), 128)
        valid = self._manifest([{
            "projection_id": valid_identifier,
            "path": str(source),
            "select": {"kind": "full"},
        }])
        self.assertEqual(
            self._run("measure", "--manifest", valid).returncode, 0
        )
        cases = [
            (
                {
                    "projection_id": "x" * 129,
                    "path": str(source),
                    "select": {"kind": "full"},
                },
                "projection",
            ),
            (
                {
                    "projection_id": "a",
                    "path": "",
                    "select": {"kind": "full"},
                },
                "projection",
            ),
            (
                {
                    "projection_id": "a",
                    "path": "bad\x00path",
                    "select": {"kind": "full"},
                },
                "projection",
            ),
            (
                {
                    "projection_id": "a",
                    "path": "\ud800",
                    "select": {"kind": "full"},
                },
                "projection",
            ),
            (
                {
                    "projection_id": "a",
                    "path": str(source),
                    "select": {"kind": "region", "begin": "", "end": "x"},
                },
                "select",
            ),
            (
                {
                    "projection_id": "a",
                    "path": str(source),
                    "select": {
                        "kind": "region", "begin": "\ud800", "end": "x",
                    },
                },
                "select",
            ),
        ]
        for index, (entry, location) in enumerate(cases):
            with self.subTest(case=index):
                manifest = self._manifest([entry])
                completed = self._run("measure", "--manifest", manifest)
                self._assert_usage(
                    completed, location, "MANIFEST_VALUE"
                )

    def test_manifest_file_failures_are_fixed_and_value_free(self):
        invalid_utf8 = self._file("manifest-utf8.json", b"\xff" + self.SENTINEL.encode())
        invalid_json = self._file(
            "manifest-json.json",
            ("{" + self.SENTINEL).encode("ascii"),
        )
        cases = [
            (self.root / "absent-manifest.json", "MANIFEST_UNREADABLE"),
            (invalid_utf8, "MANIFEST_INVALID_UTF8"),
            (invalid_json, "MANIFEST_INVALID_JSON"),
        ]
        for path, error_class in cases:
            with self.subTest(error_class=error_class):
                completed = self._run("measure", "--manifest", path)
                self._assert_usage(completed, "manifest", error_class)

    def test_path_unreadable_covers_missing_and_nonregular_targets(self):
        directory = self.root / "directory"
        directory.mkdir()
        for index, path in enumerate((self.root / "missing", directory)):
            with self.subTest(path=index):
                manifest = self._manifest([{
                    "projection_id": "a", "path": str(path),
                    "select": {"kind": "full"},
                }])
                completed = self._run("measure", "--manifest", manifest)
                self.assertEqual(completed.returncode, 2)
                row = json.loads(completed.stdout)["projections"][0]
                self.assertEqual(row["failure_class"], "PATH_UNREADABLE")
                self.assertTrue(all(
                    row[key] is None
                    for key in (
                        "raw_sha256", "normalized_sha256", "bytes",
                        "characters", "words",
                    )
                ))

    def test_symlink_to_regular_file_is_measured(self):
        target = self._file("target.txt", b"safe\n")
        link = self.root / "link.txt"
        link.symlink_to(target)
        manifest = self._manifest([{
            "projection_id": "a", "path": str(link),
            "select": {"kind": "full"},
        }])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_invalid_utf8_receipt_has_only_raw_digest_and_bytes(self):
        source = self._file("invalid.bin", b"\xff\xfe")
        manifest = self._manifest([{
            "projection_id": "a", "path": str(source),
            "select": {"kind": "full"},
        }])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 2)
        receipt = json.loads(completed.stdout)
        row = receipt["projections"][0]
        self.assertEqual(row["failure_class"], "INVALID_UTF8")
        self.assertEqual(row["raw_sha256"], hashlib.sha256(b"\xff\xfe").hexdigest())
        self.assertEqual(row["bytes"], 2)
        self.assertIsNone(row["normalized_sha256"])
        self.assertIsNone(row["characters"])
        self.assertIsNone(row["words"])
        self.assertIsNone(receipt["totals"])

    def test_newline_semantics_and_canonical_bytes(self):
        raw = b"a\r\nb\rc\n"
        source = self._file("newlines.txt", raw)
        manifest = self._manifest([{
            "projection_id": "a", "path": str(source),
            "select": {"kind": "full"},
        }])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        row = receipt["projections"][0]
        normalized = b"a\nb\nc\n"
        self.assertEqual(row["bytes"], len(raw))
        self.assertEqual(row["characters"], len(normalized.decode("utf-8")))
        self.assertEqual(
            row["normalized_sha256"], hashlib.sha256(normalized).hexdigest()
        )
        self.assertEqual(
            completed.stdout,
            (
                json.dumps(
                    receipt, indent=2, sort_keys=True, ensure_ascii=True
                ) + "\n"
            ).encode("ascii"),
        )
        self.assertEqual(completed.stderr, b"")

    def test_region_precedence_and_adjacent_markers(self):
        cases = [
            (b"aaaa", "aa", "Z", "REGION_NOT_FOUND", 2),
            (b"aaXaaZ", "aa", "Z", "REGION_AMBIGUOUS", 2),
            (b"END middle BEGIN", "BEGIN", "END", "REGION_MISORDERED", 2),
            (b"BEGINEND", "BEGIN", "END", None, 0),
        ]
        for index, (raw, begin, end, expected, exit_code) in enumerate(cases):
            with self.subTest(case=index):
                source = self._file(f"region-{index}.txt", raw)
                manifest = self._manifest([{
                    "projection_id": "a", "path": str(source),
                    "select": {
                        "kind": "region", "begin": begin, "end": end,
                    },
                }])
                completed = self._run("measure", "--manifest", manifest)
                self.assertEqual(completed.returncode, exit_code)
                row = json.loads(completed.stdout)["projections"][0]
                self.assertEqual(row["failure_class"], expected)

    def test_region_receipt_uses_marker_digests_only(self):
        begin = "BEGIN-" + self.SENTINEL
        end = "END-" + self.SENTINEL
        source = self._file(
            "region.txt", (begin + "\nbody\n" + end).encode("utf-8")
        )
        manifest = self._manifest([{
            "projection_id": "a", "path": str(source),
            "select": {"kind": "region", "begin": begin, "end": end},
        }])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn(self.SENTINEL.encode("ascii"), completed.stdout)
        select = json.loads(completed.stdout)["projections"][0]["select"]
        self.assertEqual(select, {
            "kind": "region",
            "begin_sha256": hashlib.sha256(begin.encode("utf-8")).hexdigest(),
            "end_sha256": hashlib.sha256(end.encode("utf-8")).hexdigest(),
        })

    def test_region_markers_match_before_newline_normalization(self):
        begin = "BEGIN\r\n"
        end = "END\r"
        raw = (begin + "middle\r\n" + end).encode("utf-8")
        source = self._file("raw-markers.txt", raw)
        manifest = self._manifest([{
            "projection_id": "a",
            "path": str(source),
            "select": {"kind": "region", "begin": begin, "end": end},
        }])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        row = json.loads(completed.stdout)["projections"][0]
        self.assertEqual(row["raw_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            row["normalized_sha256"],
            hashlib.sha256(b"BEGIN\nmiddle\nEND\n").hexdigest(),
        )

    def test_all_canonical_rows_are_evaluated_when_one_blocks(self):
        invalid = self._file("invalid.bin", b"\xff")
        manifest = self._manifest([
            {
                "projection_id": "z-invalid", "path": str(invalid),
                "select": {"kind": "full"},
            },
            {
                "projection_id": "a-missing",
                "path": str(self.root / "absent"),
                "select": {"kind": "full"},
            },
        ])
        completed = self._run("measure", "--manifest", manifest)
        self.assertEqual(completed.returncode, 2)
        receipt = json.loads(completed.stdout)
        self.assertEqual(
            [row["projection_id"] for row in receipt["projections"]],
            ["a-missing", "z-invalid"],
        )
        self.assertEqual(
            [row["failure_class"] for row in receipt["projections"]],
            ["PATH_UNREADABLE", "INVALID_UTF8"],
        )

    def test_relative_path_uses_process_working_directory(self):
        source = self._file("relative.txt", b"relative\n")
        manifest = self._manifest([{
            "projection_id": "a", "path": source.name,
            "select": {"kind": "full"},
        }])
        ok = self._run("measure", "--manifest", manifest, cwd=self.root)
        blocked = self._run(
            "measure", "--manifest", manifest, cwd=self.root.parent
        )
        self.assertEqual(ok.returncode, 0)
        self.assertEqual(blocked.returncode, 2)
        self.assertEqual(
            json.loads(blocked.stdout)["projections"][0]["failure_class"],
            "PATH_UNREADABLE",
        )

    def test_single_path_mode_uses_same_validation(self):
        source = self._file("source.txt", b"x\n")
        completed = self._run(
            "measure", "--path", source,
            "--projection-id", "bad space",
            "--client-root-class", "c",
            "--baseline-id", "b",
        )
        self._assert_usage(completed, "projection", "MANIFEST_VALUE")
        paired = self._run(
            "measure", "--path", source,
            "--projection-id", "a",
            "--client-root-class", "c",
            "--baseline-id", "b",
            "--region-begin", "x",
        )
        self._assert_usage(paired, "cli", "CLI_ARGUMENTS")

    def test_help_is_zero_and_unknown_cli_is_three(self):
        help_result = self._run("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertEqual(help_result.stderr, b"")
        unknown = self._run("unknown", self.SENTINEL)
        self._assert_usage(unknown, "cli", "CLI_ARGUMENTS")

    def test_receipt_validation_rejects_null_boolean_and_bad_totals(self):
        cases = []
        null_receipt = None
        cases.append(null_receipt)
        boolean_count = self._receipt()
        boolean_count["projections"][0]["bytes"] = True
        cases.append(boolean_count)
        bad_totals = self._receipt()
        bad_totals["totals"]["characters"] = 2
        cases.append(bad_totals)
        unsorted = self._receipt([
            self._ok_row("z", "/z"),
            self._ok_row("a", "/a"),
        ])
        cases.append(unsorted)
        duplicate = self._receipt([
            self._ok_row("a", "/a"),
            self._ok_row("a", "/b"),
        ])
        cases.append(duplicate)
        for index, baseline in enumerate(cases):
            with self.subTest(case=index):
                completed = self._compare_values(
                    baseline, self._receipt()
                )
                self.assertEqual(completed.returncode, 4)
                self.assertIn(
                    "BASELINE_RECEIPT_INVALID",
                    json.loads(completed.stdout)["reasons"],
                )

    def test_receipt_validation_rejects_top_level_unknown_and_noncanonical(self):
        unknown = self._receipt()
        unknown["unexpected"] = self.SENTINEL
        completed = self._compare_values(unknown, self._receipt())
        self.assertEqual(completed.returncode, 4)
        self.assertEqual(
            json.loads(completed.stdout)["reasons"],
            ["BASELINE_RECEIPT_INVALID"],
        )
        self._assert_no_traceback_or_sentinel(completed)

        baseline = self._json_file(
            "baseline.json", self._receipt(), canonical=False
        )
        candidate = self._json_file(
            "candidate.json", self._receipt()
        )
        completed = self._run(
            "compare", "--baseline", baseline, "--candidate", candidate
        )
        self.assertEqual(completed.returncode, 4)
        self.assertEqual(
            json.loads(completed.stdout)["reasons"],
            ["BASELINE_RECEIPT_INVALID"],
        )

    def test_receipt_malformed_types_never_escape_public_exit(self):
        mutations = []
        wrong_status = self._receipt()
        wrong_status["status"] = []
        mutations.append(wrong_status)
        wrong_row_status = self._receipt()
        wrong_row_status["projections"][0]["status"] = {}
        mutations.append(wrong_row_status)
        wrong_failure = self._blocked_receipt()
        wrong_failure["projections"][0]["failure_class"] = []
        mutations.append(wrong_failure)
        wrong_selector = self._receipt()
        wrong_selector["projections"][0]["select"]["kind"] = []
        mutations.append(wrong_selector)
        for index, baseline in enumerate(mutations):
            with self.subTest(case=index):
                completed = self._compare_values(
                    baseline, self._receipt()
                )
                self.assertEqual(completed.returncode, 4)
                self.assertEqual(completed.stderr, b"")
                self.assertIn(
                    "BASELINE_RECEIPT_INVALID",
                    json.loads(completed.stdout)["reasons"],
                )
                self._assert_no_traceback_or_sentinel(completed)

    def test_receipt_validation_enforces_blocked_nullability(self):
        valid = self._blocked_receipt("INVALID_UTF8")
        completed = self._compare_values(valid, self._receipt())
        self.assertEqual(completed.returncode, 4)
        self.assertIn(
            "BASELINE_NOT_OK", json.loads(completed.stdout)["reasons"]
        )
        invalid = self._blocked_receipt("PATH_UNREADABLE")
        invalid["projections"][0]["raw_sha256"] = "0" * 64
        completed = self._compare_values(invalid, self._receipt())
        self.assertEqual(
            json.loads(completed.stdout)["reasons"],
            ["BASELINE_RECEIPT_INVALID"],
        )

    def test_receipt_region_selector_and_failure_invariants(self):
        region = {
            "kind": "region",
            "begin_sha256": "2" * 64,
            "end_sha256": "3" * 64,
        }
        equal_region = dict(region)
        equal_region["end_sha256"] = equal_region["begin_sha256"]
        invalid_equal = self._receipt([
            self._ok_row(select=equal_region)
        ])
        with self.assertRaises(kpcm.ReceiptInvalid):
            kpcm.validate_receipt(invalid_equal)
        compared = self._compare_values(
            invalid_equal, self._receipt()
        )
        self.assertEqual(
            json.loads(compared.stdout)["reasons"],
            ["BASELINE_RECEIPT_INVALID"],
        )

        for failure_class in (
            "REGION_NOT_FOUND",
            "REGION_AMBIGUOUS",
            "REGION_MISORDERED",
        ):
            with self.subTest(failure_class=failure_class):
                invalid_full = self._blocked_receipt(failure_class)
                with self.assertRaises(kpcm.ReceiptInvalid):
                    kpcm.validate_receipt(invalid_full)
                compared = self._compare_values(
                    invalid_full, self._receipt()
                )
                self.assertEqual(
                    json.loads(compared.stdout)["reasons"],
                    ["BASELINE_RECEIPT_INVALID"],
                )

                valid_region = self._blocked_receipt(failure_class)
                valid_region["projections"][0]["select"] = dict(region)
                self.assertIs(kpcm.validate_receipt(valid_region), valid_region)
                candidate_region = self._receipt([
                    self._ok_row(select=dict(region))
                ])
                compared = self._compare_values(
                    valid_region, candidate_region
                )
                self.assertEqual(
                    json.loads(compared.stdout)["reasons"],
                    ["BASELINE_NOT_OK"],
                )

        for failure_class in ("PATH_UNREADABLE", "INVALID_UTF8"):
            with self.subTest(full_failure=failure_class):
                valid_full = self._blocked_receipt(failure_class)
                self.assertIs(kpcm.validate_receipt(valid_full), valid_full)

    def test_compare_read_and_parse_failures_are_side_specific(self):
        candidate = self._json_file("candidate.json", self._receipt())
        missing = self.root / "missing-receipt.json"
        malformed = self._file("malformed-receipt.json", b"\xff")
        completed = self._run(
            "compare", "--baseline", missing, "--candidate", malformed
        )
        self.assertEqual(completed.returncode, 4)
        self.assertEqual(
            json.loads(completed.stdout)["reasons"],
            [
                "BASELINE_RECEIPT_UNREADABLE",
                "CANDIDATE_RECEIPT_INVALID",
            ],
        )
        self.assertEqual(completed.stderr, b"")
        self.assertTrue(candidate.exists())

    def test_compare_identity_unsupported_and_mismatch_reasons(self):
        dimensions = [
            (
                "algorithm",
                "baseline-algorithm/v9",
                "candidate-algorithm/v9",
                "BASELINE_ALGORITHM_UNSUPPORTED",
                "CANDIDATE_ALGORITHM_UNSUPPORTED",
                "ALGORITHM_MISMATCH",
            ),
            (
                "tool_contract",
                "baseline-tool/v9",
                "candidate-tool/v9",
                "BASELINE_TOOL_CONTRACT_UNSUPPORTED",
                "CANDIDATE_TOOL_CONTRACT_UNSUPPORTED",
                "TOOL_CONTRACT_MISMATCH",
            ),
            (
                "whitespace_set_version",
                "baseline-whitespace/v9",
                "candidate-whitespace/v9",
                "BASELINE_WHITESPACE_SET_UNSUPPORTED",
                "CANDIDATE_WHITESPACE_SET_UNSUPPORTED",
                "WHITESPACE_SET_MISMATCH",
            ),
        ]
        for (field, left, right, left_reason, right_reason,
             mismatch_reason) in dimensions:
            with self.subTest(field=field):
                baseline = self._receipt()
                candidate = self._receipt()
                baseline[field] = left
                candidate[field] = right
                completed = self._compare_values(baseline, candidate)
                self.assertEqual(completed.returncode, 4)
                self.assertEqual(
                    json.loads(completed.stdout)["reasons"],
                    sorted([left_reason, right_reason, mismatch_reason]),
                )

    def test_compare_workload_mismatch_reasons(self):
        cases = []
        candidate = self._receipt()
        candidate["client_root_class"] = "other/root"
        cases.append(("CLIENT_ROOT_CLASS_MISMATCH", candidate))
        candidate = self._receipt()
        candidate["baseline_id"] = "baseline-2"
        cases.append(("BASELINE_ID_MISMATCH", candidate))
        candidate = self._receipt([
            self._ok_row("b", "/logical/b")
        ])
        cases.append(("PROJECTION_ORDER_MISMATCH", candidate))
        for reason, candidate in cases:
            with self.subTest(reason=reason):
                completed = self._compare_values(
                    self._receipt(), candidate
                )
                self.assertEqual(completed.returncode, 4)
                self.assertIn(
                    reason, json.loads(completed.stdout)["reasons"]
                )

    def test_every_closed_comparison_refusal_reason_is_reachable(self):
        observed = set()

        valid_path = self._json_file("valid.json", self._receipt())
        missing_path = self.root / "missing.json"
        for baseline, candidate in (
            (missing_path, valid_path),
            (valid_path, missing_path),
        ):
            completed = self._run(
                "compare", "--baseline", baseline,
                "--candidate", candidate,
            )
            observed.update(json.loads(completed.stdout)["reasons"])

        invalid = self._compare_values({}, {})
        observed.update(json.loads(invalid.stdout)["reasons"])

        legacy = {"schema": "kp-context-measurement/v1"}
        unsupported = self._compare_values(legacy, legacy)
        observed.update(json.loads(unsupported.stdout)["reasons"])

        baseline = self._receipt()
        candidate = self._receipt()
        baseline["algorithm"] = "baseline-algorithm/v9"
        candidate["algorithm"] = "candidate-algorithm/v9"
        baseline["tool_contract"] = "baseline-tool/v9"
        candidate["tool_contract"] = "candidate-tool/v9"
        baseline["whitespace_set_version"] = "baseline-space/v9"
        candidate["whitespace_set_version"] = "candidate-space/v9"
        identity = self._compare_values(baseline, candidate)
        observed.update(json.loads(identity.stdout)["reasons"])

        blocked = self._compare_values(
            self._blocked_receipt(), self._blocked_receipt()
        )
        observed.update(json.loads(blocked.stdout)["reasons"])

        candidate = self._receipt()
        candidate["client_root_class"] = "other/root"
        candidate["baseline_id"] = "other-baseline"
        candidate["projections"][0]["path"] = "/other/path"
        workload = self._compare_values(self._receipt(), candidate)
        observed.update(json.loads(workload.stdout)["reasons"])

        candidate = self._receipt([
            self._ok_row("b", "/logical/b")
        ])
        order = self._compare_values(self._receipt(), candidate)
        observed.update(json.loads(order.stdout)["reasons"])

        self.assertEqual(observed, set(kpcm.COMPARISON_REASONS))

    def test_compare_success_is_closed_and_uses_floor_math(self):
        baseline = self._receipt([
            self._ok_row(count=101)
        ])
        candidate = self._receipt([
            self._ok_row(raw="2" * 64, normalized="3" * 64, count=70)
        ])
        completed = self._compare_values(baseline, candidate)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        value = json.loads(completed.stdout)
        self.assertEqual(
            set(value),
            {
                "schema", "algorithm", "tool", "tool_contract",
                "whitespace_set_version", "status", "baseline_id",
                "client_root_class", "projection_order",
                "baseline_totals", "candidate_totals", "delta",
                "target_30pct",
            },
        )
        self.assertEqual(value["delta"]["characters"], -31)
        self.assertEqual(value["target_30pct"], {
            "max_characters": 70,
            "max_words": 70,
            "meets_characters": True,
            "meets_words": True,
        })

    def test_measurement_is_deterministic_cwd_independent_and_immutable(self):
        source = self._file("source.txt", b"one two\r\nthree\n")
        manifest = self._manifest([{
            "projection_id": "a", "path": str(source),
            "select": {"kind": "full"},
        }])
        before = source.stat()
        before_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        run_a = self._run("measure", "--manifest", manifest, cwd=self.root)
        run_b = self._run("measure", "--manifest", manifest, cwd=Path("/"))
        after = source.stat()
        after_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(run_a.returncode, 0)
        self.assertEqual(run_b.returncode, 0)
        self.assertEqual(run_a.stdout, run_b.stdout)
        self.assertEqual(
            (
                before.st_ino, stat.S_IMODE(before.st_mode), before.st_size,
                before.st_mtime_ns, before_digest,
            ),
            (
                after.st_ino, stat.S_IMODE(after.st_mode), after.st_size,
                after.st_mtime_ns, after_digest,
            ),
        )


if __name__ == "__main__":
    unittest.main()
